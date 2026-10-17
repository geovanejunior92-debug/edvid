"""Conferência da ficha do comercial animado.

A skill de origem pedia ao agente para checar de olho: cenas contínuas, até 6
palavras, cronômetro zerando junto do som `destrava`. Cada um desses virou erro
de máquina aqui. O preset do consultório ancora o caso que precisa passar limpo.
"""
import copy
import json
from pathlib import Path
import sys
import unittest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / 'helpers'))
import comercial

FICHA = json.loads((RAIZ / 'assets' / 'comercial' / 'ficha-drgeovane.json').read_text())


class ConferirTests(unittest.TestCase):
    def ficha(self):
        return copy.deepcopy(FICHA)

    def test_preset_do_consultorio_passa_limpo(self):
        erros, avisos = comercial.conferir(self.ficha())
        self.assertEqual(erros, [])
        self.assertEqual(avisos, [])

    def test_buraco_entre_cenas_e_erro(self):
        f = self.ficha()
        f['cenas'][3]['ini'] += 0.2
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('buraco' in e for e in erros), erros)

    def test_ultima_cena_tem_que_fechar_na_duracao(self):
        f = self.ficha()
        f['duracao'] = 30
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('última cena' in e for e in erros), erros)

    def test_mais_de_seis_palavras_e_erro(self):
        f = self.ficha()
        f['textos'][4]['linhas'] = ['Sem fórmula pronta para', 'ninguém aqui dentro.']
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('palavras' in e for e in erros), erros)

    def test_texto_atravessando_troca_de_cena_e_erro(self):
        f = self.ficha()
        f['textos'][1]['fim'] = 4.5   # S03 termina em 3.8
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('atravessa' in e for e in erros), erros)

    def test_cronometro_sem_destrava_no_zero_e_erro(self):
        f = self.ficha()
        f['sons'] = [s for s in f['sons'] if s['tipo'] != 'destrava']
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('destrava' in e for e in erros), erros)

    def test_zera_tem_que_ser_comeca_mais_segundos(self):
        f = self.ficha()
        f['cronometro']['zera'] = 24.0
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('comeca + segundos' in e for e in erros), erros)

    def test_destaque_tem_que_ser_o_final_da_linha(self):
        f = self.ficha()
        f['textos'][1]['destaque'] = [0, 'Me dá']
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('destaque' in e for e in erros), erros)

    def test_cena_fora_do_catalogo_e_erro(self):
        f = self.ficha()
        f['cenas'][6]['tipo'] = 'video'
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('catálogo' in e for e in erros), erros)

    def test_cor_curta_e_erro(self):
        f = self.ficha()
        f['cores']['fundo'] = '#000'
        erros, _ = comercial.conferir(f)
        self.assertTrue(any('#rrggbb' in e for e in erros), erros)


class MontarTests(unittest.TestCase):
    def test_build_injeta_a_ficha_sem_tocar_no_motor(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ficha_path = Path(d) / 'ficha.json'
            ficha_path.write_text(json.dumps(FICHA, ensure_ascii=False))
            alvo = comercial.montar(ficha_path, Path(d) / 'out')
            lida = comercial.ler_ficha_html(alvo.parent)
            self.assertEqual(lida['marca'], FICHA['marca'])
            self.assertEqual(lida['fontes']['arquivos'], {'Poppins': 'fontes/Poppins-ExtraBold.ttf'})
            self.assertTrue((alvo.parent / 'fontes' / 'Poppins-ExtraBold.ttf').is_file())
            motor = comercial.MOTOR.read_text()
            fora = lambda h: h[:h.index(comercial.INICIO)] + h[h.index(comercial.FIM):]
            self.assertEqual(fora(alvo.read_text()), fora(motor))


if __name__ == '__main__':
    unittest.main()
