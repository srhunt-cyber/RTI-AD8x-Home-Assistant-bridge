# 1.9 beta: YAML configuration and deployment

Version `1.9.0-beta.2` is an optional test release. The stable `main` branch
remains on v1.8.4.

The beta deliberately preserves the field-tested RTI command, pacing, polling,
and reconnect behavior. Its changes are focused on configuration and packaging:

- amplifiers, IP addresses, ports, zone counts, zone names, and optional source
  names now live in YAML;
- one to eight amplifiers and one to eight configured zones per amplifier are
  supported;
- guided Ubuntu/Debian installation with systemd;
- Docker Compose sidecar deployment;
- experimental Home Assistant app/add-on deployment;
- configuration validation before service startup;
- opt-in, verified restoration of volume, bass, treble, and source defaults.

Native Home Assistant `media_player` entities remain deferred. They change the
Home Assistant entity model and should be evaluated separately from deployment
and amplifier-restoration behavior.

## Compatibility rules

To preserve an existing v1.8 Home Assistant installation:

1. Keep amplifier IDs as `amp1` and `amp2`.
2. Copy the existing zone names exactly into YAML.
3. Leave `mqtt.base_topic` set to `rti/ad8x`.
4. Leave `home_assistant.use_source_names` set to `false`.

With those settings, MQTT topics, discovery unique IDs, and existing dashboard
entity IDs remain unchanged.

> Never run stable and beta bridges simultaneously. The AD-series Ethernet
> control interface accepts a single TCP client, and both bridges would also
> publish conflicting retained MQTT state.

## Option A: guided Linux install

Use a dedicated Debian or Ubuntu host, VM, or Raspberry Pi:

```bash
git clone --branch beta-v1.9.0-beta.2 \
  https://github.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge.git
cd RTI-AD8x-Home-Assistant-bridge
sudo ./scripts/install.sh
```

The installer asks whether an MQTT broker already exists. If not, it can install
an authenticated Mosquitto broker locally. It then prompts for each amplifier
and zone, validates the YAML, installs a locked-down systemd service, and starts
the bridge.

Useful commands:

```bash
sudo systemctl status rti-ad8x-bridge.service
sudo journalctl -fu rti-ad8x-bridge.service
sudo /opt/rti-ad8x-bridge/.venv/bin/python \
  /opt/rti-ad8x-bridge/bridge/rti_ad8x_bridge.py \
  --config /etc/rti-ad8x-bridge/config.yaml --check-config
```

An existing `/etc/rti-ad8x-bridge/config.yaml` is retained during a reinstall.

## Option B: Docker Compose sidecar

```bash
cp config.example.yaml config.yaml
# Edit config.yaml first.
docker compose up -d --build
docker compose logs -f rti-bridge
```

The compose file uses host networking so the container can reach amplifiers and
an MQTT broker on the LAN. Host networking is intended for Linux hosts.

## Option C: Home Assistant app/add-on

Because this beta is intentionally isolated from `main`, install it as a local
Home Assistant app/add-on: download the `beta-v1.9.0-beta.2` branch source
archive, copy the
`rti_ad_series_bridge_beta` folder into Home Assistant's local apps/add-ons
directory, reload the store, and install **RTI AD-series MQTT Bridge Beta**.
Start it once; the first start creates an app configuration file and exits.
Edit that YAML in the app configuration directory, then start the app again.

The Home Assistant app expects an existing broker. With the official Mosquitto
Broker app the broker hostname is normally `core-mosquitto`. Home Assistant does
not permit one app to silently install another, so broker installation remains
an explicit administrator step.

## Optional amplifier-default restoration

Restoration is disabled by default. The public example also sets `dry_run: true`,
which guarantees that restore requests publish a plan/status but send no RTI
commands.

The default target values match the reference 16-zone installation:

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
    minimum_matching_zones: 0
  defaults:
    volume: 20
    bass: 8
    treble: 12
    safe_source: 8
    ready_source: 1
    leave_powered_off: true
```

`volume` uses the existing Home Assistant/display scale. A target of 20 is sent
to the amplifier as attenuation 55. Bass and treble must be even values from
-12 through 12. `safe_source` must be an unused or silent input: the bridge
selects it before the volume command powers the zone, preventing the previous
music source from playing during calibration.

`minimum_matching_zones: 0` means every restore-enabled zone on an amplifier
must match the factory signature. A legitimate zero setting in one room cannot
trigger an amp-wide restore. Automatic restoration also requires the signature
on two complete successful polls by default.

A zone can override any default without changing its number or entity ID:

```yaml
zones:
  1: Kitchen
  2:
    name: Great Room
    defaults:
      bass: 10
      treble: 12
```

### Safe live-test sequence

Keep the existing Home Assistant restore automation disabled while testing so
only one restoration owner can issue commands.

1. Set `enabled: true`, retain `automatic: false` and `dry_run: true`, validate
   the configuration, and restart the beta.
2. Subscribe to restoration status:

   ```bash
   mosquitto_sub -v -t 'rti/ad8x/+/restore/status'
   ```

3. Request a read-only signature check:

   ```bash
   mosquitto_pub -t rti/ad8x/amp1/restore/command -m CHECK
   ```

4. Confirm that a one-zone dry run sends no amplifier commands:

   ```bash
   mosquitto_pub -t rti/ad8x/amp1/restore/command -m 'ZONE 1'
   ```

5. Choose an unused, powered-off zone. Set `dry_run: false`, restart the bridge,
   issue `ZONE 1`, and verify its volume, bass, treble, final source, and final
   powered-off state in Home Assistant and `bridge.log`.
6. Test `ALL` on one amplifier before enabling `automatic: true`.
7. Only after both amplifiers pass should automatic restoration be enabled.

Manual command payloads are `CHECK`, `ZONE <number>`, and `ALL`. Progress and
the final result are retained as JSON at
`rti/ad8x/<amp>/restore/status`. Each setting is paced, read back, and retried.
If calibration fails, the bridge still makes a best-effort attempt to turn the
zone off.

Automatic mode does not act merely because the bridge, VM, or Home Assistant
restarted. It acts only after the amp-wide reset signature is confirmed.

## Rollback

Stop the beta before restoring v1.8.4. On a guided Linux installation:

```bash
sudo systemctl disable --now rti-ad8x-bridge.service
```

Then restart the prior v1.8.4 service. The amplifier and MQTT broker do not need
to be reset merely because the bridge implementation changed.
