"""Settings and History windows (tkinter). Opened from the tray menu;
always constructed on the tkinter main thread via Overlay.call()."""
import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from overlay import POSITIONS

MODELS = ["tiny", "tiny.en", "base", "base.en", "small", "small.en"]
LANGUAGES = ["auto", "en", "hi", "es", "fr", "de", "it", "pt", "ru",
             "ja", "ko", "zh", "ar", "bn", "ta", "te", "mr", "gu", "ur", "pa"]

MODEL_HINTS = {
    "tiny": "fastest, lowest accuracy",
    "tiny.en": "fastest, English only",
    "base": "recommended — good balance",
    "base.en": "recommended for English only",
    "small": "most accurate, ~2.5x slower",
    "small.en": "most accurate, English only",
}


def list_input_devices():
    import sounddevice as sd
    names = []
    for dev in sd.query_devices():
        if dev["max_input_channels"] > 0 and dev["name"] not in names:
            names.append(dev["name"])
    return names


class SettingsWindow:
    def __init__(self, root, app):
        self.app = app
        cfg = app.config
        self.win = tk.Toplevel(root)
        self.win.title("WhispLocal Settings")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        f = ttk.Frame(self.win, padding=14)
        f.grid()
        row = 0

        def label(text):
            nonlocal row
            ttk.Label(f, text=text).grid(row=row, column=0, sticky="w", pady=3)

        label("Model")
        self.model = ttk.Combobox(f, values=MODELS, state="readonly", width=24)
        self.model.set(cfg.get("model", "base"))
        self.model.grid(row=row, column=1, sticky="w", pady=3)
        self.hint = ttk.Label(f, foreground="#666")
        self.hint.grid(row=row + 1, column=1, sticky="w")
        self.model.bind("<<ComboboxSelected>>", lambda e: self._hint())
        self._hint()
        row += 2

        label("Language")
        self.language = ttk.Combobox(f, values=LANGUAGES, state="readonly", width=24)
        self.language.set(cfg.get("language") or "auto")
        self.language.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label("Microphone")
        devices = ["System default"]
        try:
            devices += list_input_devices()
        except Exception:
            pass
        mic_row = ttk.Frame(f)
        mic_row.grid(row=row, column=1, sticky="w", pady=3)
        self.mic = ttk.Combobox(mic_row, values=devices, state="readonly",
                                width=34)
        self.mic.set(cfg.get("input_device") or "System default")
        self.mic.pack(side="left")
        self.scan_button = ttk.Button(mic_row, text="Scan for best…",
                                      width=13, command=self._scan_mic)
        self.scan_button.pack(side="left", padx=(6, 0))
        row += 1
        self.scan_status = ttk.Label(f, foreground="#666")
        self.scan_status.grid(row=row, column=1, sticky="w")
        row += 1

        label("Dictation hotkey")
        self.hotkey = ttk.Entry(f, width=26)
        self.hotkey.insert(0, cfg.get("hotkey", "right ctrl"))
        self.hotkey.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label("Translate-to-English hotkey")
        self.tr_hotkey = ttk.Entry(f, width=26)
        self.tr_hotkey.insert(0, cfg.get("translate_hotkey", ""))
        self.tr_hotkey.grid(row=row, column=1, sticky="w", pady=3)
        ttk.Label(f, text="(blank = disabled; e.g. f9, right alt)",
                  foreground="#666").grid(row=row + 1, column=1, sticky="w")
        row += 2

        label("Voice control hotkey")
        self.cmd_hotkey = ttk.Entry(f, width=26)
        self.cmd_hotkey.insert(0, cfg.get("command_hotkey", ""))
        self.cmd_hotkey.grid(row=row, column=1, sticky="w", pady=3)
        ttk.Label(f, text='(blank = disabled; say "open chrome", "volume up"...)',
                  foreground="#666").grid(row=row + 1, column=1, sticky="w")
        row += 2

        label("Insert method")
        self.insert_mode = ttk.Combobox(
            f, values=["paste", "type"], state="readonly", width=24)
        self.insert_mode.set(cfg.get("insert_mode", "paste"))
        self.insert_mode.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label("On-screen bar position")
        self.overlay_pos = ttk.Combobox(
            f, values=list(POSITIONS), state="readonly", width=24)
        self.overlay_pos.set(cfg.get("overlay_position", "bottom-center"))
        self.overlay_pos.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label("Obsidian vault (for notes)")
        vault_row = ttk.Frame(f)
        vault_row.grid(row=row, column=1, sticky="w", pady=3)
        self.vault = ttk.Entry(vault_row, width=32)
        self.vault.insert(0, cfg.get("obsidian_vault", ""))
        self.vault.pack(side="left")
        ttk.Button(vault_row, text="Browse…", width=8,
                   command=self._pick_vault).pack(side="left", padx=4)
        row += 1

        label("Accuracy (beam size 1–5)")
        self.beam = ttk.Spinbox(f, from_=1, to=5, width=6)
        self.beam.set(cfg.get("beam_size", 2))
        self.beam.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # Optional local-LLM fallback for genuinely novel commands. Off by
        # default; a GGUF file (llama.cpp) or an ONNX model folder turns it
        # on. It only runs after every fast pattern match fails, on a
        # background thread, so reply latency is untouched.
        label("Local LLM fallback model")
        llm_row = ttk.Frame(f)
        llm_row.grid(row=row, column=1, sticky="w", pady=3)
        self.llm_path = ttk.Entry(llm_row, width=30)
        self.llm_path.insert(0, cfg.get("llm_model_path", ""))
        self.llm_path.pack(side="left")
        ttk.Button(llm_row, text="Browse…", width=8,
                   command=self._pick_llm).pack(side="left", padx=4)
        ttk.Button(llm_row, text="Test", width=6,
                   command=self._test_llm).pack(side="left", padx=4)
        row += 1
        self.llm_status = ttk.Label(
            f, foreground="#666",
            text="(optional) GGUF for llama.cpp, or an ONNX model folder")
        self.llm_status.grid(row=row, column=1, sticky="w")
        row += 1

        self.flags = {}
        for key, text, default in [
            ("remove_fillers", "Remove filler words (um, uh…)", True),
            ("capitalize_first", "Auto-capitalize sentences", True),
            ("strip_trailing_period", "Strip trailing period (chat style)", False),
            ("sound_cues", "Sound cues on start/stop", True),
            ("auto_select_mic",
             "Auto-select a working microphone at startup", True),
            ("save_history", "Save dictation history", True),
            ("restore_clipboard", "Restore clipboard after paste", True),
            ("live_partials",
             "Show words live as I speak (experimental)", False),
            ("adaptive_learning",
             "Learn my vocabulary and languages (stored locally)", True),
            ("llm_enabled",
             "Use the local LLM for commands I don't recognize yet (offline)",
             False),
            ("voice_replies", "Speak confirmations in voice control mode", True),
        ]:
            var = tk.BooleanVar(value=bool(cfg.get(key, default)))
            ttk.Checkbutton(f, text=text, variable=var).grid(
                row=row, column=0, columnspan=2, sticky="w")
            self.flags[key] = var
            row += 1

        ttk.Label(f, text="Custom dictionary (one per line: heard => replacement)"
                  ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))
        row += 1
        self.dict_text = tk.Text(f, width=48, height=5, font=("Consolas", 9))
        self.dict_text.grid(row=row, column=0, columnspan=2, sticky="w")
        for wrong, right in (cfg.get("dictionary") or {}).items():
            self.dict_text.insert("end", f"{wrong} => {right}\n")
        row += 1

        btns = ttk.Frame(f)
        btns.grid(row=row, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btns, text="Save & Apply", command=self.save).pack(
            side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.win.destroy).pack(side="left")

    def _hint(self):
        self.hint.config(text=MODEL_HINTS.get(self.model.get(), ""))

    def _scan_mic(self):
        """Probe every input device off the UI thread and offer the first
        working one. Results are marshaled back onto the tkinter thread
        via the app's overlay queue (the codebase's thread-safe pattern)."""
        from audio import scan_mics
        self.scan_button.config(state="disabled", text="Scanning…")
        self.scan_status.config(text="Probing input devices… (a few seconds)",
                                foreground="#666")

        def _run():
            # scan_mics() runs on this worker thread; the result is
            # marshaled to the tkinter thread via the overlay queue.
            name = scan_mics()
            self.app.overlay.call(lambda: self._scan_done(name))

        threading.Thread(target=_run, daemon=True).start()

    def _scan_done(self, name):
        # The window may have been closed while the scan ran — never touch
        # dead widgets, or tkinter raises TclError inside its main loop.
        if not self.win.winfo_exists():
            return
        self.scan_button.config(state="normal", text="Scan for best…")
        self.scan_status.config(
            text=(f"Selected: {name} (press Save to apply)" if name else
                  "No working mic found — check Windows mic privacy"),
            foreground="#2a7" if name else "#c44")
        if name:
            self.mic.set(name)

    def _pick_llm(self):
        path = filedialog.askopenfilename(
            parent=self.win, title="Select a local LLM model",
            filetypes=[("GGUF model", "*.gguf"),
                       ("ONNX model", "*.onnx"),
                       ("All files", "*.*")])
        if path:
            self.llm_path.delete(0, "end")
            self.llm_path.insert(0, os.path.normpath(path))
            self._test_llm()

    def _test_llm(self):
        """Load the configured model off the UI thread and report the
        result — the same thread-safe pattern as the mic scan."""
        from locallm import LocalLLM
        path = self.llm_path.get().strip()
        if not path:
            self.llm_status.config(text="Enter a model path first.",
                                   foreground="#c44")
            return
        self.llm_status.config(text="Loading model… (may take a moment)",
                               foreground="#666")

        def _run():
            llm = LocalLLM(path)
            llm.load()  # force the lazy load so the status is truthful
            self.app.overlay.call(lambda: self._llm_done(llm))

        threading.Thread(target=_run, daemon=True).start()

    def _llm_done(self, llm):
        if not self.win.winfo_exists():
            return
        ok = llm.healthy()
        self.llm_status.config(text=llm.describe(),
                               foreground="#2a7" if ok else "#c44")

    def _pick_vault(self):
        path = filedialog.askdirectory(
            parent=self.win, title="Select your Obsidian vault folder")
        if path:
            self.vault.delete(0, "end")
            self.vault.insert(0, os.path.normpath(path))

    def save(self):
        import keyboard
        hotkey = self.hotkey.get().strip().lower()
        tr_hotkey = self.tr_hotkey.get().strip().lower()
        cmd_hotkey = self.cmd_hotkey.get().strip().lower()
        for name, k in [("Dictation hotkey", hotkey),
                        ("Translate hotkey", tr_hotkey),
                        ("Voice control hotkey", cmd_hotkey)]:
            if not k:
                continue
            try:
                keyboard.key_to_scan_codes(k)
            except ValueError:
                messagebox.showerror("WhispLocal",
                                     f"{name} '{k}' is not a valid key name.",
                                     parent=self.win)
                return
        if not hotkey:
            messagebox.showerror("WhispLocal", "Dictation hotkey cannot be empty.",
                                 parent=self.win)
            return
        used = [k for k in (hotkey, tr_hotkey, cmd_hotkey) if k]
        if len(used) != len(set(used)):
            messagebox.showerror("WhispLocal",
                                 "Each hotkey must be a different key.",
                                 parent=self.win)
            return

        dictionary = {}
        for line in self.dict_text.get("1.0", "end").splitlines():
            if "=>" in line:
                wrong, _, right = line.partition("=>")
                if wrong.strip() and right.strip():
                    dictionary[wrong.strip()] = right.strip()

        cfg = dict(self.app.config)
        lang = self.language.get()
        mic = self.mic.get()
        cfg.update({
            "model": self.model.get(),
            "language": None if lang == "auto" else lang,
            "input_device": None if mic == "System default" else mic,
            "hotkey": hotkey,
            "translate_hotkey": tr_hotkey,
            "command_hotkey": cmd_hotkey,
            "insert_mode": self.insert_mode.get(),
            "overlay_position": self.overlay_pos.get(),
            "obsidian_vault": self.vault.get().strip(),
            "beam_size": max(1, min(5, int(self.beam.get() or 2))),
            "llm_model_path": self.llm_path.get().strip(),
            "dictionary": dictionary,
        })
        for key, var in self.flags.items():
            cfg[key] = bool(var.get())

        self.app.save_config(cfg)
        self.app.reload_config()
        self.win.destroy()


class HistoryWindow:
    def __init__(self, root, history_path, app=None):
        self.app = app
        self.win = tk.Toplevel(root)
        self.win.title("WhispLocal History")
        self.win.attributes("-topmost", True)
        self.win.geometry("600x440")
        frame = ttk.Frame(self.win, padding=8)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Recent dictations (newest first). Double-click "
                              "to copy. Select a line and press Correct to "
                              "teach the app what you actually said."
                  ).pack(anchor="w")
        self.listbox = tk.Listbox(frame, font=("Segoe UI", 10))
        self.listbox.pack(fill="both", expand=True, pady=6)
        self.entries = []
        if os.path.exists(history_path):
            with open(history_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        self.entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        self.entries.reverse()
        for e in self.entries[:200]:
            self.listbox.insert("end", f"[{e.get('ts', '?')}]  {e.get('text', '')}")
        self.listbox.bind("<Double-Button-1>", self._copy)
        bottom = ttk.Frame(frame)
        bottom.pack(fill="x")
        self.status = ttk.Label(bottom, text=f"{len(self.entries)} entries")
        self.status.pack(side="left")
        if app is not None:
            ttk.Button(bottom, text="Correct…", command=self._correct).pack(
                side="right")

    def _copy(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        import pyperclip
        pyperclip.copy(self.entries[sel[0]].get("text", ""))
        self.status.config(text="Copied to clipboard.")

    def _correct(self):
        sel = self.listbox.curselection()
        if not sel:
            self.status.config(text="Select a dictation first.")
            return
        entry = self.entries[sel[0]]
        original = entry.get("text", "")
        task = entry.get("task", "transcribe")
        # Command entries store "heard -> feedback"; the user wants to fix
        # the heard phrase, not the result note.
        if task == "command":
            from commands import heard_part
            original = heard_part(original)
        dlg = tk.Toplevel(self.win)
        dlg.title("Teach a correction")
        dlg.attributes("-topmost", True)
        f = ttk.Frame(dlg, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="What the app heard:").pack(anchor="w")
        ttk.Label(f, text=original, wraplength=460,
                  foreground="#666").pack(anchor="w", pady=(0, 8))
        ttk.Label(f, text="What you actually said (edit below):").pack(anchor="w")
        box = tk.Text(f, width=60, height=4, font=("Segoe UI", 10), wrap="word")
        box.pack(pady=(2, 8))
        box.insert("1.0", original)

        def save():
            corrected = box.get("1.0", "end").strip()
            n = self.app.teach_correction(original, corrected, task=task)
            if task == "command":
                self.status.config(
                    text=(f"Learned: {corrected} will now work." if n else
                          "No new phrase to learn."))
            else:
                self.status.config(
                    text=f"Learned {n} correction(s)." if n else
                    "No word-level changes found to learn.")
            dlg.destroy()

        btns = ttk.Frame(f)
        btns.pack(anchor="e")
        ttk.Button(btns, text="Learn", command=save).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="left")
