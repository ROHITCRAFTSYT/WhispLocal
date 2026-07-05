"""Floating status pill with a live waveform.

A borderless, always-on-top rounded pill that can sit in any corner or
edge of the screen (see POSITIONS). While recording it animates a
gradient waveform from real microphone levels; while working it shows an
animated label; brief check / cross flashes for done / error.

Runs on the main thread. Other threads post state changes via `post()`
and can schedule UI work (opening windows) via `call()`.
"""
import queue
import tkinter as tk

TRANSPARENT = "#010101"   # transparent color key (Windows)
BG = "#16161e"
BG_EDGE = "#0d0d12"
FG = "#f8f8f2"
ACCENT = "#8be9fd"
ACCENT_HI = "#ff79c6"     # waveform peak color

POSITIONS = ("bottom-center", "bottom-right", "bottom-left",
             "top-center", "top-right", "top-left", "center")

TEXT_STATES = {
    "transcribing": ("Transcribing", "#f1fa8c"),
    "done": ("✓  Inserted", "#50fa7b"),
    "error": ("✕  Error — see whisp.log", "#ff5555"),
    "loading": ("Loading model…", ACCENT),
    "translate": ("Translating…", "#bd93f9"),
    "thinking": ("Working on it", "#50fa7b"),
}


def _lerp_color(c1, c2, t):
    a = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    b = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return f"#{r[0]:02x}{r[1]:02x}{r[2]:02x}"


class Overlay:
    W, H = 340, 54

    def __init__(self, get_levels=None, position="bottom-center"):
        self.get_levels = get_levels or (lambda: [])
        self.position = position if position in POSITIONS else "bottom-center"
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
        self._place()
        self.root.after(40, self._poll)

    # ----- thread-safe API ----------------------------------------------
    def post(self, state):
        self.events.put(("state", state))

    def call(self, fn):
        """Run fn() on the tkinter thread (for opening windows etc.)."""
        self.events.put(("call", fn))

    def set_position(self, position):
        if position in POSITIONS and position != self.position:
            self.position = position
            self.call(self._place)

    # ----- geometry -------------------------------------------------------
    def _place(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = self.W, self.H
        mx, my_top, my_bot = 40, 60, 70
        pos = self.position
        if "left" in pos:
            x = mx
        elif "right" in pos:
            x = sw - w - mx
        else:
            x = (sw - w) // 2
        if pos == "center":
            y = (sh - h) // 2
        elif "top" in pos:
            y = my_top
        else:
            y = sh - h - my_bot
        self.root.geometry(f"{w}x{h}+{x}+{y}")

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
        self._place()
        self.root.deiconify()
        self._tick = 0
        self._draw()
        if state in ("done", "error") or (
                isinstance(state, tuple) and state[0] == "message"):
            self._hide_job = self.root.after(2400, self.root.withdraw)

    # ----- drawing --------------------------------------------------------
    def _pill(self):
        c, w, h = self.canvas, self.W, self.H
        c.delete("all")
        r = h // 2
        # Two-tone body: a darker edge ring under a lighter face for depth.
        c.create_oval(0, 0, h, h, fill=BG_EDGE, outline=BG_EDGE)
        c.create_oval(w - h, 0, w, h, fill=BG_EDGE, outline=BG_EDGE)
        c.create_rectangle(r, 0, w - r, h, fill=BG_EDGE, outline=BG_EDGE)
        pad = 2
        c.create_oval(pad, pad, h - pad, h - pad, fill=BG, outline=BG)
        c.create_oval(w - h + pad, pad, w - pad, h - pad, fill=BG, outline=BG)
        c.create_rectangle(r, pad, w - r, h - pad, fill=BG, outline=BG)

    def _draw(self):
        self._pill()
        c, w, h = self.canvas, self.W, self.H
        st = self.state

        if isinstance(st, tuple) and st[0] == "message":
            _, text, ok = st
            if len(text) > 44:
                text = text[:43] + "…"
            c.create_text(w // 2, h // 2, text=text,
                          font=("Segoe UI", 11, "bold"),
                          fill="#50fa7b" if ok else "#ff5555")
            return

        if st in ("recording", "locked", "recording_translate",
                  "recording_command"):
            # Status dot: red = dictation, orange = locked,
            # purple = translate, green = voice control.
            color = {"recording": "#ff5555", "locked": "#ffb86c",
                     "recording_translate": "#bd93f9",
                     "recording_command": "#50fa7b"}[st]
            pulse = 5 + (self._tick // 4) % 2
            c.create_oval(22 - pulse, h // 2 - pulse, 22 + pulse, h // 2 + pulse,
                          fill=color, outline=color)
            # Gradient waveform bars, mirrored around the centre line.
            levels = list(self.get_levels())
            n = 34
            levels = levels[-n:]
            levels = [0.0] * (n - len(levels)) + levels
            x0, gap = 44, (w - 60) / n
            mid = h / 2
            for i, lv in enumerate(levels):
                frac = min(1.0, lv * 16)
                bh = max(3, frac * (h - 18))
                x = x0 + i * gap
                col = _lerp_color(ACCENT, ACCENT_HI, frac)
                c.create_rectangle(x, mid - bh / 2, x + gap - 2, mid + bh / 2,
                                   fill=col, outline=col)
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
