RTI AD-8x MQTT Bridge & Sonos Integration for Home Assistant

✅ Project Overview
This project replaces legacy control apps with a modern, unified Home Assistant (HA) interface. It integrates two RTI AD-8x amplifiers (16 zones), multiple Sonos players (including two Sonos Ports as inputs), and Amazon Alexa into a single, seamless multi-room music control system. The result is a fast, intuitive, source-first system that lets you start music quickly, distribute it to any combination of RTI zones, and control everything by phone or voice.

✨ Key Features

Full RTI Zone Control — Power, Mute, Source, Volume, Bass, Treble for all 16 zones.

Dynamic Sonos Favorites — Script auto-scans all Sonos favorites (stations/playlists) and populates a touch-friendly dropdown in HA.

Complete Alexa Voice Control — On/off and safe, clamped volume via virtual template lights (e.g., “Alexa, set Kitchen Speakers to 50 percent”).

MQTT Auto-Discovery — Bridge publishes RTI entities so HA picks them up automatically.

Responsive, Optimistic UI — Dashboards update instantly; commands don’t wait for amp confirmation to render.

Discrete Commands — volume_up/down, bass_up/down, treble_up/down for snappy button behavior.

Global “All Off” — One command powers down all 16 zones.

Robust Connection — “Fail-fast” behavior with automatic reconnects and retries.

Network Failover — The bridge now detects amp network failures after 3 consecutive missed polls and publishes a "down" message, enabling external automations to power cycle the network switch.

Tone Controls & Latency
On the AD-8x, Bass/Treble apply more slowly than Volume. They’re ideal for occasional tuning, not constant adjustment. Rapid taps can queue; prefer small, deliberate changes. (Optional bridge tweak: rate-limit/coalesce tone commands to keep things snappy.)

🧱 System Requirements
Hardware

2 × RTI AD-8x amplifiers (Ethernet)

2 × Sonos Port → Amp1 Inputs 1 & 2

Additional Sonos speakers (for grouping)

Amazon Echo devices

Software

Host VM (Ubuntu 24.04, rtipoll.local) — Mosquitto MQTT + Python bridge (systemd service)

Home Assistant (HAOS on separate VM, homeassistant.local)

MQTT Integration

Pyscript Integration (via HACS)

Home Assistant Cloud (Nabu Casa) for Alexa

🚀 Quick Start
1) Ubuntu Host — Mosquitto

Bash
sudo apt update && sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
(Recommended hardening)
/etc/mosquitto/conf.d/local.conf

allow_anonymous false
password_file /etc/mosquitto/passwd
listener 1883 0.0.0.0
persistence true
persistence_location /var/lib/mosquitto/
Bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd homeassistant
sudo systemctl restart mosquitto
2) Ubuntu Host — Bridge (systemd)
/etc/systemd/system/rti-ad8x-bridge.service

[Unit]
Description=RTI AD-8x MQTT Bridge
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/rti-ad8x-bridge
Environment="MQTT_HOST=127.0.0.1" "MQTT_PORT=1883" "MQTT_USER=homeassistant" "MQTT_PASS=REDACTED"
ExecStart=/usr/bin/python3 /opt/rti-ad8x-bridge/rti_ad8x_bridge.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
Bash
sudo systemctl daemon-reload
sudo systemctl enable --now rti-ad8x-bridge
3) Home Assistant — Integrations & UI
Install HACS, then install Pyscript. Add MQTT integration and point it to the Ubuntu host. RTI entities will appear automatically.
UI prerequisite: install custom:button-card (via HACS) and add the resource: Settings → Dashboards → Resources → Add Resource

URL: /hacsfiles/button-card/button-card.js

Type: Module
4) Sonos Favorites — Helper & Automations
Add a helper:
configuration.yaml (or via UI → Helpers)

input_select:
  sonos_favorites:
    name: Sonos Favorites
    options: []
Automations (two common patterns):

Sync favorites → keeps input_select.sonos_favorites up-to-date

Play selected favorite → calls media_player.select_source on the target Sonos
(Names you can search in HA: sonos_favorites_sync and sonos_play_selected_favorite.)
5) Alexa (Nabu Casa)
Create template lights (below) for each RTI zone you want voice-controlled. In Nabu Casa → Alexa, expose those lights and Run Discovery.
Voice example: “Alexa, set Kitchen Speakers to 40 percent.”

💡 Template Lights (Safe-Clamped Volume for Alexa & iPhone)
Goal: Map HA brightness 1–254 → amp volume 5–40 (on the AD-8x scale 0–75). This keeps voice control safe and predictable. AD-8x volume range: 0–75 (not 0–79). Default clamp in examples below: 5–40. Adjust to taste per room.
configuration.yaml (excerpt)

template:
  light:
    - name: "Kitchen Speakers"
      unique_id: ad8x_amp1_kitchen_music_light
      state: "{{ is_state('switch.rti_ad_8x_amp1_kitchen_power', 'on') }}"
      # Map amp 5..40 -> HA 1..254
      level: >
        {% set v = states('number.rti_ad_8x_amp1_kitchen_volume') | float(15) %}
        {% set v = [40, [v, 5]|max]|min %}
        {{ (((v - 5) / 35) * 253 + 1) | round(0) }}
      set_level:
        # Map HA 1..254 -> amp 5..40, clamp, round
        variables:
          b: "{{ [[brightness | int, 1] | max, 254] | min }}"
          v: "{{ ((b - 1) / 253.0) * 35 + 5 }}"
        service: number.set_value
        target: { entity_id: number.rti_ad_8x_amp1_kitchen_volume }
        data: { value: "{{ [40, [v, 5]|max]|min | round(0) }}" }
      turn_on:
        - service: switch.turn_on
          target: { entity_id: switch.rti_ad_8x_amp1_kitchen_power }
        - service: number.set_value
          target: { entity_id: number.rti_ad_8x_amp1_kitchen_volume }
          data: { value: 15 }
      turn_off:
        service: switch.turn_off
        target: { entity_id: switch.rti_ad_8x_amp1_kitchen_power }
🛠️ Replicate per zone by changing the switch._power and number.volume entity IDs.

📱 Dashboards (iPhone-Optimized)

Expanded “Phone” Dashboard — Per-zone controls (Power, Source, Volume, Bass, Treble) with responsive sliders and optimistic ± buttons.

Compact “At-a-Glance” Dashboard — Single-line status for all 16 zones + Sonos favorites dropdown for fast starts.
UI prerequisites: HACS + custom:button-card (resource added as Module).

📡 MQTT API

State Topics (Bridge → MQTT)

rti/ad8x/<amp>/zone/<zone>/power → on / off

rti/ad8x/<amp>/zone/<zone>/mute → on / off

rti/ad8x/<amp>/zone/<zone>/source → 1..8

rti/ad8x/<amp>/zone/<zone>/volume → 0..75

rti/ad8x/<amp>/zone/<zone>/bass → -12..12

rti/ad8x/<amp>/zone/<zone>/treble → -12..12

rti/ad8x/<amp>/status → online / offline

rti/ad8x/bridge/status → online / offline

rti/ad8x/network_status/<amp> → down

Command Topics (MQTT → Bridge)

rti/ad8x/all/command → OFF

rti/ad8x/<amp>/zone/<zone>/set/power → on / off

rti/ad8x/<amp>/zone/<zone>/set/mute → on / off

rti/ad8x/<amp>/zone/<zone>/set/toggle_mute

rti/ad8x/<amp>/zone/<zone>/set/source → 1..8

rti/ad8x/<amp>/zone/<zone>/set/volume → 0–75

rti/ad8x/<amp>/zone/<zone>/set/bass → -12..12

rti/ad8x/<amp>/zone/<zone>/set/treble → -12..12

rti/ad8x/<amp>/zone/<zone>/set/volume_up

rti/ad8x/<amp>/zone/<zone>/set/volume_down

rti/ad8x/<amp>/zone/<zone>/set/bass_up

rti/ad8x/<amp>/zone/<zone>/set/bass_down

rti/ad8x/<amp>/zone/<zone>/set/treble_up

rti/ad8x/<amp>/zone/<zone>/set/treble_down

MQTT Discovery Prefix: homeassistant/
Example (power switch) discovery topic: homeassistant/switch/rti_ad8x/amp1_zone1_power/config
Example payload shape (abridged):

{
  "name": "Amp1 Zone1 Power",
  "unique_id": "rti_ad8x_amp1_zone1_power",
  "state_topic": "rti/ad8x/amp1/zone/1/power",
  "command_topic": "rti/ad8x/amp1/zone/1/set/power",
  "payload_on": "on",
  "payload_off": "off",
  "device": {
    "identifiers": ["rti_ad8x_amp1"],
    "manufacturer": "RTI",
    "model": "AD-8x",
    "name": "RTI AD-8x (Amp1)"
  }
}
🧩 Entity Naming Pattern

switch.rti_ad_8x_amp{1|2}{zone}power

switch.rti_ad_8x_amp{1|2}{zone}mute

number.rti_ad_8x_amp{1|2}{zone}volume

number.rti_ad_8x_amp{1|2}{zone}bass

number.rti_ad_8x_amp{1|2}{zone}_treble
Use this pattern for template lights, automations, and scripts.

🧪 Troubleshooting

No Sonos favorites? Open a Sonos media_player and confirm source_list is populated. Restart Sonos or HA if empty.

Nothing responds in HA?

Watch MQTT: mosquitto_sub -v -t 'rti/ad8x/#'

Check service: journalctl -u rti-ad8x-bridge -f

Alexa can’t find devices? Ensure template lights are exposed via Nabu Casa and run Alexa discovery again.

Network quirks (Sonos/HA/RTI): Keep them on the same VLAN; enable IGMP Snooping; avoid cross-subnet mDNS unless you’ve configured relays.

🛠️ Optional Bridge Tweaks (Quality of Life)

Tone control rate-limit/coalesce: Per-zone debounce ~200–300 ms, max ~2–4 updates/sec. Coalesce rapid ± taps into a single absolute set.

Power-aware commands (recommended): Don’t let volume/bass/treble power a zone on unintentionally.

Retry/backoff: Short, bounded retries on transient socket timeouts; mark bridge/status = offline during outages.

🗒️ Changelog (excerpt)

v1.4.0 — Network Failover: Adds logic to detect amp network freezes and publish an MQTT message for external automations to trigger a switch power cycle.

v1.1.x — iPhone-optimized dashboards noted. Template lights with safe volume clamp 5–40 (AD-8x scale 0–75). Documented tone-control latency + bridge-side smoothing suggestions. Discrete ± commands; fail-fast reconnects; global All Off.


