"""O plano de som nunca apaga efeito manual, e o encerramento é do swell.

O caso que originou isto: rodar o helper substituía `sfxCues` inteiro, o
`outro-swell` posto à mão sumia, e a transição da tela azul ainda ganhava whoosh.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'helpers'))
import review_final
import sfx_plan


def projeto(edit_data=None, edl=None, falas=()):
    edit = Path(tempfile.mkdtemp())
    if edit_data is not None:
        (edit / 'remotion/public').mkdir(parents=True)
        (edit / 'remotion/public/edit-data.json').write_text(json.dumps(edit_data))
    if edl is not None:
        (edit / 'edl.json').write_text(json.dumps(edl))
    if falas:
        (edit / 'transcripts').mkdir()
        palavras = [{'type': 'word', 'start': t, 'end': t + 0.3, 'text': txt} for t, txt in falas]
        (edit / 'transcripts/cut.json').write_text(json.dumps({'words': palavras}))
    return edit


def rodar(edit, *extra):
    sys.argv = ['sfx_plan', str(edit), *extra]
    with contextlib.redirect_stdout(io.StringIO()):
        sfx_plan.main()


def dados(edit):
    return json.loads((edit / 'remotion/public/edit-data.json').read_text())


def guardados(edit):
    return json.loads((edit / 'sfx_cues.json').read_text())['cues']


BASE = {'durationSec': 40.0,
        'transitions': [{'at': 5.0, 'variant': 'corte'}, {'at': 9.0, 'variant': 'saida'},
                        {'at': 36.8, 'variant': 'saida'}],
        'outro': {'enabled': True, 'startSec': 37.0, 'durationSec': 3.0}}
FALAS = [(2.0, 'olha'), (10.0, 'a'), (10.3, 'verdade'), (30.0, 'o'), (30.3, 'resultado')]


def base(**extra):
    return json.loads(json.dumps({**BASE, **extra}))


class PreservaManualTests(unittest.TestCase):
    def test_rodar_de_novo_nao_apaga_cue_manual_e_nao_duplica_automatica(self):
        manual = {'at': 20.0, 'src': 'typing.mp3', 'volume': 0.5, 'dur': 1.2}
        edit = projeto(base(sfxCues=[manual]), falas=FALAS)
        rodar(edit)
        primeira = dados(edit)['sfxCues']
        rodar(edit)
        segunda = dados(edit)['sfxCues']
        self.assertEqual(primeira, segunda)
        achado = [c for c in segunda if c['src'] == 'typing.mp3']
        self.assertEqual(len(achado), 1)
        self.assertEqual(achado[0]['origin'], 'manual')

    def test_cada_cue_declara_a_origem(self):
        edit = projeto(base(), falas=FALAS)
        rodar(edit)
        cues = dados(edit)['sfxCues']
        self.assertTrue(cues)
        self.assertEqual({c['origin'] for c in cues}, {'auto'})

    def test_cue_novo_em_sfxcues_sem_origem_vira_manual_na_proxima(self):
        edit = projeto(base(), falas=FALAS)
        rodar(edit)
        d = dados(edit)
        d['sfxCues'].append({'at': 22.0, 'src': 'key.mp3', 'volume': 0.4, 'dur': 0.3})
        (edit / 'remotion/public/edit-data.json').write_text(json.dumps(d))
        rodar(edit)
        origem = {c['src']: c['origin'] for c in guardados(edit)}
        self.assertEqual(origem['key.mp3'], 'manual')

    def test_so_as_automaticas_sao_regeneradas(self):
        edit = projeto(base(), falas=FALAS)
        rodar(edit)
        # a fala muda: o acento automático antigo tem que sumir, o manual não
        cues = guardados(edit) + [{'at': 20.0, 'src': 'key.mp3', 'origin': 'manual'}]
        (edit / 'sfx_cues.json').write_text(json.dumps({'cues': cues}))
        (edit / 'transcripts/cut.json').write_text(json.dumps({'words': []}))
        rodar(edit)
        srcs = [c['src'] for c in dados(edit)['sfxCues']]
        self.assertIn('key.mp3', srcs)
        self.assertNotIn('hit-soft.mp3', srcs)

    def test_automatica_nao_empilha_em_cima_de_manual(self):
        edit = projeto(base(sfxCues=[{'at': 2.05, 'src': 'key.mp3'}]), falas=FALAS)
        rodar(edit)
        self.assertNotIn('ui-blip.mp3', [c['src'] for c in dados(edit)['sfxCues']])

    def test_projeto_antigo_nao_vira_manual_o_que_o_helper_gerou(self):
        antigo = {'at': 36.9, 'src': 'whoosh-long.mp3', 'volume': 0.36, 'dur': 1.1,
                  'label': 'entra a tela final'}
        edit = projeto(base(sfxCues=[antigo]), falas=FALAS)
        rodar(edit)
        self.assertNotIn('whoosh-long.mp3', [c['src'] for c in dados(edit)['sfxCues']])

    def test_dry_run_nao_grava_nada(self):
        edit = projeto(base(), falas=FALAS)
        rodar(edit, '--dry-run')
        self.assertFalse((edit / 'sfx_cues.json').exists())
        self.assertNotIn('sfxCues', dados(edit))


class SemEditDataTests(unittest.TestCase):
    def test_roda_antes_do_preset_e_a_fusao_vem_depois(self):
        edit = projeto(edl={'total_duration_s': 40.0}, falas=FALAS)
        rodar(edit)
        self.assertTrue(guardados(edit))
        self.assertFalse((edit / 'remotion').exists())
        # o preset chega, sem saber do som; a fusão acontece na segunda execução
        (edit / 'remotion/public').mkdir(parents=True)
        (edit / 'remotion/public/edit-data.json').write_text(json.dumps(base()))
        rodar(edit)
        srcs = [c['src'] for c in dados(edit)['sfxCues']]
        self.assertIn('outro-swell.mp3', srcs)
        self.assertIn('ui-blip.mp3', srcs)


class EncerramentoTests(unittest.TestCase):
    def test_swell_cai_na_transicao_para_a_tela_azul(self):
        edit = projeto(base(transitions=[{'at': 36.7, 'variant': 'saida'}]), falas=FALAS)
        rodar(edit)
        swell = [c for c in dados(edit)['sfxCues'] if c['src'] == 'outro-swell.mp3']
        self.assertEqual(len(swell), 1)
        self.assertEqual(swell[0]['at'], 36.7)

    def test_sem_transicao_o_swell_fica_0_2_antes_da_tela(self):
        edit = projeto(base(transitions=[]), falas=FALAS)
        rodar(edit)
        swell = [c for c in dados(edit)['sfxCues'] if c['src'] == 'outro-swell.mp3']
        self.assertAlmostEqual(swell[0]['at'], 36.8)

    def test_sem_whoosh_long_e_a_ultima_transicao_fica_muda(self):
        edit = projeto(base(), falas=FALAS)
        rodar(edit)
        d = dados(edit)
        self.assertNotIn('whoosh-long.mp3', [c['src'] for c in d['sfxCues']])
        final = d['transitions'][-1]
        self.assertNotIn('sfx', final)
        self.assertEqual(final['volume'], 0)
        # as outras continuam com o som delas
        self.assertEqual(d['transitions'][0]['sfx'], 'shutter.mp3')
        self.assertEqual(d['transitions'][1]['sfx'], 'whoosh.mp3')

    def test_a_revisao_nao_lista_a_transicao_muda_como_fonte_de_som(self):
        edit = projeto(base(), falas=FALAS)
        rodar(edit)
        linhas = review_final.fontes_de_audio(dados(edit))
        self.assertFalse([l for l in linhas if l.startswith('transição') and '36.80' in l])

    def test_swell_manual_nao_ganha_um_segundo(self):
        edit = projeto(base(sfxCues=[{'at': 36.75, 'src': 'outro-swell.mp3', 'volume': 0.5}]), falas=FALAS)
        rodar(edit)
        self.assertEqual(sum(c['src'] == 'outro-swell.mp3' for c in dados(edit)['sfxCues']), 1)

    def test_tela_final_desligada_nao_agenda_swell_nem_reserva_transicao(self):
        edit = projeto(base(outro={'enabled': False, 'startSec': 37.0}), falas=FALAS)
        rodar(edit)
        d = dados(edit)
        self.assertNotIn('outro-swell.mp3', [c['src'] for c in d['sfxCues']])
        self.assertEqual(d['transitions'][-1]['sfx'], 'whoosh.mp3')

    def test_o_acento_da_fala_nao_toma_o_lugar_do_swell(self):
        edit = projeto(base(), falas=[(36.0, 'é'), (36.8, 'isso')])
        rodar(edit)
        perto = [c for c in dados(edit)['sfxCues'] if abs(c['at'] - 36.8) < 0.3]
        self.assertEqual([c['src'] for c in perto], ['outro-swell.mp3'])


class TransicaoManualTests(unittest.TestCase):
    def test_som_escolhido_a_mao_na_transicao_fica(self):
        edit = projeto(base(transitions=[{'at': 5.0, 'variant': 'corte', 'sfx': 'hit.mp3'}]))
        rodar(edit)
        self.assertEqual(dados(edit)['transitions'][0]['sfx'], 'hit.mp3')


class BanidosTests(unittest.TestCase):
    def test_nenhum_helper_propoe_riser_nem_whoosh_rev(self):
        for nome, (arquivo, _, _) in sfx_plan.CATALOGO.items():
            self.assertNotIn('riser', nome + arquivo)
            self.assertNotIn('whoosh-rev', nome + arquivo)
        texto = 'mas porém o problema presta atenção o mais perigoso a verdade'.split()
        edit = projeto(base(), falas=list(zip(range(1, 20), texto)))
        rodar(edit)
        for c in dados(edit)['sfxCues']:
            self.assertNotIn('riser', c['src'])
            self.assertNotIn('whoosh-rev', c['src'])


if __name__ == '__main__':
    unittest.main()
