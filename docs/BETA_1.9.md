# 1.9 beta: YAML configuration and deployment

Version `1.9.0-beta.1` is an optional test release. The stable `main` branch
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
- configuration validation before service startup.

Automatic bass/treble restoration and native Home Assistant `media_player`
entities are intentionally deferred. They change runtime behavior and should be
tested separately from this deployment refactor.

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
git clone --branch beta-v1.9.0-beta.1 \
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
Home Assistant app/add-on: download the `beta-v1.9.0-beta.1` branch source
archive, copy the
`rti_ad_series_bridge_beta` folder into Home Assistant's local apps/add-ons
directory, reload the store, and install **RTI AD-series MQTT Bridge Beta**.
Start it once; the first start creates an app configuration file and exits.
Edit that YAML in the app configuration directory, then start the app again.

The Home Assistant app expects an existing broker. With the official Mosquitto
Broker app the broker hostname is normally `core-mosquitto`. Home Assistant does
not permit one app to silently install another, so broker installation remains
an explicit administrator step.

## Rollback

Stop the beta before restoring v1.8.4. On a guided Linux installation:

```bash
sudo systemctl disable --now rti-ad8x-bridge.service
```

Then restart the prior v1.8.4 service. The amplifier and MQTT broker do not need
to be reset merely because the bridge implementation changed.
