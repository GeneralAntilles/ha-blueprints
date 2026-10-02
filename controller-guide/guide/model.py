"""Data model for the controller guide."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

# Gesture kinds -> (glyph, word). The word always accompanies the glyph.
GESTURE_WORDS: dict[str, tuple[str, str]] = {
    "press": ("●", "Press"),
    "single": ("●", "Tap"),
    "double": ("●●", "Double tap"),
    "triple": ("●●●", "Triple tap"),
    "quadruple": ("●×4", "Tap 4×"),
    "quintuple": ("●×5", "Tap 5×"),
    "hold": ("◉", "Hold"),
    "release": ("○", "Release"),
    "up_1x": ("▲", "Tap up"),
    "up_2x": ("▲▲", "Double tap up"),
    "up_3x": ("▲▲▲", "Triple tap up"),
    "down_1x": ("▼", "Tap down"),
    "down_2x": ("▼▼", "Double tap down"),
    "down_3x": ("▼▼▼", "Triple tap down"),
    "up_hold": ("▲◉", "Hold up"),
    "down_hold": ("▼◉", "Hold down"),
    "tap": ("✦", "Tap on table"),
    "slide": ("⇢", "Slide"),
    "rotate_right": ("↻", "Turn right"),
    "rotate_left": ("↺", "Turn left"),
    "flip": ("⤾", "Flip onto this face"),
    "shake": ("≋", "Shake"),
    "flip_any": ("⤾", "Flip (any way)"),
    "flip_90": ("⤾", "Flip a quarter turn"),
    "flip_180": ("⤾", "Flip upside down"),
    "throw": ("⤴", "Throw"),
    "info": ("ⓘ", "Note"),
}


@dataclass
class Gesture:
    kind: str
    short: str
    long: str
    tier: int = 2                       # 1 = mini label, 2 = card, 3 = letter only
    input_key: str | None = None
    conditions: list[str] = field(default_factory=list)
    source: str = "ha"                  # ha | hue | device | manual
    broken: bool = False                # references an entity that no longer exists
    detail: str = ""                    # technical summary (entity ids) for the details toggle

    @property
    def glyph(self) -> str:
        return GESTURE_WORDS.get(self.kind, ("•", self.kind))[0]

    @property
    def word(self) -> str:
        return GESTURE_WORDS.get(self.kind, ("", self.kind.replace("_", " ").title()))[1]


@dataclass
class Control:
    id: str
    badge: str
    label: str
    gestures: list[Gesture] = field(default_factory=list)


@dataclass
class Controller:
    slug: str
    title: str
    location: str
    area: str
    floor: str
    floor_level: int
    model: str
    layout: str
    drawing: str
    device_ids: list[str]
    device_names: list[str]
    automation_ids: list[str] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    source: str = "blueprint"
    disabled: bool = False
    leds: list[Any] = field(default_factory=list)          # guide.leds.LedLine
    led_raw: list[tuple[str, str]] = field(default_factory=list)

    @property
    def rev(self) -> str:
        """Short hash of what a printed card shows; changes when the card would."""
        content = {
            "title": self.title, "location": self.location, "notes": self.notes,
            "disabled": self.disabled, "drawing": self.drawing, "floor": self.floor,
            "leds": [(ln.text, ln.swatches, ln.tier) for ln in self.leds],
            "controls": [
                {"id": c.id, "badge": c.badge, "label": c.label,
                 "g": [(g.kind, g.short, g.long, g.conditions, g.tier, g.broken, g.source)
                       for g in c.gestures]}
                for c in self.controls
            ],
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:4]

    @property
    def has_broken(self) -> bool:
        return any(g.broken for c in self.controls for g in c.gestures)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rev"] = self.rev
        return d
