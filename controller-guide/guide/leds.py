"""What each switch's indicator lights mean, from live LED settings.

Inputs: snapshot["leds"][device_id] = {"zwave": [{param, label, value, state}],
"zha": {on_color, on_intensity, off_color, off_intensity}} plus the Switch LED
Day/Night instance for that device (if any) and overlay led_notifications.
The sentence per model is written here; the values come from the device.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Zooz / HomeSeer named colours -> swatch CSS.
NAMED = {
    "white": "#ffffff", "red": "#e0453a", "green": "#2fa84f", "blue": "#2f6fe0",
    "yellow": "#f2c230", "magenta": "#d63fb8", "pink": "#ec6fb0", "purple": "#7b3fe4",
    "orange": "#f28c28", "cyan": "#19c3d6", "off": None,
}
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
MODE_PHRASES = {
    "on when load is on": "on while the lights are on",
    "on when load is off": "on while the lights are off, as a night-light for finding the switch",
    "off when load is off": "off while the lights are off",
    "always on": "always on",
    "always off": "always off",
}


@dataclass
class LedLine:
    text: str
    tier: int = 2
    swatches: list[tuple[str | None, str]] = field(default_factory=list)   # (css colour, label)
    source: str = "device"            # device | notification


def swatch(name: str | None) -> str | None:
    return NAMED.get((name or "").strip().lower())


def inovelli_css(value: Any) -> str | None:
    """Inovelli colour numbers: 0-254 = hue around the wheel, 255 = white."""
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return None
    if v >= 255:
        return "#ffffff"
    return f"hsl({round(v / 255 * 360)}, 85%, 50%)"


def inovelli_name(value: Any) -> str:
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return "unknown colour"
    if v >= 255:
        return "white"
    hue = v / 255 * 360
    for limit, name in ((15, "red"), (45, "orange"), (70, "yellow"), (165, "green"),
                        (200, "cyan"), (255, "blue"), (290, "purple"), (335, "pink"), (361, "red")):
        if hue < limit:
            return name
    return "red"


def _mode(state: str | None, subject: str = "the lights are") -> str:
    phrase = MODE_PHRASES.get((state or "").strip().lower(), (state or "unknown").lower())
    return phrase.replace("the lights are", subject)


class LedDescriber:
    def __init__(self, leds: dict[str, Any]) -> None:
        self.leds = leds

    def describe(self, drawing: str, device_ids: list[str],
                 led_instance: dict[str, Any] | None) -> tuple[list[LedLine], list[tuple[str, str]]]:
        """(lines for the card/page, raw rows for technical details)."""
        data: dict[str, Any] = {}
        for d in device_ids:
            if d in self.leds:
                data = self.leds[d]
                break
        rows = data.get("zwave") or []
        raw = [(r["label"], str(r["state"] if r["state"] is not None else r["value"])) for r in rows]
        raw += [(f"Light bar {k.replace('_', ' ')}", str(v)) for k, v in (data.get("zha") or {}).items()]
        by_label = {r["label"]: r for r in rows}
        fn = getattr(self, "_" + drawing.replace("-", "_"), None)
        lines = fn(by_label, data, led_instance) if fn else []
        return lines, raw

    # ---------- per model ----------
    def _zen37(self, rows: dict[str, Any], data: dict[str, Any], inst: Any) -> list[LedLine]:
        # Zooz manual: the LED in the top-left corner of button 1 lights on any
        # press and blinks once per tap (twice for a double tap...).
        sw = []
        for n in range(1, 5):
            r = rows.get(f"LED Indicator Color (Button {n})")
            if r:
                sw.append((swatch(r["state"]), f"{n} {r['state'].lower()}"))
        if not sw:
            return []
        return [LedLine("The light in the top-left corner of button 1 blinks once for each tap, "
                        "in the colour of the button you pressed.", 2, sw)]

    def _paddle_zooz(self, rows: dict[str, Any], data: dict[str, Any], inst: Any) -> list[LedLine]:
        mode, color, bright = (rows.get("LED Indicator"), rows.get("LED Indicator Color"),
                               rows.get("LED Indicator Brightness"))
        if not mode:
            return []
        sw = [(swatch(color["state"]), (color["state"] or "").lower())] if color else []
        level = (bright or {}).get("state") or ""
        extra = f", at {level.lower().replace(' (', ' brightness (')}" if level else ""
        return [LedLine(f"The small light at the bottom right is {_mode(mode['state'])}{extra}.", 2, sw)]

    def _paddle_zen30(self, rows: dict[str, Any], data: dict[str, Any], inst: Any) -> list[LedLine]:
        out = []
        for part, where, tier in (("Dimmer", "The column of dots beside the paddle is", 2),
                                  ("Relay", "The small button's light is", 3)):
            mode = rows.get(f"LED Indicator Mode for {part}")
            color = rows.get(f"LED Indicator Color for {part}")
            if not mode:
                continue
            subject = "the lights are" if part == "Dimmer" else "its circuit is"
            text = f"{where} {_mode(mode['state'], subject)}."
            sw = [(swatch(color["state"]), (color["state"] or "").lower())] if color else []
            out.append(LedLine(text, tier, sw))
        return out

    def _paddle_ge(self, rows: dict[str, Any], data: dict[str, Any], inst: Any) -> list[LedLine]:
        mode = rows.get("LED Indicator") or rows.get("LED Light")
        return [LedLine(f"The small light at the bottom is {_mode(mode['state'])}.", 2)] if mode else []

    def _paddle_hs(self, rows: dict[str, Any], data: dict[str, Any], inst: Any) -> list[LedLine]:
        out = []
        load = rows.get("Load Status LED Color")
        if load and (load["state"] or "").lower() != "off":
            out.append(LedLine("The column of lights beside the paddle shows how bright the lights "
                               "are.", 2, [(swatch(load["state"]), load["state"].lower())]))
        bottom = rows.get("Bottom LED Operation")
        if bottom:
            out.append(LedLine(f"The bottom light is {_mode(bottom['state'])}.", 3))
        status = []
        for n in range(1, 8):
            r = rows.get(f"Status LED {n} Color")
            if r and (r["state"] or "off").lower() != "off":
                blink = rows.get(f"LED {n} Blink Status")
                how = "blinking" if blink and "blink" in (blink["state"] or "").lower() else "solid"
                status.append((swatch(r["state"]), f"light {n}: {how} {r['state'].lower()}"))
        if status:
            out.append(LedLine("Status lights set by Home Assistant:", 2, status))
        if inst and str(inst.get("hs_night_mode")) == "1":
            bands = ", ".join(inst.get("night_bands") or []) or "night"
            out.append(LedLine(f"At night ({bands}) the column goes dark unless a status light is set.", 2))
        return out

    def _vzm35(self, rows: dict[str, Any], data: dict[str, Any], inst: Any) -> list[LedLine]:
        zha = data.get("zha") or {}
        color = zha.get("on_color")
        sw = [(inovelli_css(color), inovelli_name(color))] if color is not None else []
        out = [LedLine("The light bar beside the paddle shows the fan speed.", 2, sw)]
        if inst:
            bands = ", ".join(inst.get("night_bands") or []) or "night"
            n_on, n_off = str(inst.get("inovelli_night_on")), str(inst.get("inovelli_night_off"))
            if n_on == "0" and n_off == "0":
                out.append(LedLine(f"It turns itself off at night ({bands}).", 2))
            elif n_on != "None" or n_off != "None":
                out.append(LedLine(f"At night ({bands}) it dims to {n_on}% while the fan runs and "
                                   f"{n_off}% while it's off.", 2))
        return out


def notification_lines(spec: list[dict[str, Any]] | None) -> list[LedLine]:
    """Overlay led_notifications: [{color, effect, means}] -> lines with swatches."""
    out = []
    for n in spec or []:
        color = str(n.get("color", "")).strip()
        effect = str(n.get("effect", "")).strip()
        label = " ".join(x for x in (effect, color.lower()) if x) or "Light"
        css = swatch(color)
        if css is None and HEX_RE.fullmatch(color):
            css = color            # only plain #rgb / #rrggbb: nothing else reaches a style attribute
        out.append(LedLine(f"{label[:1].upper() + label[1:]}: {n.get('means', '')}", 1,
                           [(css, label)], source="notification"))
    return out
