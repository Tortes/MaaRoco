import json
from pathlib import Path
import tempfile
import unittest

from validate_native_package import validate_resources


class NativePackageResourcesTest(unittest.TestCase):
    def test_missing_lazy_template_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "resource/pipeline").mkdir(parents=True)
            (root / "resource/image").mkdir()
            (root / "interface.json").write_text("{}")
            pipeline = root / "resource/pipeline/LaunchGame.json"
            pipeline.write_text(json.dumps({"Launch": {"recognition": {"type": "TemplateMatch", "param": {
                "template": ["wegame_start_button.png"]}}}}))
            errors = validate_resources(root)
            self.assertEqual(len(errors), 1)
            self.assertIn("missing template wegame_start_button.png", errors[0])
            (root / "resource/image/wegame_start_button.png").write_bytes(b"present")
            self.assertEqual(validate_resources(root), [])

    def test_missing_model_in_task_override_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tasks").mkdir()
            (root / "interface.json").write_text("{}")
            (root / "tasks/TargetPet.json").write_text(json.dumps({"option": {"model": {
                "cases": [{"pipeline_override": {"Detect": {"model": "yueya_xuexiong.onnx"}}}]}}}))
            errors = validate_resources(root)
            self.assertEqual(len(errors), 1)
            self.assertIn("missing model yueya_xuexiong.onnx", errors[0])


if __name__ == "__main__":
    unittest.main()
