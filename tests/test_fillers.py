"""Palavra da oração não é vício de fala: pausa dos dois lados, ou fica fora.

"é" e "um" são também palavras comuns da frase. Com pausa de um lado só, um
material limpo dava 100% de falso positivo, o que ensina a ignorar o helper.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helpers'))
import fillers


def frase(*palavras):
    """Palavras como (texto, início, fim)."""
    return [{'word': t, 'start': a, 'end': b} for t, a, b in palavras]


def vicios(words, inicio=0.0, fim=10.0):
    return [i['text'] for i in fillers.find_in_range(words, inicio, fim, use_weak=False)
            if i['kind'] == 'vício']


class VicioForteTests(unittest.TestCase):
    def test_e_dentro_da_frase_com_pausa_so_depois_nao_e_vicio(self):
        # "Uma coisa é fome": colado antes, respiração depois.
        words = frase(('Uma', 0.5, 0.7), ('coisa', 0.72, 1.0), ('é', 1.02, 1.1), ('fome', 1.3, 1.7))
        self.assertEqual(vicios(words), [])

    def test_um_dentro_da_frase_com_pausa_so_antes_nao_e_vicio(self):
        # "do que só um medicamento": pausa antes, colado depois.
        words = frase(('do', 0.5, 0.6), ('que', 0.62, 0.7), ('só', 0.72, 0.9),
                      ('um', 1.1, 1.2), ('medicamento', 1.22, 1.9))
        self.assertEqual(vicios(words), [])

    def test_muleta_isolada_dos_dois_lados_continua_vicio(self):
        words = frase(('Então', 0.5, 0.9), ('é', 1.2, 1.4), ('vamos', 1.7, 2.0), ('lá', 2.02, 2.2))
        self.assertEqual(vicios(words), ['é'])

    def test_borda_do_range_conta_como_pausa(self):
        # Um "é" abrindo o take, com pausa depois, é justamente o que se corta.
        words = frase(('é', 1.0, 1.1), ('vamos', 1.5, 1.8))
        self.assertEqual(vicios(words, inicio=0.98), ['é'])
        words = frase(('vamos', 1.0, 1.3), ('né', 1.6, 1.7))
        self.assertEqual(vicios(words, fim=1.72), ['né'])

    def test_primeira_palavra_sem_pausa_depois_nao_e_vicio(self):
        words = frase(('Um', 1.0, 1.1), ('medicamento', 1.12, 1.7))
        self.assertEqual(vicios(words, inicio=0.98), [])


if __name__ == '__main__':
    unittest.main()
