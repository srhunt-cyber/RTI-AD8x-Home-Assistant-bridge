# RTI AD-Series MQTT Bridge for Home Assistant

> [!NOTE]
> **Version 2.0 is the current production release.** It was validated on a
> two-amplifier, 16-zone AD-8x installation using Home Assistant, MQTT, native
> speaker entities, Amazon Alexa, and automatic post-reset restoration.

## Project overview

RTI AD-4x and AD-8x amplifiers are durable distributed-audio matrix amplifiers,
but their original control path assumes dealer programming, legacy RTI
processors, or older applications. This project turns that installed hardware
into a modern Home Assistant appliance without placing the amplifier's fragile
TCP behavior inside Home Assistant.

The bridge runs as a dedicated MQTT service. It owns one persistent connection
to each amplifier, serializes and paces commands, polls for reconciliation, and
publishes retained state. Home Assistant and Alexa communicate through MQTT,
so their restarts and UI activity do not repeatedly open amplifier sessions.

Version 2.0 supports up to eight amplifiers through the guided installer, with
one to eight configured zones and up to eight sources per amplifier: as many as
64 independently controlled zones. A smaller AD-4x installation simply defines
the zones it uses.

## Why a persistent MQTT bridge?

### The amplifier behaves like a serial device behind TCP

Field testing found that the AD-series Ethernet control interface:

- permits only one active TCP control client per amplifier;
- may refuse a new connection while releasing the previous session;
- drops or delays commands that arrive faster than its internal processors can
  handle; and
- processes bass and treble much more slowly than power, source, mute, and
  volume.

A small installation can appear to work with occasional connect/send/disconnect
transactions. At whole-home scale, connection churn and concurrent commands
make that approach vulnerable to latency, refused connections, dropped work,
and stale state.

### One connection owner and a hardware-safe pipeline

The standalone bridge maintains one long-lived connection per amplifier.
Per-amplifier locks serialize polling and commands, while MQTT decouples Home
Assistant from amplifier timing and reconnects. Rapid GUI changes are
coalesced, commands are paced, and important changes are read back.

This architecture is intentionally suitable for multi-amplifier automation:
a scene can target many zones at once without allowing multiple Home Assistant
tasks to compete for the same RTI socket. Home Assistant remains responsive if
an amplifier is slow, rebooting, or temporarily unreachable.

> [!IMPORTANT]
> Close amplifier web clients, Telnet/netcat sessions, RTI test utilities, and
> any other IP driver before starting the bridge. A second client usually sees
> `Connection refused` or a timeout.

### Recommended HA-only operating model

Version 2.0 assumes Home Assistant/MQTT is the normal control path. Commands
from Home Assistant or Alexa are sent immediately; a conservative 60-second
background poll reconciles state and detects physical amplifier resets without
constantly loading the RTI TCP server.

If an RS-232 processor or another controller can also change state, shorten the
poll interval according to how quickly those external changes must appear in
Home Assistant. Do not run a second IP integration against the same amplifier.

Tone commands receive special treatment: rapid bass/treble adjustments
coalesce to the final even target, the bridge waits six seconds for the slower
tone DSP, and then verifies once without resending during the settle window.

## Features

- **Complete zone control:** power, mute, source, volume, bass, and treble.
- **Multi-amplifier scale:** up to eight amplifiers and 64 configured zones
  through the installer.
- **YAML configuration:** amplifier addresses, zone/source names, MQTT,
  timing, entity mode, restoration targets, and per-zone overrides.
- **Home Assistant MQTT Discovery:** traditional switch, number, and select
  entities require no hand-written zone YAML.
- **Native speaker layer:** generated `media_player` entities work with media
  cards and are the recommended Alexa exposure method.
- **Safe migration:** `dual` mode keeps existing dashboards working while
  adding speakers; `legacy` and `media_player`-only modes are also available.
- **Volume safety range:** speaker 0–100% maps to a configurable RTI display
  range of 5–40 by default, preventing a voice request for 100% from selecting
  the amplifier's full level 75.
- **Command coalescing and pacing:** rapid volume/tone changes resolve to the
  latest target without flooding the amplifier.
- **Guarded default restoration:** after a verified factory-default signature,
  the bridge can safely restore volume, bass, treble, source, and final power
  state with paced read-back verification.
- **Health and availability:** retained bridge/per-amplifier status plus CPU,
  memory, uptime, connection, and zone-count diagnostics over MQTT.
- **Global all-off:** publish `OFF` to `rti/ad8x/all/command`.
- **Flexible deployment:** guided Debian/Ubuntu/Raspberry Pi installation,
  Docker Compose sidecar, or an experimental Home Assistant app/add-on.

## Installation

For complete migration, testing, restoration, Docker, app/add-on, and rollback
instructions, see the [deployment guide](docs/DEPLOYMENT.md).

### Option A — guided Linux installation (recommended)

Use a Debian/Ubuntu host, VM, or Raspberry Pi that can reach the amplifiers and
MQTT broker:

```bash
git clone https://github.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge.git
cd RTI-AD8x-Home-Assistant-bridge
sudo ./scripts/install.sh
```

The installer can use an existing MQTT broker or install an authenticated local
Mosquitto broker. It prompts for amplifiers and zones, validates the YAML,
installs a dedicated Python environment, and enables the systemd service.

Production paths:

```text
Service:  rti-ad8x-bridge.service
Code:     /opt/rti-ad8x-bridge
Config:   /etc/rti-ad8x-bridge/config.yaml
```

Useful commands:

```bash
sudo systemctl status rti-ad8x-bridge.service --no-pager -l
sudo journalctl -fu rti-ad8x-bridge.service
sudo /opt/rti-ad8x-bridge/.venv/bin/python \
  /opt/rti-ad8x-bridge/bridge/rti_ad8x_bridge.py \
  --config /etc/rti-ad8x-bridge/config.yaml \
  --check-config
```

The installer preserves an existing production configuration during upgrades.

### Option B — Docker Compose sidecar

```bash
cp config.example.yaml config.yaml
# Edit config.yaml before starting.
docker compose up -d --build
docker compose logs -f rti-bridge
```

The supplied Compose file uses host networking on Linux so the container can
reach LAN amplifiers and the MQTT broker.

### Option C — Home Assistant app/add-on (experimental)

The package in `rti_ad_series_bridge_beta` runs the same 2.0 bridge, but the
app/add-on packaging remains experimental. It expects an existing MQTT broker
and a YAML file in its app configuration directory. See its `DOCS.md` before
using it.

## Configuration

The full annotated configuration is in [`config.example.yaml`](config.example.yaml).
The recommended Home Assistant mode for new and upgraded installations is:

```yaml
home_assistant:
  discovery: true
  use_source_names: false
  entity_mode: dual
  media_players:
    include: all
    name_suffix: Speakers
    volume_min: 5
    volume_max: 40
    volume_step: 1
```

Entity modes:

| Mode | Traditional entities | Speaker entities | Use case |
|---|---:|---:|---|
| `dual` | Yes | Yes | Recommended; safest migration and default for 2.0 |
| `legacy` | Yes | No | Exact v1.8-style entity model |
| `media_player` | No | Yes | After all dashboards/automations are migrated |

`dual` does not create a second amplifier connection. The generated speaker
package consumes the bridge's MQTT topics.

## Home Assistant speaker entities

Home Assistant's Universal Media Player configuration contains the mapping
between zone MQTT topics and native speaker behavior. Generate it from the same
validated bridge YAML so names, sources, topics, and safety ranges cannot drift:

```bash
sudo /opt/rti-ad8x-bridge/.venv/bin/python \
  /opt/rti-ad8x-bridge/scripts/generate_ha_media_players.py \
  --config /etc/rti-ad8x-bridge/config.yaml \
  --output /tmp/rti_ad8x_media_players.yaml
```

The generator also writes `/tmp/rti_ad8x_alexa_cloud.yaml`. That second file
contains only Alexa `MUSIC_SYSTEM` category metadata for the generated zones;
it does not expose, filter, or rename any entity.

Copy the resulting file to:

```text
/config/packages/rti_ad8x_media_players.yaml
```

Ensure Home Assistant has one packages include beneath its existing
`homeassistant:` key:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Run **Developer Tools → YAML → Check configuration**, then restart Home
Assistant. Regenerate the package after changing amplifier IDs, zones, source
names, the MQTT base topic, or media-player volume limits.

## Alexa: expose speakers, not template lights

The generated `media_player` entities are the supported and recommended Alexa
path in 2.0. Alexa recognizes them as speakers and can use speaker-oriented
power, mute, volume, and input-selection intents. Numeric RTI sources are
presented to Home Assistant and Alexa as `INPUT 1` through `INPUT 8`; the
package translates selections back to the amplifier's numeric MQTT protocol.
The older template-light workaround exposed volume as brightness and was
unreliable for voice volume commands.

With Home Assistant Cloud/Nabu Casa:

1. Generate and validate the media-player package.
2. Expose only the resulting `media_player.<zone>_speakers` entities to Alexa.
3. Do not expose the package's diagnostic helper sensors.
4. Unexpose any old template-light speaker entities with the same names.
5. Remove stale duplicate devices in Alexa if necessary, then run discovery.

For reliable input-selection voice commands, merge the generated
`rti_ad8x_alexa_cloud.yaml` into your Home Assistant Cloud configuration. If
`configuration.yaml` contains `cloud: !include cloud.yaml`, copy its `alexa:`
section into that included file. If Cloud is configured directly, nest the
generated content beneath `cloud:`. Users who otherwise auto-expose entities
can omit a `filter:` section; the generated snippet changes only the RTI
speakers' Alexa category.

Example voice command:

```text
Alexa, change Kitchen Speakers input to Input 2.
```

Amazon/Nabu Casa synchronization can take several minutes. Existing dashboards
may continue using their switch/number/select entities indefinitely in `dual`
mode; Alexa and dashboards do not have to use the same entity type.

## Guarded amplifier-default restoration

Restoration is disabled and dry-run-only in the public example. Configure the
desired defaults and complete the documented `CHECK`, one-zone, and one-amp
tests before enabling unattended restoration.

```yaml
restoration:
  enabled: false
  automatic: false
  dry_run: true
  confirmation_polls: 2
  command_delay: 5
  verification_attempts: 4
  factory_signature:
    bass: 0
    treble: 0
    minimum_matching_zones: 0  # all enabled zones must match
  defaults:
    volume: 20
    bass: 8
    treble: 12
    safe_source: 8             # must be unused or silent
    ready_source: 1
    leave_powered_off: true
```

Automatic restoration requires the factory signature on two complete
successful polls by default. It then restores each zone sequentially, verifies
each setting, and publishes retained progress to:

```text
rti/ad8x/<amp-id>/restore/status
```

This is intentionally different from treating a transient connection failure
as proof that an amplifier reset. Network status alone never triggers default
restoration.

## Operational behavior

- A single incomplete poll can occur and recover normally. Investigate repeated
  failures that cross the configured threshold and publish retained `down`.
- `Connection refused` usually means another client owns the amplifier's TCP
  slot or the amplifier has not released a previous socket yet.
- Do not automatically power-cycle amplifiers after one failed poll.
- MQTT retained messages are delivered immediately to new subscribers; inspect
  timestamps embedded in JSON status payloads before treating them as new work.
- The 60-second poll affects only background reconciliation. Home Assistant and
  Alexa commands are sent immediately.

## Troubleshooting

### Nothing responds in Home Assistant

```bash
sudo systemctl status rti-ad8x-bridge.service --no-pager -l
sudo journalctl -u rti-ad8x-bridge.service -n 200 --no-pager
mosquitto_sub -v -t 'rti/ad8x/#'
```

Confirm the MQTT broker address/credentials and verify that only one bridge
process is connected to each amplifier.

### Repeated connection refusals or timeouts

Close web/Telnet/test clients, stop competing integrations, and allow several
seconds for the RTI control port to release. Restart the bridge once; avoid a
rapid restart loop.

### Alexa reports a speaker unavailable

Confirm the corresponding `media_player` works in Home Assistant, check the
amplifier availability topic, ensure the media player—not an old light—is
exposed, and allow the cloud device list time to synchronize.

## Upgrading from 1.8 or the 1.9 beta

To preserve existing MQTT topics and entity IDs:

1. Keep the same amplifier IDs (`amp1`, `amp2`, and so on).
2. Keep existing zone names exactly.
3. Keep `mqtt.base_topic: rti/ad8x`.
4. Keep `home_assistant.use_source_names: false` unless you intend to migrate
   existing source selections.
5. Use `entity_mode: dual` while retaining existing dashboards.
6. Never run old and new bridges simultaneously.

Version 2.0 uses the same `rti-ad8x-bridge.service` and production paths as the
1.9 guided installation. See the [deployment guide](docs/DEPLOYMENT.md) for a
staged migration and rollback procedure.

## License and scope

This is an independent community project and is not affiliated with or
supported by RTI. Keep a tested rollback path before changing a working
installation, especially when enabling automatic restoration.
