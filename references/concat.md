# CONCAT — ajuste fino do corte no editor nativo

Leia este arquivo quando ele pedir o Concat ("abre no Concat", "ajustar no
editor do Mac"). O contrato é o mesmo do `references/opencut.md`: o `edl.json`
manda e o Concat só decide onde cada take começa, termina e em que ordem entra.
Cor, J-cut, fades de 30ms, `gain_db`, concat lossless e Fase 2 seguem no
`render.py` e no Remotion.

## Quando usar

- **Preview do edvid:** continua sendo o primeiro caminho para trim e remoção,
  porque valida a borda contra `speech_regions.py`.
- **Concat ou OpenCut:** reordenar takes e recuperar material descartado.
- **Concat em vez de OpenCut:** fonte grande. A mídia fica no disco, sem cópia
  para o navegador, e não há servidor local para manter no ar.

## Testando os dois

Desde 2026-11-06 o gate oferece OpenCut e Concat juntos (passo 9c do SKILL.md),
até ele decidir qual fica. Exceção: Formato 1, que não oferece nenhum.

Os dois editam o mesmo `edl.json`, então **depois de uma volta o outro fica
desatualizado**:

- Voltou do OpenCut ou do preview: o `pull` do Concat recusa, em vez de apagar o
  ajuste. Rode `open --rebuild` para partir do corte atual. `pull --force` existe
  só para quando ele quiser mesmo descartar a outra edição.
- Voltou do Concat: o botão Devolver do OpenCut não tem essa trava. Reimporte pela
  URL antes de editar lá de novo.

## O ciclo

1. `python3 helpers/concat_bridge.py open --edit-dir <edit>` monta
   `<edit>/concat/corte` (um clipe por take, com o `beat` como nome, na resolução
   e no fps da primeira fonte) e abre o app.
2. Ele ajusta e salva com **Cmd+S**. A volta lê o arquivo salvo; o que não foi
   salvo não existe para ela.
3. `python3 helpers/concat_bridge.py pull --edit-dir <edit>` reescreve o
   `edl.json`, com backup em `edl.json.bak-<timestamp>`, e imprime o que mudou.
4. **Sempre:** `verify_cut.py` → `render.py` → gate. O Concat deixa cortar no meio
   de uma sílaba sem avisar, e a Hard Rule 4 não se suspende por isso.

Rodar `open` de novo reusa o projeto, para não perder o que foi arrastado. Se o
`edl.json` mudou por outro caminho, ele avisa; aí use `open --rebuild`, que guarda
o projeto antigo em `corte.bak-<timestamp>`.

## O que a volta faz com o resto

- `grade`, `voice_master`, `jcut` e `sources` voltam intactos.
- `beat`, `quote`, `reason`, `gain_db` e `chapter` são herdados do take original
  com maior sobreposição na mesma fonte (`merge_back`, a mesma do OpenCut).
- Borda não mexida guarda o valor exato do `edl.json`.

**Bloqueia com mensagem:** vídeo em mais de uma trilha e mídia que não está em
`sources`.

**Só avisa, porque não cabe no `edl.json`:** velocidade, títulos, legendas e
efeitos ficam só no Concat; vão entre clipes é fechado.

## Limites

- Exportar pelo Concat não passa pelo pipeline: sai sem a cor, o J-cut e a Fase 2
  do edvid. O vídeo final continua saindo do `render.py`.
- O MCP do Concat só escreve dentro da pasta pessoal. Projeto em disco externo
  precisa de `CONCAT_MCP_ROOTS`.
- O app é beta e tem assinatura ad hoc. Baixe releases novos com `gh release
  download` e confira o `SHA256SUMS`.

## Licença

O Concat é AGPL-3.0. A ponte fala com o binário por MCP, em processo separado.
Não copie código dele para o edvid sem rever a licença.

## Onde as peças moram

| Peça | Caminho |
|---|---|
| App | `/Applications/Concat.app` (ou `CONCAT_BIN`) |
| Ponte | `helpers/concat_bridge.py` |
| Testes | `tests/test_concat_bridge.py` |
| Projeto, por vídeo | `<edit>/concat/corte` |
| Última devolução | `<edit>/concat/last_return.json` |
