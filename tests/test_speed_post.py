"""A aceleração é um passo do pipeline: uma vez só, com tudo que depende dela junto.

Tudo aqui roda sobre vídeo sintético. O tom é medido pelo pico do espectro.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'helpers'))
import diagnostics
import fillers
import speed_post
from studio_pipeline import StudioPipeline


def sintetico(path, w=720, h=1280, fps=60, dur=3.0, freq=440):
    subprocess.run(['ffmpeg', '-y', '-v', 'error',
                    '-f', 'lavfi', '-i', f'testsrc2=s={w}x{h}:r={fps}:d={dur}',
                    '-f', 'lavfi', '-i', f'sine=frequency={freq}:duration={dur}:sample_rate=48000',
                    '-vf', 'setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                    '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                    '-color_range', 'tv', '-c:a', 'aac', '-shortest', str(path)], check=True)


def ffprobe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,r_frame_rate,color_space,color_primaries,color_transfer,color_range'
                          ':format=duration', '-of', 'json', str(path)],
                         capture_output=True, text=True, check=True).stdout
    doc = json.loads(out)
    return doc['streams'][0], float(doc['format']['duration'])


def pico_hz(path):
    raw = subprocess.run(['ffmpeg', '-v', 'quiet', '-i', str(path), '-ac', '1', '-ar', '48000',
                          '-f', 'f32le', '-'], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    x = x[len(x) // 4: 3 * len(x) // 4]
    esp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / 48000)[int(np.argmax(esp))])


class Projeto(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.edit = Path(tmp.name)
        self.cut = self.edit / 'cut.mp4'
        self.edl = self.edit / 'edl.json'
        self.cut_1x = self.edit / 'cut_1x.mp4'
        sintetico(self.cut)
        self.dur_1x = ffprobe(self.cut)[1]
        self.edl.write_text(json.dumps({
            'ranges': [{'source': 'a', 'start': 0, 'end': 1.5}, {'source': 'a', 'start': 2, 'end': 3.5}],
            'jcut_timeline': [
                {'video_start_in_output': 0.0, 'video_duration': 1.5,
                 'audio_start_in_output': 0.0, 'audio_duration': 1.5, 'tail_trim_frames': 2},
                {'video_start_in_output': 1.5, 'video_duration': 1.5,
                 'audio_start_in_output': 1.33, 'audio_duration': 1.67, 'tail_trim_frames': 0}],
            'total_duration_s': 3.0}))

    def aplicar(self, speed=None, **kw):
        return speed_post.aplicar(self.cut, self.edl, self.cut_1x, speed, **kw)

    def lido(self):
        return json.loads(self.edl.read_text())


class SaidaTests(Projeto):
    def test_padrao_e_1_07_com_resolucao_fps_e_tom_preservados(self):
        antes_stream, _ = ffprobe(self.cut)
        antes_hz = pico_hz(self.cut)
        self.aplicar()
        depois, dur = ffprobe(self.cut)
        self.assertAlmostEqual(dur, self.dur_1x / 1.07, delta=0.05)
        for campo in ('width', 'height', 'r_frame_rate', 'color_space', 'color_primaries',
                      'color_transfer', 'color_range'):
            self.assertEqual(depois[campo], antes_stream[campo], campo)
        self.assertEqual(antes_stream['color_primaries'], 'bt709')
        self.assertAlmostEqual(pico_hz(self.cut), antes_hz, delta=antes_hz * 0.01)
        self.assertEqual(self.lido()['speed_post'], 1.07)

    def test_setpts_sem_atempo_mudaria_o_tom_e_o_teste_acima_pegaria(self):
        # sanidade da própria medida: reamostrar sobe o tom 7% e sai da tolerância
        cru = self.edit / 'cru.mp4'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(self.cut), '-vn', '-af',
                        'asetrate=48000*1.07,aresample=48000', str(cru)], check=True)
        self.assertGreater(abs(pico_hz(cru) - pico_hz(self.cut)), 440 * 0.03)

    def test_4k60_continua_4k60(self):
        grande = self.edit / 'g'
        grande.mkdir()
        sintetico(grande / 'cut.mp4', 2160, 3840, 60, 1.0)
        (grande / 'edl.json').write_text(json.dumps({'ranges': []}))
        speed_post.aplicar(grande / 'cut.mp4', grande / 'edl.json', grande / 'cut_1x.mp4')
        s, _ = ffprobe(grande / 'cut.mp4')
        self.assertEqual((s['width'], s['height'], s['r_frame_rate']), (2160, 3840, '60/1'))

    def test_guarda_o_corte_em_1x_intacto(self):
        self.aplicar()
        self.assertAlmostEqual(ffprobe(self.cut_1x)[1], self.dur_1x, delta=0.001)


class IdempotenciaTests(Projeto):
    def test_segunda_execucao_nao_acelera_de_novo(self):
        self.aplicar()
        bytes_antes = self.cut.read_bytes()
        edl_antes = self.lido()
        r = self.aplicar()
        self.assertEqual(r['status'], 'ja-aplicado')
        self.assertEqual(self.cut.read_bytes(), bytes_antes)
        self.assertEqual(self.lido(), edl_antes)

    def test_outra_velocidade_parte_do_1x(self):
        self.aplicar()
        self.aplicar(1.03)
        self.assertAlmostEqual(ffprobe(self.cut)[1], self.dur_1x / 1.03, delta=0.05)
        self.assertEqual(self.lido()['speed_post'], 1.03)
        self.assertAlmostEqual(self.lido()['total_duration_s'], 3.0 / 1.03, places=2)

    def test_sem_cut_1x_recusa_em_vez_de_acelerar_em_cima(self):
        self.aplicar()
        self.cut_1x.unlink()
        with self.assertRaises(speed_post.SpeedError):
            self.aplicar()

    def test_interrompido_antes_de_gravar_o_edl_nao_acelera_duas_vezes(self):
        limpo = self.edl.read_text()
        self.aplicar()
        self.edl.write_text(limpo)
        self.aplicar()
        self.assertAlmostEqual(ffprobe(self.cut)[1], self.dur_1x / 1.07, delta=0.05)
        self.assertEqual(self.lido()['speed_post'], 1.07)

    def test_velocidade_pedida_sobrevive_ao_corte_refeito(self):
        edl = self.lido()
        edl['speed_post_pedido'] = 1.03
        self.edl.write_text(json.dumps(edl))
        self.aplicar()
        self.assertEqual(self.lido()['speed_post'], 1.03)
        self.assertNotIn('speed_post_pedido', self.lido())

    def test_fora_da_faixa_recusa(self):
        with self.assertRaises(speed_post.SpeedError):
            self.aplicar(3.0)


class DadosDerivadosTests(Projeto):
    def test_jcut_timeline_e_duracao_divididos_pela_velocidade(self):
        self.aplicar()
        edl = self.lido()
        self.assertAlmostEqual(edl['jcut_timeline'][1]['video_start_in_output'], 1.5 / 1.07, places=4)
        self.assertAlmostEqual(edl['jcut_timeline'][1]['audio_duration'], 1.67 / 1.07, places=4)
        self.assertEqual(edl['jcut_timeline'][0]['tail_trim_frames'], 2)
        self.assertAlmostEqual(edl['total_duration_s'], 3.0 / 1.07, places=2)
        self.assertEqual(edl['ranges'][1]['end'], 3.5)   # tempo da fonte não muda

    def test_transcricao_e_cues_reescalados_uma_vez(self):
        tr = self.edit / 'tr.json'
        tr.write_text(json.dumps({'words': [{'start': 1.07, 'end': 2.14, 'text': 'oi'}], '_cache': {'start': 9}}))
        cues = self.edit / 'c.json'
        cues.write_text(json.dumps({'cues': [{'at': 2.14, 'src': 'x.mp3', 'origin': 'manual'}]}))
        self.aplicar(transcript=tr, cues=cues)
        self.aplicar(transcript=tr, cues=cues)
        palavra = json.loads(tr.read_text())['words'][0]
        self.assertEqual((palavra['start'], palavra['end']), (1.0, 2.0))
        self.assertEqual(json.loads(tr.read_text())['_cache']['start'], 9)
        self.assertEqual(json.loads(cues.read_text())['cues'][0]['at'], 2.0)

    def test_tempo_da_fonte_e_tempo_do_corte_acelerado_se_convertem(self):
        self.aplicar()
        edl = self.lido()
        # 1 s depois do início do segundo range, na fonte
        self.assertAlmostEqual(diagnostics.out_time(edl, 'a', 3.0), (1.5 + 1.0) / 1.07, places=2)
        cortes = fillers.text_cuts_to_source(edl, [{'renderedStart': 2.0, 'renderedEnd': 2.2, 'text': 'x'}])
        o = 1.5 / 1.07
        self.assertAlmostEqual(cortes[0]['start'], 2 + (2.0 - o) * 1.07, places=2)
        mapeado = StudioPipeline._map_text_cuts(edl, [{'renderedStart': 2.0, 'renderedEnd': 2.2}])
        self.assertAlmostEqual(mapeado[0]['start'], 2 + (2.0 - o) * 1.07, places=2)


class RenderTests(unittest.TestCase):
    """O corte refeito nasce em 1×: o EDL não pode continuar dizendo que acelerou."""

    def test_refazer_o_corte_e_aplicar_de_novo(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp)
            fonte = edit / 'fonte.mp4'
            sintetico(fonte, 360, 640, 30, 4.0)
            edl = edit / 'edl.json'
            edl.write_text(json.dumps({
                'version': 1, 'sources': {'a': str(fonte)}, 'grade': '',
                'ranges': [{'source': 'a', 'start': 0.2, 'end': 1.8},
                           {'source': 'a', 'start': 2.2, 'end': 3.8}]}))
            cut = edit / 'cut.mp4'

            def render():
                subprocess.run([sys.executable, str(SKILL / 'helpers/render.py'), str(edl), '-o', str(cut),
                                '--no-subtitles', '--draft'], check=True, capture_output=True)
            render()
            total_1x = json.loads(edl.read_text())['total_duration_s']
            speed_post.aplicar(cut, edl, edit / 'cut_1x.mp4', 1.04)
            self.assertEqual(json.loads(edl.read_text())['speed_post'], 1.04)
            render()
            doc = json.loads(edl.read_text())
            self.assertNotIn('speed_post', doc)
            self.assertEqual(doc['speed_post_pedido'], 1.04)
            self.assertAlmostEqual(doc['total_duration_s'], total_1x, delta=0.05)
            speed_post.aplicar(cut, edl, edit / 'cut_1x.mp4')
            doc = json.loads(edl.read_text())
            self.assertEqual(doc['speed_post'], 1.04)
            self.assertAlmostEqual(doc['total_duration_s'], total_1x / 1.04, delta=0.05)
            self.assertAlmostEqual(ffprobe(cut)[1], ffprobe(edit / 'cut_1x.mp4')[1] / 1.04, delta=0.1)


class DocumentacaoTests(unittest.TestCase):
    def test_skill_diz_em_que_passo_roda_e_a_regra(self):
        texto = (SKILL / 'SKILL.md').read_text()
        self.assertIn('7b.', texto)
        self.assertIn('speed_post.py', texto)
        self.assertIn('sempre 1,07×', texto)


if __name__ == '__main__':
    unittest.main()
