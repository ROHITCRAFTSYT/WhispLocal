"""Settings, History and Stats windows (tkinter). Opened from the tray
menu; always constructed on the tkinter main thread via Overlay.call()."""
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

CATEGORY_LABELS = [
    ("email", "Email (Outlook, Gmail…)"),
    ("chat", "Chat (Slack, Discord, WhatsApp…)"),
    ("ai_chat", "AI chats (ChatGPT, Claude…)"),
    ("code", "Code editors (VS Code, Cursor…)"),
    ("notes", "Notes (Obsidian, Notion…)"),
    ("docs", "Documents (Word, Google Docs…)"),
    ("terminal", "Terminals"),
    ("general", "Everything else"),
]


def list_input_devices():
    import sounddevice as sd
    names = []
    for dev in sd.query_devices():
        if dev["max_input_channels"] > 0 and dev["name"] not in names:
            names.append(dev["name"])
    return names


def _pairs_to_text(mapping):
    return "".join(f"{k} => {v}\n" for k, v in (mapping or {}).items())


def _text_to_pairs(text):
    result = {}
    for line in text.splitlines():
        if "=>" in line:
            left, _, right = line.partition("=>")
            if left.strip() and right.strip():
                result[left.strip()] = right.strip()
    return result


def validate_hotkey(key):
    """True when every part of a key or chord ('ctrl+windows') is a key
    name the keyboard library knows."""
    import keyboard
    parts = [p.strip() for p in key.split("+") if p.strip()] or [key]
    try:
        for p in parts:
            keyboard.key_to_scan_codes(p)
    except ValueError:
        return False
    return True


class SettingsWindow:
    def __init__(self, root, app):
        import styles
        self.app = app
        cfg = app.config
        self.win = tk.Toplevel(root)
        self.win.title("WhispLocal Settings")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        outer = ttk.Frame(self.win, padding=10)
        outer.grid()
        nb = ttk.Notebook(outer)
        nb.grid(row=0, column=0)

        def tab(title):
            frame = ttk.Frame(nb, padding=12)
            nb.add(frame, text=title)
            return frame

        # ----- General ------------------------------------------------------
        f = tab("General")
        row = 0

        def label(parent, r, text):
            ttk.Label(parent, text=text).grid(row=r, column=0, sticky="w",
                                              pady=3)

        label(f, row, "Model")
        self.model = ttk.Combobox(f, values=MODELS, state="readonly", width=24)
        self.model.set(cfg.get("model", "base"))
        self.model.grid(row=row, column=1, sticky="w", pady=3)
        self.hint = ttk.Label(f, foreground="#666")
        self.hint.grid(row=row + 1, column=1, sticky="w")
        self.model.bind("<<ComboboxSelected>>", lambda e: self._hint())
        self._hint()
        row += 2

        label(f, row, "Language")
        self.language = ttk.Combobox(f, values=LANGUAGES, state="readonly",
                                     width=24)
        self.language.set(cfg.get("language") or "auto")
        self.language.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label(f, row, "Indian languages output")
        self.script = ttk.Combobox(
            f, values=["native script", "roman (Hinglish style)"],
            state="readonly", width=24)
        self.script.set("roman (Hinglish style)"
                        if cfg.get("indic_script") == "roman"
                        else "native script")
        self.script.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label(f, row, "Microphone")
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

        self.hotkeys = {}
        for key, text, hint in [
            ("hotkey", "Dictation hotkey",
             "single key or chord, e.g. right ctrl, ctrl+windows"),
            ("translate_hotkey", "Translate-to-English hotkey",
             "(blank = disabled; e.g. f9, right alt)"),
            ("command_hotkey", "Voice control hotkey",
             '(blank = disabled; say "open chrome", "volume up"...)'),
            ("edit_hotkey", "Voice edit hotkey",
             '(blank = disabled; select text, hold, say "make it formal")'),
        ]:
            label(f, row, text)
            entry = ttk.Entry(f, width=26)
            entry.insert(0, cfg.get(key, "right ctrl" if key == "hotkey"
                                    else ""))
            entry.grid(row=row, column=1, sticky="w", pady=3)
            ttk.Label(f, text=hint, foreground="#666").grid(
                row=row + 1, column=1, sticky="w")
            self.hotkeys[key] = entry
            row += 2

        label(f, row, "Insert method")
        self.insert_mode = ttk.Combobox(
            f, values=["paste", "type"], state="readonly", width=24)
        self.insert_mode.set(cfg.get("insert_mode", "paste"))
        self.insert_mode.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label(f, row, "On-screen bar position")
        self.overlay_pos = ttk.Combobox(
            f, values=list(POSITIONS), state="readonly", width=24)
        self.overlay_pos.set(cfg.get("overlay_position", "bottom-center"))
        self.overlay_pos.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        self.flags = {}

        def flags(parent, r, items):
            for key, text, default in items:
                var = tk.BooleanVar(value=bool(cfg.get(key, default)))
                ttk.Checkbutton(parent, text=text, variable=var).grid(
                    row=r, column=0, columnspan=2, sticky="w")
                self.flags[key] = var
                r += 1
            return r

        row = flags(f, row, [
            ("remove_fillers", "Remove filler words (um, uh…)", True),
            ("capitalize_first", "Auto-capitalize sentences", True),
            ("strip_trailing_period", "Strip trailing period (chat style)",
             False),
            ("sound_cues", "Sound cues on start/stop", True),
            ("auto_select_mic",
             "Auto-select a working microphone at startup", True),
            ("save_history", "Save dictation history", True),
            ("restore_clipboard", "Restore clipboard after paste", True),
            ("live_partials",
             "Show words live as I speak (experimental)", False),
            ("voice_replies", "Speak confirmations in voice control mode",
             True),
        ])

        # ----- Styles -----------------------------------------------------
        s = tab("Styles")
        row = 0
        row = flags(s, row, [
            ("context_styles",
             "Adapt my writing style to the app I'm typing in", True),
            ("read_context",
             "Look at the text before the cursor to fit spacing and "
             "capitals", True),
            ("spoken_commands",
             'Understand "new line", "bullet point", "scratch that"', True),
            ("smart_lists",
             'Turn "first…, then…, finally…" into numbered lists', True),
        ])
        ttk.Label(s, text="Style per kind of app", font=("Segoe UI", 9,
                                                          "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row += 1
        presets = cfg.get("style_presets") or {}
        self.presets = {}
        for cat, text in CATEGORY_LABELS:
            label(s, row, text)
            box = ttk.Combobox(s, values=list(styles.PRESETS),
                               state="readonly", width=14)
            box.set(presets.get(cat) or styles.DEFAULT_PRESETS[cat])
            box.grid(row=row, column=1, sticky="w", pady=2)
            self.presets[cat] = box
            row += 1
        ttk.Label(s, text="verbatim = exact words · casual = relaxed · "
                          "standard = cleaned · formal = full sentences · "
                          "concise = no filler", foreground="#666",
                  wraplength=430).grid(row=row, column=0, columnspan=2,
                                       sticky="w", pady=(2, 8))
        row += 1
        ttk.Label(s, text="Per-app overrides (one per line: app.exe name "
                          "=> preset, e.g. slack => formal)").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self.app_styles = tk.Text(s, width=52, height=4, font=("Consolas", 9))
        self.app_styles.grid(row=row, column=0, columnspan=2, sticky="w")
        self.app_styles.insert("1.0", _pairs_to_text(cfg.get("app_styles")))
        row += 1

        # ----- Shortcuts & words -----------------------------------------------
        w = tab("Shortcuts & words")
        row = 0
        ttk.Label(w, text="Spoken shortcuts (trigger => text; {date} {time} "
                          "{day} and \\n allowed)").grid(
            row=row, column=0, sticky="w")
        row += 1
        self.snippets = tk.Text(w, width=56, height=6, font=("Consolas", 9))
        self.snippets.grid(row=row, column=0, sticky="w", pady=(2, 8))
        self.snippets.insert("1.0", _pairs_to_text(cfg.get("snippets")))
        row += 1
        ttk.Label(w, text="My vocabulary (names, jargon, product terms; one "
                          "per line) — always recognised").grid(
            row=row, column=0, sticky="w")
        row += 1
        self.vocab = tk.Text(w, width=56, height=5, font=("Consolas", 9))
        self.vocab.grid(row=row, column=0, sticky="w", pady=(2, 8))
        self.vocab.insert("1.0", "\n".join(cfg.get("vocabulary") or []))
        row += 1
        ttk.Label(w, text="Custom dictionary (one per line: heard => "
                          "replacement)").grid(row=row, column=0, sticky="w")
        row += 1
        self.dict_text = tk.Text(w, width=56, height=5, font=("Consolas", 9))
        self.dict_text.grid(row=row, column=0, sticky="w", pady=(2, 0))
        self.dict_text.insert("1.0", _pairs_to_text(cfg.get("dictionary")))

        # ----- Advanced ---------------------------------------------------
        a = tab("Advanced")
        row = 0
        label(a, row, "Obsidian vault (for notes)")
        vault_row = ttk.Frame(a)
        vault_row.grid(row=row, column=1, sticky="w", pady=3)
        self.vault = ttk.Entry(vault_row, width=32)
        self.vault.insert(0, cfg.get("obsidian_vault", ""))
        self.vault.pack(side="left")
        ttk.Button(vault_row, text="Browse…", width=8,
                   command=self._pick_vault).pack(side="left", padx=4)
        row += 1

        label(a, row, "Accuracy (beam size 1–5)")
        self.beam = ttk.Spinbox(a, from_=1, to=5, width=6)
        self.beam.set(cfg.get("beam_size", 2))
        self.beam.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        label(a, row, "Stop a recording after (seconds)")
        self.max_take = ttk.Spinbox(a, from_=0, to=3600, increment=30,
                                    width=6)
        self.max_take.set(cfg.get("max_take_seconds", 360))
        self.max_take.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # Optional local LLM. Off by default; a GGUF file (llama.cpp) or an
        # ONNX model folder turns it on. It runs on this machine only.
        label(a, row, "Local LLM model")
        llm_row = ttk.Frame(a)
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
            a, foreground="#666",
            text="(optional) GGUF for llama.cpp, or an ONNX model folder")
        self.llm_status.grid(row=row, column=1, sticky="w")
        row += 1
        row = flags(a, row, [
            ("llm_enabled",
             "Use the local LLM for commands I don't recognize yet", False),
            ("llm_polish",
             "Polish dictations with the local LLM (slower)", False),
            ("adaptive_learning",
             "Learn my vocabulary and languages (stored locally)", True),
            ("retain_last_take",
             "Keep my last recording (encrypted) so I can retry it", True),
        ])

        btns = ttk.Frame(outer)
        btns.grid(row=1, column=0, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="Save & Apply", command=self.save).pack(
            side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.win.destroy).pack(
            side="left")

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
        import styles
        keys = {k: e.get().strip().lower() for k, e in self.hotkeys.items()}
        names = {"hotkey": "Dictation hotkey",
                 "translate_hotkey": "Translate hotkey",
                 "command_hotkey": "Voice control hotkey",
                 "edit_hotkey": "Voice edit hotkey"}
        for key, k in keys.items():
            if k and not validate_hotkey(k):
                messagebox.showerror(
                    "WhispLocal", f"{names[key]} '{k}' is not a valid key "
                    "name.", parent=self.win)
                return
        if not keys["hotkey"]:
            messagebox.showerror("WhispLocal",
                                 "Dictation hotkey cannot be empty.",
                                 parent=self.win)
            return
        used = [k for k in keys.values() if k]
        if len(used) != len(set(used)):
            messagebox.showerror("WhispLocal",
                                 "Each hotkey must be a different key.",
                                 parent=self.win)
            return

        app_styles = {}
        for name, preset in _text_to_pairs(
                self.app_styles.get("1.0", "end")).items():
            if preset.lower() not in styles.PRESETS:
                messagebox.showerror(
                    "WhispLocal", f"Unknown style '{preset}' for {name}. "
                    f"Use one of: {', '.join(styles.PRESETS)}.",
                    parent=self.win)
                return
            name = name.lower()
            app_styles[name[:-4] if name.endswith(".exe") else name] = \
                preset.lower()

        cfg = dict(self.app.config)
        lang = self.language.get()
        mic = self.mic.get()
        try:
            max_take = max(0, int(float(self.max_take.get() or 0)))
        except ValueError:
            max_take = 360
        cfg.update(keys)
        cfg.update({
            "model": self.model.get(),
            "language": None if lang == "auto" else lang,
            "indic_script": ("roman" if self.script.get().startswith("roman")
                             else "native"),
            "input_device": None if mic == "System default" else mic,
            "insert_mode": self.insert_mode.get(),
            "overlay_position": self.overlay_pos.get(),
            "obsidian_vault": self.vault.get().strip(),
            "beam_size": max(1, min(5, int(self.beam.get() or 2))),
            "max_take_seconds": max_take,
            "llm_model_path": self.llm_path.get().strip(),
            "dictionary": _text_to_pairs(self.dict_text.get("1.0", "end")),
            "snippets": _text_to_pairs(self.snippets.get("1.0", "end")),
            "vocabulary": [v.strip() for v in
                           self.vocab.get("1.0", "end").splitlines()
                           if v.strip()],
            "style_presets": {c: b.get() for c, b in self.presets.items()},
            "app_styles": app_styles,
        })
        for key, var in self.flags.items():
            cfg[key] = bool(var.get())

        self.app.save_config(cfg)
        self.app.reload_config()
        self.win.destroy()


class HistoryWindow:
    def __init__(self, root, history_path, app=None):
        import history
        self.app = app
        self.win = tk.Toplevel(root)
        self.win.title("WhispLocal History")
        self.win.attributes("-topmost", True)
        self.win.geometry("680x480")
        frame = ttk.Frame(self.win, padding=8)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Double-click to copy. Select a line and press "
                              "Correct to teach the app what you actually "
                              "said.").pack(anchor="w")
        self.all = history.load(history_path)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Label(bar, text="Search").pack(side="left")
        self.query = ttk.Entry(bar, width=30)
        self.query.pack(side="left", padx=(4, 10))
        self.query.bind("<KeyRelease>", lambda e: self._refresh())
        ttk.Label(bar, text="App").pack(side="left")
        self.app_filter = ttk.Combobox(
            bar, values=["All apps"] + history.apps(self.all),
            state="readonly", width=16)
        self.app_filter.set("All apps")
        self.app_filter.pack(side="left", padx=4)
        self.app_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        self.kind = ttk.Combobox(
            bar, values=["Everything", "Dictation", "Voice control",
                         "Edits"], state="readonly", width=12)
        self.kind.set("Everything")
        self.kind.pack(side="left", padx=4)
        self.kind.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        self.listbox = tk.Listbox(frame, font=("Segoe UI", 10))
        self.listbox.pack(fill="both", expand=True, pady=6)
        self.entries = []
        self.listbox.bind("<Double-Button-1>", self._copy)
        bottom = ttk.Frame(frame)
        bottom.pack(fill="x")
        self.status = ttk.Label(bottom)
        self.status.pack(side="left")
        if app is not None:
            ttk.Button(bottom, text="Correct…", command=self._correct).pack(
                side="right")
        self._refresh()

    def _refresh(self):
        import history
        app = self.app_filter.get()
        task = {"Dictation": "transcribe", "Voice control": "command",
                "Edits": "edit"}.get(self.kind.get())
        self.entries = history.search(
            self.all, self.query.get(),
            app=None if app == "All apps" else app, task=task, limit=300)
        self.listbox.delete(0, "end")
        for e in self.entries:
            where = f"  · {e['app']}" if e.get("app") else ""
            self.listbox.insert(
                "end", f"[{e.get('ts', '?')}{where}]  {e.get('text', '')}")
        self.status.config(text=f"{len(self.entries)} of {len(self.all)} "
                                "entries")

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
        ttk.Label(f, text="What you actually said (edit below):").pack(
            anchor="w")
        box = tk.Text(f, width=60, height=4, font=("Segoe UI", 10),
                      wrap="word")
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


class StatsWindow:
    """How much you dictate: words, speed, time saved and streak."""

    def __init__(self, root, history_path):
        import history
        st = history.stats(history.load(history_path))
        self.win = tk.Toplevel(root)
        self.win.title("WhispLocal Stats")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        f = ttk.Frame(self.win, padding=16)
        f.pack()
        tiles = [
            (f"{st['total_words']:,}", "words dictated"),
            (f"{st['words_7d']:,}", "words in the last 7 days"),
            (f"{st['wpm']}", "words per minute when speaking"),
            (f"{st['minutes_saved']:,} min", "saved vs typing at 40 wpm"),
            (f"{st['streak_days']}", "day streak"),
            (f"{st['dictations']} / {st['commands']} / {st['edits']}",
             "dictations / commands / edits"),
        ]
        for i, (value, caption) in enumerate(tiles):
            cell = ttk.Frame(f, padding=(10, 6))
            cell.grid(row=i // 2, column=i % 2, sticky="w")
            ttk.Label(cell, text=value, font=("Segoe UI", 18, "bold")).pack(
                anchor="w")
            ttk.Label(cell, text=caption, foreground="#666").pack(anchor="w")
        if st["top_apps"]:
            apps = ", ".join(f"{a} ({n})" for a, n in st["top_apps"])
            ttk.Label(f, text=f"Most dictated into: {apps}",
                      wraplength=420).grid(row=4, column=0, columnspan=2,
                                           sticky="w", pady=(10, 0))
        ttk.Label(f, text="Computed from your local history file. Nothing "
                          "leaves this computer.", foreground="#888").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
