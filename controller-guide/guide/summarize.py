"""Turn Home Assistant action lists into short and long human phrases.

Lookup order for each action (and for a whole multi-step sequence):
  1. overlay `labels:` keyed by the action's signature
  2. generated fallback from script aliases / friendly names (emits a warning)

Signatures (what you write as overlay label keys):
  script.<id>[@k=v...]                     script called directly or via script.turn_on
  scene.turn_on:<scene>
  <domain>.<service>:<entity>[,<entity>][@k=v...]
  device:<domain>.<type>:<entity_id>[@k=v...]
  repeat:<inner signature>
  A multi-step sequence's signature is the step signatures joined with " + ".
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

PREFIX_RE = re.compile(r"^[A-Z][\w ]*: [^-]+ - ")      # "Comfort: Living Room - "
TRAILING_NUM_RE = re.compile(r"\s+\d+$")                # "Natural light 16"
SKIP_KEYS = {"metadata", "continue_on_error", "enabled", "alias"}
ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
HEX32_RE = re.compile(r"[0-9a-f]{32}")


@dataclass
class Phrase:
    short: str
    long: str
    detail: str
    signature: str
    labeled: bool
    broken: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Summarizer:
    def __init__(self, friendly: dict[str, str], entities: dict[str, dict[str, Any]],
                 labels: dict[str, Any], all_entity_ids: list[str] | None = None) -> None:
        self.friendly = friendly
        # Every entity HA reported at fetch time. Empty (old snapshot) = fall back to friendly names.
        self.known = set(all_entity_ids or []) or set(friendly)
        self.domains = {e.split(".", 1)[0] for e in self.known}
        self.labels = {k: self._norm_label(v) for k, v in (labels or {}).items()}
        self.reg_id_to_entity = {e["id"]: eid for eid, e in entities.items() if e.get("id")}

    @staticmethod
    def _norm_label(value: Any) -> tuple[str, str]:
        if isinstance(value, str):
            return value, value
        short = value.get("short") or value.get("long") or ""
        return short, value.get("long") or short

    # ---------- public ----------
    def phrase(self, actions: Any) -> Phrase | None:
        if not actions:
            return None
        steps = actions if isinstance(actions, list) else [actions]
        steps = [s for s in steps if not (isinstance(s, dict) and s.get("enabled") is False)]
        if not steps:
            return None
        parts = [self._step(s) for s in steps]
        sig = " + ".join(p.signature for p in parts)
        broken = [b for p in parts for b in p.broken]
        detail = " + ".join(p.detail for p in parts)
        if sig in self.labels:
            short, long = self.labels[sig]
            return Phrase(short, long, detail, sig, True, broken)
        if len(parts) == 1:
            return parts[0]
        long = " + ".join(p.long for p in parts)
        warnings = [w for p in parts for w in p.warnings]
        if not all(p.labeled for p in parts):
            warnings.append(f"unlabeled sequence: {sig}")
        return Phrase(parts[0].short + " + more", long, detail, sig,
                      all(p.labeled for p in parts), broken, warnings)

    def name(self, entity_id: str) -> str:
        name = self.friendly.get(entity_id)
        if not name:
            return entity_id.split(".", 1)[-1].replace("_", " ").title()
        return _cap_words(TRAILING_NUM_RE.sub("", name))

    def names(self, entity_ids: list[str]) -> str:
        labels = [self.name(e) for e in entity_ids]
        if len(labels) <= 2:
            return " & ".join(labels)
        return f"{labels[0]} + {len(labels) - 1} more"

    def exists(self, entity_id: str) -> bool:
        return entity_id in self.known

    # ---------- one step ----------
    def _step(self, step: dict[str, Any]) -> Phrase:
        if "repeat" in step:
            inner = self.phrase(step["repeat"].get("sequence", []))
            if inner is None:
                return self._unknown(step, "repeat:")
            sig = "repeat:" + inner.signature
            return self._finish(sig, inner.short, inner.long, inner.detail,
                                inner.broken, labeled=inner.labeled)
        if "parallel" in step or "sequence" in step:
            inner = self.phrase(step.get("parallel") or step.get("sequence") or [])
            if inner is None:
                return self._unknown(step, "empty")
            return self._finish("group:" + inner.signature, inner.short, inner.long, inner.detail,
                                inner.broken, labeled=inner.labeled)
        if "choose" in step or "if" in step:
            branches = ([b.get("sequence", []) for b in step.get("choose") or []]
                        + [step.get("default") or [], step.get("then") or [], step.get("else") or []])
            parts = [p for p in (self.phrase(b) for b in branches if b) if p]
            digest = hashlib.sha256(json.dumps(step, sort_keys=True, default=str).encode()).hexdigest()[:8]
            sig = f"branch:{digest}"
            broken = [b for p in parts for b in p.broken]
            long = "Depends on the situation: " + " / ".join(p.long for p in parts) if parts else "Depends on the situation"
            return self._finish(sig, "Depends", long, sig, broken)
        if "device_id" in step and "type" in step:
            return self._device_step(step)
        service = step.get("action") or step.get("service")
        if not service:
            return self._unknown(step, "complex")
        data = {k: v for k, v in (step.get("data") or {}).items()
                if k not in SKIP_KEYS and k != "entity_id"}
        targets = _targets(step)

        if service == "script.turn_on" and targets:
            script_ids = targets
            data = data.get("variables", {}) or {}
        elif service.startswith("script.") and service not in ("script.turn_off", "script.toggle"):
            script_ids = [service]
        else:
            script_ids = []

        data_refs = self._entity_refs(data)
        if script_ids:
            sig = ",".join(script_ids) + _data_suffix(data)
            broken = [s for s in script_ids + data_refs if not self.exists(s)]
            long = " + ".join(self._script_phrase(sid, data) for sid in script_ids)
            return self._finish(sig, long, long, sig, broken)

        sig = f"{service}:{','.join(targets)}" + _data_suffix(data)
        broken = [t for t in targets + data_refs if not self.exists(t)]
        long = self._service_phrase(service, targets, data)
        return self._finish(sig, long, long, sig, broken)

    def _entity_refs(self, value: Any) -> list[str]:
        """Entity ids mentioned inside action data (e.g. tts media_player_entity_id)."""
        found: list[str] = []
        if isinstance(value, str):
            if ENTITY_ID_RE.match(value) and value.split(".", 1)[0] in self.domains:
                found.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                found += self._entity_refs(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                found += self._entity_refs(v)
        return found

    def _device_step(self, step: dict[str, Any]) -> Phrase:
        raw = step.get("entity_id", "")
        entity = self.reg_id_to_entity.get(raw, raw or "?")
        unresolved = bool(HEX32_RE.fullmatch(raw or "")) and raw not in self.reg_id_to_entity
        extra = {k: v for k, v in step.items()
                 if k not in ("device_id", "domain", "entity_id", "type") and k not in SKIP_KEYS}
        sig = f"device:{step['domain']}.{step['type']}:{entity}" + _data_suffix(extra)
        value = ", ".join(str(v) for v in extra.values())
        long = f"{self.name(entity)}: {step['type'].replace('_', ' ')}" + (f" {value}" if value else "")
        broken = [f"entity registry id {raw}"] if unresolved else ([] if self.exists(entity) else [entity])
        return self._finish(sig, long, long, sig, broken)

    def _finish(self, sig: str, short: str, long: str, detail: str,
                broken: list[str], labeled: bool = False) -> Phrase:
        if sig in self.labels:
            s, lng = self.labels[sig]
            return Phrase(s, lng, detail, sig, True, broken)
        warnings = [] if labeled else [f"unlabeled: {sig}"]
        return Phrase(short, long, detail, sig, labeled, broken, warnings)

    def _unknown(self, step: dict[str, Any], sig: str) -> Phrase:
        return Phrase("Custom action", "Custom action (see automation)", str(step)[:120],
                      sig, False, [], [f"unsupported action shape: {str(step)[:80]}"])

    # ---------- fallbacks ----------
    def _script_phrase(self, script_id: str, data: dict[str, Any]) -> str:
        if script_id == "script.room_light_toggle":
            lights = _as_list(data.get("light_target")) or _as_list(data.get("area_target"))
            return f"{self.names(lights) or 'Room'} lights on/off"
        alias = self.friendly.get(script_id) or script_id.split(".", 1)[1].replace("_", " ").title()
        alias = PREFIX_RE.sub("", alias)
        if data.get("brightness_pct") is not None:
            alias += f" ({data['brightness_pct']}%)"
        return alias

    def _service_phrase(self, service: str, targets: list[str], data: dict[str, Any]) -> str:
        who = self.names(targets) if targets else ""
        verb = service.split(".", 1)[1]
        pct = data.get("brightness_pct")
        table = {
            "turn_off": f"{who} off",
            "turn_on": f"{who} on" + (f" {pct}%" if pct is not None else ""),
            "toggle": f"{who} on/off",
            "increase_speed": f"{who} faster",
            "decrease_speed": f"{who} slower",
            "volume_up": f"{who} volume up",
            "volume_down": f"{who} volume down",
            "media_play_pause": f"{who} play/pause",
            "speak": "Spoken announcement",
        }
        if service == "scene.turn_on":
            return who
        return table.get(verb, f"{who}: {verb.replace('_', ' ')}").strip()


def _cap_words(text: str) -> str:
    """Capitalise each word's first letter without lowering the rest ("TV" stays)."""
    return " ".join(w[:1].upper() + w[1:] for w in text.split(" "))


def _targets(step: dict[str, Any]) -> list[str]:
    """Entity targets, wherever they were written, sorted and de-duplicated
    so a UI re-save that reorders or moves them keeps the same signature."""
    target = step.get("target") or {}
    ents = (_as_list(target.get("entity_id")) + _as_list(step.get("entity_id"))
            + _as_list((step.get("data") or {}).get("entity_id")))
    return sorted({e for e in ents if isinstance(e, str)})


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _hash_templates(value: Any) -> Any:
    """Replace Jinja templates with a short content hash: keeps label keys
    readable while still telling different templates apart."""
    if isinstance(value, str) and ("{{" in value or "{%" in value):
        return "tpl:" + hashlib.sha256(value.encode()).hexdigest()[:8]
    if isinstance(value, dict):
        return {k: _hash_templates(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_hash_templates(v) for v in value]
    return value


def _data_suffix(data: dict[str, Any]) -> str:
    """Every parameter (templates and nested values included) in a stable
    order, so two actions that behave differently never share a label."""
    parts = []
    for key in sorted(data):
        val = _hash_templates(data[key])
        if isinstance(val, (list, tuple)) and all(not isinstance(v, (dict, list)) for v in val):
            val = ",".join(str(v) for v in val)
        elif isinstance(val, (dict, list, tuple)):
            val = json.dumps(val, sort_keys=True, separators=(",", ":"), default=str)
        parts.append(f"{key}={val}")
    return ("@" + "@".join(parts)) if parts else ""
