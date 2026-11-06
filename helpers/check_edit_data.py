"""Lint do `edit-data.json` ANTES de gastar o render da Fase 2.

É o equivalente do `verify_cut.py` para a Fase 2: mede o arquivo, não o vídeo
pronto. O `check_inserts.py` continua obrigatório e olha o MOVIMENTO e a
PROPORÇÃO dos clipes; este olha o TEMPO e as referências — a classe de defeito
que renderiza sem erro nenhum e só aparece quando alguém assiste.

Duas camadas:

1. **As invariantes que o Studio já sabia.** `studio_phase2.validate()` cobre
   fps/dimensões contra o `cut.mp4`, `durationSec` contra o corte + encerramento,
   legenda (via `caption_edit`) e asset ausente em `public/`. Essa validação só
   rodava por dentro do Studio: quem escreve o `edit-data.json` na mão e chama
   `npx remotion render` direto — o fluxo que a própria SKILL.md descreve —
   nunca passava por ela. Aqui ela vira linha de comando.

2. **O que ninguém media.** Janela fora do vídeo, janela invertida, duas janelas
   do mesmo tipo no mesmo instante (uma fica por cima da outra e some), flash ou
   som depois do fim, capa/logo/encerramento fora do corte, e efeito sonoro sem
   par visual — a regra dele de 2026-08-17, *todo efeito precisa cair num
   flash/corte*, que até agora vivia só na memória.

3. **Legenda e arquivos do bundle.** `caption-cues.json` vazio (o render sai sem
   legenda e sem erro), legenda sobre a tela de encerramento, vão longo entre
   blocos de texto quando a legenda está desligada, e JSON que o template importa
   de forma estática e não está em `public/` (o bundle quebra).

ERRO bloqueia (exit ≠ 0). AVISO é escolha editorial: aparece e deixa passar.

Uso:
    uv run python helpers/check_edit_data.py <edit-dir>
    uv run python helpers/check_edit_data.py <edit>/remotion/public/edit-data.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# Campos que descrevem uma JANELA (start/end em segundos do cut.mp4).
WINDOW_FIELDS = ("splitInserts", "inserts", "behind", "behindVideos", "graphics", "titleCards")
# Campos que descrevem um INSTANTE (`at`).
MOMENT_FIELDS = ("transitions", "sfxCues")
# Quanto um som pode ficar longe de um evento visual e ainda contar como "no corte".
SFX_PAR_VISUAL_S = 0.20
# Folga ao comparar com o fim do vídeo: um quadro a 24fps é 0.042s.
FIM_TOL_S = 0.05
# Sem legenda contínua, tempo sem texto na tela a partir do qual vale avisar.
VAO_TEXTO_S = 2.0
# Blocos de texto que substituem a legenda quando ela está desligada.
TEXTO_FIELDS = ("graphics", "titleCards")
IMPORT_PUBLIC = re.compile(r"""from\s+['"]\.\./public/([\w./-]+\.json)['"]""")


class Achado:
    __slots__ = ("nivel", "texto")

    def __init__(self, nivel: str, texto: str):
        self.nivel = nivel
        self.texto = texto


def _num(valor) -> float | None:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _janela(item: dict) -> tuple[float | None, float | None]:
    """start/end de uma janela, aceitando `end` ou `duration`/`durationSec`."""
    start = _num(item.get("start", item.get("startSec")))
    end = _num(item.get("end", item.get("endSec")))
    if end is None and start is not None:
        dur = _num(item.get("duration", item.get("durationSec")))
        if dur is not None:
            end = start + dur
    return start, end


def _rotulo(campo: str, i: int, item: dict) -> str:
    src = item.get("src") or item.get("kind") or item.get("type") or ""
    return f"{campo}[{i}]" + (f" ({src})" if src else "")


def checar_tempos(data: dict) -> list[Achado]:
    """O lint de TEMPO — o que renderiza sem erro e estraga o vídeo."""
    achados: list[Achado] = []
    duracao = _num(data.get("durationSec"))
    if duracao is None or duracao <= 0:
        return [Achado("ERRO", "durationSec ausente ou inválido — sem ele nada mais pode ser medido")]
    limite = duracao + FIM_TOL_S

    eventos_visuais: list[float] = []
    janelas_por_campo: dict[str, list[tuple[float, float, str]]] = {}

    for campo in WINDOW_FIELDS:
        itens = data.get(campo)
        if not isinstance(itens, list):
            continue
        validas: list[tuple[float, float, str]] = []
        for i, item in enumerate(itens):
            if not isinstance(item, dict):
                achados.append(Achado("ERRO", f"{campo}[{i}] não é um objeto"))
                continue
            rot = _rotulo(campo, i, item)
            start, end = _janela(item)
            if start is None or end is None:
                achados.append(Achado("ERRO", f"{rot}: start/end ausente ou não numérico"))
                continue
            if start < 0:
                achados.append(Achado("ERRO", f"{rot}: começa em {start:.2f}s, antes do vídeo"))
            if end <= start:
                achados.append(Achado("ERRO", f"{rot}: termina em {end:.2f}s, antes de começar ({start:.2f}s)"))
                continue
            if start > limite:
                achados.append(Achado("ERRO", f"{rot}: começa em {start:.2f}s, depois do fim ({duracao:.2f}s) — nunca aparece"))
            elif end > limite:
                achados.append(Achado("AVISO", f"{rot}: termina em {end:.2f}s, {end - duracao:.2f}s depois do fim ({duracao:.2f}s)"))
            validas.append((start, end, rot))
            eventos_visuais.extend((start, end))
        janelas_por_campo[campo] = validas

    # Duas janelas do mesmo tipo no mesmo instante: uma cobre a outra em silêncio.
    for campo, validas in janelas_por_campo.items():
        for a, b in zip(sorted(validas), sorted(validas)[1:]):
            if b[0] < a[1] - 0.01:
                achados.append(Achado(
                    "ERRO",
                    f"{a[2]} e {b[2]} se sobrepõem ({b[0]:.2f}s < {a[1]:.2f}s) — uma fica por cima da outra"))

    for campo in MOMENT_FIELDS:
        itens = data.get(campo)
        if not isinstance(itens, list):
            continue
        for i, item in enumerate(itens):
            if not isinstance(item, dict):
                achados.append(Achado("ERRO", f"{campo}[{i}] não é um objeto"))
                continue
            at = _num(item.get("at"))
            if at is None:
                achados.append(Achado("ERRO", f"{campo}[{i}]: `at` ausente ou não numérico"))
                continue
            if at < 0 or at > limite:
                achados.append(Achado("ERRO", f"{campo}[{i}]: `at` {at:.2f}s fora do vídeo (0–{duracao:.2f}s)"))
            if campo == "transitions":
                eventos_visuais.append(at)

    # Regra dele (2026-08-17): som sem par visual é som solto. Aviso, não erro —
    # um efeito deliberadamente fora do corte é decisão editorial.
    for i, item in enumerate(data.get("sfxCues") or []):
        if not isinstance(item, dict):
            continue
        at = _num(item.get("at"))
        if at is None or not eventos_visuais:
            continue
        perto = min(abs(at - ev) for ev in eventos_visuais)
        if perto > SFX_PAR_VISUAL_S:
            achados.append(Achado(
                "AVISO",
                f"sfxCues[{i}] em {at:.2f}s não cai em flash nem em corte (o mais perto está a {perto:.2f}s)"))

    # Capa, logo e encerramento contra o fim do vídeo.
    for campo, chave in (("hook", "endSec"), ("hookStacked", "endSec"),
                         ("logo", "endSec"), ("outro", "startSec")):
        bloco = data.get(campo)
        if not isinstance(bloco, dict) or not bloco.get("enabled"):
            continue
        valor = _num(bloco.get(chave))
        if valor is None:
            achados.append(Achado("ERRO", f"{campo} ligado, mas `{chave}` ausente ou não numérico"))
        elif valor < 0 or valor > limite:
            achados.append(Achado("ERRO", f"{campo}.{chave} = {valor:.2f}s, fora do vídeo (0–{duracao:.2f}s)"))

    # Insert por cima da capa: ela desliza e segura até ~4s (memória do canal).
    capa = data.get("hookStacked") if isinstance(data.get("hookStacked"), dict) else data.get("hook")
    fim_capa = _num((capa or {}).get("endSec")) if isinstance(capa, dict) and capa.get("enabled") else None
    if fim_capa:
        for start, _end, rot in janelas_por_campo.get("splitInserts", []):
            if start < fim_capa - 0.01:
                achados.append(Achado(
                    "AVISO",
                    f"{rot} começa em {start:.2f}s, antes de a capa sair ({fim_capa:.2f}s)"))
    return achados


def _ler_cues(arquivo: Path) -> list[dict] | None:
    """Os cues de um JSON de legenda; None se o arquivo não existe ou não abre."""
    try:
        bruto = json.loads(arquivo.read_text())
    except (OSError, ValueError):
        return None
    cues = bruto if isinstance(bruto, list) else (bruto.get("cues") or bruto.get("captions") or [])
    return [c for c in cues if isinstance(c, dict)]


def _fim_do_cue_s(cue: dict) -> float | None:
    if "endMs" in cue:
        fim = _num(cue["endMs"])
        return None if fim is None else fim / 1000
    return _num(cue.get("end"))


def checar_legenda(edit_dir: Path, data: dict) -> list[Achado]:
    """Arquivo de legenda vazio e legenda por cima da tela de encerramento."""
    cap = data.get("captions")
    if not isinstance(cap, dict) or not cap.get("enabled"):
        return []
    achados: list[Achado] = []
    stacked = cap.get("style") == "stacked"
    arquivo = edit_dir / "remotion" / "public" / ("caption-cues.json" if stacked else "captions.json")
    cues = _ler_cues(arquivo)
    if stacked and not cues:
        # O scaffold traz o arquivo vazio: o render conclui sem uma legenda sequer.
        formato_1 = "FORMATO 1" in str(data.get("_preset", "")).upper()
        achados.append(Achado(
            "ERRO" if formato_1 else "AVISO",
            "legenda stacked ligada, mas caption-cues.json está vazio ou ausente — "
            "o render sai sem legenda; gere com caption_style.py"))
    outro = data.get("outro")
    inicio = _num(outro.get("startSec")) if isinstance(outro, dict) and outro.get("enabled") else None
    if inicio is not None:
        fins = [f for f in map(_fim_do_cue_s, cues or []) if f is not None and f > inicio + FIM_TOL_S]
        if fins:
            achados.append(Achado(
                "AVISO",
                f"{len(fins)} cue(s) de legenda invadem a tela de encerramento "
                f"(entra em {inicio:.2f}s; a última legenda vai até {max(fins):.2f}s)"))
    return achados


def checar_vaos_de_texto(data: dict) -> list[Achado]:
    """Legenda desligada e texto em blocos: os vãos que a legenda nunca teve."""
    cap = data.get("captions")
    if isinstance(cap, dict) and cap.get("enabled"):
        return []
    blocos = sorted(
        (start, end)
        for campo in TEXTO_FIELDS
        for item in (data.get(campo) if isinstance(data.get(campo), list) else [])
        if isinstance(item, dict)
        for start, end in [_janela(item)]
        if start is not None and end is not None and end > start)
    if not blocos:
        return []
    capa = data.get("hookStacked") if isinstance(data.get("hookStacked"), dict) else data.get("hook")
    fim_capa = _num(capa.get("endSec")) if isinstance(capa, dict) and capa.get("enabled") else None
    outro = data.get("outro")
    inicio_outro = _num(outro.get("startSec")) if isinstance(outro, dict) and outro.get("enabled") else None
    fim = inicio_outro if inicio_outro is not None else _num(data.get("durationSec"))

    achados: list[Achado] = []
    cursor = fim_capa or 0.0
    for start, end in blocos:
        if start - cursor > VAO_TEXTO_S:
            achados.append(Achado("AVISO", f"{start - cursor:.1f}s sem texto na tela, de {cursor:.2f}s a {start:.2f}s"))
        cursor = max(cursor, end)
    if fim is not None and fim - cursor > VAO_TEXTO_S:
        achados.append(Achado("AVISO", f"{fim - cursor:.1f}s sem texto na tela, de {cursor:.2f}s a {fim:.2f}s"))
    return achados


def checar_imports_estaticos(edit_dir: Path) -> list[Achado]:
    """JSON que o template importa direto: sem o arquivo, o webpack nem compila."""
    remotion = edit_dir / "remotion"
    src = remotion / "src"
    if not src.is_dir():
        return []
    nomes = {nome for fonte in src.rglob("*.ts*") for nome in IMPORT_PUBLIC.findall(fonte.read_text())}
    return [Achado("ERRO", f"public/{nome} não existe e o template o importa — o bundle da Fase 2 quebra")
            for nome in sorted(nomes) if not (remotion / "public" / nome).is_file()]


def checar_com_studio(edit_dir: Path, data: dict) -> list[Achado]:
    """As invariantes que o Studio já validava, agora também fora dele."""
    cut = edit_dir / "cut.mp4"
    if not cut.is_file():
        return [Achado("AVISO", "cut.mp4 não encontrado — fps, dimensões, duração e assets não foram conferidos")]
    try:
        import studio_phase2
    except ImportError as exc:
        return [Achado("AVISO", f"studio_phase2 indisponível ({exc}) — só o lint de tempo rodou")]
    try:
        projeto = studio_phase2.StudioPhase2(edit_dir.parent)
    except studio_phase2.Phase2Error as exc:
        return [Achado("AVISO", f"não deu para montar o projeto do Studio ({exc}) — só o lint de tempo rodou")]
    if projeto.edit.resolve() != edit_dir.resolve():
        return [Achado("AVISO", "a pasta de edição não se chama `edit/` — as checagens do Studio foram puladas")]
    try:
        projeto.validate(data)
    except studio_phase2.Phase2Error as exc:
        return [Achado("ERRO", str(exc))]
    except Exception as exc:  # noqa: BLE001 — validação de terceiro não pode derrubar o lint
        return [Achado("AVISO", f"a validação do Studio não completou ({exc})")]
    return [Achado("ok", "fps, dimensões, duração, legenda e assets conferem com o cut.mp4")]


def resolver(alvo: Path) -> tuple[Path, Path]:
    """Aceita o edit-dir ou o próprio edit-data.json; devolve (edit_dir, arquivo)."""
    alvo = alvo.expanduser().resolve()
    # Decidir pelo SUFIXO, não pela existência: um edit-dir com erro de digitação
    # não é um diretório, e tratá-lo como arquivo dava uma mensagem sobre um
    # caminho que o usuário nunca escreveu.
    if alvo.suffix.lower() == ".json":
        # .../<edit>/remotion/public/edit-data.json
        return alvo.parent.parent.parent, alvo
    return alvo, alvo / "remotion" / "public" / "edit-data.json"


def main() -> None:
    ap = argparse.ArgumentParser(description="Confere o edit-data.json antes do render da Fase 2")
    ap.add_argument("alvo", type=Path, help="o edit-dir ou o próprio edit-data.json")
    ap.add_argument("--json", action="store_true", help="saída em JSON")
    args = ap.parse_args()

    edit_dir, arquivo = resolver(args.alvo)
    if not arquivo.is_file():
        sys.exit(f"edit-data.json não encontrado: {arquivo}")
    try:
        data = json.loads(arquivo.read_text())
    except json.JSONDecodeError as exc:
        sys.exit(f"edit-data.json não é JSON válido: {exc}")
    if not isinstance(data, dict):
        sys.exit("edit-data.json precisa conter um objeto")

    achados = (checar_com_studio(edit_dir, data) + checar_tempos(data)
               + checar_imports_estaticos(edit_dir) + checar_legenda(edit_dir, data)
               + checar_vaos_de_texto(data))
    erros = [a for a in achados if a.nivel == "ERRO"]
    avisos = [a for a in achados if a.nivel == "AVISO"]

    if args.json:
        print(json.dumps({"file": str(arquivo), "errors": [a.texto for a in erros],
                          "warnings": [a.texto for a in avisos]}, ensure_ascii=False, indent=2))
    else:
        for a in achados:
            print(f"{a.nivel:<6} {a.texto}")
        if not erros and not avisos:
            print("ok     nada a apontar")
        print(f"\n{len(erros)} erro(s), {len(avisos)} aviso(s) — {arquivo}")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
