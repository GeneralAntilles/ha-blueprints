"""Snapshot + overlay -> list[Controller]."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .layouts import (
    AUX_EVENT_KINDS, BUTTON_LAYOUTS, CONTROLLER_BLUEPRINTS, CUBE_FACE_GESTURES, CUBE_GLOBAL_GESTURES,
    HUE_BUTTON_LABELS, HUE_SWITCH_MODELS, PINNED_SCHEMAS, STATIC_MODELS, drawing_for,
)
from .hue import HUE_MODEL_DRAWING, HueSwitches
from .leds import LedDescriber, notification_lines
from .model import Control, Controller, Gesture
from .summarize import Phrase, Summarizer

BUTTON_NUM_RE = re.compile(r"_button_(\d+)$")
WALL_DIMMER = "wall-dimmer-natural-light-controller.yaml"
CUBE = "aqara-cube-controller.yaml"
SWITCH_LED = "switch-led-day-night-controller.yaml"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class Report:
    warnings: list[str] = field(default_factory=list)

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


class Extractor:
    def __init__(self, snapshot: dict[str, Any], overlay: dict[str, Any]) -> None:
        self.snap = snapshot
        self.overlay = overlay or {}
        self.report = Report()
        self.sum = Summarizer(snapshot["friendly"], snapshot["entities"],
                              self.overlay.get("labels") or {}, snapshot.get("all_entity_ids"))
        self.ctl_overrides: dict[str, Any] = self.overlay.get("controllers") or {}

    # ---------- helpers ----------
    def device(self, dev_id: str) -> dict[str, Any]:
        return self.snap["devices"].get(dev_id) or {"id": dev_id, "name": dev_id[:8], "model": None}

    def device_name(self, dev_id: str) -> str:
        d = self.device(dev_id)
        return d.get("name_by_user") or d.get("name") or dev_id[:8]

    def inputs(self, inst: dict[str, Any]) -> dict[str, Any]:
        """Instance inputs with blueprint defaults merged underneath."""
        schema = self.snap["blueprints"].get(inst["blueprint"], {}).get("inputs", {})
        merged = {k: v.get("default") for k, v in schema.items()}
        merged.update(inst["input"])
        return merged

    def new_controller(self, dev_id: str, *, layout: str, source: str,
                       automation_ids: list[str] | None = None, disabled: bool = False) -> Controller:
        dev = self.device(dev_id)
        area = self.snap["areas"].get(dev.get("area_id") or "", {})
        floor = self.snap["floors"].get(area.get("floor_id") or "", {})
        name = self.device_name(dev_id)
        return Controller(
            slug=slugify(name), title=name, location=area.get("name", ""),
            area=area.get("name", "Unassigned"), floor=floor.get("name", ""),
            floor_level=floor.get("level") if floor.get("level") is not None else 99,
            model=" ".join(x for x in (dev.get("manufacturer"), dev.get("model")) if x),
            layout=layout, drawing=drawing_for(dev.get("model")), device_ids=[dev_id],
            device_names=[name], automation_ids=automation_ids or [], source=source,
            disabled=disabled,
        )

    def gesture(self, where: str, kind: str, phrase: Phrase | None, tier: int,
                input_key: str | None = None) -> Gesture | None:
        if phrase is None:
            return None
        for w in phrase.warnings:
            self.report.warn(where, w)
        for b in phrase.broken:
            self.report.warn(where, f"BROKEN binding ({kind}): {b} does not exist in HA")
        return Gesture(kind=kind, short=phrase.short, long=phrase.long, tier=tier,
                       input_key=input_key, broken=bool(phrase.broken), detail=phrase.detail)

    # ---------- entry point ----------
    def run(self) -> list[Controller]:
        self.check_schemas()
        by_auto: dict[str, Controller] = {}
        led_by_device: dict[str, dict[str, Any]] = {}
        aux: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

        for inst in self.snap["instances"]:
            bp = inst["blueprint"]
            inp = self.inputs(inst)
            disabled = inst["state"] == "off"
            if bp == SWITCH_LED:
                if not disabled:
                    for dev in inp.get("inovelli_devices") or []:
                        led_by_device[dev] = {"kind": "inovelli", **inp}
                    for dev in inp.get("hs_devices") or []:
                        led_by_device[dev] = {"kind": "homeseer", **inp}
                continue
            if bp in BUTTON_LAYOUTS:
                ctl = self.button_controller(inst, inp, disabled)
            elif bp == WALL_DIMMER:
                ctl = self.wall_dimmer(inst, inp, disabled)
                if not disabled and (inp.get("aux_on_events") or inp.get("aux_off_events")):
                    aux.append((inst["id"], inp, {"title": ctl.title}))
            elif bp == CUBE:
                ctl = self.cube(inst, inp, disabled)
            else:
                continue
            if disabled:
                self.report.warn(ctl.title, f"automation {inst['entity_id']} is OFF; card marked disabled")
            by_auto[inst["id"]] = ctl

        controllers = self.apply_groups(by_auto)
        controllers += self.static_fans(led_by_device)
        controllers += self.manual()
        self.hue_switches(controllers)
        self.add_leds(controllers, led_by_device)
        self.inject_aux(controllers, aux)
        self.warn_missing_hue(controllers)
        for ctl in controllers:
            self.apply_overrides(ctl)
        controllers.sort(key=lambda c: (c.disabled, c.floor_level, c.area, c.title))
        self.check_unique_slugs(controllers)
        return controllers

    def check_schemas(self) -> None:
        used = {i["blueprint"] for i in self.snap["instances"]}
        missing = sorted(b for b in used if not self.snap["blueprints"].get(b, {}).get("inputs"))
        if missing:
            raise SystemExit(f"snapshot has no blueprint schema for {missing}; without it the "
                             "blueprint defaults are unknown and cards could be wrong. Re-run fetch.py.")
        for path in CONTROLLER_BLUEPRINTS:
            got = self.snap["blueprints"].get(path, {}).get("hash")
            if got and got != PINNED_SCHEMAS.get(path):
                self.report.warn(path, f"blueprint inputs changed (schema {got}, layout written for "
                                       f"{PINNED_SCHEMAS.get(path)}): review guide/layouts.py + "
                                       "extract.py, then update PINNED_SCHEMAS")

    # ---------- button remotes ----------
    def button_controller(self, inst: dict[str, Any], inp: dict[str, Any], disabled: bool) -> Controller:
        dev_key = "minimote_device" if "minimote" in inst["blueprint"] else "zen37_device"
        ctl = self.new_controller(inp[dev_key], layout=inst["blueprint"], source="blueprint",
                                  automation_ids=[inst["id"]], disabled=disabled)
        for spec in BUTTON_LAYOUTS[inst["blueprint"]]:
            control = Control(spec.id, spec.badge, spec.label)
            for g in spec.gestures:
                gest = self.gesture(ctl.title, g.kind, self.sum.phrase(inp.get(g.input_key)),
                                    g.tier, g.input_key)
                if gest:
                    control.gestures.append(gest)
            ctl.controls.append(control)
        return ctl

    # ---------- wall dimmer (fixed grammar) ----------
    # Mirrors the choose-branches in wall-dimmer-natural-light-controller.yaml
    # (UP 1x ~line 986, UP 2x ~1025, DOWN 1x ~1072, DOWN 2x ~1098). Excluded
    # house modes only skip the scene recalls in UP 1x and DOWN 2x (scene_ok).
    def wall_dimmer(self, inst: dict[str, Any], inp: dict[str, Any], disabled: bool) -> Controller:
        ctl = self.new_controller(inp["dimmer_device"], layout=WALL_DIMMER, source="blueprint",
                                  automation_ids=[inst["id"]], disabled=disabled)
        hue_lights = _as_list(inp.get("hue_lights"))
        hue = self.sum.names(hue_lights) if hue_lights else ""
        scene = inp.get("hue_scene") or ""
        lamps_scene = inp.get("lamps_only_scene") or scene
        pct = inp.get("full_bright_pct", 100)
        linked = _as_list(inp.get("linked_lights"))
        cans = "Overhead lights"
        missing = {e for e in [inp.get("dimmer_light"), scene, lamps_scene, *hue_lights, *linked]
                   if e and not self.sum.exists(e)}
        for ent in sorted(missing):
            self.report.warn(ctl.title, f"BROKEN binding: {ent} does not exist in HA")

        bands = inp.get("brightness_map") if isinstance(inp.get("brightness_map"), dict) else {}
        zero_bands = [b for b, v in bands.items() if str(v).strip() in ("0", "0.0")]
        up1 = f"{cans} on at the time-of-day level"
        if zero_bands:
            up1 += f" (they stay off during {', '.join(zero_bands)})"
        if scene:
            up1 += f", plus {self.sum.name(scene)}"
        up2 = f"{cans} {pct}%"
        if inp.get("full_bright_hue") and hue:
            up2 += f" and {hue} 100%"
        down1 = f"{cans} off" + (f" and {hue} off" if inp.get("off_includes_hue") and hue else "")
        down2 = f"{cans} off, {self.sum.name(lamps_scene)} on" if lamps_scene else f"{cans} off"

        modes = [m.strip() for m in str(inp.get("excluded_house_modes") or "").split(",") if m.strip()]
        scene_cond = ([f"In {' or '.join(m.title() for m in modes)} mode the Hue scene is skipped"]
                      if modes and inp.get("house_mode_entity") else [])
        fixed = [
            ("up_1x", 1, "Lights on", up1, [scene] if scene else [], scene_cond if scene else []),
            ("up_2x", 2, "Full bright", up2, hue_lights if inp.get("full_bright_hue") else [], []),
            ("down_1x", 1, "Lights off", down1, hue_lights if inp.get("off_includes_hue") else [], []),
            ("down_2x", 2, "Lamps only", down2, [lamps_scene] if lamps_scene else [],
             scene_cond if lamps_scene else []),
        ]
        up = Control("up", "▲", "Top of paddle")
        down = Control("down", "▼", "Bottom of paddle")
        load = [inp.get("dimmer_light"), *linked]
        for kind, tier, short, long, refs, conds in fixed:
            broken = any(e in missing for e in [*load, *refs])
            (up if kind.startswith("up") else down).gestures.append(
                Gesture(kind=kind, short=short, long=long, tier=tier, detail="fixed grammar",
                        conditions=list(conds), broken=broken))
        for kind, key, control in (("up_3x", "up_triple_action", up), ("down_3x", "down_triple_action", down)):
            g = self.gesture(ctl.title, kind, self.sum.phrase(inp.get(key)), 3, key)
            if g:
                control.gestures.append(g)
        up.gestures.append(Gesture("up_hold", "Brighter", f"{cans} brighter (the switch dims them itself)",
                                   3, detail="local dimming"))
        down.gestures.append(Gesture("down_hold", "Dimmer", f"{cans} dimmer (the switch dims them itself)",
                                     3, detail="local dimming"))
        ctl.controls += [up, down]

        relay_keys = ("relay_single_action", "relay_double_action", "relay_hold_action")
        if inp.get("relay_scene") and any(inp.get(k) for k in relay_keys):
            relay = Control("relay", "R", "Small button")
            for kind, key, tier in (("single", "relay_single_action", 1), ("double", "relay_double_action", 2),
                                    ("hold", "relay_hold_action", 2)):
                g = self.gesture(ctl.title, kind, self.sum.phrase(inp.get(key)), tier, key)
                if g:
                    relay.gestures.append(g)
            ctl.controls.append(relay)

        if linked:
            ctl.notes.append(f"Works together with the {self.sum.names(linked)}: "
                             "either switch controls both sets of overhead lights.")
        if inp.get("legacy_paddle"):
            window = inp.get("legacy_double_window", 5)
            ctl.notes.append(f"After a double tap, wait {window} seconds before tapping once.")
        return ctl

    # ---------- cube ----------
    def cube(self, inst: dict[str, Any], inp: dict[str, Any], disabled: bool) -> Controller:
        ctl = self.new_controller(inp["cube_device"], layout=CUBE, source="blueprint",
                                  automation_ids=[inst["id"]], disabled=disabled)
        any_face = Control("any", "✱", "Any face up")
        for kind, key, tier in CUBE_GLOBAL_GESTURES:
            g = self.gesture(ctl.title, kind, self.sum.phrase(inp.get(key)), tier, key)
            if g:
                any_face.gestures.append(g)
        if any_face.gestures:
            ctl.controls.append(any_face)

        scene_list = _as_list(inp.get("rotate_scene_list"))
        scene_face = inp.get("rotate_scene_face") or 0
        light = inp.get("rotate_light") or ""
        light_face = inp.get("rotate_light_face") or 0
        for face in range(1, 7):
            control = Control(f"face{face}", str(face), f"Face {face} up")
            for kind, suffix, tier in CUBE_FACE_GESTURES:
                key = f"face_{face}_{suffix}"
                g = self.gesture(ctl.title, kind, self.sum.phrase(inp.get(key)), tier, key)
                if g:
                    control.gestures.append(g)
            if len(scene_list) >= 2 and scene_face in (0, face):
                names = " › ".join(self.sum.name(s) for s in scene_list)
                step = inp.get("rotate_scene_degrees_per_step", 60)
                ends = "then starts over" if inp.get("rotate_scene_wrap") else "and stops at the ends"
                bad = [x for x in scene_list if not self.sum.exists(x)]
                for x in bad:
                    self.report.warn(ctl.title, f"BROKEN binding (scene cycle): {x} does not exist in HA")
                control.gestures += [
                    Gesture("rotate_right", "Next scene",
                            f"Next scene every {step}° of turn: {names}, {ends}", 2,
                            detail="rotate_scene_list", broken=bool(bad)),
                    Gesture("rotate_left", "Previous scene", "Previous scene", 2,
                            detail="rotate_scene_list", broken=bool(bad)),
                ]
            if light and light_face in (0, face):
                pct = inp.get("rotate_percent_per_quarter_turn", 25)
                name = self.sum.names(_as_list(light))
                bad = [x for x in _as_list(light) if not self.sum.exists(x)]
                for x in bad:
                    self.report.warn(ctl.title, f"BROKEN binding (rotate dimming): {x} does not exist in HA")
                control.gestures += [
                    Gesture("rotate_right", "Brighter", f"{name} brighter ({pct}% per quarter turn)", 2,
                            broken=bool(bad)),
                    Gesture("rotate_left", "Dimmer", f"{name} dimmer", 2, broken=bool(bad)),
                ]
            if control.gestures:
                ctl.controls.append(control)
        return ctl

    # ---------- groups ----------
    def apply_groups(self, by_auto: dict[str, Controller]) -> list[Controller]:
        groups = self.overlay.get("groups") or {}
        used: set[str] = set()
        out: list[Controller] = []
        for slug, spec in groups.items():
            members = [m for m in spec.get("members", []) if m in by_auto]
            missing = set(spec.get("members", [])) - set(members)
            if missing:
                self.report.warn(f"group {slug}", f"members not found: {sorted(missing)}")
            # A switched-off member must not be advertised as working: leave it
            # out of the group so it gets its own card under "Switched off".
            enabled = [m for m in members if not by_auto[m].disabled]
            if enabled and len(enabled) < len(members):
                for m in members:
                    if m not in enabled:
                        self.report.warn(f"group {slug}", f"{by_auto[m].title} is switched off; "
                                                         "shown separately, not on the group card")
                members = enabled
            if not members:
                continue
            first = by_auto[members[0]]
            base_sig = _controls_sig(first)
            for m in members[1:]:
                if _controls_sig(by_auto[m]) != base_sig:
                    self.report.warn(f"group {slug}",
                                     f"{by_auto[m].title} is bound differently from {first.title}; "
                                     f"the card shows {first.title}'s buttons")
            first.slug = slug
            first.title = spec.get("title") or " & ".join(by_auto[m].title for m in members)
            for m in members[1:]:
                first.device_ids += by_auto[m].device_ids
                first.device_names += by_auto[m].device_names
                first.automation_ids += by_auto[m].automation_ids
            used.update(members)
            out.append(first)
        out += [c for a, c in by_auto.items() if a not in used]
        return out

    # ---------- static fan switches ----------
    def static_fans(self, led_by_device: dict[str, dict[str, Any]]) -> list[Controller]:
        out = []
        text = self.overlay.get("vzm35") or {}
        for dev_id, dev in self.snap["devices"].items():
            if not any(m == dev.get("model") for m in STATIC_MODELS):
                continue
            ctl = self.new_controller(dev_id, layout="VZM35-SN", source="static")
            up = Control("up", "▲", "Top of paddle", [
                Gesture("up_1x", text.get("up_1x", "Fan on"),
                        text.get("up_1x_long", "Fan on"), 1, source="device"),
                Gesture("up_hold", text.get("up_hold", "Faster"),
                        text.get("up_hold_long", "Hold to speed the fan up"), 2, source="device"),
            ])
            down = Control("down", "▼", "Bottom of paddle", [
                Gesture("down_1x", text.get("down_1x", "Fan off"),
                        text.get("down_1x_long", "Fan off"), 1, source="device"),
                Gesture("down_hold", text.get("down_hold", "Slower"),
                        text.get("down_hold_long", "Hold to slow the fan down"), 2, source="device"),
            ])
            config = Control("config", "C", "Small button beside the paddle", [
                Gesture("info", text.get("config", "Not used"),
                        text.get("config_long", "Not used day to day"), 3, source="device"),
            ])
            ctl.controls += [up, down, config]
            ctl.notes.append(text.get("air_gap_note", "Pull the small tab under the paddle out "
                                                      "to cut power to the fan, e.g. before cleaning it."))
            override = self.override_for(ctl.slug, [dev_id])
            if dev_id not in led_by_device and not override.get("led_night_off_not_needed"):
                self.report.warn(ctl.title, "light bar brightness is not managed by any "
                                            "Switch LED Day/Night instance (set "
                                            "led_night_off_not_needed: true if that's intended)")
            out.append(ctl)
        return out

    def add_leds(self, controllers: list[Controller], led_by_device: dict[str, dict[str, Any]]) -> None:
        describer = LedDescriber(self.snap.get("leds") or {})
        for ctl in controllers:
            inst = next((led_by_device[d] for d in ctl.device_ids if d in led_by_device), None)
            ctl.leds, ctl.led_raw = describer.describe(ctl.drawing, ctl.device_ids, inst)

    # ---------- hand-entered Hue switches ----------
    def manual(self) -> list[Controller]:
        out = []
        for i, spec in enumerate(self.overlay.get("manual") or []):
            dev_id = spec.get("device_id")
            layout = spec.get("layout") or "hue-dimmer"
            if dev_id:
                ctl = self.new_controller(dev_id, layout=layout, source="manual")
            else:
                title = spec.get("title") or f"Manual {i + 1}"
                ctl = Controller(slug=slugify(title), title=title, location=spec.get("location", ""),
                                 area=spec.get("location", ""), floor="", floor_level=99, model="",
                                 layout=layout, drawing=layout, device_ids=[], device_names=[title],
                                 source="manual")
            ctl.drawing = spec.get("drawing") or (layout if ctl.drawing == "generic" else ctl.drawing)
            labels = HUE_BUTTON_LABELS.get(layout, {})
            for n, btn in (spec.get("buttons") or {}).items():
                n = int(n)
                control = Control(f"b{n}", str(n), (btn or {}).get("label") or labels.get(n, f"Button {n}"))
                for kind in ("press", "double", "hold"):
                    val = (btn or {}).get(kind)
                    if val:
                        short, long = (val, val) if isinstance(val, str) else (val.get("short"), val.get("long"))
                        control.gestures.append(Gesture(kind, short or long, long or short,
                                                        1 if kind == "press" else 2, source="hue"))
                ctl.controls.append(control)
            ctl.notes += spec.get("notes") or []
            out.append(ctl)
        return out

    def hue_device_id(self, dev: dict[str, Any]) -> str | None:
        for ident in dev.get("identifiers") or []:
            if len(ident) == 2 and ident[0] == "hue":
                return ident[1]
        return None

    def hue_switches(self, controllers: list[Controller]) -> None:
        """Cards for switches programmed in the Hue app, read from the bridge."""
        hue = self.snap.get("hue")
        if not hue:
            return
        if hue.get("stale"):
            self.report.warn("Hue", "Hue switch data is from an earlier fetch (bridge or credentials "
                                    "unavailable); cards may be out of date")
        manual_devs = {m.get("device_id") for m in self.overlay.get("manual") or []}
        helper = HueSwitches(hue, self.report.warn)
        behaviors = helper.by_hue_device()
        have = {d: c for c in controllers for d in c.device_ids}
        for dev_id, dev in self.snap["devices"].items():
            if dev.get("model") not in HUE_SWITCH_MODELS or dev_id in manual_devs:
                continue
            hue_id = self.hue_device_id(dev)
            candidates = behaviors.get(hue_id or "", [])
            if not candidates:
                continue
            enabled = [b for b in candidates if b.get("enabled") is not False]
            if len(enabled) > 1:
                self.report.warn(self.device_name(dev_id), f"{len(enabled)} active Hue configurations; "
                                                           f"using {enabled[0].get('name')!r}")
            behavior = enabled[0] if enabled else None
            ctl = have.get(dev_id)
            if ctl is None:
                ctl = self.new_controller(dev_id, layout="hue", source="hue")
                controllers.append(ctl)
                have[dev_id] = ctl
            ctl.layout = "hue"
            model_id = (behavior or candidates[0]).get("model_id") or ""
            ctl.drawing = HUE_MODEL_DRAWING.get(model_id, ctl.drawing)
            if behavior is None:
                # Switched off in the Hue app: publish no Hue gestures as if they worked.
                ctl.notes.append("Its Hue app setup is switched off, so its buttons do nothing in "
                                 "the Hue app right now.")
                self.report.warn(ctl.title, "Hue switch configuration is disabled on the bridge; "
                                            "no Hue gestures shown")
                continue
            ctl.controls = helper.controls(behavior, ctl.title) + ctl.controls
            ctl.notes.append("These buttons are set up in the Hue app.")
            bridge_name = hue.get("devices", {}).get(hue_id, {}).get("name")
            if bridge_name and bridge_name.lower() != ctl.title.lower():
                self.report.warn(ctl.title, f"called {bridge_name!r} in the Hue app; "
                                            "consider renaming one so they match")

    def warn_missing_hue(self, controllers: list[Controller]) -> None:
        """Hue switches nobody has written down still get a visible card."""
        manual_devs = {m.get("device_id") for m in self.overlay.get("manual") or []}
        have = {d: c for c in controllers for d in c.device_ids}
        for dev_id, dev in self.snap["devices"].items():
            if dev.get("model") not in HUE_SWITCH_MODELS or dev_id in manual_devs:
                continue
            ctl = have.get(dev_id)
            if ctl is not None and ctl.layout == "hue":
                continue
            if ctl is None:
                ctl = self.new_controller(dev_id, layout=drawing_for(dev.get("model")), source="manual")
                controllers.append(ctl)
            ctl.notes.insert(0, "This switch is programmed in the Hue app, and what its buttons "
                                "do there hasn't been written down here yet.")
            self.report.warn(ctl.title, f"Hue switch has no configuration on the bridge and no overlay "
                                        f"`manual:` entry (device_id {dev_id})")

    # ---------- extra buttons (Hue Tap etc. feeding a wall dimmer) ----------
    def inject_aux(self, controllers: list[Controller], aux: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> None:
        by_dev = {d: c for c in controllers for d in c.device_ids}
        for auto_id, inp, meta in aux:
            mood_names = [s.strip() for s in str(inp.get("aux_off_scene_names") or "").split(",") if s.strip()]
            probe = str(inp.get("aux_scene_probe") or "").strip()
            mood = " or ".join(mood_names) if (mood_names and probe) else ""
            types = [t.strip() for t in str(inp.get("aux_event_types") or "").split(",") if t.strip()]
            kinds: list[str] = []
            for t in types or ["initial_press"]:
                kind = AUX_EVENT_KINDS.get(t)
                if kind is None:
                    self.report.warn(meta["title"], f"Extra Buttons event type {t!r} has no card wording; "
                                                    "add it to AUX_EVENT_KINDS in guide/layouts.py")
                elif kind not in kinds:
                    kinds.append(kind)
            if not types:
                self.report.warn(meta["title"], "Extra Buttons accept every event type; card shows Press only")
            for key, on in (("aux_on_events", True), ("aux_off_events", False)):
                for ent in _as_list(inp.get(key)):
                    if not ent.startswith("event."):
                        continue      # input_button helpers etc. have no physical button
                    reg = self.snap["entities"].get(ent)
                    if not reg or not reg.get("device_id"):
                        self.report.warn(meta["title"], f"extra button {ent} not found in the entity registry")
                        continue
                    dev_id = reg["device_id"]
                    ctl = by_dev.get(dev_id)
                    if ctl is None:
                        ctl = self.new_controller(dev_id, layout=drawing_for(self.device(dev_id).get("model")),
                                                  source="manual")
                        controllers.append(ctl)
                        by_dev[dev_id] = ctl
                    m = BUTTON_NUM_RE.search(ent)
                    num = m.group(1) if m else ent
                    control = next((c for c in ctl.controls if c.id == f"b{num}"), None)
                    if control is None:
                        labels = HUE_BUTTON_LABELS.get(ctl.layout, {})
                        control = Control(f"b{num}", str(num), labels.get(int(num), f"Button {num}")
                                          if str(num).isdigit() else ent)
                        ctl.controls.append(control)
                        ctl.controls.sort(key=lambda c: c.badge)
                    if on:
                        long = "Also turns the overhead lights on at the time-of-day level"
                        if mood:
                            long += (f". If the Hue app lands on {mood}, they switch "
                                     "back off a moment later")
                        short = "+ overheads on"
                    else:
                        long, short = "Also turns the overhead lights off", "+ overheads off"
                    for kind in kinds:
                        same = next((g for g in control.gestures if g.kind == kind and g.source == "hue"), None)
                        if same is not None:
                            # One press does both: say so on one line, at the Hue gesture's tier.
                            same.short = f"{same.short}; overheads {'on' if on else 'off'}"
                            lead = same.long.rstrip(".")
                            same.long = f"{lead}. {long.replace('Also turns', 'Home Assistant also turns')}."
                            same.detail += f" + {auto_id}: {ent}"
                            continue
                        control.gestures.append(Gesture(kind, short, long, 1 if kind == "press" else 2,
                                                        source="ha", input_key=key,
                                                        detail=f"{auto_id}: {ent}"))
                    if auto_id not in ctl.automation_ids:
                        ctl.automation_ids.append(auto_id)

    # ---------- overlay overrides ----------
    def override_for(self, slug: str, keys: list[str]) -> dict[str, Any]:
        return next((self.ctl_overrides[k] for k in (slug, *keys) if k in self.ctl_overrides), {})

    def apply_overrides(self, ctl: Controller) -> None:
        o = self.override_for(ctl.slug, [*ctl.device_ids, *ctl.automation_ids])
        if not o:
            return
        ctl.title = o.get("title", ctl.title)
        ctl.location = o.get("location", ctl.location)
        if "slug" in o:
            ctl.slug = o["slug"]
        ctl.notes = list(o.get("notes_before") or []) + ctl.notes + list(o.get("notes") or [])
        ctl.leds = notification_lines(o.get("led_notifications")) + ctl.leds
        labels = o.get("control_labels") or {}
        hidden = set(o.get("hide") or [])
        overrides = o.get("gestures") or {}
        for control in ctl.controls:
            control.label = labels.get(control.id, control.label)
            kept = []
            for g in control.gestures:
                key = f"{control.id}.{g.kind}"
                if key in hidden:
                    continue
                if key in overrides:
                    val = overrides[key]
                    if isinstance(val, str):
                        g.short = g.long = val
                    else:
                        g.short = val.get("short", g.short)
                        g.long = val.get("long", g.long)
                        g.tier = val.get("tier", g.tier)
                kept.append(g)
            control.gestures = kept

    def check_unique_slugs(self, controllers: list[Controller]) -> None:
        seen: dict[str, int] = {}
        for c in controllers:
            if c.slug in seen:
                seen[c.slug] += 1
                self.report.warn(c.title, f"duplicate slug {c.slug}; renamed")
                c.slug = f"{c.slug}-{seen[c.slug]}"
            else:
                seen[c.slug] = 1


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _controls_sig(ctl: Controller) -> str:
    return json.dumps([(c.id, [(g.kind, g.detail) for g in c.gestures]) for c in ctl.controls])
