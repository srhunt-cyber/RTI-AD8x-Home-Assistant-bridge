#!/usr/bin/env python3
"""
RTI AD-series <-> MQTT bridge
Version 1.9.0-beta.2 (2026-09-17)

- BETA (v1.9.0-beta.2): Add opt-in, guarded amplifier-default
  restoration with YAML targets, per-zone overrides, dry-run/manual testing,
  amp-wide reset detection, confirmation polls, pacing, and verification.

- STABILITY (v1.8.4): Use the field-tested HA-only polling profile by
  default: 60-second reconciliation polls, 200ms command spacing, and a
  3-second reply timeout. HA and Alexa commands still execute immediately.
- STABILITY (v1.8.3): Stagger Amp 2 startup by five seconds so the two
  fragile Telnet servers are not polled in lockstep.
- STABILITY (v1.8.3): Close a failed Telnet socket immediately and allow
  five seconds before the first reconnect attempt.
- FIX (v1.8.2): Publish retained network status on actual full-poll
  transitions, including an initial "up" after service startup.
- OPERATIONS (v1.8.2): Include the date in log timestamps.
- REFINED (v1.8.1): Use the amp IP address in its Home Assistant device name
  and publish the bridge software version through MQTT discovery.

- NEW: Added instrumentation and diagnostics, mirroring the vantage-bridge.
  The bridge now publishes CPU, memory, uptime, and connection status
  to 'rti/ad8x/diagnostics/...' for monitoring in Home Assistant.
- REFINED: The main thread now serves as the diagnostics publisher,
  running every HEALTH_CHECK_INTERVAL.
- FIX (v1.7.0): Intercept 'power on' command to call 'set_volume'
  with the last known volume. This avoids the amp's default
  power-on volume (45) after a reboot, per the AD-8x spec.
- FIX (v1.8.0): Added command coalescing (batching) to set_bass
  and set_treble to prevent flooding the amp with commands.
- FIX (v1.8.0): Re-added power-on guards to set_bass/set_treble,
  as hardware ignores these commands when the zone is off.
- REFINED (v1.8.0): Increased default VOL_COALESCE_SEC to 1.2s
  to better handle rapid button taps.
"""

import argparse, os, sys, time, json, random, signal, socket, logging, traceback, threading
from pathlib import Path
from typing import Optional, Tuple
import paho.mqtt.client as mqtt
from config import ConfigError, load_config
# --- INSTRUMENTATION ---
import psutil # REQUIRED FOR METRICS
# --- INSTRUMENTATION ---

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
VERSION = "1.9.0-beta.2"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s.%(msecs)03d %(levelname)s:%(name)s:%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rti_ad8x_bridge")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
AMPS = {}
AMP_METADATA = {}
ZONE_NAMES = {}
SOURCE_NAMES = {}
RESTORATION_CONFIG = {}

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")
MQTT_BASE = os.getenv("MQTT_BASE", "rti/ad8x")
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant")

POLL_INTERVAL_SEC = float(os.getenv("POLL_INTERVAL", "60.0"))
CONNECT_TIMEOUT   = float(os.getenv("CONNECT_TIMEOUT", "2.0"))
PER_CMD_TIMEOUT   = float(os.getenv("PER_CMD_TIMEOUT", "3.0"))
POST_SEND_SETTLE  = float(os.getenv("POST_SEND_SETTLE", "0.05"))
INTER_CMD_SLEEP   = float(os.getenv("INTER_CMD_SLEEP", "0.20"))
SET_RETRIES       = int(os.getenv("SET_RETRIES", "2"))
RETRY_SLEEP       = float(os.getenv("RETRY_SLEEP", "0.2"))
DUMP_RAW_CHUNKS   = os.getenv("DUMP_RAW_CHUNKS", "1") not in ("0", "false", "False")
RECONNECT_BACKOFF_INITIAL = float(os.getenv("RECONNECT_BACKOFF_INITIAL", "5.0"))
NETWORK_FAILURE_THRESHOLD = int(os.getenv("NETWORK_FAILURE_THRESHOLD", "3"))

VOL_COALESCE_SEC        = float(os.getenv("VOL_COALESCE_SEC", "1.2"))
VOL_ECHO_SUPPRESS_SEC   = float(os.getenv("VOL_ECHO_SUPPRESS_SEC", "1.00"))

# --- INSTRUMENTATION ---
HEALTH_CHECK_INTERVAL = 30.0 # Interval for sending metrics and heartbeat
HA_DISCOVERY = True
USE_SOURCE_NAMES = False
POWER_ON_FALLBACK_VOLUME = 65
# --- INSTRUMENTATION ---


def configure_runtime(config: dict):
    """Apply validated YAML while retaining v1.8 environment overrides."""
    global LOG_LEVEL, AMPS, AMP_METADATA, ZONE_NAMES, SOURCE_NAMES
    global MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_BASE, DISCOVERY_PREFIX
    global POLL_INTERVAL_SEC, CONNECT_TIMEOUT, PER_CMD_TIMEOUT, POST_SEND_SETTLE
    global INTER_CMD_SLEEP, SET_RETRIES, RETRY_SLEEP, DUMP_RAW_CHUNKS
    global RECONNECT_BACKOFF_INITIAL, NETWORK_FAILURE_THRESHOLD
    global VOL_COALESCE_SEC, VOL_ECHO_SUPPRESS_SEC, HEALTH_CHECK_INTERVAL
    global HA_DISCOVERY, USE_SOURCE_NAMES, POWER_ON_FALLBACK_VOLUME
    global RESTORATION_CONFIG

    bridge_cfg = config["bridge"]
    mqtt_cfg = config["mqtt"]
    polling_cfg = config["polling"]
    command_cfg = config["commands"]
    ha_cfg = config["home_assistant"]

    LOG_LEVEL = os.getenv("LOG_LEVEL", bridge_cfg["log_level"]).upper()
    logging.getLogger().setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    MQTT_HOST = os.getenv("MQTT_HOST", mqtt_cfg["host"])
    MQTT_PORT = int(os.getenv("MQTT_PORT", str(mqtt_cfg["port"])))
    MQTT_USER = os.getenv("MQTT_USER", mqtt_cfg["username"])
    MQTT_PASS = os.getenv("MQTT_PASS", mqtt_cfg["password"])
    MQTT_BASE = os.getenv("MQTT_BASE", mqtt_cfg["base_topic"])
    DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", mqtt_cfg["discovery_prefix"])
    POLL_INTERVAL_SEC = float(os.getenv("POLL_INTERVAL", str(polling_cfg["interval"])))
    CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", str(polling_cfg["connect_timeout"])))
    PER_CMD_TIMEOUT = float(os.getenv("PER_CMD_TIMEOUT", str(polling_cfg["reply_timeout"])))
    INTER_CMD_SLEEP = float(os.getenv("INTER_CMD_SLEEP", str(polling_cfg["inter_command_delay"])))
    RECONNECT_BACKOFF_INITIAL = float(os.getenv("RECONNECT_BACKOFF_INITIAL", str(polling_cfg["reconnect_delay"])))
    NETWORK_FAILURE_THRESHOLD = int(os.getenv("NETWORK_FAILURE_THRESHOLD", str(polling_cfg["failure_threshold"])))
    POST_SEND_SETTLE = float(os.getenv("POST_SEND_SETTLE", str(command_cfg["post_send_settle"])))
    SET_RETRIES = int(os.getenv("SET_RETRIES", str(command_cfg["retries"])))
    RETRY_SLEEP = float(os.getenv("RETRY_SLEEP", str(command_cfg["retry_delay"])))
    VOL_COALESCE_SEC = float(os.getenv("VOL_COALESCE_SEC", str(command_cfg["coalesce_window"])))
    VOL_ECHO_SUPPRESS_SEC = float(os.getenv("VOL_ECHO_SUPPRESS_SEC", str(command_cfg["echo_suppress"])))
    POWER_ON_FALLBACK_VOLUME = int(command_cfg["power_on_fallback_volume"])
    HEALTH_CHECK_INTERVAL = float(bridge_cfg["health_check_interval"])
    HA_DISCOVERY = ha_cfg["discovery"]
    USE_SOURCE_NAMES = ha_cfg["use_source_names"]
    DUMP_RAW_CHUNKS = os.getenv("DUMP_RAW_CHUNKS", "1") not in ("0", "false", "False")

    AMPS = {amp["id"]: (amp["host"], amp["port"]) for amp in config["amps"]}
    AMP_METADATA = {amp["id"]: amp for amp in config["amps"]}
    ZONE_NAMES = {amp["id"]: amp["zones"] for amp in config["amps"]}
    SOURCE_NAMES = {amp["id"]: amp["sources"] for amp in config["amps"]}
    RESTORATION_CONFIG = config["restoration"]


def zone_numbers(amp_key: str) -> list[int]:
    return sorted(ZONE_NAMES.get(amp_key, {}))


def source_payload(amp_key: str, source: int) -> str:
    return SOURCE_NAMES.get(amp_key, {}).get(source, str(source)) if USE_SOURCE_NAMES else str(source)


def source_number(amp_key: str, payload: str) -> int:
    if not USE_SOURCE_NAMES:
        return int(payload)
    wanted = payload.strip().casefold()
    for number, name in SOURCE_NAMES.get(amp_key, {}).items():
        if name.casefold() == wanted or str(number) == wanted:
            return number
    raise ValueError(f"Unknown source {payload!r} for {amp_key}")


def display_volume(protocol_attenuation: int) -> int:
    """Convert the RTI attenuation value to the existing HA 0-75 scale."""
    return 75 - int(protocol_attenuation)


def protocol_volume(display_level: int) -> int:
    """Convert the existing HA 0-75 scale to RTI attenuation."""
    return 75 - int(display_level)


def restore_settings(amp_key: str, zone: int) -> dict:
    """Return global restore defaults merged with an optional zone override."""
    settings = dict(RESTORATION_CONFIG.get("defaults", {}))
    settings.update(AMP_METADATA.get(amp_key, {}).get("zone_defaults", {}).get(zone, {}))
    return settings


def factory_signature_matches(amp_key: str, zone: int, state: dict) -> bool:
    """Return whether one fully-polled zone has the configured reset signature."""
    signature = RESTORATION_CONFIG.get("factory_signature", {})
    if state.get("bass") != signature.get("bass", 0):
        return False
    if state.get("treble") != signature.get("treble", 0):
        return False
    if "volume" in signature:
        raw_volume = state.get("vol_0_75")
        if raw_volume is None or display_volume(raw_volume) != signature["volume"]:
            return False
    return bool(restore_settings(amp_key, zone).get("enabled", True))


def parse_set_topic(topic: str):
    """Return (amp, zone, command) for a command below the configured base."""
    base_parts = MQTT_BASE.split("/")
    parts = topic.split("/")
    if parts[:len(base_parts)] != base_parts:
        return None
    relative = parts[len(base_parts):]
    if len(relative) != 5 or relative[1] != "zone" or relative[3] != "set":
        return None
    try:
        return relative[0], int(relative[2]), relative[4].lower()
    except ValueError:
        return None

EOL, ESC2 = b"\r", b"\x1b" + b"2"

def zz(n: int) -> str: return f"{n:02d}"

def parse_sta(line: str):
    try:
        if not line or not line.startswith("#") or line == "#?": return None
        parts = line[1:].split(",")
        if len(parts) != 5: return None
        z, p, m, ss, nvv = [s.strip() for s in parts]
        return {"zone": int(z), "power": p == "1", "mute": m == "1", "source": int(ss), "vol_0_75": abs(int(nvv))}
    except Exception: return None

def parse_tone(line: str):
    try:
        if not line or not line.startswith("$") or line == "$?": return None
        parts = line[1:].split(",")
        if len(parts) != 3: return None
        z, b, t = [s.strip() for s in parts]
        return {"zone": int(z), "bass": int(b), "treble": int(t)}
    except Exception: return None

def _encode_tone(level: int) -> str:
    lvl = max(-12, min(12, int(level)))
    if lvl % 2 != 0: lvl = lvl - 1 if lvl > 0 else lvl + 1
    return f"{lvl:02d}" if lvl >= 0 else f"{abs(lvl) + 20:02d}"

def slugify(s: str) -> str: return "".join(ch.lower() if ch.isalnum() else "_" for ch in s).strip("_")
def discovery_topic(component: str, object_id: str) -> str: return f"{DISCOVERY_PREFIX}/{component}/{object_id}/config"
def device_block(amp_key: str, amp_ip: str) -> dict:
    metadata = AMP_METADATA.get(amp_key, {})
    return {
        "identifiers": [f"ad8x_{amp_key}"],
        "manufacturer": "RTI",
        "model": metadata.get("model", "AD-series"),
        "name": metadata.get("name", f"RTI amplifier ({amp_ip})"),
        "sw_version": VERSION,
    }
def zone_object_id(amp_key: str, zone: int, suffix: str) -> str:
    name = ZONE_NAMES.get(amp_key, {}).get(zone, f"Zone {zone}")
    return slugify(f"ad8x_{amp_key}_{name}_{suffix}")

class AmpSession(threading.Thread):
    def __init__(self, amp_name: str, addr: Tuple[str, int], mqttc: mqtt.Client,
                 start_delay: float = 0.0):
        super().__init__(daemon=True)
        self.amp_name = amp_name
        self.addr = addr
        self.mqttc = mqttc
        self.sock: Optional[socket.socket] = None
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.connected = False
        self._rbuf = b""
        self.last_fw = None
        self._last_heartbeat_ts = 0.0
        self._zone_states: dict[int, dict] = {}
        self._consecutive_failures = 0
        self._network_status = None
        self._restore_candidate_polls = 0
        self._restore_latched = False
        self._restore_guard = threading.Lock()
        self.start_delay = max(0.0, float(start_delay))

    def _cleanup_socket(self):
        """Closes the socket and clears the buffer without resetting state."""
        try:
            if self.sock: self.sock.close()
        finally:
            self.sock = None
            self._rbuf = b""

    def _connect(self) -> bool:
        self._cleanup_socket()
        try:
            log.info(f"[{self.amp_name}] connecting to {self.addr[0]}:{self.addr[1]}")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(CONNECT_TIMEOUT)
            s.connect(self.addr)
            s.sendall(ESC2 + EOL)
            time.sleep(POST_SEND_SETTLE)
            s.settimeout(PER_CMD_TIMEOUT)
            self.sock = s
            self.connected = True
            self._rbuf = b""
            self._pub_availability("online")
            log.info(f"[{self.amp_name}] connected")
            return True
        except Exception as e:
            log.warning(f"[{self.amp_name}] connect failed: {e}")
            self._cleanup_socket()
            self.connected = False # Explicitly set
            return False

    def _close(self):
        """Fully closes the connection and resets all state, including failure counts."""
        was = self.connected
        self.connected = False
        self._consecutive_failures = 0
        self._cleanup_socket()
        if was:
            self._pub_availability("offline")
            log.info(f"[{self.amp_name}] closed")

    def _readline(self, timeout_s: float) -> str:
        end = time.time() + timeout_s
        s = self.sock
        if not s: return ""
        def pop_line_from_buffer():
            if not self._rbuf: return None
            for sep in (b"\r", b"\n"):
                if sep in self._rbuf:
                    line, _, rest = self._rbuf.partition(sep)
                    self._rbuf = rest.lstrip(b"\r\n")
                    return line.decode(errors="ignore").strip()
            return None
        line = pop_line_from_buffer()
        if line is not None: return line
        while time.time() < end:
            try:
                chunk = s.recv(1024)
                if not chunk: break
                if DUMP_RAW_CHUNKS and log.isEnabledFor(logging.DEBUG):
                    log.debug(f"[{self.amp_name}] RXCHUNK {len(chunk)}B: {chunk.hex(' ')}")
                self._rbuf += chunk
                line = pop_line_from_buffer()
                if line is not None: return line
            except socket.timeout: pass
            except Exception: break
        return ""

    def _read_reply(self, expected_prefix: str, timeout_s: float) -> str:
        end = time.time() + timeout_s
        while time.time() < end:
            remaining = max(0.05, end - time.time())
            line = self._readline(remaining)
            if not line or line == "#?": continue
            if line.startswith(expected_prefix): return line
        return ""

    def _send_ascii(self, cmd_ascii: str):
        if not self.sock: raise RuntimeError("no socket")
        cmd_ascii = cmd_ascii.strip().upper()
        self.sock.sendall(cmd_ascii.encode("ascii", "ignore") + EOL)
        log.info(f"[{self.amp_name}] TX {cmd_ascii}")

    def _send_only(self, cmd_ascii: str) -> bool:
        """Fire-and-forget send, used for optimistic updates."""
        with self.lock:
            if not self.connected and not self._connect(): return False
            try:
                self._send_ascii(cmd_ascii)
                time.sleep(POST_SEND_SETTLE)
                return True
            except Exception as e:
                log.error(f"[{self.amp_name}] send_only error: {e}")
                self._close()
                return False

    def _topic(self, *parts) -> str: return "/".join([MQTT_BASE, self.amp_name, *[str(p) for p in parts]])
    def _pub_availability(self, state: str): self.mqttc.publish(self._topic("status"), state, retain=True)

    def _pub_zone_full(self, z: int, sta_data: dict, tone_data: dict):
        base = self._topic("zone", z)
        self.mqttc.publish(f"{base}/power", "on" if sta_data["power"] else "off", retain=True)
        self.mqttc.publish(f"{base}/mute", "on" if sta_data["mute"] else "off", retain=True)
        self.mqttc.publish(f"{base}/source", source_payload(self.amp_name, sta_data["source"]), retain=True)
        self.mqttc.publish(f"{base}/bass", str(tone_data["bass"]), retain=True)
        self.mqttc.publish(f"{base}/treble", str(tone_data["treble"]), retain=True)
        buf = self._zone_states.setdefault(z, {})
        if time.time() >= buf.get("suppress_until", 0.0):
            vv = sta_data["vol_0_75"]
            if buf.get("last_published_vol") != vv:
                self.mqttc.publish(f"{base}/volume", str(vv), retain=True)
                buf["last_published_vol"] = vv
        combined = {**sta_data, **tone_data}
        self.mqttc.publish(base, json.dumps(combined, separators=(",", ":")), retain=True)
        buf.update(combined)

    def _pub_volume_only(self, zone: int, v: int):
        buf = self._zone_states.setdefault(zone, {})
        if buf.get("last_published_vol") != v:
            self.mqttc.publish(self._topic("zone", zone, "volume"), str(v), retain=True)
            buf["last_published_vol"] = v

    def _is_zone_on(self, zone: int) -> bool:
        return self._zone_states.get(zone, {}).get("power", False)

    def _publish_restore_status(self, state: str, **details):
        payload = {
            "amp": self.amp_name,
            "state": state,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **details,
        }
        self.mqttc.publish(
            self._topic("restore", "status"),
            json.dumps(payload, separators=(",", ":")),
            retain=True,
        )

    def _restore_zone_numbers(self) -> list[int]:
        return [
            zone for zone in zone_numbers(self.amp_name)
            if restore_settings(self.amp_name, zone).get("enabled", True)
        ]

    def _factory_match_summary(self) -> tuple[list[int], int]:
        eligible = self._restore_zone_numbers()
        matching = [
            zone for zone in eligible
            if factory_signature_matches(
                self.amp_name, zone, self._zone_states.get(zone, {})
            )
        ]
        configured_minimum = RESTORATION_CONFIG.get("factory_signature", {}).get(
            "minimum_matching_zones", 0
        )
        required = configured_minimum or len(eligible)
        return matching, required

    def check_restore_candidate(self) -> dict:
        matching, required = self._factory_match_summary()
        result = {
            "matching_zones": matching,
            "matching_count": len(matching),
            "required_count": required,
            "candidate": bool(required and len(matching) >= required),
        }
        self._publish_restore_status("check", **result)
        return result

    def _evaluate_automatic_restore(self):
        if not RESTORATION_CONFIG.get("enabled") or not RESTORATION_CONFIG.get("automatic"):
            return
        matching, required = self._factory_match_summary()
        is_candidate = bool(required and len(matching) >= required)
        if not is_candidate:
            self._restore_candidate_polls = 0
            self._restore_latched = False
            return
        if self._restore_latched:
            return

        self._restore_candidate_polls += 1
        needed = RESTORATION_CONFIG.get("confirmation_polls", 2)
        self._publish_restore_status(
            "candidate",
            matching_zones=matching,
            matching_count=len(matching),
            required_count=required,
            confirmation_poll=self._restore_candidate_polls,
            confirmation_polls_required=needed,
        )
        log.warning(
            "[%s] Factory-default candidate: %s/%s zones match (%s/%s confirmation polls)",
            self.amp_name, len(matching), required, self._restore_candidate_polls, needed,
        )
        if self._restore_candidate_polls < needed:
            return

        if RESTORATION_CONFIG.get("dry_run", True):
            self._restore_latched = True
            log.warning(
                "[%s] Restoration dry run: reset signature confirmed; no commands sent",
                self.amp_name,
            )
            self._publish_restore_status(
                "dry_run",
                scope="all",
                matching_zones=matching,
                message="Reset signature confirmed; no commands sent",
            )
            return
        self._restore_latched = self.restore_zones(
            self._restore_zone_numbers(), reason="automatic"
        )

    def _query_zone_locked(self, zone: int) -> Optional[dict]:
        if not self.connected and not self._connect():
            return None
        try:
            self._send_ascii(f"*ZN{zz(zone)}STA00")
            time.sleep(POST_SEND_SETTLE)
            sta_line = self._read_reply(f"#{zz(zone)},", PER_CMD_TIMEOUT)
            self._send_ascii(f"*ZN{zz(zone)}SET00")
            time.sleep(POST_SEND_SETTLE)
            tone_line = self._read_reply(f"${zz(zone)},", PER_CMD_TIMEOUT)
            sta_data, tone_data = parse_sta(sta_line), parse_tone(tone_line)
            if not (sta_data and tone_data):
                return None
            self._pub_zone_full(zone, sta_data, tone_data)
            return {**sta_data, **tone_data}
        except Exception as exc:
            log.warning("[%s] Restore verification query failed for zone %s: %s",
                        self.amp_name, zone, exc)
            self._close()
            return None

    def _restore_command_locked(self, zone: int, command: str, predicate, label: str) -> bool:
        attempts = RESTORATION_CONFIG.get("verification_attempts", 4)
        delay = RESTORATION_CONFIG.get("command_delay", 5)
        for attempt in range(1, attempts + 1):
            if self.stop_flag.is_set():
                return False
            try:
                if not self.connected and not self._connect():
                    raise RuntimeError("connect failed")
                self._send_ascii(command)
            except Exception as exc:
                log.warning("[%s] Restore %s send failed for zone %s (%s/%s): %s",
                            self.amp_name, label, zone, attempt, attempts, exc)
                self._close()
            if self.stop_flag.wait(delay):
                return False
            state = self._query_zone_locked(zone)
            if state and predicate(state):
                return True
            log.warning("[%s] Restore %s not confirmed for zone %s (%s/%s)",
                        self.amp_name, label, zone, attempt, attempts)
        return False

    def _restore_zone_locked(self, zone: int) -> bool:
        settings = restore_settings(self.amp_name, zone)
        if not settings.get("enabled", True):
            return True
        display_level = settings["volume"]
        raw_volume = protocol_volume(display_level)
        steps = [
            (
                f"*ZN{zz(zone)}SRC{zz(settings['safe_source'])}",
                lambda state: state.get("source") == settings["safe_source"],
                f"safe source {settings['safe_source']}",
            ),
            (
                f"*ZN{zz(zone)}VOL{zz(raw_volume)}",
                lambda state: state.get("power") and state.get("vol_0_75") == raw_volume,
                f"volume {display_level}",
            ),
            (
                f"*ZN{zz(zone)}BAS{_encode_tone(settings['bass'])}",
                lambda state: state.get("bass") == settings["bass"],
                f"bass {settings['bass']}",
            ),
            (
                f"*ZN{zz(zone)}TRB{_encode_tone(settings['treble'])}",
                lambda state: state.get("treble") == settings["treble"],
                f"treble {settings['treble']}",
            ),
            (
                f"*ZN{zz(zone)}SRC{zz(settings['ready_source'])}",
                lambda state: state.get("source") == settings["ready_source"],
                f"ready source {settings['ready_source']}",
            ),
        ]
        success = True
        for command, predicate, label in steps:
            if not self._restore_command_locked(zone, command, predicate, label):
                success = False
                break

        # Make a best-effort power-off even when an earlier calibration step
        # fails, so an unattended restore does not leave a room playing.
        if settings.get("leave_powered_off", True):
            powered_off = self._restore_command_locked(
                zone,
                f"*ZN{zz(zone)}PWR00",
                lambda state: not state.get("power"),
                "power off",
            )
            success = success and powered_off
        return success

    def restore_zones(self, zones: list[int], *, reason: str) -> bool:
        if not RESTORATION_CONFIG.get("enabled"):
            self._publish_restore_status("disabled", reason=reason)
            return False
        zones = [zone for zone in zones if zone in self._restore_zone_numbers()]
        if not zones:
            self._publish_restore_status("error", reason=reason, message="No eligible zones")
            return False
        if RESTORATION_CONFIG.get("dry_run", True):
            self._publish_restore_status("dry_run", reason=reason, zones=zones)
            log.warning("[%s] Restoration dry run for zones %s; no commands sent",
                        self.amp_name, zones)
            return True
        if not self._restore_guard.acquire(blocking=False):
            self._publish_restore_status("busy", reason=reason, zones=zones)
            return False
        try:
            self._publish_restore_status("running", reason=reason, zones=zones)
            failures = []
            with self.lock:
                for zone in zones:
                    self._publish_restore_status(
                        "running", reason=reason, zones=zones, current_zone=zone
                    )
                    if not self._restore_zone_locked(zone):
                        failures.append(zone)
            if failures:
                self._publish_restore_status(
                    "failed", reason=reason, zones=zones, failed_zones=failures
                )
                return False
            self._publish_restore_status("complete", reason=reason, zones=zones)
            return True
        finally:
            self._restore_guard.release()

    def request_restore(self, payload: str):
        command = payload.strip().upper()
        if command == "CHECK":
            self.check_restore_candidate()
            return
        if command == "ALL":
            self.restore_zones(self._restore_zone_numbers(), reason="manual")
            return
        if command.startswith("ZONE "):
            try:
                zone = int(command.split(None, 1)[1])
            except (ValueError, IndexError):
                zone = -1
            self.restore_zones([zone], reason="manual")
            return
        self._publish_restore_status(
            "error", message="Use CHECK, ALL, or ZONE <number>"
        )

    def set_power(self, zone: int, on: bool) -> bool: return self._send_and_confirm(zone, f"*ZN{zz(zone)}PWR{'01' if on else '00'}")
    def set_mute(self, zone: int, on: bool) -> bool: return self._send_and_confirm(zone, f"*ZN{zz(zone)}MUT{'01' if on else '00'}")
    def toggle_mute(self, zone: int) -> bool: return self._send_and_confirm(zone, f"*ZN{zz(zone)}MUT02")
    def all_zones_off_optimistic(self) -> bool: return self._send_only("*ZALLPWR00")
    
    def set_source(self, zone: int, source: int) -> bool:
        if not self._is_zone_on(zone): log.warning(f"[{self.amp_name}] Ignoring source change for zone {zone}; power is off."); return False
        return self._send_and_confirm(zone, f"*ZN{zz(zone)}SRC{zz(source)}")
    
    def volume_up(self, zone: int) -> bool:
        if not self._is_zone_on(zone): log.warning(f"[{self.amp_name}] Ignoring volume up for zone {zone}; power is off."); return False
        return self._send_and_confirm(zone, f"*ZN{zz(zone)}VOLUP")
    
    def volume_down(self, zone: int) -> bool:
        if not self._is_zone_on(zone): log.warning(f"[{self.amp_name}] Ignoring volume down for zone {zone}; power is off."); return False
        return self._send_and_confirm(zone, f"*ZN{zz(zone)}VOLDN")

    def bass_up(self, zone: int) -> bool:
        if not self._is_zone_on(zone): return False
        cur = self._zone_states.get(zone, {}).get("bass", 0)
        return self.set_bass(zone, min(12, cur + 2))

    def bass_down(self, zone: int) -> bool:
        if not self._is_zone_on(zone): return False
        cur = self._zone_states.get(zone, {}).get("bass", 0)
        return self.set_bass(zone, max(-12, cur - 2))

    def treble_up(self, zone: int) -> bool:
        if not self._is_zone_on(zone): return False
        cur = self._zone_states.get(zone, {}).get("treble", 0)
        return self.set_treble(zone, min(12, cur + 2))

    def treble_down(self, zone: int) -> bool:
        if not self._is_zone_on(zone): return False
        cur = self._zone_states.get(zone, {}).get("treble", 0)
        return self.set_treble(zone, max(-12, cur - 2))

    # --- BATCHING / COALESCING FUNCTIONS ---

    def set_volume(self, zone: int, v: int) -> bool:
        # NOTE: This is our "power on" command, so it does NOT have a power check.
        v_clamped = max(0, min(75, int(v)))
        buf = self._zone_states.setdefault(zone, {}); buf["target_vol"] = v_clamped
        t = buf.get("vol_timer")
        if t and t.is_alive(): t.cancel()
        t = threading.Timer(VOL_COALESCE_SEC, self._flush_volume, args=(zone,))
        buf["vol_timer"] = t; t.start()
        return True

    def _flush_volume(self, zone: int):
        # NOTE: This is our "power on" command, so it does NOT have a power check.
        buf = self._zone_states.get(zone, {}); target = buf.get("target_vol")
        if target is None: return
        cmd = f"*ZN{zz(zone)}VOL{zz(target)}"
        log.info(f"[{self.amp_name}] Coalesced VOL zone {zz(zone)} -> {target}")
        self._pub_volume_only(zone, target)
        buf["suppress_until"] = time.time() + VOL_ECHO_SUPPRESS_SEC
        ok = self._send_and_confirm(zone, cmd)
        if not ok:
            log.warning(f"[{self.amp_name}] Coalesced volume SET failed. Re-querying.")
            self._send_and_confirm(zone, f"*ZN{zz(zone)}STA00")

    def set_bass(self, zone: int, level: int) -> bool:
        if not self._is_zone_on(zone): log.warning(f"[{self.amp_name}] Ignoring bass change for zone {zone}; power is off."); return False
        
        level_clamped = max(-12, min(12, int(level)))
        buf = self._zone_states.setdefault(zone, {}); buf["target_bass"] = level_clamped
        t = buf.get("bass_timer") 
        if t and t.is_alive(): t.cancel()
        t = threading.Timer(VOL_COALESCE_SEC, self._flush_bass, args=(zone,))
        buf["bass_timer"] = t; t.start()
        return True

    def _flush_bass(self, zone: int):
        if not self._is_zone_on(zone): return # Check again in case zone was turned off
        buf = self._zone_states.get(zone, {}); target = buf.get("target_bass")
        if target is None: return
        
        cmd = f"*ZN{zz(zone)}BAS{_encode_tone(target)}"
        log.info(f"[{self.amp_name}] Coalesced BASS zone {zz(zone)} -> {target}")
        
        ok = self._send_and_confirm(zone, cmd)
        if not ok:
            log.warning(f"[{self.amp_name}] Coalesced bass SET failed. Re-querying.")
            self._send_and_confirm(zone, f"*ZN{zz(zone)}STA00")

    def set_treble(self, zone: int, level: int) -> bool:
        if not self._is_zone_on(zone): log.warning(f"[{self.amp_name}] Ignoring treble change for zone {zone}; power is off."); return False
        
        level_clamped = max(-12, min(12, int(level)))
        buf = self._zone_states.setdefault(zone, {}); buf["target_treble"] = level_clamped
        t = buf.get("treble_timer") 
        if t and t.is_alive(): t.cancel()
        t = threading.Timer(VOL_COALESCE_SEC, self._flush_treble, args=(zone,))
        buf["treble_timer"] = t; t.start()
        return True

    def _flush_treble(self, zone: int):
        if not self._is_zone_on(zone): return # Check again in case zone was turned off
        buf = self._zone_states.get(zone, {}); target = buf.get("target_treble")
        if target is None: return
        
        cmd = f"*ZN{zz(zone)}TRB{_encode_tone(target)}"
        log.info(f"[{self.amp_name}] Coalesced TREBLE zone {zz(zone)} -> {target}")
        
        ok = self._send_and_confirm(zone, cmd)
        if not ok:
            log.warning(f"[{self.amp_name}] Coalesced treble SET failed. Re-querying.")
            self._send_and_confirm(zone, f"*ZN{zz(zone)}STA00")

    # --- END BATCHING ---

    def _send_and_confirm(self, zone: int, cmd_ascii: str) -> bool:
        with self.lock:
            if not self.connected and not self._connect(): return False
            tries = 0
            while tries <= SET_RETRIES:
                tries += 1
                try:
                    self._send_ascii(cmd_ascii); time.sleep(POST_SEND_SETTLE)
                    self._send_ascii(f"*ZN{zz(zone)}STA00"); time.sleep(POST_SEND_SETTLE)
                    sta_line = self._read_reply(f"#{zz(zone)},", PER_CMD_TIMEOUT)
                    self._send_ascii(f"*ZN{zz(zone)}SET00"); time.sleep(POST_SEND_SETTLE)
                    tone_line = self._read_reply(f"${zz(zone)},", PER_CMD_TIMEOUT)
                    sta_data, tone_data = parse_sta(sta_line), parse_tone(tone_line)
                    if sta_data and tone_data:
                        self._pub_zone_full(zone, sta_data, tone_data)
                        return True
                    log.warning(f"[{self.amp_name}] Failed to confirm {cmd_ascii} for zone {zone}")
                    if tries <= SET_RETRIES:
                        time.sleep(RETRY_SLEEP); continue
                except Exception as e:
                    log.error(f"[{self.amp_name}] command error: {e}"); self._close()
                    if tries <= SET_RETRIES:
                        if self._connect(): continue
            return False

    def _poll_once(self):
        with self.lock:
            if not self.connected and not self._connect():
                self._handle_poll_failure()
                return False
            
            try:
                for z in zone_numbers(self.amp_name):
                    if self.stop_flag.is_set(): return False
                    self._send_ascii(f"*ZN{zz(z)}STA00"); time.sleep(INTER_CMD_SLEEP)
                    sta_line = self._read_reply(f"#{zz(z)},", PER_CMD_TIMEOUT)
                    self._send_ascii(f"*ZN{zz(z)}SET00"); time.sleep(INTER_CMD_SLEEP)
                    tone_line = self._read_reply(f"${zz(z)},", PER_CMD_TIMEOUT)
                    sta_data, tone_data = parse_sta(sta_line), parse_tone(tone_line)
                    if not (sta_data and tone_data):
                        log.warning(f"[{self.amp_name}] poll failed for zone {zz(z)}, aborting poll cycle.")
                        self._handle_poll_failure()
                        return False
                    self._pub_zone_full(z, sta_data, tone_data)
                
                self._handle_poll_success()
                return True
            except Exception as e:
                log.warning(f"[{self.amp_name}] poll error: {e}")
                self._handle_poll_failure()
                return False

    def _handle_poll_success(self):
        """Resets failure counter on a successful poll."""
        if self._consecutive_failures > 0:
             log.info(f"[{self.amp_name}] Amp communication restored.")
        self._consecutive_failures = 0
        if self._network_status != "up":
            status_topic = f"{MQTT_BASE}/network_status/{self.amp_name}"
            self.mqttc.publish(status_topic, "up", retain=True)
            self._network_status = "up"
            log.info(f"[{self.amp_name}] Published network status: up")

    def _handle_poll_failure(self):
        """Increments failure counter and publishes 'down' message if threshold is met."""
        self._consecutive_failures += 1
        log.warning(f"[{self.amp_name}] Poll failed. Consecutive failures: {self._consecutive_failures}")
        self.connected = False # Mark as disconnected to force a reconnect attempt
        # The AD-8x Telnet service can take several seconds to release a failed
        # session. Close our side now, before waiting and reconnecting.
        self._cleanup_socket()
        
        if self._consecutive_failures >= NETWORK_FAILURE_THRESHOLD and self._network_status != "down":
            log.error(f"[{self.amp_name}] Exceeded poll failure threshold. Publishing 'down' message.")
            down_topic = f"{MQTT_BASE}/network_status/{self.amp_name}"
            self.mqttc.publish(down_topic, "down", retain=True)
            self._network_status = "down"

    def run(self):
        if self.start_delay and self.stop_flag.wait(self.start_delay):
            return
        backoff = RECONNECT_BACKOFF_INITIAL
        while not self.stop_flag.is_set():
            if self._poll_once():
                backoff = RECONNECT_BACKOFF_INITIAL
                self._evaluate_automatic_restore()
                self.stop_flag.wait(POLL_INTERVAL_SEC)
            else:
                self.stop_flag.wait(backoff); backoff = min(30.0, backoff * 2)

    def stop(self): self.stop_flag.set(); self._close()

class Bridge:
    def __init__(self):
        self.client = mqtt.Client(protocol=mqtt.MQTTv5, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if MQTT_USER: self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.will_set(f"{MQTT_BASE}/bridge/status", "offline", retain=True)
        self.sessions = {}
        # --- INSTRUMENTATION ---
        self._start_time = time.monotonic()
        self._pid = os.getpid()
        self._process = psutil.Process(self._pid)
        self._last_diag_pub_time = time.monotonic() # Set to start time
        # --- INSTRUMENTATION ---

    def publish_discovery(self):
        for amp_key, (amp_ip, amp_port) in AMPS.items():
            avail_t = self._topic(amp_key, "status"); dev = device_block(amp_key, amp_ip)
            for z in zone_numbers(amp_key):
                zname = ZONE_NAMES.get(amp_key, {}).get(z, f"Zone {z}")
                base = self._topic(amp_key, "zone", z); cmd_base = f"{base}/set"
                
                power_cfg = {"name": f"{zname} Power", "uniq_id": zone_object_id(amp_key, z, "power"), "stat_t": f"{base}/power", "cmd_t": f"{cmd_base}/power", "pl_on": "on", "pl_off": "off", "stat_on": "on", "stat_off": "off", "avty_t": avail_t, "device": dev, "optimistic": True}
                self.client.publish(discovery_topic("switch", zone_object_id(amp_key, z, "power")), json.dumps(power_cfg), retain=True)

                mute_cfg = {"name": f"{zname} Mute", "uniq_id": zone_object_id(amp_key, z, "mute"), "stat_t": f"{base}/mute", "cmd_t": f"{cmd_base}/mute", "pl_on": "on", "pl_off": "off", "stat_on": "on", "stat_off": "off", "avty_t": avail_t, "device": dev, "optimistic": True}
                self.client.publish(discovery_topic("switch", zone_object_id(amp_key, z, "mute")), json.dumps(mute_cfg), retain=True)

                vol_cfg = {"name": f"{zname} Volume", "uniq_id": zone_object_id(amp_key, z, "volume"), "stat_t": f"{base}/volume", "cmd_t": f"{cmd_base}/volume", "min": 0, "max": 75, "mode": "slider", "avty_t": avail_t, "device": dev, "val_tpl": "{{ 75 - (value | int) }}", "cmd_tpl": "{{ 75 - (value | int) }}", "optimistic": True}
                self.client.publish(discovery_topic("number", zone_object_id(amp_key, z, "volume")), json.dumps(vol_cfg), retain=True)

                source_options = ([SOURCE_NAMES[amp_key][number] for number in sorted(SOURCE_NAMES[amp_key])]
                                  if USE_SOURCE_NAMES else
                                  [str(number) for number in sorted(SOURCE_NAMES[amp_key])])
                source_cfg = {"name": f"{zname} Source", "uniq_id": zone_object_id(amp_key, z, "source"), "stat_t": f"{base}/source", "cmd_t": f"{cmd_base}/source", "options": source_options, "avty_t": avail_t, "device": dev}
                self.client.publish(discovery_topic("select", zone_object_id(amp_key, z, "source")), json.dumps(source_cfg), retain=True)
                
                bass_cfg = {"name": f"{zname} Bass", "uniq_id": zone_object_id(amp_key, z, "bass"), "stat_t": f"{base}/bass", "cmd_t": f"{cmd_base}/bass", "min": -12, "max": 12, "step": 2, "mode": "slider", "avty_t": avail_t, "device": dev, "icon": "mdi:speaker", "optimistic": True}
                self.client.publish(discovery_topic("number", zone_object_id(amp_key, z, "bass")), json.dumps(bass_cfg), retain=True)
                
                treble_cfg = {"name": f"{zname} Treble", "uniq_id": zone_object_id(amp_key, z, "treble"), "stat_t": f"{base}/treble", "cmd_t": f"{cmd_base}/treble", "min": -12, "max": 12, "step": 2, "mode": "slider", "avty_t": avail_t, "device": dev, "icon": "mdi:surround-sound", "optimistic": True}
                self.client.publish(discovery_topic("number", zone_object_id(amp_key, z, "treble")), json.dumps(treble_cfg), retain=True)

    # --- INSTRUMENTATION ---
    def publish_diagnostics(self):
        """Gather and publish system and connection diagnostics metrics."""
        if not self.client.is_connected():
            return

        # 1. System Process Metrics (using psutil)
        try:
            # Get instantaneous CPU% (first call returns 0.0,
            # so call with interval=None after the first time)
            cpu_pct = self._process.cpu_percent(interval=None)
            mem_info = self._process.memory_info()
            mem_mb = round(mem_info.rss / (1024 * 1024), 2)
            
            self.client.publish(self._topic("diagnostics", "cpu_usage_pct"), str(cpu_pct), retain=False)
            self.client.publish(self._topic("diagnostics", "memory_usage_mb"), str(mem_mb), retain=False)
        except Exception as e:
            log.warning(f"[Bridge] Failed to gather process metrics: {e}")

        # 2. Bridge Uptime
        uptime_s = int(time.monotonic() - self._start_time)
        self.client.publish(self._topic("diagnostics", "uptime_s"), str(uptime_s), retain=True)

        # 3. Individual Amp Connection Status
        amp_statuses = {}
        for name, session in self.sessions.items():
            amp_statuses[name] = "online" if session.connected else "offline"
        
        self.client.publish(
            self._topic("diagnostics", "amp_connection_status"),
            json.dumps(amp_statuses),
            retain=True
        )
        
        # 4. Entity Count (using Zones)
        entity_count = sum(len(zone_numbers(amp_key)) for amp_key in self.sessions)
        self.client.publish(
            self._topic("diagnostics", "entity_count"),
            str(entity_count),
            retain=True
        )
        
        # 5. Heartbeat (re-publish bridge status)
        self.client.publish(self._topic("bridge","status"), "online", retain=True)
    # --- INSTRUMENTATION ---

    def _topic(self, *parts) -> str: return "/".join([MQTT_BASE, *[str(p) for p in parts]])
    def start(self):
        self.client.on_connect = self.on_connect; self.client.on_message = self.on_message
        self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30); self.client.loop_start()
        
        # --- INSTRUMENTATION ---
        # Call cpu_percent once with interval to establish a baseline
        # This prevents the first 'None' interval call from returning 0.0
        try:
            self._process.cpu_percent(interval=0.1) 
        except Exception as e:
            log.warning(f"[Bridge] Initial psutil call failed: {e}")
        # --- INSTRUMENTATION ---

        for name, addr in AMPS.items():
            start_delay = AMP_METADATA[name]["startup_delay"]
            s = AmpSession(name, addr, self.client, start_delay=start_delay)
            self.sessions[name] = s; s.start()
            log.info(f"Started AmpSession {name} -> {addr[0]}:{addr[1]}")
    def stop(self):
        for s in self.sessions.values(): s.stop()
        self.client.loop_stop(); self.client.disconnect()
    def on_connect(self, client, userdata, flags, rc, props):
        if rc == 0:
            client.subscribe(f"{self._topic('+','zone','+','set','+')}")
            client.subscribe(f"{self._topic('+','raw')}")
            client.subscribe(f"{self._topic('+','restore','command')}")
            client.subscribe(f"{self._topic('all','command')}")
            client.subscribe("homeassistant/status")
            client.publish(self._topic("bridge","status"), "online", retain=True)
            if HA_DISCOVERY:
                self.publish_discovery()
            log.info(f"MQTT connected to {MQTT_HOST}:{MQTT_PORT}")
        else: log.error(f"MQTT connect failed code: {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = (msg.payload.decode() if msg.payload else "").strip()
            topic = msg.topic; parts = topic.split("/")
            if "/".join(parts[-2:]) == "all/command":
                log.info(f"Received master command: {payload}")
                if payload.upper() == 'OFF':
                    # First, send the efficient 'ALL OFF' command to each amp
                    for s in self.sessions.values():
                        s.all_zones_off_optimistic()

                    # Now, publish optimistic states for HA's UI
                    for amp_key, s in self.sessions.items():
                        for z in zone_numbers(amp_key):
                            base_t = s._topic("zone", z)
                            client.publish(f"{base_t}/power", "off", retain=True)
                            client.publish(f"{base_t}/mute", "off", retain=True)
                    log.info("Sent ALL OFF command and optimistically set all zones to OFF")
                return
            if topic == "homeassistant/status" and payload == "online":
                if HA_DISCOVERY:
                    self.publish_discovery()
                return
            base_parts = MQTT_BASE.split("/")
            relative = parts[len(base_parts):] if parts[:len(base_parts)] == base_parts else []
            if len(relative) == 3 and relative[1:] == ["restore", "command"]:
                sess = self.sessions.get(relative[0])
                if sess:
                    threading.Thread(
                        target=sess.request_restore,
                        args=(payload,),
                        daemon=True,
                        name=f"restore-{relative[0]}",
                    ).start()
                return
            if parts[-1] == "raw":
                sess = self.sessions.get(parts[-2])
                if sess:
                    with sess.lock:
                        if not sess.connected and not sess._connect(): return
                        sess._send_ascii(payload); time.sleep(POST_SEND_SETTLE)
                        line = sess._readline(PER_CMD_TIMEOUT)
                        client.publish(self._topic(parts[-2], "ack", "raw"), line or "", retain=False)
                return
            parsed_command = parse_set_topic(topic)
            if not parsed_command: return
            amp, zone, cmd = parsed_command
            sess = self.sessions.get(amp)
            if not sess: return
            if zone not in zone_numbers(amp):
                log.warning(f"Ignoring command for unconfigured zone {amp}/{zone}")
                return
            ok = False

            # --- SPEC-SAFE POWER-ON FIX ---
            if cmd == "power":
                is_on = payload.lower() in ("1", "on", "true")
                if is_on:
                    # 'power on' command received
                    # Per the spec, *ZNzzVOLvv* also turns the zone on.
                    # We use this to power on AT the last known volume,
                    # bypassing the amp's "default 45" behavior.
                    
                    # Get last volume from cache, default to a 'safe' 65
                    last_vol = sess._zone_states.get(zone, {}).get("vol_0_75", POWER_ON_FALLBACK_VOLUME)
                    log.info(f"[{amp}] Power ON for zone {zone} received. Setting volume to {last_vol} to power on.")
                    ok = sess.set_volume(zone, last_vol)
                else:
                    # 'power off' command is normal
                    ok = sess.set_power(zone, False)
            # --- END OF FIX ---
            
            elif cmd == "mute": ok = sess.set_mute(zone, payload.lower() in ("1", "on", "true"))
            elif cmd == "toggle_mute": ok = sess.toggle_mute(zone)
            elif cmd == "source": ok = sess.set_source(zone, source_number(amp, payload))
            elif cmd == "volume": ok = sess.set_volume(zone, int(payload))
            elif cmd == "bass": ok = sess.set_bass(zone, int(payload))
            elif cmd == "treble": ok = sess.set_treble(zone, int(payload))
            elif cmd == "volume_up": ok = sess.volume_up(zone)
            elif cmd == "volume_down": ok = sess.volume_down(zone)
            elif cmd == "bass_up": ok = sess.bass_up(zone)
            elif cmd == "bass_down": ok = sess.bass_down(zone)
            elif cmd == "treble_up": ok = sess.treble_up(zone)
            elif cmd == "treble_down": ok = sess.treble_down(zone)
            client.publish(self._topic(amp, "zone", "ack", cmd), "ok" if ok else "err", retain=False)
        except Exception: traceback.print_exc()

def _default_config_path() -> str:
    candidates = [
        os.getenv("RTI_CONFIG"),
        "/etc/rti-ad8x-bridge/config.yaml",
        str(Path(__file__).resolve().parent.parent / "config.yaml"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return candidate
    return candidates[1]


def _parse_args():
    parser = argparse.ArgumentParser(description="RTI AD-series MQTT bridge")
    parser.add_argument("--config", default=_default_config_path(), help="YAML configuration path")
    parser.add_argument("--check-config", action="store_true", help="validate configuration and exit")
    parser.add_argument("--print-effective-config", action="store_true",
                        help="print validated configuration with environment expansion and exit")
    parser.add_argument("--version", action="version", version=VERSION)
    return parser.parse_args()


def main():
    args = _parse_args()
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error(f"Configuration error: {exc}")
        return 2
    configure_runtime(config)
    if args.check_config:
        print(f"Configuration OK: {args.config}")
        return 0
    if args.print_effective_config:
        redacted = json.loads(json.dumps(config))
        if redacted["mqtt"]["password"]:
            redacted["mqtt"]["password"] = "***"
        print(json.dumps(redacted, indent=2))
        return 0

    print("RTI Bridge starting up…")
    log.info(f"Starting RTI bridge {VERSION} with config {args.config}")
    bridge = Bridge()
    def _graceful(sig, frame): log.info(f"Signal {sig} received; stopping…"); bridge.stop(); sys.exit(0)
    signal.signal(signal.SIGINT, _graceful); signal.signal(signal.SIGTERM, _graceful)
    try:
        bridge.start();
        # --- INSTRUMENTATION ---
        # The main thread is now the diagnostics publisher
        while True: 
            now = time.monotonic()
            if (now - bridge._last_diag_pub_time) > HEALTH_CHECK_INTERVAL:
                bridge.publish_diagnostics()
                bridge._last_diag_pub_time = now
            time.sleep(1.0) # Check every second
        # --- INSTRUMENTATION ---
    finally: bridge.stop()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
    
