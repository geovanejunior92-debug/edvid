"""Aplica no `edit-data.json` a altura de costura que ele ajustou no preview.

O preview escreve `seam[]` dentro de `preview_edits.json` — uma entrada por
janela mexida, com o `focusY` novo e a fração onde a linha passou a cruzar a
cabeça. Este helper é o outro lado: valida contra a geometria real e grava.

Três coisas que ele NÃO faz, de propósito:

- **Não mexe no `bandH`.** A altura da faixa é presa ao clipe (`bandH` +
  dissolução = altura natural dele a 1080 de largura); mudá-la para subir a
  costura recortaria ou ampliaria a arte. A fração onde a linha cruza a cabeça
  é `(focusY − topo) ÷ altura da cabeça` — o `bandH` e o zoom se cancelam, então
  `focusY` é a única alavanca honesta.
- **Não toca no corte.** Nada aqui altera `edl.json` nem `cut.mp4`; só a Fase 2
  re-renderiza.
- **Não decide sozinho.** Fração fora da janela aprovada vira aviso e, sem
  `--force`, recusa: o preview já mostrava o veredito ao vivo, e gravar um valor
  que o gate reprova desfaria o sentido de ter o gate.

Uso:
    uv run python helpers/seam_apply.py <edit-dir> [--apply] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seam_check


def carregar(edit: Path) -> tuple[dict, list[dict], Path]:
    edits = edit / "preview_edits.json"
    if not edits.is_file():
        sys.exit(f"preview_edits.json não encontrado: {edits}")
    dados = json.loads(edits.read_text())
    seam = dados.get("seam") or []
    if not isinstance(seam, list) or not seam:
        sys.exit("preview_edits.json não traz ajustes de costura (`seam`)")
    alvo = edit / "remotion" / "public" / "edit-data.json"
    if not alvo.is_file():
        sys.exit(f"edit-data.json não encontrado: {alvo}")
    return json.loads(alvo.read_text()), seam, alvo


def avaliar(item: dict, janela: dict, cut: Path) -> tuple[str, str]:
    """Veredito da costura com o focusY novo, medido do jeito do gate."""
    novo = float(item["focusY"])
    at = float(item.get("start", janela.get("start", 0))) + 0.5
    try:
        topo, base = seam_check.head_box(cut, at)
    except Exception as exc:  # noqa: BLE001 — sem detector não se bloqueia o ajuste
        return "SEM MEDIDA", f"não consegui medir o rosto em {at:.2f}s ({exc})"
    resultado = seam_check.seam_position(
        topo, base, novo, float(janela.get("zoom") or 1),
        float(janela.get("bandH") or 750), "top",
        float(janela.get("seamBlend") or seam_check.SEAM_BLEND))
    return resultado["verdict"], f"fração {resultado['fraction']} — {resultado['why']}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Grava no edit-data a costura ajustada no preview")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--apply", action="store_true", help="grava (sem isto, só mostra)")
    ap.add_argument("--force", action="store_true", help="grava mesmo com veredito reprovado")
    args = ap.parse_args()

    edit = args.edit_dir.expanduser().resolve()
    data, seam, alvo = carregar(edit)
    cut = edit / "cut.mp4"
    janelas = data.get("splitInserts") or []

    reprovados = 0
    mudancas: list[tuple[int, float]] = []
    for item in seam:
        ref = item.get("ref")
        if not isinstance(ref, int) or not 0 <= ref < len(janelas):
            print(f"IGNORADO  janela {ref} não existe neste edit-data")
            continue
        janela = janelas[ref]
        if (janela.get("layout") or "top") != "top":
            print(f"IGNORADO  janela {ref + 1}: só layout `top` tem geometria medida")
            continue
        antigo = float(janela.get("focusY") or 400)
        novo = float(item["focusY"])
        veredito, porque = (avaliar(item, janela, cut) if cut.is_file()
                            else ("SEM CORTE", "cut.mp4 ausente — não dá para medir"))
        marca = "ok    " if veredito in ("OK", "SEM MEDIDA", "SEM CORTE") else "REPROVA"
        if veredito not in ("OK", "SEM MEDIDA", "SEM CORTE"):
            reprovados += 1
        nome = (janela.get("src") or "").split("/")[-1] or f"janela {ref + 1}"
        print(f"{marca}  {ref + 1}. {nome:<26} focusY {antigo:.0f} → {novo:.0f}  [{veredito}] {porque}")
        mudancas.append((ref, novo))

    if not mudancas:
        sys.exit("nada a aplicar")
    if reprovados and not args.force:
        sys.exit(f"\n{reprovados} janela(s) com veredito reprovado — use --force se for deliberado")
    if not args.apply:
        print(f"\n(sem --apply: nada foi gravado) — {len(mudancas)} janela(s) prontas")
        return

    for ref, novo in mudancas:
        janelas[ref]["focusY"] = int(round(novo))
    tmp = alvo.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(alvo)
    print(f"\n{len(mudancas)} janela(s) gravadas em {alvo}")
    print("re-renderize a FASE 2 — o corte não muda")


if __name__ == "__main__":
    main()
