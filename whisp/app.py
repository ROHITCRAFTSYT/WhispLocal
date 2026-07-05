"""WhispLocal — private, fully-offline voice dictation for Windows.

Hold the hotkey and speak; release to transcribe and insert at the cursor.
Quick-tap the hotkey to lock recording on; tap again to stop.
An optional second hotkey transcribes AND translates speech to English.
Everything — audio, models, history — stays on this machine.
"""
import json
import os
import socket
import sys
import threading
import time
import traceback

import keyboard

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import configio
import obsidian
from adaptive import Adaptive
from audio import Recorder
from cleanup import clean
from commands import CommandEngine, speak
from inject import insert
from overlay import Overlay
from settings import HistoryWindow, SettingsWindow
from transcriber import Transcriber
from tray import build_tray

__version__ = "2.7.0"

HISTORY_PATH = os.path.join(APP_DIR, "history.jsonl")
LOG_PATH = os.path.join(APP_DIR, "whisp.log")
MAX_LOG_BYTES = 256 * 1024
MAX_HISTORY_BYTES = 1024 * 1024

TAP_THRESHOLD = 0.35  # seconds; shorter press = toggle mode
SINGLE_INSTANCE_PORT = 48917

# States
IDLE, HOLDING, LOCKED, STOPPING = "idle", "holding", "locked", "stopping"


def log(msg):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


def rotate_log():
    """Keep whisp.log from growing without bound."""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
            with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-200:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except OSError:
        pass


def acquire_single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


class App:
    def __init__(self):
        rotate_log()
        self.version = __version__
        self.config = configio.load_config(APP_DIR)
        self.recorder = Recorder(self.config.get("input_device") or None)
        self.transcriber = Transcriber(self.config)
        self.adaptive = Adaptive(
            APP_DIR, enabled=self.config.get("adaptive_learning", True))
        self.commands = CommandEngine(
            note_saver=self._save_note,
            profile_saver=self._save_profile,
            on_action=self._on_command)
        # Reinforcement: ambiguous app names resolve to the one used most.
        self.commands.usage = self.adaptive.app_counts
        self.overlay = Overlay(
            get_levels=lambda: list(self.recorder.levels),
            position=self.config.get("overlay_position", "bottom-center"))
        self.state = IDLE
        self.task = "transcribe"
        self.active_key = None
        self.paused = False
        self.press_time = 0.0
        self.lock = threading.Lock()
        self.hotkey = self.config.get("hotkey", "right ctrl")
        self.tray = None
        self._hooks = []

    # ----- config ---------------------------------------------------------
    def save_config(self, cfg):
        self.config = cfg
        configio.save_config(APP_DIR, cfg)

    def reload_config(self):
        try:
            self.config = configio.load_config(APP_DIR)
            self.hotkey = self.config.get("hotkey", "right ctrl")
            self._register_hotkeys()

            device = self.config.get("input_device") or None
            if device != self.recorder.device and not self.recorder.active:
                self.recorder = Recorder(device)

            new_t = Transcriber(self.config)
            old_t = self.transcriber
            if new_t.model_name != old_t.model_name:
                self.transcriber = new_t  # loads lazily on next dictation
            else:
                # Keep the loaded model; just adopt the new options.
                old_t.language = new_t.language
                old_t.beam_size = new_t.beam_size
            self.adaptive.enabled = self.config.get("adaptive_learning", True)
            self.overlay.set_position(
                self.config.get("overlay_position", "bottom-center"))
            if self.tray:
                self.tray.update_menu()
            log("config applied")
        except Exception as e:
            log(f"config reload failed: {e}")

    def set_model(self, name):
        cfg = dict(self.config)
        cfg["model"] = name
        self.save_config(cfg)
        self.reload_config()
        log(f"model switched to {name}")

    def _save_note(self, text):
        """Called by the command engine for 'take a note ...' commands."""
        return obsidian.save_note(self.config.get("obsidian_vault", ""), text)

    def _save_profile(self):
        """Write the learned profile to Obsidian and report a short summary."""
        summary = self.adaptive.profile_summary()
        vault = self.config.get("obsidian_vault", "")
        if vault:
            obsidian.save_profile(vault, summary)
        top = summary["top_apps"][0][0] if summary["top_apps"] else None
        parts = [f"I have handled {summary['commands_total']} commands"]
        if top:
            parts.append(f"you open {top} most")
        if vault:
            parts.append("I updated your profile in Obsidian")
        return True, ". ".join(parts)

    def _on_command(self, kind, arg, ok):
        """Learn from each executed command and refresh the profile note
        periodically so Obsidian stays current."""
        if not ok:
            return
        label = topic = None
        if kind in ("open_app", "open_web", "close_app", "download"):
            label = arg if isinstance(arg, str) else None
        elif kind in ("search", "lookup", "market", "booking", "youtube"):
            topic = arg if isinstance(arg, str) else None
        elif kind == "play_music" and isinstance(arg, tuple):
            topic = arg[0] or None
        self.adaptive.record_command(kind, label=label, topic=topic)
        vault = self.config.get("obsidian_vault", "")
        if vault and self.adaptive.command_total % 20 == 0:
            try:
                obsidian.save_profile(vault, self.adaptive.profile_summary())
            except Exception:
                pass

    def set_mode(self, mode):
        cfg = dict(self.config)
        cfg["mode"] = mode
        self.save_config(cfg)
        if self.tray:
            self.tray.update_menu()
        label = ("Voice control mode: speak commands"
                 if mode == "command" else "Dictation mode")
        self.overlay.post(("message", label, True))
        log(f"mode set to {mode}")

    def set_language(self, code):
        cfg = dict(self.config)
        cfg["language"] = code
        self.save_config(cfg)
        self.reload_config()
        log(f"language set to {code or 'auto'}")

    def teach_correction(self, original, corrected):
        n = self.adaptive.learn_correction(original, corrected)
        if n:
            log(f"learned {n} correction(s)")
        return n

    def toggle_pause(self):
        self.paused = not self.paused
        if self.tray:
            self.tray.update_menu()

    # ----- windows ----------------------------------------------------------
    def open_settings(self):
        self.overlay.call(lambda: SettingsWindow(self.overlay.root, self))

    def open_history(self):
        self.overlay.call(
            lambda: HistoryWindow(self.overlay.root, HISTORY_PATH, app=self))

    # ----- sounds -----------------------------------------------------------
    def _beep(self, freq, ms=70):
        if not self.config.get("sound_cues", True):
            return
        try:
            import winsound
            threading.Thread(target=winsound.Beep, args=(freq, ms),
                             daemon=True).start()
        except Exception:
            pass

    # ----- hotkey state machine ----------------------------------------------
    def _register_hotkeys(self):
        # Re-registering removes the release handler; if a recording is in
        # flight it would never get its stop event — abort it first.
        if self.state != IDLE:
            self.recorder.abort()
            self.state = IDLE
            self.overlay.post("hide")
        for h in self._hooks:
            try:
                keyboard.unhook(h)
            except (KeyError, ValueError):
                pass
        self._hooks = []
        pairs = [(self.hotkey, "main")]
        tr = (self.config.get("translate_hotkey") or "").strip()
        if tr:
            pairs.append((tr, "translate"))
        cmd = (self.config.get("command_hotkey") or "").strip()
        if cmd:
            pairs.append((cmd, "command"))
        for key, key_id in pairs:
            self._hooks.append(keyboard.on_press_key(
                key, lambda e, k=key_id: self.on_press(k), suppress=False))
            self._hooks.append(keyboard.on_release_key(
                key, lambda e, k=key_id: self.on_release(k), suppress=False))

    def _resolve_task(self, key_id):
        if key_id == "main":
            return ("command" if self.config.get("mode") == "command"
                    else "transcribe")
        return key_id

    def on_press(self, key_id):
        with self.lock:
            if self.state == IDLE:
                if self.paused:
                    return
                self.state = HOLDING
                self.active_key = key_id
                self.task = self._resolve_task(key_id)
                self.press_time = time.time()
                self._start_recording()
            elif self.state == LOCKED and key_id == self.active_key:
                self.state = STOPPING  # release for this press is ignored
                self._finish_recording()

    def on_release(self, key_id):
        with self.lock:
            if key_id != self.active_key:
                return
            if self.state == HOLDING:
                if time.time() - self.press_time < TAP_THRESHOLD:
                    self.state = LOCKED
                    self.overlay.post("locked")
                else:
                    self.state = IDLE
                    self._finish_recording()
            elif self.state == STOPPING:
                self.state = IDLE

    def _start_recording(self):
        try:
            self.recorder.start()
            state = {"translate": "recording_translate",
                     "command": "recording_command"}.get(self.task, "recording")
            self.overlay.post(state)
            self._beep(880)
        except Exception as e:
            self.state = IDLE
            log(f"mic error: {e}")
            self.overlay.post("error")

    def _finish_recording(self):
        # Note: does not touch self.state — callers own the transition.
        self._beep(440)
        audio = self.recorder.stop()
        if audio is None or len(audio) < 4000:  # < 0.25 s — ignore blips
            self.overlay.post("hide")
            return
        self.overlay.post({"translate": "translate",
                           "command": "thinking"}.get(self.task, "transcribing"))
        threading.Thread(target=self._process, args=(audio, self.task),
                         daemon=True).start()

    # ----- pipeline -------------------------------------------------------
    def _process(self, audio, task):
        if task == "command":
            self._process_command(audio)
            return
        try:
            t0 = time.time()
            hot = self.adaptive.hotwords()
            text, lang, prob = self.transcriber.transcribe(
                audio, task=task, hotwords=hot)
            # Auto-detection is shaky on short clips. If confidence is low
            # and the user has a clear language habit, retry pinned to it.
            if task == "transcribe" and not self.config.get("language"):
                pref = self.adaptive.preferred_language()
                if pref and pref != lang and prob < 0.6:
                    retry, _, _ = self.transcriber.transcribe(
                        audio, task=task, hotwords=hot, language=pref)
                    if retry:
                        log(f"language retry {lang}({prob:.2f}) -> {pref}")
                        text, lang = retry, pref
            cfg = dict(self.config)
            cfg["dictionary"] = {**(self.config.get("dictionary") or {}),
                                 **self.adaptive.learned_dictionary}
            text = clean(text, cfg)
            if text:
                insert(text, self.config)
                if task == "transcribe":
                    self.adaptive.record(text, lang)
                self._save_history(text, task, len(audio) / 16000,
                                   time.time() - t0)
                self.overlay.post("done")
            else:
                self.overlay.post("hide")
        except Exception as e:
            log(f"pipeline error: {e}\n{traceback.format_exc()}")
            self.overlay.post("error")

    def _command_hotwords(self):
        """Bias command recognition toward command verbs and the user's own
        app names, so 'open obs' or 'close discord' transcribe cleanly."""
        from commands import _VERBS
        apps = [w for label in self.commands.app_index
                for w in label.split() if len(w) > 2][:60]
        extra = self.adaptive.hotwords() or ""
        return " ".join(list(_VERBS) + apps) + " " + extra

    def _process_command(self, audio):
        try:
            # Commands are English phrases; pinning the language makes
            # short utterances like "open chrome" far more reliable.
            text, _lang, _prob = self.transcriber.transcribe(
                audio, task="transcribe", language="en",
                hotwords=self._command_hotwords())
            if not text:
                self.overlay.post("hide")
                return
            ok, feedback = self.commands.run(text)
            log(f"command: {text!r} -> {ok} {feedback!r}")
            self.overlay.post(("message", feedback or "Done", ok))
            if self.config.get("voice_replies", True):
                speak(feedback)
            self._save_history(f"{text} -> {feedback}", "command",
                               len(audio) / 16000, 0)
        except Exception as e:
            log(f"command error: {e}\n{traceback.format_exc()}")
            self.overlay.post("error")

    def _save_history(self, text, task, audio_secs, proc_secs):
        if not self.config.get("save_history", True):
            return
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "task": task,
            "audio_s": round(audio_secs, 1),
            "processing_s": round(proc_secs, 1),
        }
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            if os.path.getsize(HISTORY_PATH) > MAX_HISTORY_BYTES:
                with open(HISTORY_PATH, encoding="utf-8") as f:
                    tail = f.readlines()[-500:]
                with open(HISTORY_PATH, "w", encoding="utf-8") as f:
                    f.writelines(tail)
        except OSError:
            pass

    # ----- lifecycle ------------------------------------------------------
    def quit(self):
        self.recorder.abort()
        self.overlay.post("quit")
        if self.tray:
            self.tray.stop()
        threading.Timer(0.5, lambda: os._exit(0)).start()

    def _preload_model(self):
        try:
            self.overlay.post("loading")
            self.transcriber.load()
            self.overlay.post("hide")
            log(f"model '{self.transcriber.model_name}' loaded")
        except Exception as e:
            log(f"model load failed: {e}\n{traceback.format_exc()}")
            self.overlay.post("error")

    def run(self):
        self._register_hotkeys()
        self.tray = build_tray(self)
        threading.Thread(target=self.tray.run, daemon=True).start()
        threading.Thread(target=self._preload_model, daemon=True).start()
        log(f"WhispLocal {__version__} started — hotkey: {self.hotkey}, "
            f"model: {self.transcriber.model_name}")
        self.overlay.run()  # tkinter main loop (main thread)


if __name__ == "__main__":
    guard = acquire_single_instance()
    if guard is None:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo(
            "WhispLocal",
            "WhispLocal is already running — look for the mic icon "
            "in the system tray.")
        sys.exit(0)
    try:
        App().run()
    except Exception as e:  # pythonw has no console — surface fatal errors
        log(f"fatal: {e}\n{traceback.format_exc()}")
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(
                "WhispLocal failed to start",
                f"{e}\n\nDetails are in whisp.log.")
        except Exception:
            pass
        sys.exit(1)
