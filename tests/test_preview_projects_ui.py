import json
from pathlib import Path
import shutil
import subprocess
import unittest


class PreviewProjectsUITests(unittest.TestCase):
    def run_model(self, filename, expression):
        node = shutil.which("node")
        if not node:
            self.skipTest("node não está instalado")
        model = Path(__file__).resolve().parents[1] / "assets" / "preview" / filename
        program = f"""
const model = require({json.dumps(str(model))});
console.log(JSON.stringify({expression}));
"""
        run = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True)
        return json.loads(run.stdout)

    def test_only_one_uploaded_video_starts_automatic_cut(self):
        single, multiple = self.run_model("projects-model.js", """[
  model.automaticRequest([{id:'one'}], 'retry-key-12345678'),
  model.automaticRequest([{id:'one'},{id:'two'}], 'retry-key-12345678')
]""")
        self.assertEqual(single, {
            "mode": "automatic",
            "text": "corte automático",
            "sources": ["one"],
            "idempotencyKey": "retry-key-12345678",
        })
        self.assertIsNone(multiple)

    def test_pending_request_resumes_without_sources_query_parameter(self):
        values = self.run_model("requests-model.js", """[
  model.shouldRefreshSources('', {payload:{mode:'automatic'}}),
  model.shouldRefreshSources('', null),
  model.shouldRefreshSources('?sources=1', null)
]""")
        self.assertEqual(values, [True, False, True])


if __name__ == "__main__":
    unittest.main()
