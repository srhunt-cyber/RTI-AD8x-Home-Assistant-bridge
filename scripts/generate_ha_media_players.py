#!/usr/bin/env python3
"""Generate an optional Home Assistant media-player package from bridge YAML."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bridge"))

from config import ConfigError, load_config  # noqa: E402


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _selected_zones(config: dict[str, Any], only: list[str] | None) -> list[tuple[dict, int]]:
    media = config["home_assistant"]["media_players"]
    include = only if only else media["include"]
    wanted = None if include == "all" else {item.lower() for item in include}
    selected = []
    available = set()
    for amp in config["amps"]:
        for zone in amp["zones"]:
            ref = f"{amp['id']}:{zone}"
            available.add(ref)
            if wanted is None or ref in wanted:
                selected.append((amp, zone))
    if wanted is not None:
        missing = wanted - available
        if missing:
            raise ConfigError(f"Unknown --zone value(s): {', '.join(sorted(missing))}")
    return selected


def build_package(config: dict[str, Any], only: list[str] | None = None) -> dict[str, Any]:
    """Build a self-contained HA package without changing legacy entities."""
    media = config["home_assistant"]["media_players"]
    base_topic = config["mqtt"]["base_topic"]
    use_names = config["home_assistant"]["use_source_names"]
    volume_min = media["volume_min"]
    volume_max = media["volume_max"]
    volume_span = volume_max - volume_min
    volume_step = media["volume_step"]

    mqtt_binary_sensors: list[dict[str, Any]] = []
    mqtt_sensors: list[dict[str, Any]] = []
    template_sensors: list[dict[str, Any]] = []
    players: list[dict[str, Any]] = []

    for amp, zone in _selected_zones(config, only):
        amp_id = amp["id"]
        zone_name = amp["zones"][zone]
        key = slugify(f"rti_mp_{amp_id}_{zone_name}")
        friendly = f"{zone_name} {media['name_suffix']}"
        state_base = f"{base_topic}/{amp_id}/zone/{zone}"
        command_base = f"{state_base}/set"
        availability = {
            "availability_topic": f"{base_topic}/{amp_id}/status",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

        mqtt_binary_sensors.extend([
            {
                "name": f"RTI MP {amp_id} {zone_name} Power",
                "unique_id": f"{key}_power",
                "state_topic": f"{state_base}/power",
                "payload_on": "on",
                "payload_off": "off",
                "entity_category": "diagnostic",
                **availability,
            },
            {
                "name": f"RTI MP {amp_id} {zone_name} Mute",
                "unique_id": f"{key}_mute",
                "state_topic": f"{state_base}/mute",
                "payload_on": "on",
                "payload_off": "off",
                "entity_category": "diagnostic",
                **availability,
            },
        ])

        volume_template = (
            "{% set display = 75 - (value | int(75)) %} "
            f"{{{{ ([1, [0, (display - {volume_min}) / {volume_span}] | max] | min) "
            "| round(3) }}"
        )
        mqtt_sensors.extend([
            {
                "name": f"RTI MP {amp_id} {zone_name} Volume",
                "unique_id": f"{key}_volume",
                "state_topic": f"{state_base}/volume",
                "value_template": volume_template,
                "entity_category": "diagnostic",
                **availability,
            },
            {
                "name": f"RTI MP {amp_id} {zone_name} Source Raw",
                "unique_id": f"{key}_source_raw",
                "state_topic": f"{state_base}/source",
                "entity_category": "diagnostic",
                **availability,
            },
        ])

        power_entity = f"binary_sensor.{key}_power"
        mute_entity = f"binary_sensor.{key}_mute"
        volume_entity = f"sensor.{key}_volume"
        source_raw_entity = f"sensor.{key}_source_raw"
        source_entity = f"sensor.{key}_source"
        source_options = [
            amp["sources"][number] if use_names else str(number)
            for number in sorted(amp["sources"])
        ]
        template_sensors.append({
            "name": f"RTI MP {amp_id} {zone_name} Source",
            "unique_id": f"{key}_source",
            "state": f"{{{{ states('{source_raw_entity}') }}}}",
            "availability": f"{{{{ states('{source_raw_entity}') not in ['unknown', 'unavailable'] }}}}",
            "attributes": {"options": f"{{{{ {json.dumps(source_options)} }}}}"},
        })

        clamped = "([1, [0, volume_level | float(0)] | max] | min)"
        volume_payload = (
            f"{{{{ 75 - (({volume_min} + {clamped} * {volume_span}) "
            "| round(0) | int) }}"
        )
        up_fraction = (
            f"([1, [0, (states('{volume_entity}') | float(0)) + "
            f"({volume_step} / {volume_span})] | max] | min)"
        )
        down_fraction = (
            f"([1, [0, (states('{volume_entity}') | float(0)) - "
            f"({volume_step} / {volume_span})] | max] | min)"
        )
        up_payload = (
            f"{{{{ 75 - (({volume_min} + {up_fraction} * {volume_span}) "
            "| round(0) | int) }}"
        )
        down_payload = (
            f"{{{{ 75 - (({volume_min} + {down_fraction} * {volume_span}) "
            "| round(0) | int) }}"
        )
        players.append({
            "platform": "universal",
            "name": friendly,
            "unique_id": f"{key}_media_player",
            "device_class": "speaker",
            "state_template": (
                f"{{% if states('{power_entity}') == 'unavailable' %}}unavailable"
                f"{{% elif is_state('{power_entity}', 'on') %}}on"
                "{% else %}off{% endif %}"
            ),
            "commands": {
                "turn_on": {
                    "action": "mqtt.publish",
                    "data": {"topic": f"{command_base}/power", "payload": "on"},
                },
                "turn_off": {
                    "action": "mqtt.publish",
                    "data": {"topic": f"{command_base}/power", "payload": "off"},
                },
                "volume_set": {
                    "action": "mqtt.publish",
                    "data": {"topic": f"{command_base}/volume", "payload": volume_payload},
                },
                "volume_up": {
                    "action": "mqtt.publish",
                    "data": {"topic": f"{command_base}/volume", "payload": up_payload},
                },
                "volume_down": {
                    "action": "mqtt.publish",
                    "data": {"topic": f"{command_base}/volume", "payload": down_payload},
                },
                "volume_mute": {
                    "action": "mqtt.publish",
                    "data": {"topic": f"{command_base}/toggle_mute", "payload": "toggle"},
                },
                "select_source": {
                    "action": "mqtt.publish",
                    "data": {"topic": f"{command_base}/source", "payload": "{{ source }}"},
                },
            },
            "attributes": {
                "volume_level": volume_entity,
                "is_volume_muted": mute_entity,
                "source": source_entity,
                "source_list": f"{source_entity}|options",
            },
        })

    if not players:
        raise ConfigError("No media-player zones were selected")
    return {
        "mqtt": {
            "binary_sensor": mqtt_binary_sensors,
            "sensor": mqtt_sensors,
        },
        "template": [{"sensor": template_sensors}],
        "media_player": players,
    }


def render_package(config: dict[str, Any], only: list[str] | None = None) -> str:
    mode = config["home_assistant"]["entity_mode"]
    header = (
        "# Generated by RTI AD-series MQTT Bridge v1.9.0-beta.3\n"
        f"# Entity mode: {mode}. Regenerate this file after changing amps or zones.\n"
        "# Do not expose the diagnostic helper entities to Alexa.\n"
    )
    return header + yaml.safe_dump(build_package(config, only), sort_keys=False, width=1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml", help="validated bridge YAML")
    parser.add_argument("--output", default="rti_ad8x_media_players.yaml")
    parser.add_argument(
        "--zone", action="append", dest="zones", metavar="AMP:ZONE",
        help="generate only this zone; repeat for more than one",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).expanduser()
    if output.exists() and not args.force:
        print(f"Refusing to overwrite existing package: {output}", file=sys.stderr)
        return 2
    try:
        config = load_config(args.config)
        if config["home_assistant"]["entity_mode"] == "legacy":
            raise ConfigError(
                "set home_assistant.entity_mode to dual or media_player before generating"
            )
        rendered = render_package(config, args.zones)
    except ConfigError as exc:
        print(f"Package not written: {exc}", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"Home Assistant package written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
