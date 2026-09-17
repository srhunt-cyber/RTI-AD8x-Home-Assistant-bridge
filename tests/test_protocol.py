import sys
import unittest
from pathlib import Path

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
        self.assertEqual(_encode_tone(7), "06")

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
