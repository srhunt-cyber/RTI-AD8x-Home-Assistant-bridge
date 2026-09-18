import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bridge"))

from config import ConfigError, load_config, normalize_config  # noqa: E402


def minimal_config():
    return {
        "schema_version": 1,
        "mqtt": {"host": "mqtt.local"},
        "amps": [{
            "id": "amp1",
            "host": "192.0.2.82",
            "zones": {1: "Kitchen", 2: "Patio", 3: "Office", 4: "Pool"},
        }],
    }


class ConfigTests(unittest.TestCase):
    def test_four_zone_amp_and_defaults(self):
        config = normalize_config(minimal_config())
        self.assertEqual(config["polling"]["interval"], 60)
        self.assertEqual(config["amps"][0]["zones"][4], "Pool")
        self.assertEqual(config["amps"][0]["sources"][8], "8")
        self.assertFalse(config["restoration"]["enabled"])
        self.assertTrue(config["restoration"]["dry_run"])
        self.assertEqual(config["restoration"]["defaults"]["bass"], 8)
        self.assertEqual(config["restoration"]["defaults"]["treble"], 12)
        self.assertEqual(config["home_assistant"]["entity_mode"], "dual")
        self.assertEqual(config["home_assistant"]["media_players"]["volume_min"], 5)
        self.assertEqual(config["home_assistant"]["media_players"]["volume_max"], 40)
        self.assertEqual(config["commands"]["tone_settle_delay"], 6.0)

    def test_restore_defaults_and_zone_override(self):
        raw = minimal_config()
        raw["restoration"] = {
            "enabled": True,
            "automatic": True,
            "defaults": {"volume": 20, "bass": 8, "treble": 12},
        }
        raw["amps"][0]["zones"][2] = {
            "name": "Patio",
            "defaults": {"bass": 10, "leave_powered_off": False},
        }
        config = normalize_config(raw)
        self.assertEqual(config["amps"][0]["zones"][2], "Patio")
        self.assertEqual(config["amps"][0]["zone_defaults"][2]["bass"], 10)
        self.assertFalse(
            config["amps"][0]["zone_defaults"][2]["leave_powered_off"]
        )

    def test_odd_tone_default_is_rejected(self):
        raw = minimal_config()
        raw["restoration"] = {"defaults": {"bass": 7}}
        with self.assertRaisesRegex(ConfigError, "even value"):
            normalize_config(raw)

    def test_automatic_restore_requires_enabled(self):
        raw = minimal_config()
        raw["restoration"] = {"automatic": True}
        with self.assertRaisesRegex(ConfigError, "requires"):
            normalize_config(raw)

    def test_matching_zone_requirement_is_validated_per_amp(self):
        raw = minimal_config()
        raw["restoration"] = {
            "factory_signature": {"minimum_matching_zones": 5},
        }
        with self.assertRaisesRegex(ConfigError, "exceeds"):
            normalize_config(raw)

    def test_duplicate_amp_id_is_rejected(self):
        raw = minimal_config()
        raw["amps"].append({"id": "amp1", "host": "192.0.2.61", "zones": {1: "One"}})
        with self.assertRaisesRegex(ConfigError, "Duplicate"):
            normalize_config(raw)

    def test_invalid_zone_is_rejected(self):
        raw = minimal_config()
        raw["amps"][0]["zones"] = {9: "Invalid"}
        with self.assertRaises(ConfigError):
            normalize_config(raw)

    def test_string_boolean_is_parsed(self):
        raw = minimal_config()
        raw["home_assistant"] = {"discovery": "false", "use_source_names": "yes"}
        config = normalize_config(raw)
        self.assertFalse(config["home_assistant"]["discovery"])
        self.assertTrue(config["home_assistant"]["use_source_names"])

    def test_dual_media_player_config(self):
        raw = minimal_config()
        raw["home_assistant"] = {
            "entity_mode": "dual",
            "media_players": {
                "include": ["amp1:1", "amp1:4"],
                "volume_min": 5,
                "volume_max": 40,
                "volume_step": 2,
            },
        }
        config = normalize_config(raw)
        media = config["home_assistant"]["media_players"]
        self.assertEqual(config["home_assistant"]["entity_mode"], "dual")
        self.assertEqual(media["include"], ["amp1:1", "amp1:4"])
        self.assertEqual(media["volume_step"], 2)

    def test_invalid_media_player_zone_is_rejected(self):
        raw = minimal_config()
        raw["home_assistant"] = {
            "media_players": {"include": ["amp2:1"]},
        }
        with self.assertRaisesRegex(ConfigError, "unknown zone"):
            normalize_config(raw)

    def test_invalid_media_player_volume_range_is_rejected(self):
        raw = minimal_config()
        raw["home_assistant"] = {
            "media_players": {"volume_min": 40, "volume_max": 40},
        }
        with self.assertRaisesRegex(ConfigError, "less than"):
            normalize_config(raw)

    def test_environment_expansion(self):
        content = """
schema_version: 1
mqtt:
  host: localhost
  password: ${TEST_RTI_PASSWORD}
amps:
  - id: amp1
    host: 192.0.2.82
    zones:
      1: Kitchen
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(content, encoding="utf-8")
            os.environ["TEST_RTI_PASSWORD"] = "secret"
            try:
                config = load_config(path)
            finally:
                os.environ.pop("TEST_RTI_PASSWORD", None)
        self.assertEqual(config["mqtt"]["password"], "secret")


if __name__ == "__main__":
    unittest.main()
