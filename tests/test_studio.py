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
        while time.time() < deadline and manager.get(job["id"])["status"] != "running":
            time.sleep(0.02)
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
