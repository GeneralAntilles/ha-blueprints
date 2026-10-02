"""Hue-app switch configurations (bridge behavior_instances) -> card controls."""
from __future__ import annotations

import re
from typing import Any

from .model import Control, Gesture

# Physical labels by Hue model id (control_id -> label).
HUE_MODEL_BUTTONS: dict[str, dict[int, str]] = {
    "RWL020": {1: "On (top)", 2: "Brighter", 3: "Dimmer", 4: "Off (bottom)"},
    "RWL021": {1: "On (top)", 2: "Brighter", 3: "Dimmer", 4: "Off (bottom)"},
    "RWL022": {1: "Power (top)", 2: "Brighter", 3: "Dimmer", 4: "Hue button (bottom)"},
    "ZGPSWITCH": {1: "Big button (1 dot)", 2: "Left (2 dots)", 3: "Bottom (3 dots)", 4: "Right (4 dots)"},
}
HUE_MODEL_DRAWING = {"RWL020": "hue-dimmer-v1", "RWL021": "hue-dimmer-v1",
                     "RWL022": "hue-dimmer-v2", "ZGPSWITCH": "hue-tap"}

# Hue event -> (gesture kind, tier offset). on_repeat is the "keep holding" event.
EVENT_KINDS = {
    "on_initial_press": "press",
    "on_short_release": "press",
    "on_long_press": "hold",
    "on_repeat": "hold",
    "on_long_release": "release",
}
TRAILING_NUM_RE = re.compile(r"\s+\d+$")


def _cap(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in TRAILING_NUM_RE.sub("", text).split(" "))


class HueSwitches:
    def __init__(self, hue: dict[str, Any], warn) -> None:
        self.hue = hue
        self.warn = warn

    def by_hue_device(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for b in self.hue.get("behaviors", []):
            if b.get("device"):
                out.setdefault(b["device"], []).append(b)
        return out

    def group_name(self, where: list[dict[str, Any]]) -> str:
        names = []
        for w in where or []:
            rid = (w.get("group") or {}).get("rid")
            g = self.hue.get("groups", {}).get(rid)
            names.append(_cap(g["name"]) if g else "the room")
        return " & ".join(dict.fromkeys(names)) or "the room"

    def scene_name(self, rid: str | None) -> str | None:
        s = self.hue.get("scenes", {}).get(rid or "")
        return _cap(s["name"]) if s else None

    def controls(self, behavior: dict[str, Any], title: str) -> list[Control]:
        model = behavior.get("model_id") or ""
        labels = HUE_MODEL_BUTTONS.get(model, {})
        out: dict[int, Control] = {}
        for button_rid, cfg in (behavior.get("buttons") or {}).items():
            button = self.hue.get("buttons", {}).get(button_rid)
            if not button:
                self.warn(title, f"Hue button {button_rid} not found on the bridge")
                continue
            n = int(button["control_id"])
            control = out.setdefault(n, Control(f"b{n}", str(n), labels.get(n, f"Button {n}")))
            where = self.group_name(cfg.get("where"))
            for event, kind in EVENT_KINDS.items():
                if event not in cfg:
                    continue
                if event == "on_initial_press" and "on_short_release" in cfg:
                    continue      # one press, one line: the release event is what the Hue app uses
                phrase = self.phrase(cfg[event], where, event, title)
                if phrase is None:
                    continue
                short, long = phrase
                tier = 1 if (kind == "press" and n in (1, 4)) or model == "ZGPSWITCH" else 2
                if kind != "press":
                    tier = 2
                control.gestures.append(Gesture(kind, short, long, tier, source="hue",
                                                detail=f"hue {event}: {sorted(cfg[event])}"))
        return [out[n] for n in sorted(out)]

    def phrase(self, spec: dict[str, Any], where: str, event: str, title: str) -> tuple[str, str] | None:
        action = spec.get("action")
        if action == "do_nothing":
            return None
        if action == "dim_up":
            return "Brighter", f"{where} brighter" + (" (keep holding)" if event == "on_repeat" else "")
        if action == "dim_down":
            return "Dimmer", f"{where} dimmer" + (" (keep holding)" if event == "on_repeat" else "")
        if action == "all_off":
            return f"{where} off", f"{where} lights off"
        if action == "home_off":
            return "Whole house off", "Every Hue light in the house off"
        cycle = spec.get("scene_cycle_extended") or spec.get("scene_cycle")
        if cycle:
            names = []
            for slot in cycle.get("slots", []):
                for step in slot:
                    name = self.scene_name(((step.get("action") or {}).get("recall") or {}).get("rid"))
                    if name:
                        names.append(name)
                        break
            if not names:
                self.warn(title, f"Hue scene cycle on {where} has no scenes the bridge can name")
                return "Scene cycle", f"{where}: cycles through scenes"
            first, rest = names[0], names[1:]
            secs = (cycle.get("repeat_timeout") or {}).get("seconds")
            window = f"within {secs} seconds" if secs else "quickly"
            more = f" Press again {window} to step through {' › '.join(rest)}." if rest else ""
            if (cycle.get("with_off") or {}).get("enabled"):
                return (f"{where} on/off",
                        f"{where} on with {first}, or off if the lights are already on.{more}")
            return f"{first} + scenes", f"{where} to {first}.{more}"
        single = spec.get("recall_single_extended") or spec.get("recall_single")
        if single:
            names = [self.scene_name(((a.get("action") or {}).get("recall") or {}).get("rid"))
                     for a in single.get("actions", [])]
            name = next((n for n in names if n), "a scene")
            if (single.get("with_off") or {}).get("enabled"):
                return f"{where} on/off", f"{where} on with {name}, or off if the lights are already on"
            return f"{where} on", f"{where} on with {name}"
        recall = spec.get("recall")
        if recall:
            name = self.scene_name(recall.get("rid")) or "a scene"
            return name, f"{where} to {name}"
        if spec.get("time_based_extended") or spec.get("time_based"):
            tb = spec.get("time_based_extended") or spec.get("time_based")
            off = " (or off if the lights are on)" if (tb.get("with_off") or {}).get("enabled") else ""
            return f"{where} on", f"{where} on with the scene for this time of day{off}"
        self.warn(title, f"Hue action {sorted(spec)} on {where} has no card wording yet")
        return "Hue app action", f"Set in the Hue app ({', '.join(sorted(spec))})"
