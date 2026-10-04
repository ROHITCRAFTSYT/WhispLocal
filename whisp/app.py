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

import appcontext
import chords
import configio
import cues
import editing
import obsidian
import planner
import snippets
import styles
from adaptive import Adaptive
from audio import Recorder, SILENCE_RMS, rms, scan_mics
from bridge import Bridge, PageProxy
from cleanup import clean
from commands import CommandEngine, heard_part, parse, speak
from inject import insert
from locallm import LocalLLM
from overlay import Overlay
from recovery import LastTake, Ledger
from settings import HistoryWindow, SettingsWindow, StatsWindow
from streaming import StreamingTranscriber
from transcriber import Transcriber
from tray import build_tray

__version__ = "3.0.0"

HISTORY_PATH = os.path.join(APP_DIR, "history.jsonl")
LOG_PATH = os.path.join(APP_DIR, "whisp.log")
MAX_LOG_BYTES = 256 * 1024
MAX_HISTORY_BYTES = 1024 * 1024

TAP_THRESHOLD = 0.35  # seconds; shorter press = toggle mode
SINGLE_INSTANCE_PORT = 48917

# States
IDLE, HOLDING, LOCKED, STOPPING = "idle", "holding", "locked", "stopping"


class _LockedEngine:
    """Serialise live partials against the final transcription: skip a partial
    rather than hit the shared faster-whisper model from two threads at once."""

    def __init__(self, transcriber, lock):
        self._transcriber = transcriber
        self._lock = lock

    def transcribe(self, audio, **kw):
        if not self._lock.acquire(blocking=False):
            return "", None, None  # a real transcription holds the model; skip
        try:
            return self._transcriber.transcribe(audio, **kw)
        finally:
            self._lock.release()


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
        # Optional local-LLM fallback for genuinely novel commands (off by
        # default; needs a model path in Settings). Runs in the background
        # only when every fast pattern match fails, so replies are never
        # slowed by it.
        self.llm = LocalLLM(self.config.get("llm_model_path", ""))
        # Browser bridge: a localhost WebSocket server the companion extension
        # connects to. Degrades to a no-op if 'websockets' is missing or the
        # bridge is disabled in config, so ("page", ...) commands just report a
        # hint and the desktop experience is unchanged.
        self.bridge = Bridge(APP_DIR, config=self.config, log=log)
        self.page = PageProxy(self.bridge)
        self.commands = CommandEngine(
            note_saver=self._save_note,
            profile_saver=self._save_profile,
            on_action=self._on_command,
            on_open_settings=self.open_settings,
            llm=(self.llm.understand if self.config.get("llm_enabled",
                                                        False) else None),
            on_llm_done=self._on_llm_done,
            phrase_learner=self._learn_llm_phrase,
            page=self.page)
        # Reinforcement: ambiguous app names resolve to the one used most.
        self.commands.usage = self.adaptive.app_counts
        # Phrases the user corrected in History (heard -> corrected).
        self.commands.set_learned_phrases(self.adaptive.command_phrases())
        self.overlay = Overlay(
            get_levels=lambda: list(self.recorder.levels),
            position=self.config.get("overlay_position", "bottom-center"))
        self.state = IDLE
        self.task = "transcribe"
        self.active_key = None
        self.paused = False
        self.press_time = 0.0
        self.lock = threading.Lock()
        # faster-whisper is shared: run transcriptions one at a time so two
        # quick dictations cannot interleave inserts or hit the model from
        # two threads at once.
        self._process_lock = threading.Lock()
        # Set once the model finishes (pre)loading; the mic scan waits on
        # this before showing its result so the startup "hide" from the
        # model thread cannot swallow the message.
        self._model_ready = threading.Event()
        self.hotkey = self.config.get("hotkey", "right ctrl")
        self.tray = None
        self._hooks = []
        # Multi-key hold chords ("ctrl+windows"): (matcher, key_id) pairs
        # fed from one raw keyboard hook.
        self._chords = []
        # Live partial transcription: created per-recording when enabled.
        self._streamer = None
        # Where the current take will land (app, category, text before the
        # caret), captured when recording starts.
        self._ctx_future = None
        self._take_id = 0
        # Never lose a dictation: the last take (DPAPI-encrypted) for
        # "Retry last recording", and the last inserted text.
        self.last_take = LastTake(APP_DIR)
        self.ledger = Ledger()
        # Incognito: nothing is saved, learned or retained while on.
        self.incognito = False

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
                # Same lock the hotkey state machine uses, so this cannot
                # race the auto-select scan or an in-flight recording.
                with self.lock:
                    self.recorder = Recorder(device)

            # Swap the transcriber under the pipeline lock so an in-flight
            # transcription never picks up a half-updated object mid-call.
            with self._process_lock:
                new_t = Transcriber(self.config)
                old_t = self.transcriber
                if new_t.model_name != old_t.model_name:
                    self.transcriber = new_t  # loads lazily next dictation
                else:
                    # Keep the loaded model; just adopt the new options.
                    old_t.language = new_t.language
                    old_t.beam_size = new_t.beam_size
                    old_t.cpu_threads = new_t.cpu_threads
                    old_t.script = new_t.script
            if not self.config.get("retain_last_take", True):
                self.last_take.clear()
            self.adaptive.enabled = self.config.get("adaptive_learning", True)
            # Rebuild the LLM fallback from the new config and rewire it
            # into the engine (a new model path / enabled flag applies
            # without a restart).
            self.llm = LocalLLM(self.config.get("llm_model_path", ""))
            self.commands.llm = (self.llm.understand
                                 if self.config.get("llm_enabled", False)
                                 else None)
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

    def _on_llm_done(self, ok, feedback):
        """Announce the result of a background local-LLM resolution, so
        the user learns what the novel phrase meant."""
        self.overlay.post(("message", feedback or "Done", ok))
        if ok and self.config.get("voice_replies", True):
            speak(feedback)
        log(f"llm command resolved: ok={ok} {feedback!r}")

    def _learn_llm_phrase(self, heard, canonical):
        """Persist a successful LLM resolution as a learned phrase so the
        same utterance resolves instantly next time (no model call)."""
        n = self.adaptive.learn_command(heard, canonical)
        if n:
            self.commands.set_learned_phrases(
                self.adaptive.command_phrases())
            log(f"learned LLM-resolved phrase: {heard!r} -> {canonical!r}")

    def _on_command(self, kind, arg, ok):
        """Learn from each executed command and refresh the profile note
        periodically so Obsidian stays current."""
        if not ok:
            return
        label = topic = None
        if kind in ("open_app", "open_web", "close_app", "download"):
            label = arg if isinstance(arg, str) else None
        elif kind == "order" and isinstance(arg, tuple):
            # Learn which ordering sites the user names, so ambiguous
            # site mentions resolve to the one used most.
            label = arg[1] if isinstance(arg[1], str) else None
        elif kind in ("search", "lookup", "market", "booking", "youtube"):
            topic = arg if isinstance(arg, str) else None
        elif kind == "site_search" and isinstance(arg, tuple):
            # "open youtube and search for X": the site is the label,
            # the query is the topic — both feed the learning profile.
            label, topic = arg[0] or None, arg[1] or None
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

    def teach_correction(self, original, corrected, task="transcribe"):
        """Learn from a History correction. Dictation corrections become
        word-level dictionary entries; command corrections become whole
        phrase mappings (heard -> corrected) the engine can resolve, so
        the same sentence works the next time it is said."""
        if task == "command":
            # History stores commands as "heard -> feedback"; extract the
            # heard phrase so it maps to the user's corrected command.
            heard = heard_part(original)
            # Only teach phrases that are themselves valid commands, so
            # the map never learns something the engine cannot resolve.
            if not parse(corrected):
                log(f"command correction ignored — {corrected!r} is not "
                    "a command")
                return 0
            n = self.adaptive.learn_command(heard, corrected)
            if n:
                self.commands.set_learned_phrases(
                    self.adaptive.command_phrases())
                log(f"learned command phrase: {heard!r} -> {corrected!r}")
            return n
        n = self.adaptive.learn_correction(original, corrected)
        if n:
            log(f"learned {n} correction(s)")
        return n

    def toggle_pause(self):
        self.paused = not self.paused
        if self.tray:
            self.tray.update_menu()

    def toggle_incognito(self):
        """While on: no history, no learning, no retained audio."""
        self.incognito = not self.incognito
        if self.incognito:
            self.last_take.clear()
        if self.tray:
            self.tray.update_menu()
        self.overlay.post(("message",
                           "Incognito on: nothing is saved" if self.incognito
                           else "Incognito off", True))
        log(f"incognito {'on' if self.incognito else 'off'}")

    def paste_last(self):
        """Insert the last dictation again (for when it landed in the
        wrong window or the paste was blocked)."""
        text = self.ledger.last()
        if not text:
            self.overlay.post(("message", "Nothing dictated yet", False))
            return

        def _run():
            time.sleep(0.25)  # let the tray menu close and focus return
            insert(text, self.config)
        threading.Thread(target=_run, daemon=True).start()

    def retry_last(self):
        """Re-run the last recording through the pipeline (after a failure,
        or with a different model or language)."""
        audio, meta = self.last_take.load()
        if audio is None:
            self.overlay.post(("message", "No recent recording to retry",
                               False))
            return
        task = (meta or {}).get("task", "transcribe")
        if task not in ("transcribe", "translate"):
            task = "transcribe"
        self.overlay.post("transcribing")

        def _run():
            time.sleep(0.25)
            self._ctx_future = appcontext.capture_async(
                read_text=self.config.get("read_context", True))
            self._process(audio, task)
        threading.Thread(target=_run, daemon=True).start()

    # ----- windows ----------------------------------------------------------
    def open_settings(self):
        self.overlay.call(lambda: SettingsWindow(self.overlay.root, self))

    def open_history(self):
        self.overlay.call(
            lambda: HistoryWindow(self.overlay.root, HISTORY_PATH, app=self))

    def open_stats(self):
        self.overlay.call(
            lambda: StatsWindow(self.overlay.root, HISTORY_PATH))

    # ----- sounds -----------------------------------------------------------
    def _cue(self, name):
        cues.play(name, enabled=self.config.get("sound_cues", True))

    # ----- hotkey state machine ----------------------------------------------
    def _register_hotkeys(self):
        # Re-registering removes the release handler; if a recording is in
        # flight it would never get its stop event — abort it first.
        if self.state != IDLE:
            self._stop_streaming()
            self.recorder.abort()
            self.state = IDLE
            self.overlay.post("hide")
        for h in self._hooks:
            try:
                keyboard.unhook(h)
            except (KeyError, ValueError):
                pass
        self._hooks = []
        self._chords = []
        pairs = [(self.hotkey, "main")]
        for cfg_key, key_id in (("translate_hotkey", "translate"),
                                ("command_hotkey", "command"),
                                ("edit_hotkey", "edit")):
            key = (self.config.get(cfg_key) or "").strip()
            if key:
                pairs.append((key, key_id))
        for key, key_id in pairs:
            if chords.is_chord(key):
                self._chords.append((chords.ChordMatcher(key), key_id))
                continue
            self._hooks.append(keyboard.on_press_key(
                key, lambda e, k=key_id: self.on_press(k), suppress=False))
            self._hooks.append(keyboard.on_release_key(
                key, lambda e, k=key_id: self.on_release(k), suppress=False))
        if self._chords:
            self._hooks.append(keyboard.hook(self._on_chord_event))

    def _on_chord_event(self, event):
        """Raw key events -> chord press/release for multi-key hotkeys."""
        for matcher, key_id in self._chords:
            edge = matcher.feed(event.event_type, event.name)
            if edge == "press":
                self.on_press(key_id)
            elif edge == "release":
                self.on_release(key_id)

    def _resolve_task(self, key_id):
        if key_id == "main":
            return ("command" if self.config.get("mode") == "command"
                    else "transcribe")
        return key_id  # "translate", "command" or "edit"

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
        # Snapshot the target app before our own overlay appears. Reading
        # the text before the caret happens on a worker thread.
        self._ctx_future = appcontext.capture_async(
            read_text=(self.config.get("read_context", True)
                       and self.task in ("transcribe", "translate")))
        try:
            self.recorder.start()
            state = {"translate": "recording_translate",
                     "command": "recording_command",
                     "edit": "recording_edit"}.get(self.task, "recording")
            self.overlay.post(state)
            self._cue("edit" if self.task == "edit" else "start")
            self._start_streaming()
            self._arm_take_limit()
            log(f"recording on {self.recorder.device or 'default mic'} "
                f"@{self.recorder._sample_rate} Hz")
        except Exception as e:
            self.state = IDLE
            log(f"mic error: {e}\n{traceback.format_exc()}")
            self.overlay.post(("message",
                               "Microphone error — check Settings → "
                               "Microphone and Windows privacy", False))

    def _start_streaming(self):
        """Begin live partial transcription for this recording, if enabled."""
        self._streamer = None
        if not self.config.get("live_partials", False):
            return
        if self.task not in ("transcribe", "translate"):
            return
        self._streamer = StreamingTranscriber(
            self.recorder,
            _LockedEngine(self.transcriber, self._process_lock),
            lambda text: self.overlay.post(("partial", text)),
            hotwords_fn=self._hotwords,
            language=self.config.get("language") or None,
        )
        self._streamer.start(self.task)

    def _stop_streaming(self):
        if self._streamer is not None:
            self._streamer.stop()
            self._streamer = None

    def _arm_take_limit(self):
        """Stop a forgotten locked recording after max_take_seconds, so a
        stuck key or an accidental lock cannot record forever."""
        self._take_id += 1
        limit = float(self.config.get("max_take_seconds", 0) or 0)
        if limit <= 0:
            return
        timer = threading.Timer(limit, self._take_limit_hit,
                                args=(self._take_id,))
        timer.daemon = True
        timer.start()

    def _take_limit_hit(self, take_id):
        with self.lock:
            if take_id != self._take_id or self.state not in (HOLDING,
                                                               LOCKED):
                return
            log("take limit reached; stopping the recording")
            # IDLE (not STOPPING): a key still held down sends a release
            # that must be ignored, and a later press starts a new take.
            self.state = IDLE
            self._finish_recording()

    def _finish_recording(self):
        # Note: does not touch self.state — callers own the transition.
        # Stop live partials before the final pass so they never race the model.
        self._stop_streaming()
        self._take_id += 1  # disarm the take-limit timer
        self._cue("stop")
        audio = self.recorder.stop()
        if audio is None or len(audio) < 4000:  # < 0.25 s — ignore blips
            self.overlay.post("hide")
            return
        level = rms(audio)
        if level < SILENCE_RMS:
            # The mic delivered no signal (muted, wrong device, or Windows
            # privacy blocking access). Say so instead of silently doing
            # nothing after a "transcribing…" wait.
            log(f"no voice detected (rms={level:.5f}) on "
                f"{self.recorder.device or 'default mic'}")
            self.overlay.post(("message",
                               "No voice detected — is the mic on? "
                               "Check Settings → Microphone and Windows "
                               "privacy", False))
            return
        self.overlay.post({"translate": "translate", "command": "thinking",
                           "edit": "editing"}.get(self.task, "transcribing"))
        if self.task in ("transcribe", "translate"):
            self._retain(audio, self.task)
        threading.Thread(target=self._process, args=(audio, self.task),
                         daemon=True).start()

    def _retain(self, audio, task):
        """Keep this take (encrypted) so it can be retried from the tray."""
        if self.incognito or not self.config.get("retain_last_take", True):
            return

        def _run():
            try:
                self.last_take.save(audio, {"task": task})
            except Exception as e:
                log(f"could not retain take: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def _context(self, timeout=0.4):
        future, self._ctx_future = self._ctx_future, None
        return future(timeout) if future else appcontext.Context()

    def _hotwords(self):
        """Recognition hints: your vocabulary list plus learned words."""
        vocab = " ".join(self.config.get("vocabulary") or [])
        learned = self.adaptive.hotwords() or ""
        return (vocab + " " + learned).strip() or None

    # ----- pipeline -------------------------------------------------------
    def _process(self, audio, task):
        with self._process_lock:
            if task == "command":
                self._process_command(audio)
                return
            if task == "edit":
                self._process_edit(audio)
                return
            self._process_transcribe(audio, task)

    def _process_transcribe(self, audio, task):
        try:
            t0 = time.time()
            hot = self._hotwords()
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
            raw = text
            ctx = self._context()
            text = self._format(text, ctx)
            if text:
                self._deliver(text, ctx)
                if task == "transcribe" and not self.incognito \
                        and not ctx.secure:
                    self.adaptive.record(text, lang)
                self._save_history(text, task, len(audio) / 16000,
                                   time.time() - t0, app=ctx.exe,
                                   raw=raw)
            else:
                self.overlay.post("hide")
        except Exception as e:
            log(f"pipeline error: {e}\n{traceback.format_exc()}")
            self._cue("error")
            self.overlay.post(("message", "Dictation failed. Tray > Retry "
                               "last recording", False))

    def _format(self, text, ctx):
        """Raw transcript -> final text for this app: cleanup, spoken
        shortcuts, the app's writing style, optional local-LLM polish, and
        fitting it to the text already before the caret."""
        cfg = dict(self.config)
        cfg["dictionary"] = {**(self.config.get("dictionary") or {}),
                             **self.adaptive.learned_dictionary}
        text = clean(text, cfg)
        if not text:
            return text
        text, exact = snippets.expand(text, self.config.get("snippets") or {})
        if exact:
            return text  # a spoken shortcut is inserted exactly as saved
        preset = "standard"
        if self.config.get("context_styles", True):
            preset = styles.resolve_preset(ctx.category, ctx.exe, self.config)
            text = styles.apply(text, preset, ctx.category, self.config)
        if (self.config.get("llm_polish") and self.llm.configured()
                and preset != "verbatim" and len(text.split()) >= 4):
            polished = self.llm.polish(text, preset)
            if polished:
                text = polished
        keep = list(self.config.get("vocabulary") or []) + list(
            (self.config.get("dictionary") or {}).values())
        text = planner.plan(text, ctx.before, keep_caps=keep)
        log(f"formatted for {ctx.label()} ({ctx.category}/{preset})")
        return text

    def _deliver(self, text, ctx):
        """Insert at the cursor, or, when nothing can receive text (the
        desktop or taskbar is focused), keep it on the clipboard instead of
        losing it."""
        self.ledger.record(text, ctx.exe)
        if not ctx.has_target:
            try:
                import pyperclip
                pyperclip.copy(text)
            except Exception:
                pass
            self._cue("copied")
            self.overlay.post(("message", "No text field focused: copied "
                               "to clipboard", True))
            return
        insert(text, self.config)
        self.overlay.post("done")

    def _wait_hotkey_release(self, timeout=1.5):
        """Synthetic Ctrl+C/Ctrl+V must not mix with a still-held hotkey
        (Alt+Ctrl+C is a different shortcut)."""
        key = (self.config.get("edit_hotkey") or "").strip()
        parts = chords.parse(key) if key else []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if not any(keyboard.is_pressed(p) for p in parts):
                    return
            except Exception:
                return
            time.sleep(0.03)

    def _process_edit(self, audio):
        """Voice editing: transform the selection by a spoken instruction,
        or write new text at the cursor when nothing is selected."""
        try:
            ctx = self._context()
            instruction, _lang, _prob = self.transcriber.transcribe(
                audio, task="transcribe", hotwords=self._hotwords())
            instruction = (instruction or "").strip()
            if not instruction:
                self.overlay.post("hide")
                return
            if ctx.secure:
                self.overlay.post(("message", "Editing is off in password "
                                   "fields", False))
                return
            self._wait_hotkey_release()
            selection = editing.capture_selection()
            if selection is None:
                self.overlay.post(("message", "Clipboard busy, try again",
                                   False))
                return
            if selection.strip():
                new, desc = editing.apply_rules(instruction, selection)
                if new is None and self.llm.configured():
                    self.overlay.post(("message", "Thinking (local LLM)",
                                       True))
                    new = self.llm.rewrite(instruction, selection)
                    desc = "rewritten"
                if new is None:
                    self.overlay.post(("message", "Didn't understand that "
                                       "edit. Set a local LLM in Settings "
                                       "for free-form edits", False))
                    return
            else:
                if not self.llm.configured():
                    self.overlay.post(("message", "Select text first (or "
                                       "set a local LLM to write new text)",
                                       False))
                    return
                self.overlay.post(("message", "Writing (local LLM)", True))
                new = self.llm.author(instruction, ctx.category)
                desc = "written"
                if not new:
                    self.overlay.post(("message", "The local LLM gave no "
                                       "answer", False))
                    return
            insert(new, self.config)
            self.ledger.record(new, ctx.exe)
            self._cue("done")
            self.overlay.post(("message", f"Edited: {desc}", True))
            log(f"edit: {instruction!r} -> {desc} ({len(new)} chars)")
            self._save_history(f"{instruction} -> {new}", "edit",
                               len(audio) / 16000, 0, app=ctx.exe)
        except Exception as e:
            log(f"edit error: {e}\n{traceback.format_exc()}")
            self._cue("error")
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
            # Make sure the app index is built before resolving, so a command
            # right after startup does not miss an installed app.
            self.commands.wait_ready(3.0)
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

    def _save_history(self, text, task, audio_secs, proc_secs, app="",
                      raw=None):
        if not self.config.get("save_history", True) or self.incognito:
            return
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "task": task,
            "audio_s": round(audio_secs, 1),
            "processing_s": round(proc_secs, 1),
        }
        if app:
            entry["app"] = app
        if raw and raw != text:
            entry["raw"] = raw
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
        self.bridge.stop()
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
        finally:
            self._model_ready.set()

    def _auto_select_mic(self):
        """Background scan at startup: when no microphone is configured,
        pick the first device that delivers real audio above the silence
        threshold instead of trusting the (possibly dead) system default."""
        if not self.config.get("auto_select_mic", True):
            return
        if self.config.get("input_device"):
            return  # an explicit choice always wins
        try:
            log("auto mic scan: probing input devices...")
            found = scan_mics()
            # The user may have picked a device in Settings while the scan
            # ran — respect that instead of overwriting it.
            if self.config.get("input_device"):
                return
            if found:
                cfg = dict(self.config)
                cfg["input_device"] = found
                self.save_config(cfg)
                # Swap under the same lock the hotkey state machine uses,
                # so a recording in flight cannot race the replacement.
                with self.lock:
                    if not self.recorder.active:
                        self.recorder = Recorder(found)
                log(f"auto mic scan: selected '{found}'")
            else:
                log("auto mic scan: no device delivered audio (muted, "
                    "privacy-blocked, or unplugged)")
            # Wait for the model to finish loading so its startup "hide"
            # lands first and cannot clear our result message.
            self._model_ready.wait(timeout=30)
            if found:
                self.overlay.post(("message", f"Mic found: {found}", True))
            else:
                self.overlay.post(("message",
                                   "No working mic found — check Settings "
                                   "and Windows privacy", False))
        except Exception as e:
            log(f"auto mic scan failed: {e}\n{traceback.format_exc()}")
            self.overlay.post("hide")

    def run(self):
        self._register_hotkeys()
        self.tray = build_tray(self)
        threading.Thread(target=self.tray.run, daemon=True).start()
        threading.Thread(target=self._preload_model, daemon=True).start()
        threading.Thread(target=self._auto_select_mic, daemon=True).start()
        if self.config.get("bridge_enabled", True):
            self.bridge.start()
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
