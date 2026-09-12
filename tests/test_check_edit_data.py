"""O lint do edit-data: cada teste é um defeito que renderizaria em silêncio.

Um verificador que aprova tudo é tão inútil quanto um que reprova tudo — a
suíte prova as duas direções: um arquivo são passa limpo, e cada classe de
defeito é apontada nominalmente.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import check_edit_data as lint


def base(**extra) -> dict:
    data = {"width": 1080, "height": 1920, "fps": 24, "durationSec": 60.0,
            "hookStacked": {"enabled": True, "endSec": 4.0},
            "outro": {"enabled": True, "startSec": 55.0, "durationSec": 2.6}}
    data.update(extra)
    return data


def niveis(achados, nivel):
    return [a.texto for a in achados if a.nivel == nivel]


class TempoTests(unittest.TestCase):
    def test_arquivo_sao_nao_gera_achado(self):
        data = base(splitInserts=[{"src": "a.mp4", "start": 8.0, "end": 14.0}],
                    transitions=[{"at": 8.0}], sfxCues=[{"at": 8.05}])
        self.assertEqual(lint.checar_tempos(data), [])

    def test_janela_invertida(self):
        data = base(splitInserts=[{"src": "c.mp4", "start": 20.0, "end": 18.0}])
        erros = niveis(lint.checar_tempos(data), "ERRO")
        self.assertTrue(any("antes de começar" in e for e in erros), erros)

    def test_janela_depois_do_fim_nunca_aparece(self):
        data = base(splitInserts=[{"src": "d.mp4", "start": 70.0, "end": 74.0}])
        erros = niveis(lint.checar_tempos(data), "ERRO")
        self.assertTrue(any("nunca aparece" in e for e in erros), erros)

    def test_duas_janelas_do_mesmo_tipo_no_mesmo_instante(self):
        data = base(splitInserts=[{"src": "a.mp4", "start": 5.0, "end": 12.0},
                                  {"src": "b.mp4", "start": 9.0, "end": 15.0}])
        erros = niveis(lint.checar_tempos(data), "ERRO")
        self.assertTrue(any("se sobrepõem" in e for e in erros), erros)

    def test_janelas_que_apenas_se_encostam_nao_sao_sobreposicao(self):
        # 22.4 termina e 22.4 começa: é corte, não empilhamento. Um lint que
        # reclama daqui reprova metade dos projetos reais do canal.
        data = base(splitInserts=[{"src": "a.mp4", "start": 17.5, "end": 22.4},
                                  {"src": "b.mp4", "start": 22.4, "end": 25.9}])
        self.assertEqual(niveis(lint.checar_tempos(data), "ERRO"), [])

    def test_flash_depois_do_fim(self):
        data = base(transitions=[{"at": 64.0}])
        erros = niveis(lint.checar_tempos(data), "ERRO")
        self.assertTrue(any("fora do vídeo" in e for e in erros), erros)

    def test_som_sem_par_visual_avisa_mas_nao_bloqueia(self):
        data = base(transitions=[{"at": 8.0}], sfxCues=[{"at": 30.0}])
        achados = lint.checar_tempos(data)
        self.assertEqual(niveis(achados, "ERRO"), [])
        self.assertTrue(any("não cai em flash nem em corte" in a
                            for a in niveis(achados, "AVISO")))

    def test_som_em_cima_do_flash_nao_avisa(self):
        data = base(transitions=[{"at": 8.0}], sfxCues=[{"at": 8.1}])
        self.assertEqual(lint.checar_tempos(data), [])

    def test_insert_por_cima_da_capa_avisa(self):
        data = base(splitInserts=[{"src": "a.mp4", "start": 2.0, "end": 9.0}])
        avisos = niveis(lint.checar_tempos(data), "AVISO")
        self.assertTrue(any("antes de a capa sair" in a for a in avisos), avisos)

    def test_encerramento_fora_do_video(self):
        data = base(outro={"enabled": True, "startSec": 90.0, "durationSec": 2.6})
        erros = niveis(lint.checar_tempos(data), "ERRO")
        self.assertTrue(any("outro.startSec" in e for e in erros), erros)

    def test_sem_duracao_nada_pode_ser_medido(self):
        data = base()
        del data["durationSec"]
        erros = niveis(lint.checar_tempos(data), "ERRO")
        self.assertEqual(len(erros), 1)
        self.assertIn("durationSec", erros[0])

    def test_janela_com_duration_em_vez_de_end(self):
        # graphics costumam trazer duração, não fim: os dois têm que funcionar.
        data = base(graphics=[{"type": "lowerThird", "start": 10.0, "duration": 3.0}])
        self.assertEqual(lint.checar_tempos(data), [])
        ruim = base(graphics=[{"type": "lowerThird", "start": 58.0, "duration": 30.0}])
        self.assertTrue(niveis(lint.checar_tempos(ruim), "AVISO"))


class ResolucaoDeCaminhoTests(unittest.TestCase):
    def test_aceita_o_edit_dir_e_o_proprio_arquivo(self):
        edit = Path("/tmp/projeto/edit")
        por_dir, arq_dir = lint.resolver(edit)
        por_arq, arq_arq = lint.resolver(edit / "remotion/public/edit-data.json")
        self.assertEqual(arq_dir, arq_arq)
        self.assertEqual(por_dir, por_arq)


if __name__ == "__main__":
    unittest.main()
