"""Uma frase errada aqui troca um efeito pelo outro no vídeo dele.

"Atrás da cabeça" tem significado FIXO desde 16/08, nas palavras dele:
*"quero que fique atrás da cabeça porém mantenha a divisão das telas"*. Ou
seja, `splitInserts[]` COM matte — a divisão permanece e a cabeça sobe na
frente da faixa. O `behindVideos[]` é o oposto: fundo inteiro, sem divisão.

Isso já foi trocado uma vez, ele corrigiu, e mesmo assim a afirmação velha
sobreviveu em DOIS lugares (um comentário no template e uma frase em inglês
dentro da própria seção que dizia o contrário três linhas acima) até
2026-09-11. Este teste existe porque documentação que se contradiz não é
pega por nenhum outro gate — o render fica correto e o próximo agente lê a
frase errada.
"""
from pathlib import Path
import unittest

SKILL = Path(__file__).resolve().parents[1]
CUSTOM = SKILL / 'assets' / 'shortform' / 'src' / 'CustomGraphics.tsx'
SHORTFORM = SKILL / 'references' / 'shortform.md'
INDEX = SKILL / 'assets' / 'preview' / 'index.html'


class SplitVocabularyTests(unittest.TestCase):
    def test_template_does_not_call_behindvideos_the_users_split_screen(self):
        block = CUSTOM.read_text()
        start = block.index('type BehindVideo')
        comment = block[max(0, start - 900):start]
        self.assertIn('NÃO é o padrão do usuário', comment)
        self.assertNotIn('o padrão do usuário para "tela dividida"', comment)

    def test_docs_do_not_call_behindvideos_his_standing_meaning(self):
        doc = SHORTFORM.read_text()
        self.assertNotIn("this user's standing meaning of \"tela dividida\"", doc)
        section = doc[doc.index('### `behindVideos[]`'):][:900]
        self.assertIn('não é o padrão dele', section)

    def test_the_standing_meaning_is_stated_where_it_belongs(self):
        doc = SHORTFORM.read_text()
        section = doc[doc.index('### Tela dividida COM a pessoa na frente da faixa'):][:700]
        self.assertIn('não o `behindVideos[]`', section)

    def test_ui_label_separates_divided_from_undivided(self):
        html = INDEX.read_text()
        # a opção sem divisão não pode ser rotulada com o vocabulário da dividida
        label = html.split('<option value="behind">')[1].split('</option>')[0]
        self.assertIn('Sem divisão', label)
        for confusable in ('atrás da cabeça', 'Tela dividida'):
            self.assertNotIn(confusable, label)


if __name__ == '__main__':
    unittest.main()
