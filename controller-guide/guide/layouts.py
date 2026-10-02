"""Per-blueprint / per-model layout definitions.

A layout says which physical controls a device has (with the badge number
drawn on its line drawing), which blueprint input feeds each gesture, and
which print tier each gesture appears on (1 = mini label, 2 = 4x6 card,
3 = letter sheet only).

PINNED_SCHEMAS records the blueprint input-schema hash each layout was
written against (fetch.py computes it from input names + defaults). When a
blueprint changes, build.py warns so the layout, especially the wall-dimmer
fixed grammar in extract.py, gets reviewed. Behaviour-only edits to a
blueprint's action logic do NOT change the hash: update the grammar by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CONTROLLER_BLUEPRINTS = (
    "aeotec-minimote-controller.yaml",
    "zooz-zen37-remote-control.yaml",
    "wall-dimmer-natural-light-controller.yaml",
    "aqara-cube-controller.yaml",
    "switch-led-day-night-controller.yaml",
)

PINNED_SCHEMAS = {
    "aeotec-minimote-controller.yaml": "206183d7055c",
    "zooz-zen37-remote-control.yaml": "ce4d0decf213",
    "wall-dimmer-natural-light-controller.yaml": "cac102a6cff9",
    "aqara-cube-controller.yaml": "8569d722578e",
    "switch-led-day-night-controller.yaml": "a4682b0d3bf9",
}

# Registry models that get a card even without an automation.
STATIC_MODELS = ("VZM35-SN",)
HUE_SWITCH_MODELS = ("Hue dimmer switch", "Hue tap switch", "Hue smart button", "Hue tap dial switch")

# Registry model -> drawing template (templates/devices/<drawing>.svg.j2).
DRAWINGS = {
    "DSA03XXX-ZW": "minimote",
    "DSA03202": "minimote",
    "ZEN37 800LR": "zen37",
    "ZEN37 LR": "zen37",
    "ZEN77": "paddle-zooz",
    "ZEN30": "paddle-zen30",
    "14294 / ZW3005": "paddle-ge",
    "HS-WX300": "paddle-hs",
    "lumi.remote.cagl02": "cube",
    "lumi.sensor_cube": "cube",
    "VZM35-SN": "vzm35",
    "Hue dimmer switch": "hue-dimmer",
    "Hue tap switch": "hue-tap",
}


def is_controller_device(dev: dict[str, Any]) -> bool:
    model = dev.get("model") or ""
    return any(m.lower() in model.lower() for m in STATIC_MODELS + HUE_SWITCH_MODELS)


def drawing_for(model: str | None) -> str:
    return DRAWINGS.get(model or "", "generic")


@dataclass(frozen=True)
class GestureSpec:
    kind: str
    input_key: str
    tier: int


@dataclass(frozen=True)
class ControlSpec:
    id: str
    badge: str
    label: str
    gestures: tuple[GestureSpec, ...] = field(default_factory=tuple)


def _buttons(labels: dict[int, str], kinds: list[tuple[str, str, int]]) -> tuple[ControlSpec, ...]:
    """kinds: (gesture kind, input key suffix, tier)."""
    return tuple(
        ControlSpec(
            id=f"b{n}", badge=str(n), label=label,
            gestures=tuple(GestureSpec(k, f"button_{n}_{suffix}", tier) for k, suffix, tier in kinds),
        )
        for n, label in labels.items()
    )


# Aeotec Minimote: positions from the blueprint's section names.
MINIMOTE = _buttons(
    {1: "Button 1 (upper left)", 2: "Button 2 (upper right)",
     3: "Button 3 (lower left)", 4: "Button 4 (lower right)"},
    [("press", "press", 1), ("hold", "hold", 2), ("release", "release", 3)],
)

# Zooz ZEN37 800LR: layout from the Zooz manual (large top, large middle,
# small bottom-left, small bottom-right).
ZEN37 = _buttons(
    {1: "Button 1 (large top)", 2: "Button 2 (large middle)",
     3: "Button 3 (small bottom left)", 4: "Button 4 (small bottom right)"},
    [("single", "single", 1), ("double", "double", 2), ("triple", "triple", 3),
     ("quadruple", "quadruple", 3), ("quintuple", "quintuple", 3),
     ("hold", "hold", 2), ("release", "release", 3)],
)

BUTTON_LAYOUTS: dict[str, tuple[ControlSpec, ...]] = {
    "aeotec-minimote-controller.yaml": MINIMOTE,
    "zooz-zen37-remote-control.yaml": ZEN37,
}

CUBE_FACE_GESTURES = (
    ("tap", "tap", 1), ("rotate_right", "rotate_right", 2), ("rotate_left", "rotate_left", 2),
    ("slide", "slide", 2), ("flip", "flip", 3),
)
CUBE_GLOBAL_GESTURES = (
    ("shake", "shake_action", 2), ("tap", "tap_action", 2), ("slide", "slide_action", 2),
    ("flip_any", "flip_action", 3), ("flip_90", "flip_90_action", 3),
    ("flip_180", "flip_180_action", 3), ("rotate_right", "rotate_right_action", 3),
    ("rotate_left", "rotate_left_action", 3), ("throw", "throw_action", 3),
)

# Hue / Extra Buttons event types -> gesture kind shown on the card.
AUX_EVENT_KINDS = {
    "initial_press": "press", "short_release": "press",
    "long_press": "hold", "repeat": "hold", "long_release": "release",
}

# Hand-entered Hue switches: default control labels (overlay can override).
HUE_BUTTON_LABELS = {
    "hue-dimmer": {1: "On (top)", 2: "Brighter", 3: "Dimmer", 4: "Off or Hue (bottom)"},
    "hue-tap": {1: "Button 1", 2: "Button 2", 3: "Button 3", 4: "Button 4"},
}
