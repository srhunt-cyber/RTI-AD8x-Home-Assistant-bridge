"""Configuration loading and validation for the RTI AD-series MQTT bridge."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the bridge configuration is missing or invalid."""


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(f"Environment variable {name!r} is not set")
            return os.environ[name]
        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _as_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _as_float(value: Any, field: str, minimum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be a number") from exc
    if parsed < minimum:
        raise ConfigError(f"{field} must be at least {minimum}")
    return parsed


def _as_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ConfigError(f"{field} must be true or false")


def _normalize_numbered_names(value: Any, field: str, maximum: int = 8) -> dict[int, str]:
    if value is None:
        return {}
    if isinstance(value, list):
        value = {index: item for index, item in enumerate(value, start=1)}
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be a mapping or list")
    result: dict[int, str] = {}
    for raw_number, raw_item in value.items():
        number = _as_int(raw_number, f"{field} number", 1, maximum)
        name = raw_item.get("name") if isinstance(raw_item, dict) else raw_item
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{field}.{number}.name must be a non-empty string")
        result[number] = name.strip()
    return dict(sorted(result.items()))


def _tone_level(value: Any, field: str) -> int:
    level = _as_int(value, field, -12, 12)
    if level % 2:
        raise ConfigError(f"{field} must be an even value")
    return level


def _normalize_restore_values(value: Any, field: str, *, partial: bool) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be a mapping")

    defaults: dict[str, Any] = {} if partial else {
        "enabled": True,
        "volume": 20,
        "bass": 8,
        "treble": 12,
        "safe_source": 8,
        "ready_source": 1,
        "leave_powered_off": True,
    }
    validators = {
        "enabled": lambda raw: _as_bool(raw, f"{field}.enabled"),
        # Volume is expressed as the Home Assistant/display level. The RTI
        # protocol uses attenuation, so the bridge converts it before sending.
        "volume": lambda raw: _as_int(raw, f"{field}.volume", 0, 75),
        "bass": lambda raw: _tone_level(raw, f"{field}.bass"),
        "treble": lambda raw: _tone_level(raw, f"{field}.treble"),
        "safe_source": lambda raw: _as_int(raw, f"{field}.safe_source", 1, 8),
        "ready_source": lambda raw: _as_int(raw, f"{field}.ready_source", 1, 8),
        "leave_powered_off": lambda raw: _as_bool(raw, f"{field}.leave_powered_off"),
    }
    unknown = set(value) - set(validators)
    if unknown:
        raise ConfigError(f"{field} contains unknown option(s): {', '.join(sorted(unknown))}")
    for key, raw in value.items():
        defaults[key] = validators[key](raw)
    return defaults


def _normalize_zones(value: Any, field: str) -> tuple[dict[int, str], dict[int, dict[str, Any]]]:
    if isinstance(value, list):
        value = {index: item for index, item in enumerate(value, start=1)}
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be a mapping or list")

    names: dict[int, str] = {}
    restore_overrides: dict[int, dict[str, Any]] = {}
    for raw_number, raw_item in value.items():
        number = _as_int(raw_number, f"{field} number", 1, 8)
        if isinstance(raw_item, dict):
            name = raw_item.get("name")
            unknown = set(raw_item) - {"name", "defaults"}
            if unknown:
                raise ConfigError(
                    f"{field}.{number} contains unknown option(s): {', '.join(sorted(unknown))}"
                )
            if "defaults" in raw_item:
                restore_overrides[number] = _normalize_restore_values(
                    raw_item["defaults"], f"{field}.{number}.defaults", partial=True
                )
        else:
            name = raw_item
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{field}.{number}.name must be a non-empty string")
        names[number] = name.strip()
    return dict(sorted(names.items())), dict(sorted(restore_overrides.items()))


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a YAML mapping")
    schema_version = _as_int(raw.get("schema_version", 1), "schema_version", 1, 1)
    mqtt = raw.get("mqtt") or {}
    polling = raw.get("polling") or {}
    commands = raw.get("commands") or {}
    bridge = raw.get("bridge") or {}
    home_assistant = raw.get("home_assistant") or {}
    restoration = raw.get("restoration") or {}
    for name, section in (("mqtt", mqtt), ("polling", polling), ("commands", commands),
                          ("bridge", bridge), ("home_assistant", home_assistant),
                          ("restoration", restoration)):
        if not isinstance(section, dict):
            raise ConfigError(f"{name} must be a mapping")

    mqtt_host = str(mqtt.get("host", "localhost")).strip()
    if not mqtt_host:
        raise ConfigError("mqtt.host cannot be empty")
    amps = raw.get("amps")
    if not isinstance(amps, list) or not amps:
        raise ConfigError("amps must contain at least one amplifier")

    normalized_amps: list[dict[str, Any]] = []
    amp_ids: set[str] = set()
    for index, amp in enumerate(amps, start=1):
        if not isinstance(amp, dict):
            raise ConfigError(f"amps[{index}] must be a mapping")
        amp_id = str(amp.get("id", "")).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", amp_id):
            raise ConfigError(f"amps[{index}].id must be a lowercase MQTT-safe identifier")
        if amp_id in amp_ids:
            raise ConfigError(f"Duplicate amplifier id: {amp_id}")
        amp_ids.add(amp_id)
        host = str(amp.get("host", "")).strip()
        if not host:
            raise ConfigError(f"amps[{index}].host cannot be empty")
        zones, zone_defaults = _normalize_zones(amp.get("zones"), f"amps[{index}].zones")
        if not zones:
            raise ConfigError(f"amps[{index}].zones must contain at least one zone")
        configured_sources = _normalize_numbered_names(amp.get("sources"),
                                                       f"amps[{index}].sources")
        sources = {number: str(number) for number in range(1, 9)}
        sources.update(configured_sources)
        normalized_amps.append({
            "id": amp_id,
            "name": str(amp.get("name") or f"RTI {amp_id}").strip(),
            "model": str(amp.get("model") or "AD-8x").strip(),
            "host": host,
            "port": _as_int(amp.get("port", 23), f"amps[{index}].port", 1, 65535),
            "startup_delay": _as_float(amp.get("startup_delay", (index - 1) * 5),
                                       f"amps[{index}].startup_delay", 0),
            "zones": zones,
            "zone_defaults": zone_defaults,
            "sources": sources,
        })

    base_topic = str(mqtt.get("base_topic") or "rti/ad8x").strip().strip("/")
    discovery_prefix = str(mqtt.get("discovery_prefix") or "homeassistant").strip().strip("/")
    if not base_topic:
        raise ConfigError("mqtt.base_topic cannot be empty")
    if not discovery_prefix:
        raise ConfigError("mqtt.discovery_prefix cannot be empty")

    restore_defaults = _normalize_restore_values(
        restoration.get("defaults"), "restoration.defaults", partial=False
    )
    factory_signature = restoration.get("factory_signature") or {}
    if not isinstance(factory_signature, dict):
        raise ConfigError("restoration.factory_signature must be a mapping")
    unknown_signature = set(factory_signature) - {
        "volume", "bass", "treble", "minimum_matching_zones"
    }
    if unknown_signature:
        raise ConfigError(
            "restoration.factory_signature contains unknown option(s): "
            + ", ".join(sorted(unknown_signature))
        )
    normalized_signature: dict[str, Any] = {
        "bass": _tone_level(factory_signature.get("bass", 0),
                            "restoration.factory_signature.bass"),
        "treble": _tone_level(factory_signature.get("treble", 0),
                              "restoration.factory_signature.treble"),
        # Zero means every configured/enabled zone must match.
        "minimum_matching_zones": _as_int(
            factory_signature.get("minimum_matching_zones", 0),
            "restoration.factory_signature.minimum_matching_zones", 0, 8
        ),
    }
    if "volume" in factory_signature and factory_signature["volume"] is not None:
        normalized_signature["volume"] = _as_int(
            factory_signature["volume"], "restoration.factory_signature.volume", 0, 75
        )
    restoration_enabled = _as_bool(
        restoration.get("enabled", False), "restoration.enabled"
    )
    restoration_automatic = _as_bool(
        restoration.get("automatic", False), "restoration.automatic"
    )
    if restoration_automatic and not restoration_enabled:
        raise ConfigError("restoration.automatic requires restoration.enabled")
    minimum_matching = normalized_signature["minimum_matching_zones"]
    if minimum_matching:
        for amp in normalized_amps:
            eligible = sum(
                1 for zone in amp["zones"]
                if {**restore_defaults, **amp["zone_defaults"].get(zone, {})}.get("enabled", True)
            )
            if minimum_matching > eligible:
                raise ConfigError(
                    "restoration.factory_signature.minimum_matching_zones "
                    f"exceeds the {eligible} enabled restore zones on {amp['id']}"
                )

    return {
        "schema_version": schema_version,
        "bridge": {
            "log_level": str(bridge.get("log_level", "INFO")).upper(),
            "health_check_interval": _as_float(bridge.get("health_check_interval", 30),
                                                "bridge.health_check_interval", 5),
        },
        "mqtt": {
            "host": mqtt_host,
            "port": _as_int(mqtt.get("port", 1883), "mqtt.port", 1, 65535),
            "username": str(mqtt.get("username") or ""),
            "password": str(mqtt.get("password") or ""),
            "base_topic": base_topic,
            "discovery_prefix": discovery_prefix,
        },
        "polling": {
            "interval": _as_float(polling.get("interval", 60), "polling.interval", 5),
            "connect_timeout": _as_float(polling.get("connect_timeout", 2), "polling.connect_timeout", 0.1),
            "reply_timeout": _as_float(polling.get("reply_timeout", 3), "polling.reply_timeout", 0.1),
            "inter_command_delay": _as_float(polling.get("inter_command_delay", 0.20),
                                              "polling.inter_command_delay", 0),
            "reconnect_delay": _as_float(polling.get("reconnect_delay", 5),
                                         "polling.reconnect_delay", 1),
            "failure_threshold": _as_int(polling.get("failure_threshold", 3),
                                         "polling.failure_threshold", 1, 100),
        },
        "commands": {
            "post_send_settle": _as_float(commands.get("post_send_settle", 0.05),
                                           "commands.post_send_settle", 0),
            "retries": _as_int(commands.get("retries", 2), "commands.retries", 0, 10),
            "retry_delay": _as_float(commands.get("retry_delay", 0.2), "commands.retry_delay", 0),
            "coalesce_window": _as_float(commands.get("coalesce_window", 1.2),
                                         "commands.coalesce_window", 0),
            "echo_suppress": _as_float(commands.get("echo_suppress", 1.0),
                                       "commands.echo_suppress", 0),
            "power_on_fallback_volume": _as_int(commands.get("power_on_fallback_volume", 65),
                                                 "commands.power_on_fallback_volume", 0, 75),
        },
        "home_assistant": {
            "discovery": _as_bool(home_assistant.get("discovery", True),
                                  "home_assistant.discovery"),
            "use_source_names": _as_bool(home_assistant.get("use_source_names", False),
                                          "home_assistant.use_source_names"),
        },
        "restoration": {
            "enabled": restoration_enabled,
            "automatic": restoration_automatic,
            "dry_run": _as_bool(restoration.get("dry_run", True), "restoration.dry_run"),
            "confirmation_polls": _as_int(restoration.get("confirmation_polls", 2),
                                           "restoration.confirmation_polls", 1, 10),
            "command_delay": _as_float(restoration.get("command_delay", 5),
                                       "restoration.command_delay", 0),
            "verification_attempts": _as_int(restoration.get("verification_attempts", 4),
                                              "restoration.verification_attempts", 1, 10),
            "defaults": restore_defaults,
            "factory_signature": normalized_signature,
        },
        "amps": normalized_amps,
    }


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ConfigError(f"Configuration file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
    return normalize_config(_expand_env(raw))
