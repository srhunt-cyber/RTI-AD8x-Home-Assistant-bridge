# Changelog

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
