"""A ponte do Edits leva o corte exato e traz de volta só o que mudou.

Roda contra um Edits de mentira, que imita o que o app real fez no teste de
09/11/2026: bordas arredondadas para o quadro e clipe novo no fim da trilha.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import edits_bridge as eb
import edits_mcp_proxy as proxy


class FakeEdits:
    DURATION = 12.0

    def __init__(self, rate=30, fail_on=None):
        self.rate, self.fail_on = rate, fail_on
        self.elements, self.calls, self.next_id = [], [], 0

    def snap(self, seconds):
        return round(seconds * self.rate) / self.rate

    def relay(self):
        cursor = 0.0
        for e in self.elements:
            e['startTime'] = cursor
            cursor += e['sourceOutPoint'] - e['sourceInPoint']
            e['endTime'] = cursor

    def tool(self, name, /, **args):
        self.calls.append((name, args))
        if name == self.fail_on:
            raise eb.EditsError(f'{name}: falhou')
        if name == 'newProject':
            return {'id': 'P1'}
        if name == 'importToMediaPanel':
            return {'aliasIds': [f'alias-{Path(args["path"]).stem}']}
        if name == 'addMediaPanelItemsToTimeline':
            self.next_id += 1
            element = {'id': f'e{self.next_id}', 'aliasId': args['aliasIds'][0],
                       'trackType': 'video', 'sourceMediaType': 'video', 'speed': 1,
                       'sourceInPoint': 0.0, 'sourceOutPoint': self.DURATION}
            self.elements.append(element)
            self.relay()
            return {'added': [{'id': element['id'], 'duration': self.DURATION}]}
        if name == 'trim':
            element = next(e for e in self.elements if e['id'] == args['id'])
            if args['side'] == 'left':
                element['sourceInPoint'] = self.snap(
                    element['sourceInPoint'] + args['deltaSeconds'])
            else:
                element['sourceOutPoint'] = self.snap(
                    element['sourceOutPoint'] - args['deltaSeconds'])
            self.relay()
            return {}
        if name == 'reorderClip':
            element = next(e for e in self.elements if e['id'] == args['id'])
            self.elements.remove(element)
            self.elements.insert(args['position'], element)
            self.relay()
            return {}
        if name == 'elements':
            return {'elements': [dict(e) for e in self.elements]}
        return {}


class EditsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.source = self.tmp / 'fonte.mp4'
        self.source.write_bytes(b'video')
        self.edit = self.tmp / 'projeto' / 'edit'
        self.edit.mkdir(parents=True)
        self.edl = {'sources': {'A': str(self.source)},
                    'ranges': [{'source': 'A', 'start': 2.013, 'end': 5.021, 'beat': 'um'},
                               {'source': 'A', 'start': 7.0, 'end': 9.0, 'beat': 'dois'}],
                    'grade': 'neutral', 'jcut': {'lead': 0.2}}
        (self.edit / 'edl.json').write_text(json.dumps(self.edl))
        movies = mock.patch.object(eb, 'MOVIES', self.tmp / 'Movies')
        movies.start()
        self.addCleanup(movies.stop)
        info = {'width': 1080, 'height': 1920, 'fps': 30.0, 'duration': 12.0}
        probed = mock.patch.object(eb, 'probe', return_value=info)
        probed.start()
        self.addCleanup(probed.stop)


class Builds(EditsCase):
    def test_takes_in_order_on_main_lane(self):
        fake = FakeEdits()
        state = eb.build_project(self.edit, self.edl, fake)
        self.assertEqual(state['project'], 'P1')
        self.assertEqual([round(e['sourceInPoint'], 3) for e in fake.elements], [2.0, 7.0])
        placed = [c for c in fake.calls if c[0] == 'addMediaPanelItemsToTimeline']
        # sourceIn/startTime mandariam o clipe para uma trilha de sobreposição
        self.assertTrue(all(set(c[1]) == {'aliasIds'} for c in placed))

    def test_source_enters_by_hard_link(self):
        link = eb.expose_source('A', self.source, self.tmp / 'Movies' / 'x')
        self.assertEqual(link.stat().st_ino, self.source.stat().st_ino)
        self.assertEqual(eb.expose_source('A', self.source, self.tmp / 'Movies' / 'x'), link)

    def test_source_already_in_movies_is_used_directly(self):
        inside = self.tmp / 'Movies' / 'f.mp4'
        inside.parent.mkdir()
        inside.write_bytes(b'v')
        self.assertEqual(eb.expose_source('A', inside.resolve(), inside.parent / 'x'),
                         inside.resolve())

    def test_failed_build_removes_only_its_own_project(self):
        fake = FakeEdits(fail_on='reorderClip')
        with self.assertRaises(eb.EditsError):
            eb.build_project(self.edit, self.edl, fake)
        self.assertIn(('deleteProject', {'id': 'P1'}), fake.calls)

    def test_wrong_montage_is_refused(self):
        clips = [{'sourceInPoint': 3.0, 'sourceOutPoint': 5.0}]
        with self.assertRaises(eb.EditsError):
            eb.verify_built(self.edl['ranges'][:1], clips, 30)

    def test_canvas_choices(self):
        self.assertEqual(eb.nearest_aspect(2160, 3840), ('9:16', True))
        self.assertEqual(eb.nearest_aspect(1920, 1080), ('16:9', True))
        self.assertFalse(eb.nearest_aspect(1000, 1300)[1])
        self.assertEqual(eb.nearest_rate(59.94), 60)
        self.assertEqual(eb.nearest_rate(29.97), 30)


class Exports(unittest.TestCase):
    def test_preset_follows_source_resolution(self):
        preset = eb.export_preset(2160, 3840, 60, 'SDR')
        self.assertEqual(preset, {'resolutionType': '4K', 'aspectRatio': 'nineBySixteen',
                                  'quality': 'High', 'dynamicRange': 'SDR', 'frameRate': 60})
        self.assertEqual(eb.export_preset(1080, 1920, 30, 'SDR')['resolutionType'], 'HD')
        self.assertEqual(eb.export_preset(3840, 2160, 30, 'SDR')['aspectRatio'], 'sixteenByNine')


class Returns(EditsCase):
    def built(self):
        fake = FakeEdits()
        return fake, eb.build_project(self.edit, self.edl, fake)

    def test_frame_rounding_keeps_exact_values(self):
        fake, state = self.built()
        ranges, notes = eb.ranges_from_elements(fake.elements, state, self.edl)
        self.assertEqual([(r['start'], r['end']) for r in ranges],
                         [(2.013, 5.021), (7.0, 9.0)])
        self.assertEqual(notes, [])

    def test_real_trim_comes_back(self):
        fake, state = self.built()
        fake.tool('trim', id=fake.elements[1]['id'], side='right', deltaSeconds=0.5)
        ranges, _ = eb.ranges_from_elements(fake.elements, state, self.edl)
        self.assertAlmostEqual(ranges[1]['end'], 8.5, places=2)

    def test_foreign_media_blocks(self):
        fake, state = self.built()
        fake.elements[0]['aliasId'] = 'desconhecido'
        with self.assertRaises(eb.EditsError):
            eb.ranges_from_elements(fake.elements, state, self.edl)

    def test_overlay_and_speed_only_warn(self):
        fake, state = self.built()
        fake.elements[0]['speed'] = 1.07
        extra = [{'id': 'txt', 'trackType': 'overlay', 'sourceMediaType': 'text'}]
        _, notes = eb.ranges_from_elements(fake.elements + extra, state, self.edl)
        self.assertEqual(len(notes), 2)

    def test_pull_refuses_when_edl_moved(self):
        fake, state = self.built()
        eb.write_state(self.edit, state, self.edl)
        moved = dict(self.edl, ranges=self.edl['ranges'][:1])
        (self.edit / 'edl.json').write_text(json.dumps(moved))
        args = argparse.Namespace(edit_dir=str(self.edit), force=False)
        with mock.patch.object(eb, 'connect', return_value=fake):
            with self.assertRaises(eb.EditsError):
                eb.cmd_pull(args)
        self.assertEqual(json.loads((self.edit / 'edl.json').read_text()), moved)


class Proxy(unittest.TestCase):
    def test_strips_only_the_rejected_field(self):
        message = {'id': 1, 'result': {'resultType': 'complete', 'tools': [], '_meta': {}}}
        self.assertEqual(proxy.clean(message), {'id': 1, 'result': {'tools': [], '_meta': {}}})

    def test_session_survives_with_app_closed(self):
        listed = proxy.offline_reply({'id': 1, 'method': 'tools/list'}, 'x')
        self.assertEqual(listed['result'], {'tools': []})
        called = proxy.offline_reply({'id': 2, 'method': 'tools/call'}, 'abra o app')
        self.assertTrue(called['result']['isError'])
        self.assertIsNone(proxy.offline_reply({'method': 'notifications/initialized'}, 'x'))

    def test_token_comes_from_environment_first(self):
        with mock.patch.dict(os.environ, {'EDITS_MCP_TOKEN': 'abc'}):
            self.assertEqual(proxy.read_token(), 'abc')


if __name__ == '__main__':
    unittest.main()
