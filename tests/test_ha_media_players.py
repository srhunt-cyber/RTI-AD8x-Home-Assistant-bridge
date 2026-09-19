import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bridge"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from config import ConfigError, normalize_config  # noqa: E402
from generate_ha_media_players import (  # noqa: E402
    build_alexa_cloud_config,
    build_package,
    render_alexa_cloud_snippet,
    render_package,
)
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
        self.assertIn('"1": "Sonos 1"', helper["state"])
        payload = package["media_player"][0]["commands"]["select_source"]["data"]["payload"]
        self.assertIn('"Sonos 1": "1"', payload)

    def test_numeric_sources_use_alexa_input_labels_and_publish_numbers(self):
        config = media_config()
        config["home_assistant"]["use_source_names"] = False
        package = build_package(config, ["amp1:1"])
        helper = package["template"][0]["sensor"][0]
        self.assertIn('"INPUT 1"', helper["attributes"]["options"])
        self.assertIn('"1": "INPUT 1"', helper["state"])
        payload = package["media_player"][0]["commands"]["select_source"]["data"]["payload"]
        self.assertIn('"INPUT 1": "1"', payload)
        self.assertIn("replace('INPUT ', '')", payload)

    def test_alexa_cloud_snippet_has_music_system_without_filters_or_names(self):
        cloud = build_alexa_cloud_config(media_config(), ["amp1:1"])
        self.assertEqual(
            cloud["alexa"]["entity_config"]["media_player.kitchen_speakers"],
            {"display_categories": "MUSIC_SYSTEM"},
        )
        self.assertNotIn("filter", cloud["alexa"])
        self.assertNotIn("name", cloud["alexa"]["entity_config"]["media_player.kitchen_speakers"])
        rendered = render_alexa_cloud_snippet(media_config(), ["amp1:1"])
        self.assertEqual(yaml.safe_load(rendered), cloud)

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
