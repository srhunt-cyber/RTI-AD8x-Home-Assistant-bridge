# RTI AD-8x MQTT Bridge & Home Assistant Integration

## ✅ Project Overview

This project replaces legacy control apps with a modern, unified Home Assistant (HA) interface. It integrates two RTI AD-8x amplifiers (16 zones) and multiple Sonos players into a single, seamless multi-room music control system.

The core of the project is a Python-based service that provides a two-way bridge between the RTI amplifiers and an MQTT broker, enabling full integration with Home Assistant via MQTT Discovery.

This repository contains the Python bridge script. The documentation below explains how to set it up and how to integrate it with other Home Assistant components like Sonos and Alexa for a complete solution.

## ✨ Key Features

* **Full RTI Zone Control:** Power, Mute, Source, Volume, Bass, & Treble for all 16 zones.
* **Home Assistant Auto-Discovery:** Bridge publishes RTI entities so HA picks them up automatically.
* **Service Health Monitoring:** Publishes bridge health stats (CPU, memory, uptime, amp connection status) to MQTT for monitoring.
* **Dynamic Sonos Favorites:** (Requires Pyscript) Auto-scans Sonos favorites and populates a dropdown in HA.
* **Complete Alexa Voice Control:** (Requires Nabu Casa) On/off and safe, clamped volume via virtual template lights.
* **Optimistic UI:** Dashboards update instantly; commands don't wait for amp confirmation.
* **Global "All Off" Command:** Listens on `rti/ad8x/all/command` for an `OFF` payload to turn all 16 zones off.
* **Robust Connection:** Detects amp network failures after 3 missed polls and publishes a "down" message for external automations.

---

## 🚀 Part 1: Bridge Installation & Setup

This section covers installing the Python bridge script on its Linux host (e.g., `rtipoll.local`).

### 1. Clone the Repository

```bash
git clone [https://github.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge.git](https://github.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge.git)
cd RTI-AD8x-Home-Assistant-bridge
```

### 2. Create a Virtual Environment

It is highly recommended to use a Python virtual environment.

```bash
# Create the virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate
```

### 3. Install Dependencies

This script requires Python packages. The `requirements.txt` file lists all dependencies.

```bash
# Install all required packages
pip install -r requirements.txt
```

Your `requirements.txt` file should contain:
```
paho-mqtt
psutil
```

### 4. Configure the Bridge

First, copy the example environment file:

```bash
cp .env.example .env
```

Now, edit the `.env` file to add your MQTT broker details:
```bash
nano .env
```
```ini
# .env
MQTT_HOST=your-broker-ip
MQTT_USER=your-mqtt-user
MQTT_PASS=your-mqtt-password
```

You must also **edit the `rti_ad8x_mqtt_bridge.py` script** to set the static IP addresses for your amplifiers in the `AMPS` dictionary at the top of the file.

### 5. Set Up the `systemd` Service

Create a `systemd` service file to keep the bridge running in the background.

```bash
sudo nano /etc/systemd/system/rti-ad8x-mqtt-bridge.service
```

Paste the following configuration. **Remember to change `YOUR_USER`** and the `WorkingDirectory`/`ExecStart` paths if you cloned the repo to a different location.

```ini
[Unit]
Description=RTI AD-8x MQTT Bridge Service
After=network-online.target

[Service]
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/RTI-AD8x-Home-Assistant-bridge
ExecStart=/home/YOUR_USER/RTI-AD8x-Home-Assistant-bridge/.venv/bin/python rti_ad8x_mqtt_bridge.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Finally, enable and start the new service:

```bash
# Reload systemd to find the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable rti-ad8x-mqtt-bridge.service

# Start the service now
sudo systemctl start rti-ad8x-mqtt-bridge.service
```

You can check the logs at any time with:
`journalctl -u rti-ad8x-mqtt-bridge.service -f`

---

## 📺 Part 2: Home Assistant Integration

Once the bridge is running, all your RTI amplifier zones will be auto-discovered in Home Assistant. These next steps integrate them with the rest of your smart home.

### 1. Bridge Health Monitoring (Sensors)

To monitor the bridge's health, add the following sensors to your Home Assistant configuration.

Add this block to your `configuration.yaml` (or a dedicated `mqtt_sensors.yaml` file):

```yaml
mqtt:
  sensor:
    # Uptime Sensor
    - unique_id: rtipoll_bridge_uptime
      name: "RTI Bridge Uptime"
      state_topic: "rti/ad8x/diagnostics/uptime_s"
      device_class: duration
      unit_of_measurement: "s"
      icon: mdi:clock-start
      value_template: "{{ value | int }}"
      
    # CPU Usage Sensor
    - unique_id: rtipoll_bridge_cpu
      name: "RTI Bridge CPU"
      state_topic: "rti/ad8x/diagnostics/cpu_usage_pct"
      unit_of_measurement: "%"
      value_template: "{{ value | float }}"
      icon: mdi:cpu-64-bit
      
    # Memory Usage Sensor
    - unique_id: rtipoll_bridge_memory
      name: "RTI Bridge Memory"
      state_topic: "rti/ad8x/diagnostics/memory_usage_mb"
      unit_of_measurement: "MB"
      value_template: "{{ value | float }}"
      icon: mdi:memory

    # Discovered Zones Count
    - unique_id: rtipoll_entity_count
      state_topic: "rti/ad8x/diagnostics/entity_count"
      unit_of_measurement: "zones"
      value_template: "{{ value | int }}"
      icon: mdi:speaker-multiple
      
    # Amp Connection Status
    - unique_id: rtipoll_controller_link
      name: "RTI Amp Connections"
      state_topic: "rti/ad8x/diagnostics/amp_connection_status"
      icon: mdi:lan
      value_template: >
        {% set amps = value_json | default({}) %}
        {% set online_count = (amps.values() | select('eq', 'online') | list | count) %}
        {{ online_count }}/{{ amps | length }} online

  binary_sensor:
    # LWT Service Status
    - unique_id: rtipoll_bridge_service_status
      name: "RTI Bridge Service Status"
      state_topic: "rti/ad8x/bridge/status"
      payload_on: "online"
      payload_off: "offline"
      device_class: connectivity
      icon: mdi:check-circle-outline
```

After adding the YAML, restart Home Assistant or **Reload the MQTT Integration** from the "Devices & Services" page.

### 2. Sonos Favorites Integration (Pyscript)

This allows you to select a Sonos favorite from a dropdown and have it play on a Sonos Port (which is connected as an input to your RTI amp).

1.  **Install Pyscript:** Go to HACS -> Integrations -> and install "Pyscript".
2.  **Create a Helper:** Create an `input_select` helper (via UI or YAML) to hold the favorites list.
    ```yaml
    input_select:
      sonos_favorites:
        name: Sonos Favorites
        options:
          - "Select a Favorite"
    ```
3.  **Create Automations:**
    * **Automation 1 (Sync Favorites):** An automation that runs `pyscript.sonos_favorites_sync` to keep the `input_select` updated.
    * **Automation 2 (Play Favorite):** An automation triggered by the `input_select` changing, which calls `media_player.select_source` on the target Sonos Port.

### 3. Alexa Voice Control (via Nabu Casa)

This creates virtual "light" entities for Alexa. It allows you to say, "Alexa, set Kitchen Speakers to 50 percent," and have it safely map that to a pre-defined volume range on the amp.

1.  **Expose Entities:** Ensure you have Home Assistant Cloud (Nabu Casa) set up.
2.  **Add Template Lights:** Add the following to your `configuration.yaml` (or a `templates.yaml` file).

```yaml
template:
  light:
    - name: "Kitchen Speakers"
      unique_id: ad8x_amp1_kitchen_music_light
      # Light is "on" if the amp zone is on
      state: "{{ is_state('switch.kitchen_power', 'on') }}"
      
      # Map amp volume 5..40 -> HA brightness 1..254
      level: >
        {% set v = states('number.kitchen_volume') | float(15) %}
        {% set v = [40, [v, 5]|max]|min %}
        {{ (((v - 5) / 35) * 253 + 1) | round(0) }}
        
      # Map HA brightness 1..254 -> amp volume 5..40
      set_level:
        variables:
          b: "{{ [[brightness | int, 1] | max, 254] | min }}"
          v: "{{ ((b - 1) / 253.0) * 35 + 5 }}"
        service: number.set_value
        target: { entity_id: number.kitchen_volume }
        data: { value: "{{ [40, [v, 5]|max]|min | round(0) }}" }
        
      # What to do on "Alexa, turn on Kitchen Speakers"
      turn_on:
        - service: switch.turn_on
          target: { entity_id: switch.kitchen_power }
        # Set a default volume when turning on
        - service: number.set_value
          target: { entity_id: number.kitchen_volume }
          data: { value: 15 }
          
      # What to do on "Alexa, turn off Kitchen Speakers"
      turn_off:
        service: switch.turn_off
        target: { entity_id: switch.kitchen_power }

    # --- REPEAT FOR OTHER ZONES ---
    # - name: "Great Room Speakers"
    #   unique_id: ad8x_amp1_great_room_music_light
    #   state: "{{ is_state('switch.great_room_power', 'on') }}"
    #   ...
```
*Note: You must replace `switch.kitchen_power` and `number.kitchen_volume` with the actual entity IDs created by the bridge.*

3.  **Expose & Discover:** In Nabu Casa settings, expose these new `light.kitchen_speakers` entities to Alexa. Ask Alexa to "Discover devices."

### 4. Dashboard UI Dependencies

The dashboards shown in this project's screenshots rely on the `custom:button-card` plugin.

* **Install:** Go to HACS -> Frontend -> and install "Button Card".
* **Add Resource:** Go to Settings → Dashboards → More Options (⋮) → Resources → Add Resource.
    * URL: `/hacsfiles/button-card/button-card.js`
    * Type: `JavaScript Module`

---

## 🧪 Troubleshooting

**Symptom:** The service fails to start, and `journalctl -u rti-ad8x-mqtt-bridge.service` shows `-- No entries --`.

**Cause:** This almost always means a Python error is happening on import, before logging is set up. The most common cause is a missing dependency (like `psutil`).

**Fix:**
1.  Stop the service: `sudo systemctl stop rti-ad8x-mqtt-bridge.service`
2.  Go to the script directory: `cd /home/YOUR_USER/RTI-AD8x-Home-Assistant-bridge`
3.  Activate the virtual environment: `source .venv/bin/activate`
4.  Install dependencies: `pip install -r requirements.txt`
5.  Test run it manually: `python rti_ad8x_mqtt_bridge.py`
6.  If it runs, `CTRL+C` and restart the service: `sudo systemctl start rti-ad8x-mqtt-bridge.service`

**Symptom:** Nothing responds in Home Assistant.

**Fix:**
1.  Watch MQTT traffic on your broker host: `mosquitto_sub -v -t 'rti/ad8x/#'`
2.  Check the service log: `journalctl -u rti-ad8x-mqtt-bridge.service -f`

**Symptom:** Alexa can’t find devices.

**Fix:** Ensure the `light.kitchen_speakers` entities are exposed via Nabu Casa and run an Alexa discovery again.
