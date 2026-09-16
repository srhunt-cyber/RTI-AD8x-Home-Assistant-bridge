# Changelog

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
