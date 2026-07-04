"""System tray icon and menu. Runs in its own thread; anything that
touches tkinter is routed to the UI thread through app.ui()."""
from functools import partial

import pystray
from PIL import Image, ImageDraw

from settings import MODELS


def make_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0
    d.rounded_rectangle([24 * s, 8 * s, 40 * s, 36 * s], radius=8 * s, fill="#8be9fd")
    d.arc([16 * s, 20 * s, 48 * s, 48 * s], start=0, end=180,
          fill="#8be9fd", width=max(2, int(4 * s)))
    d.line([32 * s, 48 * s, 32 * s, 56 * s], fill="#8be9fd", width=max(2, int(4 * s)))
    d.line([22 * s, 56 * s, 42 * s, 56 * s], fill="#8be9fd", width=max(2, int(4 * s)))
    return img


def build_tray(app):
    model_items = [
        pystray.MenuItem(
            m,
            partial(lambda name, *a: app.set_model(name), m),
            radio=True,
            checked=partial(lambda name, item: app.config.get("model") == name, m),
        )
        for m in MODELS
    ]
    menu = pystray.Menu(
        pystray.MenuItem(lambda item: f"WhispLocal {app.version} — hotkey: {app.hotkey}",
                         None, enabled=False),
        pystray.MenuItem("Hold to talk · quick-tap to lock on", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings…", lambda *a: app.open_settings()),
        pystray.MenuItem("History…", lambda *a: app.open_history()),
        pystray.MenuItem("Model", pystray.Menu(*model_items)),
        pystray.MenuItem("Pause dictation", lambda *a: app.toggle_pause(),
                         checked=lambda item: app.paused),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda *a: app.quit()),
    )
    return pystray.Icon("WhispLocal", make_icon(),
                        "WhispLocal — offline dictation", menu)
