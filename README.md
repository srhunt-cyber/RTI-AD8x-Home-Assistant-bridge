RTI AD-8x MQTT Bridge & Sonos Integration for Home Assistant
Version: v1.3.0 • Status: Public beta
Highlights: Optimistic UI, corrected MQTT Discovery, fail-fast polling, power-aware commands, volume coalescing, “All Off,” tone control sliders, iPhone dashboards, Alexa voice control.
✅ Project Overview
This bridge replaces legacy control apps with a modern, unified Home Assistant (HA) interface. It integrates two RTI AD-8x amplifiers (16 zones total), Sonos (including two Sonos Ports as sources), and Amazon Alexa into one seamless multi-room audio system.
Results: a fast, intuitive, source-first UX. Start music, route it anywhere, and control it from iPhone dashboards or by voice.
✨ Features
Full Zone Control (16 zones): Power, Mute, Source (1–8), Volume (0–75), Bass (-12..12), Treble (-12..12).
Optimistic, responsive UI: HA number entities for Volume/Bass/Treble publish instantly (optimistic: true).
Volume coalescing & echo suppression: Smooth slider use without flood; reduces flicker on state echoes.
Discrete commands: volume_up/down, bass_up/down, treble_up/down for snappy buttons.
Power-aware safety: Tone/volume changes never power on a zone by accident.
Global “All Off”: One MQTT command to shut down all zones across both amps.
Corrected MQTT Discovery: Clean HA auto-discovery for switch/number/select entities.
Fail-fast polling: Robust reconnects; offline/online status topics.
Sonos Favorites integration: Pyscript populates an HA dropdown; auto-refresh on startup and every 3h.
iPhone dashboards: Expanded (per-zone detail) + At-a-Glance (all zones + favorites picker).
Alexa voice control: Template-light “safe clamp” (default 5..40 on 0–75 scale) + naming guidance to avoid NLU collisions.
Tone controls process more slowly on the AD-8x than volume. Great for occasional tuning, not constant riding. Bridge optionally rate-limits via coalescing; prefer small, deliberate changes.
🧱 Requirements
Hardware
2 × RTI AD-8x (Ethernet to the HA network, Telnet port 23)
2 × Sonos Port → Amp1 Inputs 1 & 2, plus any Sonos speakers (for grouping)
Amazon Echo devices (optional, for voice)
Software
Ubuntu 24.04 host (e.g., rtipoll.local) running Mosquitto + this bridge (systemd)
Home Assistant OS (e.g., homeassistant.local)
MQTT Integration
Pyscript (via HACS)
Home Assistant Cloud (Nabu Casa) for Alexa
(UI) HACS + custom:button-card for dashboards
🚀 Quick Start
1) MQTT broker (Ubuntu)
sudo apt update && sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
Recommended hardening
# /etc/mosquitto/conf.d/local.conf
allow_anonymous false
password_file /etc/mosquitto/passwd
listener 1883 0.0.0.0
persistence true
persistence_location /var/lib/mosquitto/
sudo mosquitto_passwd -c /etc/mosquitto/passwd homeassistant
sudo systemctl restart mosquitto
2) Bridge (Ubuntu, systemd)
Install deps (Python)
python3 -m pip install -r bridge/requirements.txt
# requirements.txt includes: paho-mqtt>=1.6.1
Systemd unit
# /etc/systemd/system/rti-ad8x-bridge.service
[Unit]
Description=RTI AD-8x MQTT Bridge
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/rti-ad8x-bridge
Environment="MQTT_HOST=rtipoll.local" "MQTT_PORT=1883" "MQTT_USER=homeassistant" "MQTT_PASS=__REDACTED__"
# Optional tuning (defaults shown):
# Environment="MQTT_BASE=rti/ad8x" "DISCOVERY_PREFIX=homeassistant"
# Environment="POLL_INTERVAL=20.0" "CONNECT_TIMEOUT=2.0" "PER_CMD_TIMEOUT=2.0"
# Environment="POST_SEND_SETTLE=0.05" "INTER_CMD_SLEEP=0.1"
# Environment="SET_RETRIES=2" "RETRY_SLEEP=0.2"
# Environment="VOL_COALESCE_SEC=0.15" "VOL_ECHO_SUPPRESS_SEC=1.0"
# Environment="DUMP_RAW_CHUNKS=0"
ExecStart=/usr/bin/python3 /opt/rti-ad8x-bridge/bridge/rti_ad8x_bridge.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
Start service
sudo systemctl daemon-reload
sudo systemctl enable --now rti-ad8x-bridge
systemctl status rti-ad8x-bridge.service --no-pager
Amp IPs & Zones are configured in the code (see AMPS and ZONE_NAMES). Adjust as needed.
3) Home Assistant
MQTT: Add the MQTT integration and point it to the Ubuntu host. Entities will appear via MQTT Discovery.
HACS + Pyscript: Install Pyscript.
UI resource: add /hacsfiles/button-card/button-card.js (type Module) under Settings → Dashboards → Resources.
Template lights (safe clamp for Alexa/iPhone)
Map HA brightness 1–254 ↔︎ amp volume 5–40 (on 0–75 scale). Example for one room:
template:
  - light:
      - name: "Zone Kitchen"  # naming avoids Alexa "room" collisions
        unique_id: ad8x_amp1_kitchen_music_light
        state: "{{ is_state('switch.rti_ad_8x_amp1_kitchen_power', 'on') }}"
        # Map amp 5..40 -> HA 1..254
        level: >
          {% set v = states('number.rti_ad_8x_amp1_kitchen_volume') | float(15) %}
          {% set v = [40, [v, 5]|max]|min %}
          {{ (((v - 5) / 35) * 253 + 1) | round(0) }}
        set_level:
          - variables:
              b: "{{ [[brightness | int, 1] | max, 254] | min }}"
              v: "{{ ((b - 1) / 253.0) * 35 + 5 }}"
          - service: number.set_value
            target: { entity_id: number.rti_ad_8x_amp1_kitchen_volume }
            data:   { value: "{{ [40, [v, 5]|max]|min | round(0) }}" }
        turn_on:
          - service: switch.turn_on
            target: { entity_id: switch.rti_ad_8x_amp1_kitchen_power }
          - service: number.set_value
            target: { entity_id: number.rti_ad_8x_amp1_kitchen_volume }
            data:   { value: 15 }
        turn_off:
          - service: switch.turn_off
            target: { entity_id: switch.rti_ad_8x_amp1_kitchen_power }
Repeat for each zone, swapping the entity IDs.
Sonos Favorites helper
input_select:
  sonos_favorites:
    name: Sonos Favorites
    options: []
Auto-refresh Sonos Favorites (startup + every 3h)
Add to automations.yaml:
# On HA start (wait until any Sonos source_list exists), then refresh
- alias: Sonos Favorites → Refresh on HA Start
  id: sonos_favorites_refresh_on_ha_start
  mode: restart
  trigger: [{ platform: homeassistant, event: start }]
  action:
    - wait_template: >
        {{ states.media_player | selectattr('attributes.source_list','defined') | list | length > 0 }}
      timeout: "00:02:00"
      continue_on_timeout: true
    - delay: "00:00:05"
    - service: pyscript.sonos_refresh_favorites_1

# Refresh every 3 hours
- alias: Sonos Favorites → Refresh every 3h
  id: sonos_favorites_refresh_every_3h
  mode: single
  trigger: [{ platform: time_pattern, hours: "/3" }]
  action:
    - service: pyscript.sonos_refresh_favorites_1
Auto-play Sonos when a zone powers on or selects Source 1/2
- alias: RTI Zone → Auto Play Sonos (power on or source→1/2)
  id: rti_zone_autoplay_sonos_power_or_source
  mode: parallel
  max: 16
  trigger:
    # A) Zone power turns on
    - platform: state
      entity_id:
        - switch.rti_ad_8x_amp1_kitchen_power
        - switch.rti_ad_8x_amp1_great_room_power
        - switch.rti_ad_8x_amp1_upper_deck_power
        - switch.rti_ad_8x_amp1_master_bed_power
        - switch.rti_ad_8x_amp1_master_bath_power
        - switch.rti_ad_8x_amp1_mom_s_room_power
        - switch.rti_ad_8x_amp1_office_power
        - switch.rti_ad_8x_amp1_craft_room_power
        - switch.rti_ad_8x_amp2_laundry_power
        - switch.rti_ad_8x_amp2_lower_bar_power
        - switch.rti_ad_8x_amp2_golf_room_power
        - switch.rti_ad_8x_amp2_lower_guest_power
        - switch.rti_ad_8x_amp2_fitness_power
        - switch.rti_ad_8x_amp2_walkout_power
        - switch.rti_ad_8x_amp2_pool_power
        - switch.rti_ad_8x_amp2_patio_power
      from: 'off'
      to: 'on'
    # B) Zone source changes to 1 or 2
    - platform: state
      entity_id:
        - select.rti_ad_8x_amp1_kitchen_source
        - select.rti_ad_8x_amp1_great_room_source
        - select.rti_ad_8x_amp1_upper_deck_source
        - select.rti_ad_8x_amp1_master_bed_source
        - select.rti_ad_8x_amp1_master_bath_source
        - select.rti_ad_8x_amp1_mom_s_room_source
        - select.rti_ad_8x_amp1_office_source
        - select.rti_ad_8x_amp1_craft_room_source
        - select.rti_ad_8x_amp2_laundry_source
        - select.rti_ad_8x_amp2_lower_bar_source
        - select.rti_ad_8x_amp2_golf_room_source
        - select.rti_ad_8x_amp2_lower_guest_source
        - select.rti_ad_8x_amp2_fitness_source
        - select.rti_ad_8x_amp2_walkout_source
        - select.rti_ad_8x_amp2_pool_source
        - select.rti_ad_8x_amp2_patio_source
      to: ['1','2']
  variables:
    source_map:
      switch.rti_ad_8x_amp1_kitchen_power: select.rti_ad_8x_amp1_kitchen_source
      switch.rti_ad_8x_amp1_great_room_power: select.rti_ad_8x_amp1_great_room_source
      switch.rti_ad_8x_amp1_upper_deck_power: select.rti_ad_8x_amp1_upper_deck_source
      switch.rti_ad_8x_amp1_master_bed_power: select.rti_ad_8x_amp1_master_bed_source
      switch.rti_ad_8x_amp1_master_bath_power: select.rti_ad_8x_amp1_master_bath_source
      switch.rti_ad_8x_amp1_mom_s_room_power: select.rti_ad_8x_amp1_mom_s_room_source
      switch.rti_ad_8x_amp1_office_power: select.rti_ad_8x_amp1_office_source
      switch.rti_ad_8x_amp1_craft_room_power: select.rti_ad_8x_amp1_craft_room_source
      switch.rti_ad_8x_amp2_laundry_power: select.rti_ad_8x_amp2_laundry_source
      switch.rti_ad_8x_amp2_lower_bar_power: select.rti_ad_8x_amp2_lower_bar_source
      switch.rti_ad_8x_amp2_golf_room_power: select.rti_ad_8x_amp2_golf_room_source
      switch.rti_ad_8x_amp2_lower_guest_power: select.rti_ad_8x_amp2_lower_guest_source
      switch.rti_ad_8x_amp2_fitness_power: select.rti_ad_8x_amp2_fitness_source
      switch.rti_ad_8x_amp2_walkout_power: select.rti_ad_8x_amp2_walkout_source
      switch.rti_ad_8x_amp2_pool_power: select.rti_ad_8x_amp2_pool_source
      switch.rti_ad_8x_amp2_patio_power: select.rti_ad_8x_amp2_patio_source
    sonos_map:
      '1': media_player.sonos_1
      '2': media_player.sonos_2
  action:
    - variables:
        target_player: >-
          {% if 'power' in trigger.entity_id %}
            {% set source_entity = source_map.get(trigger.entity_id) %}
            {% set source_num = states(source_entity) | int(0) | string %}
          {% else %}
            {% set source_num = trigger.to_state.state | int(0) | string %}
          {% endif %}
          {{ sonos_map.get(source_num) }}
    - condition: template
      value_template: "{{ target_player is not none and states(target_player) != 'playing' }}"
    - service: media_player.media_play
      target: { entity_id: "{{ target_player }}" }
📡 MQTT API
Base topics
Default MQTT base: rti/ad8x (override via MQTT_BASE)
Amp availability: rti/ad8x/<amp>/status → online / offline
Bridge availability: rti/ad8x/bridge/status → online / offline
State (published by bridge)
rti/ad8x/<amp>/zone/<z>/power → on/off
rti/ad8x/<amp>/zone/<z>/mute → on/off
rti/ad8x/<amp>/zone/<z>/source → 1..8
rti/ad8x/<amp>/zone/<z>/volume → 0..75
rti/ad8x/<amp>/zone/<z>/bass → -12..12
rti/ad8x/<amp>/zone/<z>/treble → -12..12
rti/ad8x/<amp>/zone/<z> → combined JSON snapshot (power/mute/source/volume/bass/treble)
Commands (published by clients)
rti/ad8x/<amp>/zone/<z>/set/power → on/off
rti/ad8x/<amp>/zone/<z>/set/mute → on/off/toggle
rti/ad8x/<amp>/zone/<z>/set/source → 1..8
rti/ad8x/<amp>/zone/<z>/set/volume → 0..75 (bridge coalesces bursts)
rti/ad8x/<amp>/zone/<z>/set/bass → -12..12 (rounded to even step)
rti/ad8x/<amp>/zone/<z>/set/treble → -12..12 (rounded to even step)
rti/ad8x/<amp>/zone/<z>/set/volume_up|volume_down
rti/ad8x/<amp>/zone/<z>/set/bass_up|bass_down
rti/ad8x/<amp>/zone/<z>/set/treble_up|treble_down
Global All Off: rti/ad8x/all/set/all_off → 1
Raw passthrough (advanced)
Send a raw ASCII command to an amp: rti/ad8x/<amp>/raw (payload: e.g., *ZN01STA00)
Ack/first line reply: rti/ad8x/<amp>/ack/raw
Home Assistant Discovery (prefix: homeassistant/, override via DISCOVERY_PREFIX)
Bridge auto-publishes discovery for:
switch (Power, Mute)
number (Volume/Bass/Treble; optimistic: true)
select (Source 1–8)
Note: Volume discovery includes templates (val_tpl/cmd_tpl) to normalize slider behavior. If the slider feels inverted in your theme, remove those fields in publish_discovery().
🧩 Entity Naming Pattern
switch.rti_ad_8x_amp{1|2}_{zone}_power
switch.rti_ad_8x_amp{1|2}_{zone}_mute
number.rti_ad_8x_amp{1|2}_{zone}_volume|bass|treble
select.rti_ad_8x_amp{1|2}_{zone}_source
Use these in automations, template lights, and dashboards.
📱 iPhone Dashboards
Two custom dashboards:
Expanded “Phone”: per-zone Power/Source/Volume/Bass/Treble (sliders + optimistic ± buttons).
At-a-Glance: all zones in one view + Sonos favorites dropdown.
Prereq: HACS + custom:button-card (add /hacsfiles/button-card/button-card.js as a Module resource).
🗣️ Alexa Tips (naming matters)
Avoid Alexa category words and room-first names to prevent NLU collisions:
Do: Zone Kitchen, Amp Great Room, Audio Upper Deck
Don’t: Kitchen Speakers, Kitchen Music, Kitchen Light
Keep devices out of same-named Alexa room groups while testing and set Preferred speaker = None in the room. Voice examples:
“Alexa, turn on Zone Kitchen.”
“Alexa, set Zone Kitchen to 40 percent.”
“Alexa, turn off Zone Kitchen.”
⚙️ Configuration Reference (env vars)
Var	Default	Purpose
MQTT_HOST	rtipoll.local	MQTT broker host
MQTT_PORT	1883	MQTT port
MQTT_USER/MQTT_PASS	—	MQTT auth
MQTT_BASE	rti/ad8x	Base for all topics
DISCOVERY_PREFIX	homeassistant	HA MQTT Discovery prefix
POLL_INTERVAL	20.0	Seconds between polls
CONNECT_TIMEOUT	2.0	TCP connect timeout
PER_CMD_TIMEOUT	2.0	Per-command read timeout
POST_SEND_SETTLE	0.05	Delay after send
INTER_CMD_SLEEP	0.1	Delay between commands
SET_RETRIES	2	Retries on set/confirm
RETRY_SLEEP	0.2	Delay between retries
VOL_COALESCE_SEC	0.15	Volume coalescing window
VOL_ECHO_SUPPRESS_SEC	1.0	Suppress state echo flicker
DUMP_RAW_CHUNKS	1 (on if not “0/false”)	Extra RX debug logging
🧪 Troubleshooting
No Sonos favorites? Open a Sonos media_player in HA; confirm source_list exists. Restart Sonos/HA if empty.
Nothing updates in HA?
Watch MQTT: mosquitto_sub -v -t 'rti/ad8x/#'
Bridge logs: journalctl -u rti-ad8x-bridge -f
Alexa flips room lights instead? Use function-first naming (Zone Kitchen), delete stale devices, keep out of the “Kitchen” group while testing, Preferred speaker = None.
Network quirks: Keep Bridge, Sonos, HA on the same VLAN; enable IGMP Snooping; avoid cross-subnet mDNS unless configured.
Tone feels laggy? Normal on AD-8x. Use small adjustments; burst taps may serialize.
Manual RTI poke: Publish to rti/ad8x/<amp>/raw (payload *ZN01STA00), read .../ack/raw.
🗒️ Changelog (excerpt)
v1.3.0 — 2025-09-09
Based on trusted v0.3.0 code path; reformulated with added features.
Optimistic UI for number entities (Volume/Bass/Treble).
Corrected MQTT Discovery for power & mute switches.
Fail-fast polling & robust reconnects.
Power-aware commands (no unintended power-ons).
Bass/Treble per-zone sliders; tone steps coerced to even values.
Discrete volume_up/down, bass_up/down, treble_up/down.
Global “All Off” command.
Volume coalescing + echo suppression for smooth sliders.
📜 License
MIT — see LICENSE.
Contributing / Issues
Open an Issue with logs (redact secrets) and your HA/MQTT versions. PRs welcome!
