import json
from pathlib import Path
import subprocess
import unittest


class StudioPipelineUiTests(unittest.TestCase):
    def test_plan_model_reads_nested_edl_ranges_and_deduplicates_completed_poll(self):
        script = Path(__file__).resolve().parents[1] / "assets" / "studio" / "pipeline.js"
        program = f"""
const model = require({json.dumps(str(script))});
const plan = {{edl: {{ranges: [{{start: 1, end: 2}}, {{start: 3, end: 4}}]}}}};
const job = {{id: 'job-1', status: 'completed', updatedAt: 10}};
console.log(JSON.stringify({{
  ranges: model.planRanges(plan),
  first: model.shouldProcessJob(job, null),
  repeated: model.shouldProcessJob(job, model.jobKey(job)),
}}));
"""
        run = subprocess.run(["node", "-e", program], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["ranges"], [{"start": 1, "end": 2}, {"start": 3, "end": 4}])
        self.assertTrue(result["first"])
        self.assertFalse(result["repeated"])


if __name__ == "__main__":
    unittest.main()
