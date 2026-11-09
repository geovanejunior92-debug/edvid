# EDITS — ajuste do corte e acabamento no app da Meta

Leia este arquivo quando ele pedir o Edits ("abre no Edits", "ajustar no Edits",
"termina no Edits"). O contrato de corte é o mesmo do `references/concat.md`: o
`edl.json` manda e o Edits só decide onde cada take começa, termina e em que ordem
entra. Cor, J-cut, fades de 30ms, `gain_db`, concat lossless e Fase 2 seguem no
`render.py` e no Remotion.

## Quando usar

- **Preview do edvid:** continua sendo o primeiro caminho para trim e remoção,
  porque valida a borda contra `speech_regions.py`.
- **Edits:** ele quer mexer no app, no próprio Mac, com a biblioteca dele de efeitos,
  fontes, legendas e músicas.
- **Só a pedido.** O gate cita o Edits em uma linha (passo 9c), sem montar projeto:
  cada montagem cria um projeto na biblioteca dele. Não vale para o Formato 1.

## Os dois caminhos

**Volta para o edvid (padrão).** O corte volta para o `edl.json` e o vídeo final sai
do `render.py`.

1. `python3 helpers/edits_bridge.py open --edit-dir <edit>` cria o projeto, um clipe
   por take na trilha principal, e abre o app. Rodar de novo reusa o projeto.
2. Ele ajusta. Não precisa salvar: a volta lê a timeline aberta.
3. `python3 helpers/edits_bridge.py pull --edit-dir <edit>` reescreve o `edl.json`,
   com backup, e imprime o que mudou.
4. **Sempre:** `verify_cut.py` → `render.py` → gate. O Edits deixa cortar no meio de
   uma sílaba sem avisar, e a Hard Rule 4 não se suspende por isso.

**Acabamento no Edits.** Quando ele quiser o vídeo final saindo do app:
`python3 helpers/edits_bridge.py export --edit-dir <edit> [--out arquivo.mp4]`. Sai
**sem a cor, o J-cut e a Fase 2 do edvid**; diga isso antes de usar esse caminho.
A aceleração de 1,07× também não vem junto: aplique no Edits com `setSpeed` se ele
não pedir outra velocidade.

## O que a volta faz com o resto

- `grade`, `voice_master`, `jcut` e `sources` voltam intactos.
- `beat`, `quote`, `reason`, `gain_db` e `chapter` são herdados do take original com
  maior sobreposição na mesma fonte (`merge_back`).
- Borda não mexida guarda o valor exato: o app arredonda para o quadro do projeto.

**Bloqueia com mensagem:** clipe com mídia que não está em `sources`, e `edl.json`
que mudou depois da montagem (`open --rebuild` parte do corte atual; `pull --force`
descarta a outra edição).

**Só avisa, porque não cabe no `edl.json`:** velocidade, vão entre clipes e tudo fora
da trilha principal (texto, legenda, sobreposição, música).

## Fatos do app, medidos em 09/11/2026 (Edits 454.0.0)

- **Sandbox:** só abre o que está em `~/Movies`. Fora dali, a importação falha com
  "nothing imported" e abre um aviso na tela dele. A ponte põe as fontes em
  `~/Movies/edvid-edits/<projeto>-<id>/` por link físico, sem ocupar espaço. Em outro
  volume, ela copia e avisa. `edits_bridge.py clean` remove os links.
- **Contêiner do app:** o macOS bloqueia o acesso de fora (`Operation not permitted`).
  Não tente contornar.
- **Export:** o padrão sai em 1440×2560 HEVC, abaixo de uma fonte 4K. O preset só vale
  completo (`resolutionType`, `aspectRatio`, `quality`, `dynamicRange`, `frameRate`),
  e um preset parcial trava o export com "incomplete preset row". O `export` da ponte
  monta o preset pela fonte: 4K deu 2160×3840 a ~20 Mb/s. Não dá para pedir uma
  largura exata fora dessas faixas (720p, HD, 2K, 4K).
- **Inserção:** com `startTime` ou `sourceIn`, `addMediaPanelItemsToTimeline` cria
  trilha de sobreposição. O `seek` não passa do fim da timeline. Por isso a ponte
  insere o clipe inteiro, apara com `trim` e posiciona com `reorderClip`.
- **Tela define as ferramentas:** 32 na home, 274 no editor. O conjunto muda ao abrir
  um projeto.
- **Canvas:** só 9:16, 16:9, 1:1 e 4:5; só 24, 30 e 60 fps. Fonte a 59,94 fica em 60.
  Isso muda a grade do projeto, não a fonte.

## O MCP

O servidor do app fica em `http://127.0.0.1:19501/mcp` com token (Ajustes >
Automation). O Claude Code 2.1.271 rejeita o `tools/list` direto, porque o app manda
`resultType` sem `ttlMs` e `cacheScope`. Por isso o registro passa por
`helpers/edits_mcp_proxy.py`:

```bash
claude mcp add --scope user edits -- python3 ~/.agents/skills/edvid/helpers/edits_mcp_proxy.py
```

O token fica no item `edits-mcp-token` do Chaves. Se ele clicar em Regenerate:

```bash
security add-generic-password -U -s edits-mcp-token -a "$USER" -w <novo token>
```

Com as ferramentas `mcp__edits__*` o agente também pode analisar e acabar o vídeo no
próprio app: `transcribeClip`, `findPauses`, `quietPoint`, `loudness`, `detectShots`,
`detectSubjects`, `generateCaptions`, `setCaptionStyle`, `addTransition`, `applyEffect`,
`frameSheet`. As análises não substituem `transcribe.py`, `speech_regions.py` nem os
QCs do edvid; o caminho padrão continua sendo o deles.

**Não usar sem pedido:** `deleteProject` em projeto que a ponte não acabou de criar,
`startVoiceoverRecording` (liga o microfone), publicação ou música licenciada no
vídeo final.

## Onde as peças moram

| Peça | Caminho |
|---|---|
| App | `/Applications/Edits.app` (`com.burbn.basel.mac`) |
| Ponte do edvid | `helpers/edits_bridge.py` |
| Ponte MCP | `helpers/edits_mcp_proxy.py` |
| Testes | `tests/test_edits_bridge.py` |
| Estado, por vídeo | `<edit>/edits/built_from.json` |
| Última devolução | `<edit>/edits/last_return.json` |
| Fontes visíveis ao app | `~/Movies/edvid-edits/` |
