"""Quais quadros valem um still, e o teto que impede a conta de explodir.

O render do Remotion não entra aqui: o que se testa é a ESCOLHA dos instantes
(cada um é um lugar onde algo já deu errado antes) e o corte pelo orçamento,
que é onde um projeto com 20 inserts viraria 20 chamadas de ~5s cada.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import phase2_still as still


def projeto(**extra) -> dict:
    data = {"width": 1080, "height": 1920, "fps": 24, "durationSec": 60.0,
            "hookStacked": {"enabled": True, "endSec": 4.0},
            "outro": {"enabled": True, "startSec": 55.0, "durationSec": 2.6}}
    data.update(extra)
    return data


class MomentosTests(unittest.TestCase):
    def setUp(self):
        self.sem_legenda = Path("/nao/existe/captions.json")

    def test_capa_e_encerramento_sempre_entram(self):
        lista, _ = still.momentos(projeto(), self.sem_legenda)
        rotulos = " | ".join(r for _, r in lista)
        self.assertIn("capa", rotulos)
        self.assertIn("encerramento", rotulos)

    def test_o_quadro_da_janela_entra_depois_do_flash(self):
        lista, _ = still.momentos(
            projeto(splitInserts=[{"src": "a.mp4", "start": 10.0, "end": 16.0}]),
            self.sem_legenda)
        t = next(t for t, r in lista if "tela dividida 1" in r)
        self.assertAlmostEqual(t, 10.0 + still.ENTRADA_S, places=3)

    def test_janela_curta_usa_o_meio_e_nao_passa_do_fim_dela(self):
        # com 0.3s de janela, entrar 0.5s cairia DEPOIS do fim — e o quadro
        # mostraria o que já não está mais lá.
        lista, _ = still.momentos(
            projeto(splitInserts=[{"src": "a.mp4", "start": 10.0, "end": 10.3}]),
            self.sem_legenda)
        t = next(t for t, r in lista if "tela dividida 1" in r)
        self.assertAlmostEqual(t, 10.15, places=3)

    def test_instantes_fora_do_video_sao_descartados(self):
        lista, _ = still.momentos(
            projeto(splitInserts=[{"src": "a.mp4", "start": 80.0, "end": 90.0}]),
            self.sem_legenda)
        self.assertFalse([r for _, r in lista if "tela dividida" in r])

    def test_janela_sem_tempo_nao_derruba_a_escolha(self):
        lista, _ = still.momentos(
            projeto(splitInserts=[{"src": "a.mp4"}, {"src": "b.mp4", "start": 12.0, "end": 18.0}]),
            self.sem_legenda)
        self.assertTrue([r for _, r in lista if "tela dividida 2" in r])

    def test_primeira_legenda_entra_quando_ha_legenda(self):
        with tempfile.TemporaryDirectory() as tmp:
            cap = Path(tmp) / "captions.json"
            cap.write_text(json.dumps([{"text": "", "startMs": 0},
                                       {"text": "olha isso", "startMs": 9000}]))
            lista, _ = still.momentos(projeto(captions={"enabled": True}), cap)
        t = next(t for t, r in lista if "legenda" in r)
        self.assertAlmostEqual(t, 9.25, places=3)

    def test_dois_rotulos_no_mesmo_quadro_viram_um(self):
        lista, _ = still.momentos(
            projeto(splitInserts=[{"src": "a.mp4", "start": 10.0, "end": 16.0}],
                    inserts=[{"src": "b.mp4", "start": 10.02, "end": 16.0}]),
            self.sem_legenda)
        tempos = [round(t, 2) for t, _ in lista]
        self.assertEqual(len(tempos), len(set(tempos)))


class OrcamentoTests(unittest.TestCase):
    def test_corta_pelos_menos_importantes_e_mantem_a_ordem_do_tempo(self):
        lista = [(1.0, "capa"), (5.0, "split 1"), (9.0, "split 2"), (13.0, "split 3")]
        prioridades = [0, 1, 3, 3]
        mantidos = still.orcamento(lista, prioridades, 2)
        self.assertEqual(mantidos, [(1.0, "capa"), (5.0, "split 1")])

    def test_lista_dentro_do_teto_passa_inteira(self):
        lista = [(1.0, "a"), (2.0, "b")]
        self.assertEqual(still.orcamento(lista, [0, 1], 8), lista)


class FolhaTests(unittest.TestCase):
    def test_rotulo_longo_nao_invade_o_vizinho(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pngs = []
            for i in range(3):
                p = tmp / f"{i}.png"
                Image.new("RGB", (1080, 1920), (30, 30, 30)).save(p)
                pngs.append((p, "22.90s — tela dividida 3 — costura e proporção " + "x" * 40))
            sheet = still.folha(pngs, tmp / "sheet.png", cols=3)
            self.assertTrue((tmp / "sheet.png").is_file())
            # 3 colunas de tiles + 2 gaps: a folha não pode crescer com o texto
            self.assertEqual(sheet.width, 3 * 520 + 2 * 8)


if __name__ == "__main__":
    unittest.main()
