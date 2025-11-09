"""Configuration helpers covering search fixtures and method catalogues."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import yaml


@dataclass(frozen=True)
class MethodConfig:
    """Base representation of a single extraction method."""

    id: str
    kind: str
    label: str | None
    description: str | None
    params: Mapping[str, Any] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "type": self.kind,
            "label": self.label or self.id,
        }
        if self.description:
            payload["description"] = self.description
        if self.params:
            payload["params"] = dict(self.params)
        if self.config:
            payload.update(self.config)
        return payload


@dataclass(frozen=True)
class HybridStage:
    """Resolved reference to a method used within a hybrid cascade."""

    reference: str
    method: MethodConfig


@dataclass(frozen=True)
class HybridMethodConfig(MethodConfig):
    """Hybrid method capable of cascading across other strategies."""

    strategy: str = "cascade"
    stages: Tuple[HybridStage, ...] = ()
    fallback: MethodConfig | None = None

    def to_metadata(self) -> Dict[str, Any]:  # type: ignore[override]
        payload = super().to_metadata()
        payload["strategy"] = self.strategy
        payload["stages"] = [stage.method.id for stage in self.stages]
        if self.fallback is not None:
            payload["fallback"] = self.fallback.id
        return payload


@dataclass(frozen=True)
class MethodsCatalog:
    """Collection of enabled pipeline methods indexed by identifier."""

    methods: Mapping[str, MethodConfig]
    order: Tuple[str, ...]
    defaults: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.order:
            raise ValueError("Methods catalog must contain at least one enabled method")

    @property
    def default_method(self) -> MethodConfig:
        identifier = self.order[0]
        return self.methods[identifier]

    @property
    def default_method_id(self) -> str:
        return self.default_method.id

    def list_methods(self) -> Tuple[MethodConfig, ...]:
        return tuple(self.methods[identifier] for identifier in self.order)

    def to_metadata(self) -> List[Dict[str, Any]]:
        return [self.methods[identifier].to_metadata() for identifier in self.order]

    def lookup(self, identifier: str | None) -> MethodConfig | None:
        if identifier is None:
            return None
        key = identifier.strip()
        if not key:
            return None
        lowered = key.lower()
        for method_id, method in self.methods.items():
            if method_id.lower() == lowered:
                return method
        for method in self.list_methods():
            if method.kind == lowered:
                return method
        return None

    def resolve(self, identifier: str | None) -> Tuple[str | None, MethodConfig]:
        method = self.lookup(identifier)
        if method is not None:
            return identifier, method
        return identifier, self.default_method

    def __contains__(self, identifier: str) -> bool:
        return self.lookup(identifier) is not None


_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(:-([^}]*))?\}")


def _expand_env(value: object) -> object:
    if isinstance(value, str):
        def replacer(match: re.Match[str]) -> str:
            name = match.group(1)
            default = match.group(3) or ""
            return os.environ.get(name, default)

        return _ENV_PATTERN.sub(replacer, value)
    if isinstance(value, Mapping):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _ensure_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise TypeError(f"Expected '{label}' to be a mapping")


def _merge_defaults(defaults: Mapping[str, Any], params: Mapping[str, Any] | None) -> Mapping[str, Any]:
    merged: Dict[str, Any] = dict(defaults)
    if params:
        merged.update(params)
    return merged


@dataclass
class _HybridPlaceholder:
    base: MethodConfig
    strategy: str
    stage_refs: Tuple[str, ...]
    fallback_ref: str | None


def _build_method_config(entry: Mapping[str, Any], defaults: Mapping[str, Any]) -> MethodConfig | _HybridPlaceholder:
    method_id = str(entry.get("id", "")).strip()
    if not method_id:
        raise ValueError("Method entries must define an 'id'")
    method_type = str(entry.get("type", "")).strip().lower()
    if method_type not in {"rules", "llm", "hybrid"}:
        raise ValueError(f"Method '{method_id}' declared unsupported type '{method_type}'")

    label = entry.get("label")
    description = entry.get("description")
    params = entry.get("params")
    if params is not None and not isinstance(params, Mapping):
        raise TypeError(f"Method '{method_id}' must provide mapping params when defined")
    merged_params = _merge_defaults(defaults, params if isinstance(params, Mapping) else None)

    config_payload: Dict[str, Any] = {}
    for key, value in entry.items():
        if key in {"id", "type", "enabled", "params", "stages", "fallback", "label", "description"}:
            continue
        config_payload[key] = value

    base = MethodConfig(
        id=method_id,
        kind=method_type,
        label=str(label) if label not in {None, ""} else None,
        description=str(description) if description not in {None, ""} else None,
        params=dict(merged_params),
        config=dict(config_payload),
    )

    if method_type != "hybrid":
        return base

    raw_stages = entry.get("stages")
    if not isinstance(raw_stages, Sequence) or not raw_stages:
        raise ValueError(f"Hybrid method '{method_id}' must define at least one stage")
    stage_refs: List[str] = []
    for stage in raw_stages:
        if isinstance(stage, Mapping):
            ref = str(stage.get("ref", "")).strip()
        else:
            ref = str(stage).strip()
        if not ref:
            raise ValueError(f"Hybrid method '{method_id}' contains an empty stage reference")
        stage_refs.append(ref)

    strategy = str(entry.get("strategy", "cascade")).strip().lower() or "cascade"
    fallback_ref = entry.get("fallback")
    fallback_id = str(fallback_ref).strip() if fallback_ref else None

    return _HybridPlaceholder(
        base=base,
        strategy=strategy,
        stage_refs=tuple(stage_refs),
        fallback_ref=fallback_id,
    )


def _resolve_hybrid(
    identifier: str,
    placeholder: _HybridPlaceholder,
    raw_methods: Mapping[str, MethodConfig | _HybridPlaceholder],
    cache: MutableMapping[str, MethodConfig],
    stack: set[str],
) -> HybridMethodConfig:
    if identifier in cache:
        resolved = cache[identifier]
        if isinstance(resolved, HybridMethodConfig):
            return resolved
        raise TypeError(f"Cached method '{identifier}' is not hybrid")
    if identifier in stack:
        raise ValueError(f"Detected recursive hybrid method definition involving '{identifier}'")
    stack.add(identifier)

    stages: List[HybridStage] = []
    for ref in placeholder.stage_refs:
        try:
            target = raw_methods[ref]
        except KeyError as exc:
            raise ValueError(f"Hybrid method '{identifier}' references unknown stage '{ref}'") from exc
        if isinstance(target, _HybridPlaceholder):
            resolved_stage = _resolve_hybrid(ref, target, raw_methods, cache, stack)
            cache[ref] = resolved_stage
            method = resolved_stage
        else:
            method = target
        stages.append(HybridStage(reference=ref, method=method))

    fallback_method: MethodConfig | None = None
    if placeholder.fallback_ref:
        target = raw_methods.get(placeholder.fallback_ref)
        if target is None:
            raise ValueError(
                f"Hybrid method '{identifier}' declares fallback '{placeholder.fallback_ref}' which is not defined",
            )
        if isinstance(target, _HybridPlaceholder):
            resolved_fallback = _resolve_hybrid(placeholder.fallback_ref, target, raw_methods, cache, stack)
            cache[placeholder.fallback_ref] = resolved_fallback
            fallback_method = resolved_fallback
        else:
            fallback_method = target

    stack.remove(identifier)
    return HybridMethodConfig(
        id=placeholder.base.id,
        kind=placeholder.base.kind,
        label=placeholder.base.label,
        description=placeholder.base.description,
        params=placeholder.base.params,
        config=placeholder.base.config,
        strategy=placeholder.strategy,
        stages=tuple(stages),
        fallback=fallback_method,
    )


def load_methods_catalog(path: str | Path) -> MethodsCatalog:
    """Parse the YAML catalogue describing available pipeline methods."""

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Methods configuration file '{file_path}' not found")

    raw_payload = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_payload, Mapping):
        raise TypeError("Methods configuration file must decode into a mapping")

    defaults_raw = _expand_env(raw_payload.get("defaults", {}))
    defaults = _ensure_mapping(defaults_raw, label="defaults")

    raw_methods = raw_payload.get("methods")
    if not isinstance(raw_methods, Sequence):
        raise TypeError("Methods configuration must provide a sequence under 'methods'")

    methods: Dict[str, MethodConfig | _HybridPlaceholder] = {}
    order: List[str] = []
    for entry in raw_methods:
        if not isinstance(entry, Mapping):
            raise TypeError("Each method entry must be a mapping")
        expanded = _expand_env(entry)
        if not isinstance(expanded, Mapping):
            raise TypeError("Expanded method entries must remain mappings")
        enabled = expanded.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in {"false", "0", "no"}
        elif not isinstance(enabled, bool):
            enabled = bool(enabled)
        if not enabled:
            continue
        method = _build_method_config(expanded, defaults)
        identifier = method.base.id if isinstance(method, _HybridPlaceholder) else method.id
        if identifier in methods:
            raise ValueError(f"Duplicate method identifier '{identifier}' detected")
        methods[identifier] = method
        order.append(identifier)

    resolved: Dict[str, MethodConfig] = {}
    stack: set[str] = set()
    for identifier in order:
        entry = methods[identifier]
        if isinstance(entry, _HybridPlaceholder):
            resolved_method = _resolve_hybrid(identifier, entry, methods, resolved, stack)
            resolved[identifier] = resolved_method
        else:
            resolved[identifier] = entry

    return MethodsCatalog(methods=resolved, order=tuple(order), defaults=dict(defaults))


@dataclass(frozen=True)
class SearchConfiguration:
    """Wrapper around the search configuration fixture payload."""

    raw: Mapping[str, Any]

    @property
    def defaults(self) -> Mapping[str, int]:
        return self.raw.get("defaults", {})

    @property
    def party(self) -> Mapping[str, Any]:
        return self.raw.get("party", {})

    @property
    def departure_airport(self) -> Mapping[str, Any]:
        return self.raw.get("departureAirport", {})

    @property
    def destination_list(self) -> Mapping[str, Any]:
        return self.raw.get("destinationList", {})

    @property
    def rooms_configuration(self) -> Mapping[str, Any]:
        return self.raw.get("roomsConfiguration", {})

    @property
    def durations(self) -> List[Mapping[str, Any]]:
        return list(self.raw.get("durations", []))

    @property
    def flexibility(self) -> Mapping[str, Any]:
        return self.raw.get("flexibility", {})

    @property
    def required_fields(self) -> List[List[str]]:
        return [list(combo) for combo in self.raw.get("requiredFieldsForSearch", [])]

    @property
    def duration_by_name(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("name", "")).lower(): entry for entry in self.durations}

    @property
    def duration_by_id(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("id", "")): entry for entry in self.durations}

    @property
    def default_duration_id(self) -> str:
        for entry in self.durations:
            if entry.get("isDefault"):
                return str(entry.get("id", ""))
        return self.durations[0].get("id", "") if self.durations else ""

    @property
    def flex_options(self) -> List[Mapping[str, Any]]:
        return list(self.flexibility.get("flexibleList", []))

    @property
    def flex_by_name(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("name", "")).lower(): entry for entry in self.flex_options}

    @property
    def flex_by_id(self) -> Dict[str, Mapping[str, Any]]:
        return {str(entry.get("id", "")): entry for entry in self.flex_options}

    @property
    def default_flex_option(self) -> Optional[Mapping[str, Any]]:
        if not self.flexibility_allowed:
            return None
        for entry in self.flex_options:
            if entry.get("isDefault"):
                return entry
        return self.flex_options[0] if self.flex_options else None

    @property
    def flexibility_allowed(self) -> bool:
        return bool(self.flexibility.get("isFlexibleAllowed", False))

    @classmethod
    def from_fixture_payload(cls, payload: Mapping[str, Any]) -> "SearchConfiguration":
        try:
            config = payload["holidaySearchConfiguration"]
        except KeyError as exc:
            raise ValueError("Invalid configuration payload: missing 'holidaySearchConfiguration'") from exc
        if not isinstance(config, Mapping):
            raise TypeError("Configuration payload must provide a mapping")
        return cls(raw=config)


__all__ = [
    "MethodConfig",
    "HybridStage",
    "HybridMethodConfig",
    "MethodsCatalog",
    "load_methods_catalog",
    "SearchConfiguration",
]
