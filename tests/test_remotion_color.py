"""A cor do render da Fase 2 depende de uma troca de texto no comando do Remotion.

`remotion.config.ts` reescreve o zscale que o Remotion põe no comando do ffmpeg
quando o colorSpace é bt709. Se uma atualização do Remotion mudar esse texto, a
troca deixa de acontecer sem erro nenhum e o croma volta a sair deslocado. Estes
testes travam as duas pontas.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = "zscale=matrix=709:matrixin=709:range=limited"
CORRIGIDO = "zscale=matrix=709:matrixin=470bg:rangein=full:range=limited"


class RemotionColorTests(unittest.TestCase):
    def test_config_pede_bt709_e_corrige_a_matriz(self):
        for template in ("shortform", "longform"):
            cfg = (ROOT / "assets" / template / "remotion.config.ts").read_text()
            self.assertIn("setColorSpace('bt709')", cfg, template)
            self.assertIn(ORIGINAL, cfg, template)
            self.assertIn(CORRIGIDO, cfg, template)

    def test_remotion_instalado_ainda_gera_o_zscale_que_a_config_troca(self):
        args = ROOT / "assets/shortform/node_modules/@remotion/renderer/dist/ffmpeg-args.js"
        if not args.is_file():
            self.skipTest("dependências do template não instaladas")
        self.assertIn(ORIGINAL, args.read_text(),
                      "o Remotion mudou o filtro de cor; atualize a troca em remotion.config.ts")


if __name__ == "__main__":
    unittest.main()
