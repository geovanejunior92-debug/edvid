import http.client
import json
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
import studio_server as studio


class StudioServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / "data"
        self.workspace = self.base / "projects"
        self.workspace.mkdir()
        self.app = studio.StudioApp(self.data, token="bootstrap-secret")
        self.server = studio.make_server(self.app, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.app.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, cookie=None, origin=None):
        headers = {}
        if body is not None:
            body = json.dumps(body)
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        if origin:
            headers["Origin"] = origin
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        result = json.loads(payload) if response.getheader("Content-Type", "").startswith("application/json") else payload
        headers = dict(response.getheaders())
        conn.close()
        return response.status, result, headers

    def login(self):
        status, _, headers = self.request("GET", "/?token=bootstrap-secret")
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_bootstrap_token_becomes_cookie_and_is_removed_from_location(self):
        self.assertEqual(self.request("GET", "/api/projects")[0], 401)
        status, html, headers = self.request("GET", "/?token=bootstrap-secret")
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn(b"history.replaceState", html)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.request("GET", "/api/projects", cookie=cookie)[0], 200)
        self.assertEqual(self.request("GET", "/?token=wrong")[0], 401)

    def test_project_registry_is_atomic_persistent_and_rejects_non_directories(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Aula"
        status, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        self.assertEqual(status, 201)
        self.assertTrue(project.is_dir())
        self.assertTrue((project / "edit").is_dir())
        self.assertEqual(json.loads((self.data / "projects.json").read_text())["projects"][0]["path"], str(project.resolve()))
        reopened = studio.ProjectRegistry(self.data)
        self.assertEqual(reopened.list()[0]["id"], item["id"])
        bad = self.workspace / "clip.mp4"
        bad.write_bytes(b"x")
        self.assertEqual(self.request("POST", "/api/projects", {"path": str(bad)}, cookie, origin)[0], 400)
        self.assertEqual(self.request("GET", "/api/projects/../../etc", cookie=cookie)[0], 404)

    def test_mutations_require_same_origin(self):
        cookie = self.login()
        body = {"path": str(self.workspace / "x"), "create": True}
        self.assertEqual(self.request("POST", "/api/projects", body, cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/projects", body, cookie, "http://evil.invalid")[0], 403)

    def test_probe_job_persists_and_serial_queue_runs_one_at_a_time(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Aula"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        media = project / "not-video.mp4"
        media.write_bytes(b"not a video")
        status, job, _ = self.request("POST", "/api/jobs", {"projectId": item["id"], "kind": "probe", "input": str(media)}, cookie, origin)
        self.assertEqual(status, 202)
        deadline = time.time() + 5
        while time.time() < deadline:
            jobs = self.request("GET", "/api/jobs", cookie=cookie)[1]["jobs"]
            current = next(x for x in jobs if x["id"] == job["id"])
            if current["status"] in {"failed", "completed"}:
                break
            time.sleep(0.03)
        self.assertEqual(current["status"], "failed")
        self.assertIn("ffprobe", current["error"])
        saved = json.loads((self.data / "queue.json").read_text())
        self.assertEqual(saved["jobs"][0]["id"], job["id"])

    def test_music_job_requires_explicit_credit_confirmation_and_valid_fields(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Trilha"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        valid = {"projectId": item["id"], "kind": "music", "prompt": "piano leve", "lengthMin": 30, "lengthMax": 60}
        for update in [
            {},
            {"confirmed": False},
            {"confirmed": True, "prompt": ""},
            {"confirmed": True, "lengthMin": 31},
            {"confirmed": True, "lengthMin": 60, "lengthMax": 60},
            {"confirmed": True, "lengthMax": 330},
        ]:
            status, _payload, _ = self.request("POST", "/api/jobs", {**valid, **update}, cookie, origin)
            self.assertEqual(status, 400, update)

    def test_music_direct_enqueue_requires_boolean_true_confirmation(self):
        project = self.workspace / "Confirmação estrita"
        project.mkdir()
        registry = studio.ProjectRegistry(self.base / "strict-confirm-data")
        item = registry.add(project)
        manager = studio.JobQueue(self.base / "strict-confirm-data", registry)
        self.addCleanup(manager.close)
        with self.assertRaisesRegex(ValueError, "Confirme"):
            manager.enqueue_music(item["id"], "piano", 30, 60, 1)

    def test_pipeline_dispatch_validates_source_and_builds_fixed_command(self):
        data = self.base / "pipeline-command-data"
        project = self.workspace / "Pipeline"
        project.mkdir()
        source = project / "aula.mp4"
        source.write_bytes(b"video")
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        manager = studio.JobQueue(data, registry, command_builder=lambda _job: [sys.executable, "-c", "pass"])
        self.addCleanup(manager.close)
        job = manager.enqueue_pipeline(item["id"], "transcribe", {"source": str(source), "language": "pt"})
        command = manager._build_command(job)
        self.assertEqual(command[:5], [sys.executable, str(Path(studio.__file__).with_name("studio_pipeline.py")),
                                      "--root", str(project.resolve()), "--action"])
        self.assertEqual(command[5:9], ["transcribe", "--source", "aula.mp4", "--language"])
        self.assertEqual(command[9:], ["pt", "--model", "large-v3-turbo"])
        self.assertNotIn("shell", " ".join(command))
        with self.assertRaisesRegex(ValueError, "dentro do projeto"):
            manager.enqueue_pipeline(item["id"], "transcribe", {"source": "/etc/passwd", "language": "pt"})
        with self.assertRaisesRegex(ValueError, "Ação"):
            manager.enqueue_pipeline(item["id"], "publish", {})

    def test_pipeline_approval_requires_displayed_revision_hash_and_explicit_true(self):
        data = self.base / "pipeline-approval-data"
        project = self.workspace / "Approval"
        project.mkdir()
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        manager = studio.JobQueue(data, registry, command_builder=lambda _job: [sys.executable, "-c", "pass"])
        self.addCleanup(manager.close)
        base = {"revision": 2, "planHash": "a" * 64}
        for update in [{}, {"approve": 1}, {"approve": True, "revision": 0}, {"approve": True, "planHash": "bad"}]:
            with self.assertRaises(ValueError, msg=update):
                manager.enqueue_pipeline(item["id"], "approve-plan", {**base, **update})
        job = manager.enqueue_pipeline(item["id"], "approve-plan", {**base, "approve": True})
        command = manager._build_command(job)
        self.assertEqual(command[-5:], ["--revision", "2", "--plan-hash", "a" * 64, "--approve"])

    def test_pipeline_job_captures_structured_result_and_blocks_duplicate_project_write(self):
        data = self.base / "pipeline-result-data"
        project = self.workspace / "Structured"
        project.mkdir()
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        source = project / "source.mp4"; source.write_bytes(b"x")
        command = [sys.executable, "-c", "import json,time; time.sleep(.2); print(json.dumps({'revision':3,'planHash':'abc','ranges':[]}))"]
        manager = studio.JobQueue(data, registry, command_builder=lambda _job: command)
        self.addCleanup(manager.close)
        first = manager.enqueue_pipeline(item["id"], "propose-cut", {"source": str(source)})
        with self.assertRaisesRegex(ValueError, "já tem uma ação"):
            manager.enqueue_pipeline(item["id"], "undo", {})
        deadline = time.time() + 5
        while time.time() < deadline and manager.get(first["id"])["status"] not in manager.FINAL:
            time.sleep(0.03)
        self.assertEqual(manager.get(first["id"])["result"], {"revision": 3, "planHash": "abc", "ranges": []})

    def test_pipeline_api_never_autoapproves_or_renders(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "API Pipeline"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        status, payload, _ = self.request("POST", "/api/jobs", {
            "projectId": item["id"], "kind": "pipeline", "action": "approve-plan",
            "revision": 1, "planHash": "b" * 64}, cookie, origin)
        self.assertEqual(status, 400)
        self.assertNotIn("approve", [job.get("action") for job in self.app.queue.list()])
        self.assertFalse((project / "edit" / "studio-pipeline" / "state.json").exists())

    def test_pipeline_status_reads_project_state_without_enqueuing_work(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Status Pipeline"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        state_path = project / "edit" / "studio-pipeline" / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text('{"version":1,"history":[{"action":"propose-cut","ok":true,"revision":2}]}')
        before = len(self.app.queue.list())
        status, payload, _ = self.request("GET", f"/api/pipeline/{item['id']}", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"]["history"][0]["revision"], 2)
        self.assertEqual(len(self.app.queue.list()), before)

    def test_music_provider_reports_configuration_without_exposing_key(self):
        cookie = self.login()
        with patch.object(studio.treblo_music, "load_api_key", return_value="top-secret"):
            status, payload, _ = self.request("GET", "/api/providers/treblo", cookie=cookie)
        self.assertEqual((status, payload), (200, {"configured": True}))
        self.assertNotIn("top-secret", json.dumps(payload))
        with patch.object(studio.treblo_music, "load_api_key", side_effect=RuntimeError("missing top-secret")):
            status, payload, _ = self.request("GET", "/api/providers/treblo", cookie=cookie)
        self.assertEqual((status, payload), (200, {"configured": False}))

    def test_music_enqueue_rejects_missing_local_configuration(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Sem chave"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        with patch.object(studio.treblo_music, "load_api_key", side_effect=RuntimeError("secret path")):
            status, payload, _ = self.request("POST", "/api/jobs", {
                "projectId": item["id"], "kind": "music", "prompt": "piano", "lengthMin": 30,
                "lengthMax": 60, "confirmed": True}, cookie, origin)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "A Treblo ainda não está configurada neste computador.")
        self.assertNotIn("secret path", json.dumps(payload))

    def test_music_connection_check_returns_only_safe_balance_fields(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        with patch.object(studio.treblo_music, "load_api_key", return_value="hidden-key"), \
             patch.object(studio.treblo_music, "check_connection", return_value={
                 "num_credits": 12, "num_credits_payg": 3, "token": "must-not-leak"}):
            status, payload, _ = self.request("POST", "/api/providers/treblo/check", {}, cookie, origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"authenticated": True, "balance": {"num_credits": 12, "num_credits_payg": 3}})
        self.assertNotIn("hidden-key", json.dumps(payload))
        self.assertNotIn("must-not-leak", json.dumps(payload))

    def test_music_command_has_manifest_and_no_secret_argument(self):
        data = self.base / "music-command-data"
        project = self.workspace / "Command"
        project.mkdir()
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        manager = studio.JobQueue(data, registry, command_builder=lambda _job: [sys.executable, "-c", "pass"])
        self.addCleanup(manager.close)
        with patch.object(studio.treblo_music, "load_api_key", return_value="never-on-command-line"):
            job = manager.enqueue_music(item["id"], "violão calmo", 30, 90, True)
        command = manager._build_command(job)
        self.assertEqual(command[:3], [sys.executable, str(Path(studio.__file__).with_name("treblo_music.py")), "violão calmo"])
        self.assertEqual(command[command.index("--length-min") + 1], "30")
        self.assertEqual(command[command.index("--length-max") + 1], "90")
        self.assertEqual(command[command.index("--manifest") + 1], job["manifest"])
        self.assertEqual(command[command.index("-o") + 1], job["output"])
        self.assertNotIn("never-on-command-line", command)
        self.assertTrue(Path(job["output"]).is_relative_to(project.resolve() / "edit" / "music"))

    def test_music_job_completes_with_audio_and_manifest_metadata(self):
        data = self.base / "music-fake-data"
        project = self.workspace / "Fake Music"
        project.mkdir()
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        def fake_command(job):
            script = ("from pathlib import Path; import json,sys; "
                      "Path(sys.argv[1]).write_bytes(b'ID3fake'); "
                      "Path(sys.argv[2]).write_text(json.dumps({'task_id':'task-123','status':'SUCCESS'}))")
            return [sys.executable, "-c", script, job["output"], job["manifest"]]
        manager = studio.JobQueue(data, registry, command_builder=fake_command)
        self.addCleanup(manager.close)
        with patch.object(studio.treblo_music, "load_api_key", return_value="configured"):
            job = manager.enqueue_music(item["id"], "cordas discretas", 30, 60, True)
        deadline = time.time() + 5
        while time.time() < deadline and manager.get(job["id"])["status"] not in manager.FINAL:
            time.sleep(0.03)
        finished = manager.get(job["id"])
        self.assertEqual(finished["status"], "completed", finished.get("error"))
        self.assertEqual(Path(finished["output"]).read_bytes(), b"ID3fake")
        self.assertEqual(finished["provider"], {"taskId": "task-123", "status": "SUCCESS"})

    def test_music_manifest_survives_restart_without_replaying_job(self):
        data = self.base / "music-restart-data"
        project = self.workspace / "Restart Music"
        project.mkdir()
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        manifest = project / "edit" / "music" / "existing.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"task_id":"remote-existing","status":"PROCESSING"}')
        state = {"version": 1, "jobs": [{"id": "music-before-restart", "projectId": item["id"], "kind": "music",
                 "prompt": "ambient", "lengthMin": 30, "lengthMax": 60, "manifest": str(manifest),
                 "output": str(manifest.with_suffix(".mp3")), "status": "running", "createdAt": 1, "updatedAt": 1}]}
        studio.atomic_json(data / "queue.json", state)
        manager = studio.JobQueue(data, registry, command_builder=lambda _job: self.fail("job replayed"))
        self.addCleanup(manager.close)
        restored = manager.get("music-before-restart")
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["provider"], {"taskId": "remote-existing", "status": "PROCESSING"})

    def test_cancelled_music_preserves_downloaded_output_and_manifest(self):
        data = self.base / "music-cancel-data"
        project = self.workspace / "Cancelled Music"
        project.mkdir()
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        def command(job):
            script = ("from pathlib import Path; import json,sys,time; "
                      "Path(sys.argv[1]).write_bytes(b'ID3paid'); "
                      "Path(sys.argv[2]).write_text(json.dumps({'task_id':'paid-1','status':'downloaded','output':sys.argv[1]})); time.sleep(30)")
            return [sys.executable, "-c", script, job["output"], job["manifest"]]
        manager = studio.JobQueue(data, registry, command_builder=command)
        self.addCleanup(manager.close)
        with patch.object(studio.treblo_music, "load_api_key", return_value="configured"):
            job = manager.enqueue_music(item["id"], "piano", 30, 60, True)
        output = Path(job["output"]); manifest = Path(job["manifest"])
        deadline = time.time() + 3
        while time.time() < deadline and not (output.exists() and manifest.exists()):
            time.sleep(0.02)
        self.assertTrue(manager.cancel(job["id"]))
        deadline = time.time() + 3
        while time.time() < deadline and manager.get(job["id"])["status"] != "cancelled":
            time.sleep(0.02)
        self.assertEqual(output.read_bytes(), b"ID3paid")
        self.assertTrue(manifest.is_file())

    def test_cancel_running_job_and_restart_marks_running_interrupted(self):
        data = self.base / "queue-data"
        project = self.workspace / "Aula"
        project.mkdir()
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        manager = studio.JobQueue(data, registry, command_builder=lambda _: [sys.executable, "-c", "import time; time.sleep(30)"])
        (project / "input.mp4").write_bytes(b"test")
        job = manager.enqueue(item["id"], "probe", project / "input.mp4")
        deadline = time.time() + 3
        while time.time() < deadline and manager.process is None:
            time.sleep(0.02)
        self.assertIsNotNone(manager.process)
        self.assertTrue(manager.cancel(job["id"]))
        deadline = time.time() + 3
        while time.time() < deadline and manager.get(job["id"])["status"] != "cancelled":
            time.sleep(0.02)
        self.assertEqual(manager.get(job["id"])["status"], "cancelled")
        manager.close()
        queued = {**job, "id": "queued-before-restart", "status": "queued"}
        state = {"version": 1, "jobs": [{**job, "status": "running"}, queued]}
        studio.atomic_json(data / "queue.json", state)
        restarted = studio.JobQueue(data, registry)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.get(job["id"])["status"], "interrupted")
        self.assertEqual(restarted.get(queued["id"])["status"], "interrupted")

    def test_cancel_kills_pipeline_descendants(self):
        data = self.base / "process-group-data"
        project = self.workspace / "Process Group"
        project.mkdir()
        marker = project / "child-survived"
        ready = project / "child-started"
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        child = f"import time; from pathlib import Path; time.sleep(.8); Path({str(marker)!r}).write_text('alive')"
        parent = f"import subprocess,sys,time; from pathlib import Path; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); Path({str(ready)!r}).write_text('ready'); time.sleep(30)"
        manager = studio.JobQueue(data, registry, command_builder=lambda _job: [sys.executable, "-c", parent, child])
        self.addCleanup(manager.close)
        source = project / "source.mp4"; source.write_bytes(b"x")
        job = manager.enqueue(item["id"], "probe", source)
        deadline = time.time() + 3
        while time.time() < deadline and not ready.exists():
            time.sleep(0.02)
        self.assertTrue(ready.exists())
        self.assertTrue(manager.cancel(job["id"]))
        time.sleep(1.1)
        self.assertFalse(marker.exists(), "o subprocesso filho continuou após o cancelamento")

    def test_cancel_kills_descendants_after_group_leader_exits(self):
        data = self.base / "exited-leader-data"
        project = self.workspace / "Exited Leader"
        project.mkdir()
        marker = project / "orphan-survived"
        ready = project / "orphan-started"
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        child = f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).write_text('alive')"
        leader = f"import subprocess,sys; from pathlib import Path; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); Path({str(ready)!r}).write_text('ready')"
        manager = studio.JobQueue(data, registry, command_builder=lambda _job: [sys.executable, "-c", leader, child])
        self.addCleanup(manager.close)
        source = project / "source.mp4"; source.write_bytes(b"x")
        job = manager.enqueue(item["id"], "probe", source)
        deadline = time.time() + 3
        while time.time() < deadline and (not ready.exists() or manager.process is None or manager.process.poll() is None):
            time.sleep(0.02)
        self.assertIsNotNone(manager.process)
        self.assertIsNotNone(manager.process.poll(), "o líder do grupo ainda não encerrou")
        self.assertTrue(manager.cancel(job["id"]))
        time.sleep(1.2)
        self.assertFalse(marker.exists(), "o descendente órfão continuou após o cancelamento")

    def test_failed_partial_cleanup_does_not_kill_queue_worker(self):
        data = self.base / "cleanup-data"
        project = self.workspace / "Cleanup"
        project.mkdir()
        first_input = project / "first.mp4"; first_input.write_bytes(b"x")
        second_input = project / "second.mp4"; second_input.write_bytes(b"x")
        calls = 0
        def commands(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                output = project / "edit" / "proxies" / "partial.mp4"
                output.parent.mkdir(parents=True, exist_ok=True)
                job["output"] = str(output)
                return [sys.executable, "-c", f"from pathlib import Path; Path({str(output)!r}).write_bytes(b'x'); raise SystemExit(1)"]
            return [sys.executable, "-c", 'print(\'{"format":{"duration":"1"}}\')']
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        manager = studio.JobQueue(data, registry, command_builder=commands)
        self.addCleanup(manager.close)
        with patch.object(Path, "unlink", side_effect=PermissionError("cleanup denied")):
            first = manager.enqueue(item["id"], "proxy", first_input)
            deadline = time.time() + 5
            while time.time() < deadline and "cleanupError" not in manager.get(first["id"]):
                time.sleep(0.03)
        self.assertIn("cleanup denied", manager.get(first["id"])["cleanupError"])
        second = manager.enqueue(item["id"], "probe", second_input)
        deadline = time.time() + 5
        while time.time() < deadline and manager.get(second["id"])["status"] not in manager.FINAL:
            time.sleep(0.03)
        self.assertEqual(manager.get(second["id"])["status"], "completed")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_proxy_job_writes_separate_playable_file(self):
        data = self.base / "proxy-data"
        project = self.workspace / "Proxy"
        project.mkdir()
        source = project / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=0.2",
                        "-an", "-c:v", "libx264", "-y", str(source)], check=True)
        registry = studio.ProjectRegistry(data)
        item = registry.add(project)
        manager = studio.JobQueue(data, registry)
        self.addCleanup(manager.close)
        job = manager.enqueue(item["id"], "proxy", source)
        deadline = time.time() + 10
        while time.time() < deadline and manager.get(job["id"])["status"] not in manager.FINAL:
            time.sleep(0.03)
        finished = manager.get(job["id"])
        self.assertEqual(finished["status"], "completed", finished.get("error"))
        output = Path(finished["output"])
        self.assertTrue(output.is_file())
        self.assertNotEqual(output, source)
        duration = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)])
        self.assertGreater(float(duration), 0)

    def test_editor_mount_serves_existing_preview_with_scoped_asset_paths(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Aula"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        (project / "edit" / "state.json").write_text('{"project":"Aula"}')
        status, html, _ = self.request("GET", f"/editor/{item['id']}/", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(f"/editor/{item['id']}/assets/app.js".encode(), html)
        self.assertEqual(self.request("GET", f"/editor/{item['id']}/api/state", cookie=cookie)[1]["state"]["project"], "Aula")
        self.assertEqual(self.request("GET", "/editor/not-an-id/media/../../etc/passwd", cookie=cookie)[0], 404)

    def test_editor_media_candidates_and_relink_use_its_project_library(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Aula"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        edit = project / "edit"
        (edit / "state.json").write_text('{"project":"Aula","video":"missing.mp4"}')
        source = project / "source.mp4"
        source.write_bytes(b"original")
        status, payload, _ = self.request("GET", f"/editor/{item['id']}/api/media-candidates", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(str(source.resolve()), [x["path"] for x in payload["files"]])
        with patch.object(studio.preview_server, "probe_duration", return_value=1):
            status, payload, _ = self.request("POST", f"/editor/{item['id']}/api/relink",
                                              {"field": "video", "path": str(source)}, cookie, origin)
        self.assertEqual(status, 200, payload)
        saved = json.loads((edit / "state.json").read_text())
        self.assertEqual((edit / saved["video"]).read_bytes(), b"original")

    def test_raw_media_route_stays_inside_selected_project(self):
        cookie = self.login()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        project = self.workspace / "Aula"
        _, item, _ = self.request("POST", "/api/projects", {"path": str(project), "create": True}, cookie, origin)
        source = project / "source.mp4"
        source.write_bytes(b"safe-media")
        path = f"/project-media/{item['id']}?path={source}"
        self.assertEqual(self.request("GET", path, cookie=cookie)[:2], (200, b"safe-media"))
        self.assertEqual(self.request("GET", f"/project-media/{item['id']}?path=/etc/passwd", cookie=cookie)[0], 400)


class StudioProcessTests(unittest.TestCase):
    def test_pipeline_ui_selects_latest_job_for_current_project_only(self):
        script = Path(__file__).resolve().parents[1] / "assets" / "studio" / "pipeline.js"
        program = f"""const model=require({json.dumps(str(script))});
const jobs=[{{id:'other',kind:'pipeline',projectId:'b'}},{{id:'mine',kind:'pipeline',projectId:'a'}}];
console.log(model.latestJobForProject(jobs,'a').id);"""
        run = subprocess.run(["node", "-e", program], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), "mine")

    def test_first_stdout_line_is_json_url_and_sigterm_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(__file__).resolve().parents[1] / "helpers" / "studio_server.py"
            process = subprocess.Popen([sys.executable, str(script), "--port", "0", "--data-dir", directory],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                line = process.stdout.readline()
                payload = json.loads(line)
                self.assertRegex(payload["url"], r"^http://127\.0\.0\.1:\d+/\?token=.+$")
                process.terminate()
                _stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
