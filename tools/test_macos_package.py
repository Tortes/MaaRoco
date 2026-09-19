import copy
import unittest
from prepare_macos import convert_actions


class MacOSKeyMappingTest(unittest.TestCase):
    def test_nested_task_overrides_and_custom_keys(self):
        data = {"option": {"skill": {"cases": [{"pipeline_override": {
            "Skill": {"action": {"type": "ClickKey", "param": {"key": 49}}},
            "Alt": {"action": "KeyDown", "key": 18},
            "Battle": {"action": {"type": "Custom", "param": {
                "custom_action": "battle_focused_key", "custom_action_param": {"key": 49}}}},
            "Chord": {"action": {"type": "ClickKey", "param": {"key": [69, 32]}}},
        }}]}}}
        source = copy.deepcopy(data)
        convert_actions(data)
        nodes = data["option"]["skill"]["cases"][0]["pipeline_override"]
        self.assertEqual(nodes["Skill"]["action"]["param"]["key"], 18)
        self.assertEqual(nodes["Alt"]["key"], 58)
        self.assertEqual(nodes["Battle"]["action"]["param"]["custom_action_param"]["key"], 49)
        self.assertEqual(nodes["Chord"]["action"]["param"]["key"], [14, 49])
        self.assertEqual(source["option"]["skill"]["cases"][0]["pipeline_override"]["Skill"]["action"]["param"]["key"], 49)

    def test_unmapped_key_fails_packaging(self):
        with self.assertRaises(ValueError):
            convert_actions({"action": {"type": "ClickKey", "param": {"key": 999}}})


if __name__ == "__main__":
    unittest.main()
