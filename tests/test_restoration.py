import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bridge"))

import rti_ad8x_bridge as bridge  # noqa: E402
from config import normalize_config  # noqa: E402


class FakeMqtt:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))


def configured_bridge(*, dry_run=True, automatic=True):
    config = normalize_config({
        "mqtt": {"host": "mqtt.local"},
        "restoration": {
            "enabled": True,
            "automatic": automatic,
            "dry_run": dry_run,
            "confirmation_polls": 2,
            "factory_signature": {"bass": 0, "treble": 0},
            "defaults": {"volume": 20, "bass": 8, "treble": 12},
        },
        "amps": [{
            "id": "amp1",
            "host": "192.0.2.1",
            "zones": {
                1: "Kitchen",
                2: {"name": "Patio", "defaults": {"bass": 10}},
            },
        }],
    })
    bridge.configure_runtime(config)
    return config


class RestorationTests(unittest.TestCase):
    def test_volume_conversion_matches_existing_ha_scale(self):
        self.assertEqual(bridge.protocol_volume(20), 55)
        self.assertEqual(bridge.display_volume(55), 20)

    def test_zone_override_merges_with_global_defaults(self):
        configured_bridge()
        settings = bridge.restore_settings("amp1", 2)
        self.assertEqual(settings["volume"], 20)
        self.assertEqual(settings["bass"], 10)
        self.assertEqual(settings["treble"], 12)

    def test_factory_signature_can_require_every_zone(self):
        configured_bridge()
        mqtt = FakeMqtt()
        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), mqtt)
        session._zone_states = {
            1: {"bass": 0, "treble": 0, "vol_0_75": 30},
            2: {"bass": 0, "treble": 0, "vol_0_75": 30},
        }
        matching, required = session._factory_match_summary()
        self.assertEqual(matching, [1, 2])
        self.assertEqual(required, 2)
        session._zone_states[2]["bass"] = 8
        matching, required = session._factory_match_summary()
        self.assertEqual(matching, [1])
        self.assertEqual(required, 2)

    def test_two_confirmation_polls_are_required_and_dry_run_sends_nothing(self):
        configured_bridge(dry_run=True)
        mqtt = FakeMqtt()
        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), mqtt)
        session._zone_states = {
            1: {"bass": 0, "treble": 0, "vol_0_75": 30},
            2: {"bass": 0, "treble": 0, "vol_0_75": 30},
        }
        session._evaluate_automatic_restore()
        self.assertEqual(session._restore_candidate_polls, 1)
        self.assertFalse(session._restore_latched)
        session._evaluate_automatic_restore()
        self.assertTrue(session._restore_latched)
        self.assertTrue(any('"state":"dry_run"' in str(msg[1]) for msg in mqtt.messages))
        self.assertIsNone(session.sock)

    def test_manual_dry_run_never_opens_socket(self):
        configured_bridge(dry_run=True, automatic=False)
        mqtt = FakeMqtt()
        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), mqtt)
        self.assertTrue(session.restore_zones([1], reason="manual"))
        self.assertIsNone(session.sock)
        self.assertTrue(any('"state":"dry_run"' in str(msg[1]) for msg in mqtt.messages))

    def test_restore_sequence_uses_display_volume_and_safe_shutdown(self):
        configured_bridge(dry_run=False, automatic=False)
        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), FakeMqtt())
        commands = []

        def accept(zone, command, predicate, label):
            commands.append((zone, command, label))
            return True

        session._restore_command_locked = accept
        self.assertTrue(session._restore_zone_locked(1))
        self.assertEqual(
            [command for _, command, _ in commands],
            [
                "*ZN01SRC08",
                "*ZN01VOL55",
                "*ZN01BAS08",
                "*ZN01TRB12",
                "*ZN01SRC01",
                "*ZN01PWR00",
            ],
        )

    def test_failed_restore_still_attempts_power_off(self):
        configured_bridge(dry_run=False, automatic=False)
        session = bridge.AmpSession("amp1", ("192.0.2.1", 23), FakeMqtt())
        commands = []

        def fail_bass(zone, command, predicate, label):
            commands.append(command)
            return "BAS" not in command

        session._restore_command_locked = fail_bass
        self.assertFalse(session._restore_zone_locked(1))
        self.assertEqual(commands[-1], "*ZN01PWR00")


if __name__ == "__main__":
    unittest.main()
