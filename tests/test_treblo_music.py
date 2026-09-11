import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import treblo_music as music


def response(value, code=200):
    result = Mock(status_code=code)
    result.json.return_value = value
    return result


class TrebloTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("sys.stdout", new=io.StringIO()))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'song.mp3'
        self.manifest = self.root / 'task.json'

    def audio(self):
        result = Mock(status_code=200)
        result.__enter__ = Mock(return_value=result)
        result.__exit__ = Mock(return_value=False)
        result.iter_content.return_value = [b'ID3test-audio']
        return result

    def run_success(self, resume=None):
        get = [response('SUCCESS'), response({'song_paths':['https://cdn.treblo.com/test.mp3']}), self.audio()]
        with patch.object(music.requests, 'post', return_value=response({'task_id':'task-123'})) as post, \
             patch.object(music.requests, 'get', side_effect=get) as fetch, \
             patch.object(music.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'audio\n','')):
            music.generate('piano alegre',self.out,'private-test-key',30,60,manifest=self.manifest,resume=resume)
            if resume: post.assert_not_called()
            else:
                self.assertEqual(post.call_args.kwargs['json']['instrumental'],True)
                self.assertEqual(post.call_args.kwargs['json']['length_range'],[30,60])
            self.assertNotIn('headers',fetch.call_args.kwargs)
        self.assertTrue(self.out.exists())
        saved = json.loads(self.manifest.read_text())
        self.assertEqual(saved['status'],'downloaded')
        self.assertNotIn('private-test-key',self.manifest.read_text())

    def test_success_download_and_task_manifest(self): self.run_success()
    def test_resume_never_posts_new_generation(self): self.run_success(resume='task-123')

    def test_invalid_ranges_never_call_api(self):
        with patch.object(music.requests,'post') as post:
            for low,high in [(31,60),(60,30),(0,301),(False,30),(30,None)]:
                with self.assertRaises(ValueError): music.generate('piano',self.out,'key',low,high)
            post.assert_not_called()

    def test_timeout_does_not_retry_creation(self):
        with patch.object(music.requests,'post',side_effect=music.requests.Timeout('secret-response')) as post:
            with self.assertRaisesRegex(RuntimeError,'Não reenviar'):
                music.generate('piano',self.out,'key',30,60,manifest=self.manifest)
            self.assertEqual(post.call_count,1)
        self.assertEqual(json.loads(self.manifest.read_text())['status'],'submitting')
        self.assertNotIn('secret-response',self.manifest.read_text())

    def test_http_errors_are_sanitized(self):
        with patch.object(music.requests,'post',return_value=response({'secret':'bad'},401)):
            with self.assertRaisesRegex(RuntimeError,'HTTP 401') as error:
                music.generate('piano',self.out,'key',30,60,manifest=self.manifest)
            self.assertNotIn('secret',str(error.exception))

    def test_untrusted_download_rejected(self):
        with patch.object(music.requests,'get',side_effect=[response('SUCCESS'),response({'song_paths':['http://127.0.0.1/secret']})]) as fetch:
            with self.assertRaisesRegex(RuntimeError,'Domínio'):
                music.generate('piano',self.out,'key',30,60,resume='task-123')
            self.assertEqual(fetch.call_count,2)

    def test_existing_audio_preserved_without_request(self):
        self.out.write_bytes(b'original')
        with patch.object(music.requests,'post') as post:
            with self.assertRaises(ValueError): music.generate('piano',self.out,'key',30,60)
            post.assert_not_called()
        self.assertEqual(self.out.read_bytes(),b'original')

    def test_invalid_audio_not_committed(self):
        with patch.object(music.requests,'get',side_effect=[response('SUCCESS'),response({'song_paths':['https://cdn.treblo.com/test.mp3']}),self.audio()]), \
             patch.object(music.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','')):
            with self.assertRaisesRegex(RuntimeError,'áudio legível'):
                music.generate('piano',self.out,'key',30,60,resume='task-123')
        self.assertFalse(self.out.exists())
        self.assertFalse(self.out.with_suffix('.mp3.part').exists())

    def test_preexisting_partial_is_not_deleted(self):
        partial = self.out.with_suffix('.mp3.part')
        partial.write_bytes(b'previous download')
        with patch.object(music.requests,'get',side_effect=[response('SUCCESS'),response({'song_paths':['https://cdn.treblo.com/test.mp3']}),self.audio()]):
            with self.assertRaises(FileExistsError):
                music.generate('piano',self.out,'key',30,60,resume='task-123')
        self.assertEqual(partial.read_bytes(),b'previous download')

    def test_connection_check_reads_only_balance(self):
        with patch.object(music.requests,'get',return_value=response({'num_credits':3,'num_credits_payg':1,'secret':'no'})), patch.object(music.requests,'post') as post:
            self.assertEqual(music.check_connection('key'),{'num_credits':3,'num_credits_payg':1})
            post.assert_not_called()

    def test_environment_key_precedence(self):
        with patch.dict(music.os.environ, {'TREBLO_API_KEY':'test-env'}):
            self.assertEqual(music.load_api_key(),'test-env')

if __name__ == '__main__': unittest.main()
