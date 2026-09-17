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


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a YAML mapping")
    schema_version = _as_int(raw.get("schema_version", 1), "schema_version", 1, 1)
    mqtt = raw.get("mqtt") or {}
    polling = raw.get("polling") or {}
    commands = raw.get("commands") or {}
    bridge = raw.get("bridge") or {}
    home_assistant = raw.get("home_assistant") or {}
    for name, section in (("mqtt", mqtt), ("polling", polling), ("commands", commands),
                          ("bridge", bridge), ("home_assistant", home_assistant)):
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
        zones = _normalize_numbered_names(amp.get("zones"), f"amps[{index}].zones")
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
            "sources": sources,
        })

    base_topic = str(mqtt.get("base_topic") or "rti/ad8x").strip().strip("/")
    discovery_prefix = str(mqtt.get("discovery_prefix") or "homeassistant").strip().strip("/")
    if not base_topic:
        raise ConfigError("mqtt.base_topic cannot be empty")
    if not discovery_prefix:
        raise ConfigError("mqtt.discovery_prefix cannot be empty")

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
