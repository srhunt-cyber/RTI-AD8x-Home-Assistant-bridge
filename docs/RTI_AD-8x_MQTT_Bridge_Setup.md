# RTI AD-8x MQTT Bridge Setup

This document outlines the setup and configuration of the `rti_ad8x_mqtt_bridge.py` script running on `rtipoll` (192.168.1.220) to bridge RTI AD-8x amplifier controls to Home Assistant (HAOS) via MQTT. The setup uses a Mosquitto broker on `rtipoll` and a systemd service for reliability.

## Overview
- **Purpose**: The script polls RTI AD-8x amplifiers (at 192.168.1.82 and 192.168.1.61) and publishes control/status messages to MQTT topics under `rti/ad8x`.
- **Target**: Home Assistant OS (HAOS) on 192.168.1.214, subscribing to the `rtipoll` MQTT broker.
- **Broker**: Runs on `rtipoll` (default `rtipoll.local` or 192.168.1.220) with no authentication (`allow_anonymous true`).

## Prerequisites
- **Hardware**: `rtipoll` (Linux-based, e.g., Debian/Ubuntu) with network access to HAOS.
- **Software**:
  - Python 3 with a virtual environment (`~/.venv`) in `~/code/rti_poll/`.
  - Required Python package: `paho-mqtt==2.1.0`.
  - Mosquitto broker installed and running on `rtipoll`.
- **Network**: Port 1883 open between `rtipoll` and HAOS.

## Installation Steps

### 1. Set Up the Virtual Environment
- Navigate to the project directory:
  ```bash
  cd ~/code/rti_poll
  Create and activate the virtual environment:
bashpython3 -m venv .venv
source .venv/bin/activate

Install dependencies:
bashpip install paho-mqtt==2.1.0


2. Configure the Script

Edit rti_ad8x_mqtt_bridge.py if needed (defaults are sufficient):

MQTT_HOST: rtipoll.local (resolves to 192.168.1.220).
MQTT_PORT: 1883.
MQTT_USER: Empty (no authentication).
MQTT_PASS: Empty (no authentication).
MQTT_BASE: rti/ad8x.
DISCOVERY_PREFIX: homeassistant.



3. Create a Systemd Service

Create the service file:
bashsudo nano /etc/systemd/system/rti-ad8x-mqtt-bridge.service

Add the following content:
ini[Unit]
Description=RTI AD-8x MQTT Bridge Service
After=network.target

[Service]
User=srhunt64
WorkingDirectory=/home/srhunt64/code/rti_poll
ExecStart=/home/srhunt64/code/rti_poll/.venv/bin/python rti_ad8x_mqtt_bridge.py
Restart=always
RestartSec=5
Environment="LOG_LEVEL=DEBUG"
Environment="MQTT_PORT=1883"
StandardOutput=append:/home/srhunt64/code/rti_poll/bridge.log
StandardError=append:/home/srhunt64/code/rti_poll/bridge.log

[Install]
WantedBy=multi-user.target

Save and exit (Ctrl+O, Enter, Ctrl+X).
Apply and start the service:
bashsudo systemctl daemon-reload
sudo systemctl enable rti-ad8x-mqtt-bridge.service
sudo systemctl start rti-ad8x-mqtt-bridge.service


4. Configure HAOS MQTT Integration

In HA, go to Settings → Devices & Services → Integrations → MQTT.
Set:

Broker: rtipoll.local (or 192.168.1.220).
Port: 1883.
Username/Password: Leave blank (no authentication).


Save and restart the integration if needed.

5. Verify the Service

Check status:
bashsudo systemctl status rti-ad8x-mqtt-bridge.service

Look for Active: active (running).


Tail the log in real-time:
bashtail -f ~/code/rti_poll/bridge.log

Expect: Connected to MQTT broker at rtipoll.local.
View last 50 lines:
bashtail -n 50 ~/code/rti_poll/bridge.log




6. Test Integration

In HA, go to Developer Tools → Services and call house_music_apply.
Check HA logs (Settings → System → Logs) for MQTT activity under rti/ad8x topics.

Troubleshooting

Connection Issues: If bridge.log shows Connection refused, ensure Mosquitto is running on rtipoll:
bashps aux | grep mosquitto

Test network: telnet rtipoll.local 1883.


Log Growth: The log appends on restart. Set up log rotation if needed:
bashsudo nano /etc/logrotate.d/rti-bridge
Add:
text/home/srhunt64/code/rti_poll/bridge.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}


Notes

The log (bridge.log) is not erased on restart due to append mode.
Adjust paths if your setup differs.
Security: Consider enabling authentication (allow_anonymous false) and setting MQTT_USER/MQTT_PASS in the service file for production use.

Credits

RTI AD-8x MQTT Bridge: Home Assistant Integration Specification
This document outlines all the features and control methods exposed by the Python MQTT bridge (v1.1.0) to Home Assistant. Use this as a reference for building dashboards and automations.

1. Global Commands
These commands affect all zones on both amplifiers simultaneously.

All Zones Off

This is the most efficient way to turn off all 16 RTI zones at once.

Method: Publish to a global MQTT topic.

Service: mqtt.publish

Topic: rti/ad8x/all/set/all_off

Payload: 1 (The payload content doesn't matter, but it cannot be empty).

Example Lovelace Button:

type: button
name: All RTI Zones Off
icon: mdi:power-off
tap_action:
  action: call-service
  service: mqtt.publish
  service_data:
    topic: rti/ad8x/all/set/all_off
    payload: '1'

2. Per-Zone Controls
These controls target a specific zone on a specific amplifier.

Entity ID Naming Scheme

All entities created by the bridge follow a consistent pattern:
{component}.rti_ad_8x_<amp_key>_<zone_name>_{feature}

<amp_key>: amp1 or amp2

<zone_name>: The slugified friendly name (e.g., great_room, moms_room)

Example: The power switch for the Kitchen on amp1 is switch.rti_ad_8x_amp1_kitchen_power.

Power

HA Component: switch

Entity ID: switch.rti_ad_8x_<amp_key>_<zone_name>_power

Control Method: Standard Home Assistant switch services.

Services:

switch.turn_on

switch.turn_off

switch.toggle

Mute

HA Component: switch

Entity ID: switch.rti_ad_8x_<amp_key>_<zone_name>_mute

Control Method: Standard Home Assistant switch services.

Services:

switch.turn_on (Mutes the zone)

switch.turn_off (Unmutes the zone)

switch.toggle

Source

HA Component: select

Entity ID: select.rti_ad_8x_<amp_key>_<zone_name>_source

Control Method: Use the select.select_option service.

Service: select.select_option

Options: "1" through "8"

Note: This command is "power-aware." The bridge will ignore it if the zone is off.

Volume (Absolute / Slider)

This method is best for sliders, where you set a specific volume level.

HA Component: number

Entity ID: number.rti_ad_8x_<amp_key>_<zone_name>_volume

Control Method: Use the number.set_value service.

Value Range: 0 to 75 (where 75 is the loudest, as inverted by the bridge).

Note: This command is "power-aware." The bridge will ignore it if the zone is off.

Volume (Steps / Buttons)

This is the recommended method for + and - buttons as it provides the most responsive "snappy" feel.

Method: Publish directly to the volume step MQTT topics.

Service: mqtt.publish

Topics:

rti/ad8x/<amp_key>/zone/<zone_num>/set/volume_up

rti/ad8x/<amp_key>/zone/<zone_num>/set/volume_down

Payload: 1 (The payload content doesn't matter, but it cannot be empty).

Note: This command is "power-aware." The bridge will ignore it if the zone is off.

Bass

HA Component: number

Entity ID: number.rti_ad_8x_<amp_key>_<zone_name>_bass

Control Method: Use the number.set_value service.

Value Range: -12 to +12, in steps of 2.

Note: This command is "power-aware." The bridge will ignore it if the zone is off.

Treble

HA Component: number

Entity ID: number.rti_ad_8x_<amp_key>_<zone_name>_treble

Control Method: Use the number.set_value service.

Value Range: -12 to +12, in steps of 2.

Note: This command is "power-aware." The bridge will ignore it if the zone is off.