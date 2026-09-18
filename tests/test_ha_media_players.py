import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bridge"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from config import ConfigError, normalize_config  # noqa: E402
from generate_ha_media_players import build_package, render_package  # noqa: E402
from version import VERSION  # noqa: E402


def media_config():
    return normalize_config({
        "schema_version": 1,
        "mqtt": {"host": "mqtt.local", "base_topic": "rti/ad8x"},
        "home_assistant": {
            "entity_mode": "dual",
            "use_source_names": True,
            "media_players": {
                "include": "all",
                "volume_min": 5,
                "volume_max": 40,
                "volume_step": 1,
            },
        },
        "amps": [{
            "id": "amp1",
            "host": "192.0.2.82",
            "sources": {1: "Sonos 1", 2: "Sonos 2"},
            "zones": {1: "Kitchen", 2: "Patio"},
        }],
    })


class MediaPlayerPackageTests(unittest.TestCase):
    def test_generates_one_player_per_selected_zone(self):
        package = build_package(media_config(), ["amp1:1"])
        self.assertEqual(len(package["media_player"]), 1)
        player = package["media_player"][0]
        self.assertEqual(player["name"], "Kitchen Speakers")
        self.assertEqual(player["device_class"], "speaker")
        self.assertEqual(
            player["commands"]["volume_set"]["data"]["topic"],
            "rti/ad8x/amp1/zone/1/set/volume",
        )

    def test_safe_volume_mapping_is_embedded(self):
        package = build_package(media_config(), ["amp1:1"])
        player = package["media_player"][0]
        payload = player["commands"]["volume_set"]["data"]["payload"]
        self.assertIn("5 +", payload)
        self.assertIn("* 35", payload)
        self.assertIn("75 -", payload)

    def test_source_names_are_carried_into_helper(self):
        package = build_package(media_config(), ["amp1:1"])
        helper = package["template"][0]["sensor"][0]
        options = helper["attributes"]["options"]
        self.assertIn('"Sonos 1"', options)
        self.assertIn('"Sonos 2"', options)

    def test_rendered_package_is_valid_yaml(self):
        rendered = render_package(media_config(), ["amp1:1"])
        loaded = yaml.safe_load(rendered)
        self.assertIn("mqtt", loaded)
        self.assertIn("media_player", loaded)
        self.assertIn(f"v{VERSION}", rendered.splitlines()[0])
        self.assertNotIn("}}}", rendered)

    def test_unknown_cli_zone_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "Unknown"):
            build_package(media_config(), ["amp2:1"])


if __name__ == "__main__":
    unittest.main()
