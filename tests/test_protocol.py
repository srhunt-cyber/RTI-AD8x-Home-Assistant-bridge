import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bridge"))

import rti_ad8x_bridge as bridge  # noqa: E402
from rti_ad8x_bridge import _encode_tone, parse_set_topic, parse_sta, parse_tone  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_status_response(self):
        self.assertEqual(
            parse_sta("#01,1,0,08,-55"),
            {"zone": 1, "power": True, "mute": False, "source": 8, "vol_0_75": 55},
        )

    def test_tone_response(self):
        self.assertEqual(parse_tone("$07,8,12"), {"zone": 7, "bass": 8, "treble": 12})

    def test_tone_encoding_preserves_protocol_behavior(self):
        self.assertEqual(_encode_tone(12), "12")
        self.assertEqual(_encode_tone(-12), "32")
        with self.assertRaisesRegex(ValueError, "even value"):
            _encode_tone(7)

    def test_odd_live_tone_target_is_rejected(self):
        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), object())
        session._zone_states = {1: {"power": True, "bass": 8, "treble": 12}}
        self.assertFalse(session.set_bass(1, 7))
        self.assertFalse(session.set_treble(1, 11))
        self.assertNotIn("target_bass", session._zone_states[1])
        self.assertNotIn("target_treble", session._zone_states[1])

    def test_rapid_tone_buttons_accumulate_from_pending_target(self):
        class FakeTimer:
            def __init__(self, *_args, **_kwargs):
                self.alive = False
            def start(self):
                self.alive = True
            def cancel(self):
                self.alive = False
            def is_alive(self):
                return self.alive

        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), object())
        session._zone_states = {1: {"power": True, "bass": 6, "treble": 6}}
        with patch.object(bridge.threading, "Timer", FakeTimer):
            self.assertTrue(session.bass_up(1))
            self.assertTrue(session.bass_up(1))
            self.assertTrue(session.bass_up(1))
        self.assertEqual(session._zone_states[1]["target_bass"], 12)

    def test_tone_flush_sends_once_then_queries_after_settle(self):
        class FakeMqtt:
            def __init__(self):
                self.messages = []
            def publish(self, topic, payload, retain=False):
                self.messages.append((topic, payload, retain))

        mqtt = FakeMqtt()
        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), mqtt)
        session.connected = True
        session._zone_states = {1: {
            "zone": 1,
            "power": True,
            "mute": False,
            "source": 8,
            "vol_0_75": 75,
            "bass": 6,
            "treble": 12,
            "target_bass": 8,
        }}
        sent = []
        session._send_ascii = sent.append
        session._read_reply = lambda *_args: "$01,+08,+12"
        session.stop_flag.wait = lambda _seconds: False

        session._flush_tone(1, "bass", "BAS")

        self.assertEqual(sent, ["*ZN01BAS08", "*ZN01SET00"])
        self.assertNotIn("target_bass", session._zone_states[1])
        self.assertTrue(any(topic.endswith("/bass") and payload == "8"
                            for topic, payload, _ in mqtt.messages))

    def test_command_topic_respects_configured_base(self):
        original = bridge.MQTT_BASE
        bridge.MQTT_BASE = "house/audio/rti"
        try:
            self.assertEqual(
                parse_set_topic("house/audio/rti/amp1/zone/4/set/volume"),
                ("amp1", 4, "volume"),
            )
            self.assertIsNone(parse_set_topic("rti/ad8x/amp1/zone/4/set/volume"))
        finally:
            bridge.MQTT_BASE = original

    def test_media_player_mode_can_clear_legacy_discovery(self):
        class FakeClient:
            def __init__(self):
                self.messages = []

            def publish(self, topic, payload, retain=False):
                self.messages.append((topic, payload, retain))

        original_amps = bridge.AMPS
        original_zones = bridge.ZONE_NAMES
        original_metadata = bridge.AMP_METADATA
        try:
            bridge.AMPS = {"amp1": ("192.0.2.82", 23)}
            bridge.ZONE_NAMES = {"amp1": {1: "Kitchen"}}
            bridge.AMP_METADATA = {"amp1": {"zones": {1: "Kitchen"}}}
            instance = bridge.Bridge()
            fake = FakeClient()
            instance.client = fake
            instance.clear_legacy_discovery()
            self.assertEqual(len(fake.messages), 6)
            self.assertTrue(all(payload == "" for _, payload, _ in fake.messages))
            self.assertTrue(all(retain for _, _, retain in fake.messages))
        finally:
            bridge.AMPS = original_amps
            bridge.ZONE_NAMES = original_zones
            bridge.AMP_METADATA = original_metadata


if __name__ == "__main__":
    unittest.main()
