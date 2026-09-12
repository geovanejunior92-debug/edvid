import contextlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))

import preview_automatic as automatic
import preview_requests as requests


class FakePipeline:
    def __init__(self, root, calls):
        self.root = Path(root)
        self.calls = calls

    @contextlib.contextmanager
    def mutation_lock(self):
        self.calls.append("lock")
        try:
            yield
        finally:
            state = json.loads((self.root / 'edit' / 'state.json').read_text(encoding='utf-8'))
            self.calls.append(("unlock-message", state.get("message")))

    def transcribe(self, source, language, model):
        self.calls.append(("transcribe", source, language, model))
        return {"ok": True}

    def propose_cut(self, source):
        self.calls.append(("propose-cut", source))
        return {"ok": True, "revision": 3, "planHash": "a" * 64}

    def approve_plan(self, revision, plan_hash, approved):
        self.calls.append(("approve-plan", revision, plan_hash, approved))
        return {"ok": True}

    def render_cut(self, revision, plan_hash, preview=False):
        self.calls.append(("render-cut", revision, plan_hash, preview))
        return {"ok": True, "output": "edit/cut.mp4", "verified": True}


class AutomaticRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "Projeto"
        self.edit = self.project / "edit"
        self.edit.mkdir(parents=True)
        (self.edit / "state.json").write_text(
            json.dumps({"project": "Projeto", "phase": 1}), encoding="utf-8"
        )
        (self.project / "a.mov").write_bytes(b"a")
        (self.project / "b.mov").write_bytes(b"b")
        self.calls = []
        self.queue = automatic.AutomaticRequestQueue(
            {"test": self.edit},
            pipeline_factory=lambda root: FakePipeline(root, self.calls),
            autostart=False,
        )
        self.addCleanup(self.queue.close)

    def submit(self, source_count=1, mode="automatic"):
        ids = [item["id"] for item in requests.sources(self.edit)][:source_count]
        return requests.submit(
            self.edit,
            {"mode": mode, "text": "corte", "sources": ids},
        )

    def test_single_video_runs_full_verified_preview_pipeline(self):
        record = self.submit()

        queued = self.queue.enqueue(self.edit, record)
        self.assertEqual(queued["status"], "queued")
        self.assertTrue(self.queue.process_next())

        saved = requests.get(self.edit, record["id"])
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["result"]["revision"], 3)
        self.assertTrue(saved["result"]["verified"])
        self.assertEqual(
            self.calls,
            [
                "lock",
                ("transcribe", "a.mov", "pt", "large-v3-turbo"),
                ("propose-cut", "a.mov"),
                ("approve-plan", 3, "a" * 64, True),
                ("render-cut", 3, "a" * 64, True),
                ("unlock-message", "Corte automático pronto para revisão."),
            ],
        )
        state = json.loads((self.edit / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["message"], "Corte automático pronto para revisão.")

    def test_multiple_videos_stay_pending_for_editorial_strategy(self):
        record = self.submit(source_count=2)

        saved = self.queue.enqueue(self.edit, record)

        self.assertEqual(saved["status"], "awaiting_agent")
        self.assertIn("vários vídeos", saved["response"])
        self.assertFalse(self.queue.process_next())
        self.assertEqual(self.calls, [])

    def test_script_request_is_not_claimed_by_automatic_worker(self):
        record = self.submit(mode="script")

        saved = self.queue.enqueue(self.edit, record)

        self.assertEqual(saved["status"], "pending")
        self.assertFalse(self.queue.process_next())

    def test_restart_recovers_interrupted_automatic_request_once(self):
        record = self.submit()
        requests.update(self.edit, record["id"], status="transcribing")
        self.queue.close()

        recovered = automatic.AutomaticRequestQueue(
            {"test": self.edit},
            pipeline_factory=lambda root: FakePipeline(root, self.calls),
            autostart=False,
        )
        self.queue = recovered
        self.addCleanup(recovered.close)

        self.assertEqual(requests.get(self.edit, record["id"])["status"], "queued")
        self.assertTrue(recovered.process_next())
        self.assertFalse(recovered.process_next())
        self.assertEqual(requests.get(self.edit, record["id"])["status"], "completed")

    def test_two_queues_cannot_claim_the_same_durable_request(self):
        record = self.submit()
        first = self.queue.enqueue(self.edit, record)
        self.assertEqual(first['status'], 'queued')
        second_queue = automatic.AutomaticRequestQueue(
            {'test': self.edit},
            pipeline_factory=lambda root: FakePipeline(root, self.calls),
            autostart=False,
        )
        self.addCleanup(second_queue.close)
        self.assertFalse(second_queue.process_next())
        self.assertTrue(self.queue.process_next())
        self.assertEqual(requests.get(self.edit, record['id'])['status'], 'completed')

    def test_phase_two_project_is_never_recut_automatically(self):
        (self.edit / 'state.json').write_text(json.dumps({
            'project': 'Projeto', 'phase': 2, 'finalVideo': 'final.mp4',
        }), encoding='utf-8')
        record = self.submit()

        saved = self.queue.enqueue(self.edit, record)

        self.assertEqual(saved['status'], 'awaiting_agent')
        self.assertIn('Fase 2', saved['response'])
        self.assertFalse(self.queue.process_next())
        self.assertEqual(self.calls, [])

    def test_missing_request_does_not_kill_queue_or_block_next_job(self):
        first = self.submit()
        (self.project / 'c.mov').write_bytes(b'c')
        second = requests.submit(self.edit, {
            'mode': 'automatic', 'text': 'outro corte',
            'sources': [next(x['id'] for x in requests.sources(self.edit) if x['name'] == 'c.mov')],
        })
        self.queue.enqueue(self.edit, first)
        self.queue.enqueue(self.edit, second)
        (self.edit / 'agent-requests' / f"{first['id']}.json").unlink()

        self.assertTrue(self.queue.process_next())
        self.assertTrue(self.queue.process_next())
        self.assertEqual(requests.get(self.edit, second['id'])['status'], 'completed')

    def test_process_runner_cancels_the_whole_subprocess_group(self):
        runner = automatic.CancellableRunner()
        marker = self.project / 'child-finished'
        ready = self.project / 'child-started'
        command = [sys.executable, '-c', (
            "import pathlib,subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-c',\"import signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path({str(ready)!r}).write_text('ready');time.sleep(2);pathlib.Path({str(marker)!r}).write_text('bad')\"]); "
            "time.sleep(30)"
        )]
        result = {}
        thread = automatic.threading.Thread(
            target=lambda: result.setdefault('run', runner(command, capture_output=True, text=True)),
            daemon=True,
        )
        thread.start()
        deadline = time.time() + 3
        while (runner.pid is None or not ready.exists()) and time.time() < deadline: time.sleep(.01)
        self.assertIsNotNone(runner.pid)
        self.assertTrue(ready.exists())
        runner.cancel(); thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        time.sleep(1.2)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
