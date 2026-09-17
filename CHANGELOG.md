# Changelog

## 1.9.0-beta.3 — 2026-09-17

- Add an opt-in Home Assistant media-player package generator for native media
  cards and Alexa speaker-volume intents.
- Add `legacy`, `dual`, and `media_player` entity modes. `legacy` remains the
  default; `dual` preserves all existing switch/number/select entities while
  adding media players.
- Generate self-contained MQTT-backed Universal Media Player entities with
  power, mute, source, absolute volume, and relative volume controls.
- Preserve the existing Alexa safety mapping by default: speaker 0–100% maps
  into RTI display levels 5–40, never the amplifier's full 0–75 range.
- Support generation for a single test zone before expanding to every zone.
- Leave the RTI Telnet protocol, polling, reconnect, restoration, and existing
  MQTT topic behavior unchanged.

## 1.9.0-beta.2 — 2026-09-17

- Add optional bass, treble, volume, safe-source, ready-source, and final-power
  defaults to YAML, with per-zone overrides.
- Detect an amplifier reset only when the configured factory signature matches
  every restore-enabled zone by default; require two complete successful polls
  before automatic action.
- Add a safe dry-run mode and MQTT `CHECK`, `ZONE <number>`, and `ALL` test
  commands with retained JSON progress/status.
- Pace every restoration step, verify the resulting amplifier state, retry
  bounded failures, and make a best-effort final power-off on failure.
- Keep restoration disabled and in dry-run mode in public example
  configurations. Existing v1.8-compatible entities and polling behavior are
  unchanged unless restoration is explicitly enabled.
- Continue to defer native Home Assistant `media_player` entities to a separate
  beta so entity-model changes remain isolated from restoration testing.

## 1.9.0-beta.1 — 2026-09-17

- Move amplifier addresses, ports, zone definitions, source labels, MQTT
  settings, and timing controls into validated YAML configuration.
- Support dynamic one-to-eight-zone definitions and multiple amplifiers without
  editing Python source.
- Add a guided Debian/Ubuntu installer that uses an existing MQTT broker or can
  install an authenticated Mosquitto broker.
- Add Docker Compose sidecar and experimental Home Assistant app/add-on
  deployment paths.
- Preserve v1.8 MQTT topics and discovery IDs when existing amplifier IDs and
  zone names are retained; numeric source options remain the default.
- Preserve the v1.8.4 RTI protocol, command pacing, polling, and reconnect logic.
- Defer tone-default restoration and `media_player` entities to later betas so
  they can be evaluated independently from the deployment refactor.

## 1.8.4 — 2026-09-16

- Change the default HA-only operating profile to `POLL_INTERVAL=60`,
  `INTER_CMD_SLEEP=0.20`, and `PER_CMD_TIMEOUT=3.0`. This reduces background
  load on the fragile AD-8x Telnet server while leaving HA and Alexa commands
  immediate.
- Document Home Assistant/MQTT as the sole day-to-day control path. The former
  RTI XP-8v/RS-232 control path and legacy RTI app are retired in this
  deployment.
- Retain the v1.8.3 failed-socket cleanup, five-second reconnect delay, and
  staggered amplifier startup.
- During initial live validation, individual incomplete polls recovered on the
  next cycle without connection-refusal storms or retained `down` transitions.
- A parallel controller can change amplifier state without MQTT knowing about
  it until the next poll. Installations that retain an RTI processor, serial
  controller, or another control application may need a shorter poll interval.

## 1.8.3 — 2026-09-16

- Close a failed amplifier socket immediately so the AD-8x can release its single TCP client slot.
- Wait five seconds before the first reconnect attempt; subsequent failures continue to use bounded exponential backoff.
- Start the second amplifier worker five seconds after the first to avoid lockstep polling.
- Use interruptible waits so the service can stop cleanly during poll and reconnect delays.

## 1.8.2 — 2026-09-15

- Publish retained `up` status after the first successful full poll and whenever communication recovers.
- Publish retained `down` status only on the transition to three consecutive failures.
- Include the date in bridge log timestamps.

## Operational note

The AD-8x Ethernet control port accepts one TCP client. Close the amplifier web client, manual Telnet sessions, test utilities, and other IP integrations before starting the bridge. A refused connection usually means the control port is still occupied or has not finished releasing the previous session.
