"""Floating status pill with a live waveform, like Wispr Flow's indicator.

A borderless, always-on-top rounded pill at the bottom of the screen:
- while recording it animates bars from real microphone levels
- while transcribing it shows an animated ellipsis
- brief ✓ / ✕ flashes for done / error

Runs on the main thread. Other threads post state changes via `post()`
and can schedule UI work (opening windows) via `call()`.
"""
import queue
import tkinter as tk

TRANSPARENT = "#010101"   # transparent color key (Windows)
BG = "#16161e"
FG = "#f8f8f2"
ACCENT = "#8be9fd"

TEXT_STATES = {
    "transcribing": ("Transcribing", "#f1fa8c"),
    "done": ("✓  Inserted", "#50fa7b"),
    "error": ("✕  Error — see whisp.log", "#ff5555"),
    "loading": ("Loading model…", ACCENT),
    "translate": ("Translating…", "#bd93f9"),
}


class Overlay:
    W, H = 340, 54

    def __init__(self, get_levels=None):
        self.get_levels = get_levels or (lambda: [])
        self.events = queue.Queue()
        self.state = "hide"
        self._hide_job = None
        self._anim_job = None
        self._tick = 0

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(
            self.root, width=self.W, height=self.H,
            bg=TRANSPARENT, highlightthickness=0,
        )
        self.canvas.pack()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{sh - self.H - 70}")
        self.root.after(40, self._poll)

    # ----- thread-safe API ----------------------------------------------
    def post(self, state):
        self.events.put(("state", state))

    def call(self, fn):
        """Run fn() on the tkinter thread (for opening windows etc.)."""
        self.events.put(("call", fn))

    # ----- event pump -----------------------------------------------------
    def _poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "state":
                    if payload == "quit":
                        self.root.quit()
                        return
                    self._apply(payload)
                else:
                    try:
                        payload()
                    except Exception:
                        pass
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def _apply(self, state):
        self.state = state
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None
        if state == "hide":
            self.root.withdraw()
            return
        self.root.deiconify()
        self._tick = 0
        self._draw()
        if state in ("done", "error"):
            self._hide_job = self.root.after(1600, self.root.withdraw)

    # ----- drawing --------------------------------------------------------
    def _pill(self):
        c, w, h = self.canvas, self.W, self.H
        c.delete("all")
        r = h // 2
        c.create_oval(0, 0, h, h, fill=BG, outline=BG)
        c.create_oval(w - h, 0, w, h, fill=BG, outline=BG)
        c.create_rectangle(r, 0, w - r, h, fill=BG, outline=BG)

    def _draw(self):
        self._pill()
        c, w, h = self.canvas, self.W, self.H
        st = self.state

        if st in ("recording", "locked", "recording_translate"):
            # Status dot (red = hold mode, orange = locked, purple = translate).
            color = {"recording": "#ff5555", "locked": "#ffb86c",
                     "recording_translate": "#bd93f9"}[st]
            pulse = 5 + (self._tick // 4) % 2
            c.create_oval(22 - pulse, h // 2 - pulse, 22 + pulse, h // 2 + pulse,
                          fill=color, outline=color)
            # Waveform bars from live mic levels.
            levels = list(self.get_levels())
            n = 34
            levels = levels[-n:]
            levels = [0.0] * (n - len(levels)) + levels
            x0, gap = 44, (w - 60) / n
            for i, lv in enumerate(levels):
                frac = min(1.0, lv * 16)
                bh = max(3, frac * (h - 18))
                x = x0 + i * gap
                c.create_rectangle(x, (h - bh) / 2, x + gap - 2, (h + bh) / 2,
                                   fill=ACCENT, outline=ACCENT)
            if st == "locked":
                c.create_text(w - 26, h // 2, text="\U0001F512",
                              font=("Segoe UI Emoji", 11), fill=FG)
            self._tick += 1
            self._anim_job = self.root.after(45, self._draw)

        elif st == "transcribing" or st == "translate":
            text, color = TEXT_STATES[st]
            dots = "." * (1 + self._tick // 6 % 3)
            c.create_text(w // 2, h // 2, text=text + dots,
                          font=("Segoe UI", 12, "bold"), fill=color)
            self._tick += 1
            self._anim_job = self.root.after(80, self._draw)

        else:
            text, color = TEXT_STATES.get(st, (st, FG))
            c.create_text(w // 2, h // 2, text=text,
                          font=("Segoe UI", 12, "bold"), fill=color)

    def run(self):
        self.root.mainloop()
