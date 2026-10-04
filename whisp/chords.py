"""Multi-key hold-to-talk chords such as "ctrl+windows" or "ctrl+alt".

The keyboard library's on_press_key only watches a single key. A chord
needs every key down at once, and recording must stop the moment any of
them is released, so ChordMatcher tracks pressed keys from the raw event
stream and reports transitions:

    feed("down", "ctrl")     -> None
    feed("down", "windows")  -> "press"    (all keys now held)
    feed("up", "ctrl")       -> "release"  (chord broken)

Generic modifier names match either side: "ctrl" matches left or right
Ctrl, "windows" matches either Windows key. "right ctrl" matches only the
right one.
"""

ALIASES = {
    "control": "ctrl", "win": "windows", "cmd": "windows", "super": "windows",
    "option": "alt", "altgr": "right alt", "alt gr": "right alt",
    "return": "enter", "esc": "escape",
}
_SIDED = {"ctrl", "alt", "shift", "windows"}


def normalize(name):
    name = (name or "").strip().lower()
    return ALIASES.get(name, name)


def generic(name):
    """'left windows' -> 'windows', 'right ctrl' -> 'ctrl'."""
    name = normalize(name)
    for side in ("left ", "right "):
        if name.startswith(side) and name[len(side):] in _SIDED:
            return name[len(side):]
    return name


def is_chord(spec):
    return "+" in (spec or "").strip("+")


def parse(spec):
    return [normalize(p) for p in (spec or "").split("+") if p.strip()]


class ChordMatcher:
    def __init__(self, spec):
        self.keys = parse(spec)
        self.down = set()
        self.active = False

    def _held(self, want):
        if want in _SIDED:  # generic modifier: either side counts
            return any(generic(k) == want for k in self.down)
        return want in self.down

    def feed(self, event_type, name):
        """Feed one keyboard event; returns "press", "release" or None."""
        name = normalize(name)
        if event_type == "down":
            self.down.add(name)
        elif name in self.down:
            self.down.discard(name)
        else:
            # Some layouts report a sided name on key down and the generic
            # one on key up (or the reverse): drop the matching key.
            self.down = {k for k in self.down if generic(k) != generic(name)}
        complete = bool(self.keys) and all(self._held(k) for k in self.keys)
        if complete and not self.active:
            self.active = True
            return "press"
        if not complete and self.active:
            self.active = False
            return "release"
        return None

    def reset(self):
        self.down.clear()
        self.active = False
