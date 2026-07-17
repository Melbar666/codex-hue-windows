from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from codex_hue import cli as INDICATOR


class FakeHueClient:
    def __init__(self):
        self.light_states = {
            "1": {
                "on": True,
                "bri": 170,
                "hue": 8000,
                "sat": 120,
                "colormode": "hs",
                "effect": "none",
            },
            "2": {"on": False, "bri": 90, "colormode": "ct", "ct": 350},
        }
        self.actions = []

    def group(self, group_id):
        return {"lights": ["1", "2"]}

    def light(self, light_id):
        return {"state": dict(self.light_states[str(light_id)])}

    def lights(self):
        return {
            light_id: {"state": dict(state)}
            for light_id, state in self.light_states.items()
        }

    def group_action(self, group_id, action):
        self.actions.append(("group", str(group_id), dict(action)))
        for state in self.light_states.values():
            state.update(action)

    def light_state(self, light_id, action):
        self.actions.append(("light", str(light_id), dict(action)))
        self.light_states[str(light_id)].update(action)


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        os.environ["CODEX_HUE_DATA_DIR"] = self.temporary.name
        config = {
            "version": 1,
            "bridge_host": "127.0.0.1",
            "bridge_port": 443,
            "certificate_sha256": "00" * 32,
            "username": "test-user",
            "group_id": "7",
            "group_name": "Office",
            "busy": dict(INDICATOR.DEFAULT_BUSY),
            "complete": dict(INDICATOR.DEFAULT_COMPLETE),
            "completion_hold_seconds": 0,
            "completion_gap_seconds": 0,
            "restore_transitiontime": 0,
            "restore_request_gap_seconds": 0,
            "stale_after_seconds": 86400,
        }
        INDICATOR.write_json_atomic(INDICATOR.config_path(), config)
        self.client = FakeHueClient()
        self.original = {
            key: dict(value) for key, value in self.client.light_states.items()
        }

    def tearDown(self):
        os.environ.pop("CODEX_HUE_DATA_DIR", None)
        os.environ.pop("CODEX_HOME", None)
        self.temporary.cleanup()

    def test_each_completion_pulses_and_last_completion_restores_room(self):
        INDICATOR.process_event("UserPromptSubmit", "session", "turn-a", self.client)
        INDICATOR.process_event("UserPromptSubmit", "session", "turn-b", self.client)

        state = INDICATOR.load_state()
        self.assertEqual(2, len(state["active"]))
        self.assertIsNotNone(state["snapshot"])

        before_first_stop = len(self.client.actions)
        INDICATOR.process_event("Stop", "session", "turn-a", self.client)
        first_stop_actions = self.client.actions[before_first_stop:]
        self.assertEqual(INDICATOR.DEFAULT_COMPLETE, first_stop_actions[0][2])
        self.assertEqual(INDICATOR.DEFAULT_BUSY, first_stop_actions[1][2])
        self.assertEqual(1, len(INDICATOR.load_state()["active"]))

        before_second_stop = len(self.client.actions)
        INDICATOR.process_event("Stop", "session", "turn-b", self.client)
        second_stop_actions = self.client.actions[before_second_stop:]
        self.assertEqual(INDICATOR.DEFAULT_COMPLETE, second_stop_actions[0][2])
        self.assertTrue(any(action[0] == "light" for action in second_stop_actions[1:]))

        state = INDICATOR.load_state()
        self.assertEqual({}, state["active"])
        self.assertIsNone(state["snapshot"])
        self.assertEqual(self.original["1"]["on"], self.client.light_states["1"]["on"])
        self.assertEqual(self.original["1"]["bri"], self.client.light_states["1"]["bri"])
        self.assertEqual(self.original["2"]["on"], self.client.light_states["2"]["on"])

    def test_duplicate_stop_does_not_pulse_twice(self):
        INDICATOR.process_event("UserPromptSubmit", "session", "turn-a", self.client)
        INDICATOR.process_event("Stop", "session", "turn-a", self.client)
        action_count = len(self.client.actions)
        INDICATOR.process_event("Stop", "session", "turn-a", self.client)
        self.assertEqual(action_count, len(self.client.actions))

    def test_stop_without_observed_start_restores_room(self):
        INDICATOR.process_event("Stop", "session", "turn-a", self.client)
        self.assertEqual(self.original["1"]["on"], self.client.light_states["1"]["on"])
        self.assertEqual(self.original["1"]["bri"], self.client.light_states["1"]["bri"])
        self.assertEqual(self.original["2"]["on"], self.client.light_states["2"]["on"])

    def test_event_queue_preserves_start_then_stop_order(self):
        INDICATOR.enqueue_event("UserPromptSubmit", "session", "turn-a")
        INDICATOR.enqueue_event("Stop", "session", "turn-a")
        queued = INDICATOR.read_json(INDICATOR.queue_path(), [])
        self.assertEqual(
            ["UserPromptSubmit", "Stop"], [item["event_name"] for item in queued]
        )

    def test_hook_outputs_valid_stop_json(self):
        payload = {
            "hook_event_name": "Stop",
            "session_id": "session",
            "turn_id": "turn-a",
        }
        output = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), mock.patch.object(
            INDICATOR, "dispatch_event"
        ) as dispatch, redirect_stdout(output):
            self.assertEqual(0, INDICATOR.hook_command())
        dispatch.assert_called_once_with("Stop", "session", "turn-a")
        self.assertEqual({"continue": True}, json.loads(output.getvalue()))

    def test_hook_install_is_idempotent_and_preserves_other_hooks(self):
        codex_home = Path(self.temporary.name) / "codex-home"
        codex_home.mkdir()
        os.environ["CODEX_HOME"] = str(codex_home)
        existing = {
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "other-tool"}]}
                ],
                "PreToolUse": [
                    {
                        "matcher": "Shell",
                        "hooks": [{"type": "command", "command": "safety-check"}],
                    }
                ],
            }
        }
        INDICATOR.write_json_atomic(INDICATOR.hooks_path(), existing)

        INDICATOR.install_hooks_command()
        INDICATOR.install_hooks_command()

        installed = INDICATOR.read_json(INDICATOR.hooks_path(), {})
        prompt_handlers = [
            handler
            for group in installed["hooks"]["UserPromptSubmit"]
            for handler in group.get("hooks", [])
        ]
        self.assertEqual(
            1, sum(INDICATOR.is_our_hook_handler(item) for item in prompt_handlers)
        )
        self.assertTrue(any(item.get("command") == "other-tool" for item in prompt_handlers))
        self.assertEqual(
            "safety-check",
            installed["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )

        INDICATOR.uninstall_hooks_command()
        uninstalled = INDICATOR.read_json(INDICATOR.hooks_path(), {})
        self.assertEqual([], uninstalled["hooks"]["Stop"])
        self.assertEqual(
            "safety-check",
            uninstalled["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )


if __name__ == "__main__":
    unittest.main()
