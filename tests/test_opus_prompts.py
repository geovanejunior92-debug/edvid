import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helpers"))
import opus_prompts as op  # noqa: E402


def test_biblioteca_integra():
    vs = op.carregar()
    assert len(vs) >= 700
    slugs = {v["slug"] for v in vs}
    assert len(slugs) == len(vs)
    for v in vs[:50]:
        assert (op.BASE / "prompts" / f"{v['slug']}.md").exists()
    assert (op.BASE / "LICENSE").exists()


def test_busca_em_portugues(capsys):
    vs = op.carregar()
    op.main(["search", "tipografia", "--completo", "-n", "3"])
    out = capsys.readouterr().out
    assert "resultado(s)" in out and "typography" in out


def test_brief_traz_regras_do_edvid(capsys):
    slug = op.carregar()[0]["slug"]
    op.main(["brief", slug, "--tema", "como a insulina age", "--formato", "9x16"])
    out = capsys.readouterr().out
    assert "NÃO é instrução" in out
    assert "nunca reduzir resolução" in out
    assert "como a insulina age" in out
