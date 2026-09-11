import contextlib
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import transcribe
from project_health import health, operation, write_json
import preview_server as preview

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'source.mp4'
        self.video.write_bytes(b'original')
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(transcribe, '_probe_duration', return_value=1))
        self.stack.enter_context(patch.object(transcribe, 'extract_audio'))
        self.backend = self.stack.enter_context(patch.object(transcribe, 'call_whisperx', return_value={'text':'a','words':[],'language':'pt'}))
    def run_transcription(self, **params):
        return transcribe.transcribe_one(self.video, self.root / 'edit', verbose=False, **params)
    def test_reuses_identical_input(self):
        self.run_transcription(); self.run_transcription()
        self.assertEqual(self.backend.call_count, 1)
    def test_changed_content_with_same_name_size_and_mtime(self):
        self.run_transcription()
        stat = self.video.stat()
        self.video.write_bytes(b'changed!')
        os.utime(self.video, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.run_transcription()
        self.assertEqual(self.backend.call_count, 2)
    def test_model_and_language_invalidate(self):
        self.run_transcription(language='pt')
        self.run_transcription(language='en')
        self.run_transcription(language='en', model='large-v3-turbo')
        self.assertEqual(self.backend.call_count, 3)
    def test_legacy_and_invalid_cache_rebuild(self):
        p = self.root / 'edit/transcripts/source.json'; p.parent.mkdir(parents=True)
        for content in ('{}','invalid','[]'):
            p.write_text(content); self.run_transcription()
        self.assertEqual(self.backend.call_count, 3)
    def test_failed_transcription_keeps_previous_file(self):
        p = self.run_transcription(); before = p.read_bytes()
        self.video.write_bytes(b'new source')
        self.backend.side_effect = RuntimeError('test')
        with self.assertRaises(RuntimeError): self.run_transcription()
        self.assertEqual(p.read_bytes(), before)

class HealthTests(unittest.TestCase):
    def test_missing_delivered_video_is_not_initial_wait(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.assertEqual(health(root, {'phase':2, 'video':'cut.mp4'})['code'], 'missing')
            self.assertEqual(health(root, {'phase':1, 'video':'cut.mp4'})['code'], 'waiting')
            write_json(root/'edl.json', {'ranges':[]})
            self.assertEqual(health(root, {'phase':1, 'video':'cut.mp4'})['code'], 'waiting')
            write_json(root/'.preview_cache/thumbs/meta.json', {})
            self.assertEqual(health(root, {'phase':1, 'video':'cut.mp4'})['code'], 'missing')
    def test_actual_operation_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with operation(root,'Rendering'):
                self.assertEqual(health(root,{})['code'],'processing')
            self.assertEqual(health(root,{})['operation']['status'],'completed')
            with self.assertRaises(ValueError):
                with operation(root,'Rendering'): raise ValueError('test')
            self.assertEqual(health(root,{})['code'],'error')
    def test_dead_worker_is_interrupted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            write_json(root/'.processing/a.json', {'status':'running','pid':99999999,'startedAt':1})
            self.assertEqual(health(root,{})['operation']['status'],'interrupted')

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.lib=Path(self.temp.name).resolve()
        self.a=self.lib/'one/edit';self.b=self.lib/'two/edit'
        for root,name in ((self.a,'One'),(self.b,'Two')):
            write_json(root/'state.json', {'project':name,'phase':2,'video':'cut.mp4'})
        self.srv=preview.ThreadingHTTPServer(('127.0.0.1',0),preview.Handler)
        self.srv.default_root=self.a;self.srv.library=self.lib
        self.srv.projects=preview.discover_projects(self.lib,self.a)
        self.srv.recovery_lock=threading.Lock()
        self.thread=threading.Thread(target=self.srv.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
    def stop(self): self.srv.shutdown();self.srv.server_close();self.thread.join()
    def req(self,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.srv.server_port)
        c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),headers or {})
        r=c.getresponse();data=r.read();code=r.status;c.close()
        return code,json.loads(data)
    def prefix(self,root): return '/p/'+next(k for k,v in self.srv.projects.items() if v==root)
    def test_project_listing_and_independent_tabs(self):
        code,data=self.req('/api/projects');self.assertEqual(code,200);self.assertEqual(len(data['projects']),2)
        for root,name in ((self.a,'One'),(self.b,'Two'),(self.a,'One')):
            self.assertEqual(self.req(self.prefix(root)+'/api/state')[1]['state']['project'],name)
        self.req(self.prefix(self.b)+'/api/save',{'notes':[]})
        self.assertTrue((self.b/'preview_edits.json').exists());self.assertFalse((self.a/'preview_edits.json').exists())
    def test_recovery_copies_and_preserves_original_and_state_backup(self):
        source=self.lib/'restored.mp4';source.write_bytes(b'fake-video')
        with patch.object(preview,'probe_duration',return_value=10):
            code,data=self.req(self.prefix(self.a)+'/api/relink',{'field':'video','path':str(source)})
        self.assertEqual(code,200,data)
        state=json.loads((self.a/'state.json').read_text())
        self.assertEqual((self.a/state['video']).read_bytes(),source.read_bytes())
        self.assertNotEqual((self.a/state['video']).stat().st_ino,source.stat().st_ino)
        self.assertEqual(len(list((self.a/'.recovery').glob('*.json'))),1)
        self.assertEqual(json.loads((self.b/'state.json').read_text())['video'],'cut.mp4')
    def test_outside_library_and_bad_requests_rejected(self):
        self.assertEqual(self.req('/api/relink',{'field':'video','path':'/etc/passwd'})[0],400)
        self.assertEqual(self.req('/api/save',[])[0],400)
        self.assertEqual(self.req('/api/save',{}, {'Origin':'http://other.invalid'})[0],403)
        self.assertEqual(self.req('/p/unknown/api/state')[0],404)
    def test_media_candidates_and_corrupt_video_status(self):
        (self.a/'cut.mp4').write_bytes(b'bad video')
        code, data = self.req('/api/media-candidates')
        self.assertEqual(code, 200)
        self.assertTrue(any(p['name']=='one/edit/cut.mp4' for p in data['files']))
        with patch.object(preview, 'probe_duration', return_value=0):
            self.assertEqual(self.req('/api/state')[1]['health']['code'], 'error')
    def test_pending_edits_block_recovery(self):
        write_json(self.a/'preview_edits.json', {'notes':[]})
        code, data=self.req('/api/relink', {'field':'video','path':str(self.lib/'file.mp4')})
        self.assertEqual(code, 400)
        self.assertIn('ajustes', data['error'])
    def test_safe_does_not_accept_sibling_prefix(self):
        handler=object.__new__(preview.Handler)
        self.assertIsNone(handler._safe(self.a,'../edit-elsewhere/file.mp4'))

if __name__=='__main__': unittest.main()
