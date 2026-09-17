#!/usr/bin/env python3
"""Interactive configuration wizard for the RTI AD-series MQTT bridge."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bridge"))

from config import ConfigError, normalize_config  # noqa: E402


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_int(prompt: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"Enter a number from {minimum} through {maximum}.")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{marker}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def build_config(args: argparse.Namespace) -> dict:
    print("\nRTI AD-series MQTT Bridge configuration\n")
    mqtt_host = args.mqtt_host or ask("MQTT broker hostname or IP", "localhost")
    mqtt_port = args.mqtt_port or ask_int("MQTT broker port", 1883, 1, 65535)
    mqtt_user = args.mqtt_user if args.mqtt_user is not None else ask("MQTT username (blank if unused)")
    supplied_password = os.getenv("RTI_INSTALL_MQTT_PASSWORD")
    mqtt_password = supplied_password if supplied_password is not None else getpass.getpass(
        "MQTT password (blank if unused): "
    )

    amp_count = ask_int("Number of RTI amplifiers", 1, 1, 8)
    amps = []
    for index in range(1, amp_count + 1):
        print(f"\nAmplifier {index}")
        amp_id = ask("Stable amplifier ID", f"amp{index}").lower()
        amp_name = ask("Friendly amplifier name", f"RTI Amplifier {index}")
        model = ask("Model", "AD-8x")
        host = ask("Amplifier hostname or IP")
        port = ask_int("Control port", 23, 1, 65535)
        zone_count = ask_int("Number of configured zones", 8, 1, 8)
        zones = {}
        for zone in range(1, zone_count + 1):
            zones[zone] = ask(f"Zone {zone} name", f"Zone {zone}")

        sources = {source: str(source) for source in range(1, 9)}
        if ask_yes_no("Assign friendly source names? Numeric sources preserve v1.8 dashboards", False):
            sources = {source: ask(f"Source {source} name", f"Source {source}")
                       for source in range(1, 9)}

        amps.append({
            "id": amp_id,
            "name": amp_name,
            "model": model,
            "host": host,
            "port": port,
            "startup_delay": (index - 1) * 5,
            "zones": zones,
            "sources": sources,
        })

    return {
        "schema_version": 1,
        "bridge": {"log_level": "INFO", "health_check_interval": 30},
        "mqtt": {
            "host": mqtt_host,
            "port": mqtt_port,
            "username": mqtt_user,
            "password": mqtt_password,
            "base_topic": "rti/ad8x",
            "discovery_prefix": "homeassistant",
        },
        "polling": {
            "interval": 60,
            "connect_timeout": 2,
            "reply_timeout": 3,
            "inter_command_delay": 0.20,
            "reconnect_delay": 5,
            "failure_threshold": 3,
        },
        "commands": {
            "post_send_settle": 0.05,
            "retries": 2,
            "retry_delay": 0.2,
            "coalesce_window": 1.2,
            "echo_suppress": 1.0,
            "power_on_fallback_volume": 65,
        },
        "home_assistant": {
            "discovery": True,
            "use_source_names": False,
        },
        "amps": amps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="config.yaml")
    parser.add_argument("--mqtt-host")
    parser.add_argument("--mqtt-port", type=int)
    parser.add_argument("--mqtt-user")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    if output.exists() and not args.force:
        print(f"Refusing to overwrite existing configuration: {output}", file=sys.stderr)
        return 2
    try:
        config = build_config(args)
        normalize_config(config)
    except (ConfigError, EOFError, KeyboardInterrupt) as exc:
        print(f"\nConfiguration not written: {exc}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    output.chmod(0o600)
    print(f"\nConfiguration written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
