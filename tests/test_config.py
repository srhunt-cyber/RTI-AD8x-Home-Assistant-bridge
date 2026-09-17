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
            "host": "192.168.1.82",
            "zones": {1: "Kitchen", 2: "Patio", 3: "Office", 4: "Pool"},
        }],
    }


class ConfigTests(unittest.TestCase):
    def test_four_zone_amp_and_defaults(self):
        config = normalize_config(minimal_config())
        self.assertEqual(config["polling"]["interval"], 60)
        self.assertEqual(config["amps"][0]["zones"][4], "Pool")
        self.assertEqual(config["amps"][0]["sources"][8], "8")

    def test_duplicate_amp_id_is_rejected(self):
        raw = minimal_config()
        raw["amps"].append({"id": "amp1", "host": "192.168.1.61", "zones": {1: "One"}})
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

    def test_environment_expansion(self):
        content = """
schema_version: 1
mqtt:
  host: localhost
  password: ${TEST_RTI_PASSWORD}
amps:
  - id: amp1
    host: 192.168.1.82
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
