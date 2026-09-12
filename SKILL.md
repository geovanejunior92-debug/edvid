---
name: edvid
description: Conversation-driven video editing for short-form vertical (Reels, TikTok, Shorts) and longform horizontal video. Use when asked to cut, grade, caption, add graphics, create a soundtrack, transcribe, or prepare video edits. Run Phase 1 (audio-led clean cut and grade), obtain approval, then build Phase 2/3 Remotion visuals and audio.
---

# Edvid

## Abertura padrão — versão web

Quando o usuário pedir apenas para “abrir o Edvid”, abrir sempre o Edvid Preview
web no navegador interno do agente, na tela para iniciar um vídeo novo. Não abrir
o aplicativo nativo Edvid Studio nesse caso. O aplicativo só deve ser aberto
quando o usuário disser explicitamente “aplicativo”, “Edvid Studio” ou
equivalente. No Preview web, a raiz `/` continua sendo a abertura padrão; projeto
antigo só abre quando for pedido pelo nome.

## Aplicativo próprio Edvid Studio

Para abrir, compilar ou diagnosticar o aplicativo local do usuário, leia `desktop/README.md`. O Studio usa este mesmo motor compartilhado entre Astra e Claude; não confundir com o aplicativo comercial Edvid. A versão inicial oferece apenas as operações expostas e testadas na interface. Não declarar paridade integral nem geração/publicação integrada. Antes de alterar um projeto, conferir a fila do Studio e evitar dois escritores simultâneos.

Para finalizar pelo painel local do Studio, leia `docs/STUDIO-FINISH.md` e `docs/STUDIO-STATUS.md`. O perfil manual não substitui o Formato 1/Remotion; QC aprovado não comprova revisão visual integral.

Para gerar música no Studio ou recuperar uma tarefa Treblo, leia `docs/TREBLO.md`. Confirmar o uso de créditos por geração; cancelamento local não garante cancelamento remoto. Não repetir automaticamente uma solicitação de resultado incerto.

## Título e mixagem escolhidos no preview

Ao consumir preview_style.json, aplicar headlineText a hook.lines (vazio preserva o anterior). Para audioMix, partir das faixas isoladas da mixagem-base, aplicar os offsets de voz/trilha/efeitos uma vez e manter verificação de loudness e sincronismo. `helpers/preview_mix.py` oferece validação, atualização do título e mistura em WAV novo; ver docs/PREVIEW-COMPARTILHADO.md. Atualizar state.style com as escolhas efetivamente aplicadas após render, para a interface reabrir com os valores corretos. Não apresentar sliders como separação de áudio pronto nem como prévia isolada ao vivo.

## Mídia marcada na timeline

Ao aplicar `preview_edits.json`, conferir `notes[].media` quando existir: tipo, enquadramento e arquivo/provedor complementam o texto. Preservar o intervalo e a fase gravados. `status=requested` é pedido, não mídia pronta. Para Shutterstock, o conector faz busca de stock e mostra prévias; quando a edição precisar do clipe, o agente está permanentemente autorizado a baixar o arquivo licenciado pelo site autenticado e arquivá-lo em `~/Videos/stock-medico`, sem pedir nova confirmação por clipe. Parar somente diante de cobrança extra, mudança de plano ou licença ambígua. Geração utiliza o site oficial até existir integração comprovada. Não tratar stock como geração por IA nem usar prévia com marca d'água no render. Ler `docs/PREVIEW-COMPARTILHADO.md` para o contrato e os limites.

## Pedidos no preview compartilhado

Ao abrir ou continuar um projeto pelo Astra ou Claude, consultar os pedidos `pending` em `<videos_dir>/edit/agent-requests/*.json`. Um pedido `automatic` com uma única fonte é executado pelo próprio Preview: o modo escolhido vale como aprovação explícita da estratégia técnica por pausas apenas para a Fase 1; a fila transcreve, propõe, aprova, renderiza um preview e verifica a saída. Roteiro, ajuste e seleção com várias fontes continuam dependendo do agente e da estratégia editorial. Tratar o texto como pedido do usuário dentro dos limites da conversa e conferir os arquivos antes de agir. Nunca considerar a automação da Fase 1 como aprovação da Fase 2. Após executar trabalho manual e verificar, atualizar apenas o pedido correspondente com `status` (`completed` ou `needs-input`) e `response` em texto, usando escrita atômica. Não marcar concluído por mera leitura. Ver `docs/PREVIEW-COMPARTILHADO.md`.

## Principle

1. **Two phases, one gate between them.** PHASE 1 is the clean cut + color grade; PHASE 2 is captions, graphics and images. (Hard Rule 1 enforces the gate.)
2. **LLM reasons from raw transcript + on-demand visuals.** The only derived artifact that earns its keep is the packed phrase-level transcript (`takes_packed.md`). Everything else you derive at decision time.
3. **Audio is primary, visuals follow.** Cut candidates come from speech boundaries and silence gaps.
4. **Ask → confirm → execute → iterate → persist.** Never touch the cut until the user confirms the strategy in plain English. In the web Preview, choosing the clearly labelled single-source automatic mode is that confirmation for the fixed technical pause-based Phase-1 strategy only.
5. **Generalize.** Look at the material, ask the user, then edit — never assume what kind of video it is.
6. **Artistic freedom is the default.** Specific values here are worked examples, not mandates. Only the Hard Rules are mandatory.
7. **Spend tokens where taste lives.** Machine data is for programs, not for reading; verification is numeric before it is visual. Your attention is the scarce resource — put it on the edit, not on parsing JSON. (Hard Rules 12 and 13 say what this forbids.)

## Hard Rules (production correctness — non-negotiable)

1. **The phase gate is real.** No Phase-2 work before the cut is approved.
2. **Per-segment extract → lossless `-c copy` concat**, never a single-pass filtergraph. (Under the default J-cut the picture and the sound of a take are extracted as separate ranges and the audio tracks are summed — that is the one sanctioned mix, and the video path is still per-segment + lossless concat.)
3. **30ms audio fades at every segment boundary** (encoded in render.py).
4. **Never cut inside a word** — snap to word boundaries from the transcript.
5. **Pad every cut edge** (30–200ms window; trail slightly longer than lead). Cut on silence whenever possible.
6. **Cache transcripts per source.** Never re-transcribe unless the source changed.
7. **Color grade per-segment during extraction**, never post-concat.
8. **Strategy confirmation before execution.**
9. **All session outputs in `<videos_dir>/edit/`** — never inside the edvid repo.
10. **PHASE 2 is Remotion-only** — no ffmpeg/PIL burned text or overlays.
11. **PHASE 2 is data-driven.** Scaffold by copying the track template; describe the video in `public/edit-data.json`. **Never read or edit the template TSX** (`src/Main.tsx` etc.) — the only editable code file is `src/CustomGraphics.tsx`, only for bespoke graphics. *(O template ganhou em 2026-09-11 o estilo de headline `personalizada`, autorizado pelo usuário, justamente para NÃO precisar editá-lo por vídeo: cor, peso, teto de tamanho e distância do topo chegam pelo `edit-data.json`. A regra segue valendo — aparência livre é dado, não código de projeto.)*
12. **Verify numerically first.** Run `verify_cut.py` on every rendered cut; open images only for flagged junctions. Batch any multi-frame look into one `contact_sheet.py` / `grade.py --candidates` montage.
13. **Never Read machine data into context**: `transcripts/*.json` (raw), `captions.json`, `track.json`, `segments.json`, matte/track binaries. Read `takes_packed.md` and helper stdout instead.

## Execution medium — ffmpeg pipeline (default), Adobe Premiere (MCP), OpenCut (timeline)

The default engine is the ffmpeg/Remotion pipeline below. **If the user asks for the
edit inside Adobe Premiere Pro via the `premiere-pro` MCP** ("edite a sequência no
Premiere", "corte via MCP"), the METHOD is unchanged — audio-primary, cut on
silence, phase gate, grade with taste — but the hands change: **read
`references/premiere-mcp.md`**. Transcription and `edl.json` are identical and
cached, so reuse an approved EDL and skip `cut.mp4`/preview.

**Se ele quiser ARRASTAR o corte numa timeline** ("abre no OpenCut", "quero
ajustar na timeline", "deixa eu mexer nas bordas vendo o material") — read
`references/opencut.md`. O OpenCut roda local em `localhost:3000` e a ponte é
`helpers/opencut_bridge.py`: leva o `edl.json` pra uma timeline de verdade e
traz os ajustes de volta pro mesmo `edl.json`, preservando grade, J-cut e os
metadados de cada take. **Antes de mandar pra lá, lembre que o preview padrão já
tem trim e remoção de take** e valida a borda nova contra `speech_regions.py`;
o OpenCut ganha dele em reordenar takes e em ver o material descartado ao
esticar um take, e perde na validação. Toda devolução volta pro fluxo normal:
`verify_cut.py` → `render.py` → gate.

## Directory layout

```
<videos_dir>/
├── <source files, untouched>
└── edit/
    ├── project.md               ← memory; appended every session
    ├── takes_packed.md          ← phrase-level transcripts, the primary reading view
    ├── edl.json                 ← cut decisions (Phase 1)
    ├── transcripts/<name>.json  ← cached word-level transcripts (WhisperX, local)
    ├── clips_graded/            ← per-segment extracts with grade + fades
    ├── cut.mp4                  ← PHASE 1 output: clean graded cut (approval artifact)
    ├── verify/                  ← montages / flagged-boundary views
    ├── captions.srt + chapters.txt   ← longform deliverables
    ├── final.mp4                ← delivered render (Phase 2 + 3, loudnorm'd)
    └── remotion/                ← Remotion project (Phase 2 + 3)
        ├── public/              ← cut.mp4, edit-data.json (THE edit), captions.json,
        │                          track.json, segments.json, pexels/ web/ brand/, sfx/, trilha.mp3
        └── src/                 ← immutable template code + CustomGraphics.tsx
```

## Setup

First-time install lives in `install.md`. On cold start just verify:

- **Transcription needs NO API key.** WhisperX ships as a dependency: `uv sync` is the whole install. It transcribes with Whisper and then runs FORCED ALIGNMENT (wav2vec2) against the waveform, so word times are measured, not inferred — 93% of words land inside a real speech region and the end of speech is placed within 10ms (measured against `speech_regions.py`). Models download once on first run and cache. Speed is ~realtime and improves with length (loading the model is a fixed ~18s: a 16s clip took 23s, a 166s source took 109s).
- A `/UNALIGNED` suffix in `_transcription_backend` means no wav2vec2 model existed for the detected language, so the word times are the decoder's own — coarse, and not safe for Phase-2 karaoke captions. Say so if it happens.
- `ffmpeg` + `ffprobe` on PATH; Python deps (`uv sync`); Node 18+ for Phase 2. `yt-dlp` ships with the Python deps, so URL sources need no extra install.
- The `remotion-best-practices` skill for Phase-2 domain knowledge (install from https://github.com/remotion-dev/skills if missing).
- Phase 2/3 can use optional API keys (illustrative images, AI soundtrack). They are listed in the track reference, asked for lazily when the feature is first used, and never at install time. **Nothing in Phase 1 needs a key.**

Helpers live in `helpers/`, resolved relative to this SKILL.md (shared installation at `~/.agents/skills/edvid/`, with `~/.claude/skills/edvid/` pointing there). Run them as `uv run python helpers/<name>.py` — a bare `python` misses the `.venv` that `uv sync` builds.

## Helpers

Phase 1:
- **`ingest_url.py <url> --dest <videos_dir> [--section 12:00-25:30] [--max-height 1080]`** — edit from a link: yt-dlp → MP4 (≤1080p) straight into the videos dir; from there it's a source like any other. `--section` downloads ONLY a time range of a longform source (keyframe-accurate) — the cheap way to clip minutes 12–25 of a 1h video. `--simulate` prints title/duration/resolution without downloading (confirm before big fetches; run those in the background).
- **`transcribe.py <video> --edit-dir <edit> [--language pt] [--model large-v3-turbo]`** — word-level, cached, local (WhisperX + forced alignment). No cap, no chunking. Pass `--language` when you know it — auto-detect costs a pass and can pick wrong on a short clip.
- **`parakeet.py <video> --edit-dir <edit> [--bench]`** — transcricao RAPIDA (Parakeet TDT 0.6B v3 em ONNX, 2026-09-10): **16-21x tempo real** contra ~1x do `transcribe.py`, medido em 60 min de aula; 41 min sairam em 130 s. Mesmo schema, entao `pack_transcripts.py`, o EDL e as legendas consomem sem saber qual motor rodou. Use-o como PADRAO em fonte longa. **NAO use para legenda karaoke nem para borda de corte** — sai marcado `/UNALIGNED`, a mesma convencao do WhisperX sem wav2vec2. Medido contra o `speech_regions.py` (2026-09-10): **88,4%** dos inicios caem dentro de fala real, com a linha de base do acaso em **80,8%** e o WhisperX em **93%** — ou seja, so 7,6 pontos acima do acaso contra 12 do WhisperX. Serve para LER a transcricao, escolher trecho e pesquisar fala. Para karaoke e para fechar EDL, rode o `transcribe.py`. **O que ele NAO da:** a borda de palavra e menos precisa, porque o transdutor comprime a pausa — o helper reconstroi a linha do tempo pelo silencio acustico (sem isso, 864 palavras viravam 3 frases), mas a frase sai mais grossa que a do WhisperX. Para decidir borda de corte nada muda: quem manda e o `speech_regions.py`, como a regra 4 sempre exigiu. Precisa do modelo em `~/Library/Application Support/Edvid/cache/parakeet` ou `--model-dir`; sem ele, cai no `transcribe.py`.
- **`transcribe_batch.py <videos_dir>`** — every source in a directory, one at a time (local inference already uses every core). Per-file cached, and a failure on one source doesn't lose the ones already done.
- **`pack_transcripts.py --edit-dir <dir>`** — transcripts → `takes_packed.md` (phrase-level, breaks on ≥0.5s silence). **The** reading view: 1/10 the tokens of raw JSON.
- **`speech_regions.py <video>`** — acoustic speech intervals via silencedetect. The source of truth for cut EDGES (Whisper times drift/stretch). Answers *where* speech is — never *how loud* it is.
- **`voice_levels.py <video> [--edit-dir <dir>] [--edl edl.json] [--drop-db 5]`** — the source of truth for speech LEVEL. Flags every phrase, run and EDL range ≥5 dB under the speaker's own median and sizes a `gain_db`. It catches what nothing else does: a whispered aside where the transcript is perfect, `speech_regions` says "speech" and `verify_cut` finds no fault — and the viewer still cannot hear it. **Run it before writing the EDL.**
- **`audio_clean.py <source> --edit-dir <edit> [--denoise rnnoise|demucs|both|off] [--no-breath] [--no-level] [--no-bed]`** — cadeia de diálogo aplicada UMA vez por fonte e cacheada (`<edit>/audio_clean/<stem>.wav`): denoise RNNoise (~140× tempo real; Demucs isola a voz quando há música/trânsito/outra voz por baixo, ~2× tempo real), respirações entre palavras a −14 dB, nivelamento por frase para a mediana da própria voz (+6/−3 dB) e uma cama de tom de sala extraída do original para as pausas não virarem preto digital. Precisa do transcript para respiração e nivelamento. **Não substitui `gain_db`**: o nivelador ajusta frase, o `gain_db` ajusta take.
- **`check_audio.py <source> --edit-dir <edit>`** — **gate da limpeza**: SNR, nível da voz (não pode cair >2 dB), agudos 4–12 kHz (abaixo de 0,55× é o som "debaixo d'água"), espalhamento entre frases e energia das respirações, sempre original × limpo nos MESMOS trechos. Exit ≠ 0 = não use o WAV. Escreve `<stem>.ab.wav` (8 s original → 8 s limpo, para ele ouvir) e `<stem>.ab.png` (espectrogramas empilhados, para você olhar).
- **`shot_check.py <edit>/edl.json [--no-edges] [--json]`** — o lado da IMAGEM do pré-scan, direto na fonte, antes do render: **bordas** (olho fechado ou gesto brusco no quadro exato do corte, com o deslocamento em frames sugerido dentro da folga da Hard Rule 5), **takes** (luma no rosto, razão R/G e B/G da pele e saturação de cada take contra a mediana dos takes: é o "pulo" visível na junção) e **quadro** (posição e tamanho do rosto entre takes, headroom, rosto não achado). Piscada por EAR com pontos do FAN, limiar relativo à mediana do trecho. Escreve `verify/shot_check.json`; exit ≠ 0 = há CHECK. É texto primeiro, como o `verify_cut.py`: abra imagem (timeline_view) só do que ele apontar. ~10 s por take em 4K.
- **`stabilize.py <source> --edit-dir <edit> [--mode lock|smooth] [--smooth 1.0] [--max-zoom 1.08] [--report]`** — estabilização em duas passagens (fluxo óptico na moldura do quadro → trajetória → correção com zoom fixo), UMA vez por fonte, cacheada em `<edit>/stab/<stem>.mp4` já na resolução de entrega. **`lock`** (padrão) trava a câmera como num tripé: é o modo para fala de frente segurada na mão. **`smooth`** só tira a tremida de uma câmera que se move de propósito. `--report` mede sem escrever: abaixo de ~0,35 px/quadro a fonte já é estável e não vale o zoom. O ffmpeg local NÃO tem vidstab; o `deshake` dele é de passagem única — por isso este helper existe. Validado com tremida sintética conhecida: 6,9 px/quadro → 0,5 (2026-09-01).
- **`scopes.py <video> [--at t] | --edl edl.json [--json]`** — waveform e vectorscope em NÚMERO: luma P1/P50/P99 em %, % esmagado no preto e estourado no branco, croma médio, ganhos de branco (gray-world) e a PELE do rosto (luma, ângulo em graus da linha de pele do vectorscope, croma, hue HSV). `--edl` dá a tabela por take. É o "verifique em número antes de olhar" aplicado à cor: um take com 3% estourado não se salva com LUT, e um −25° da linha de pele é verde antes de qualquer olho notar.
- **`match_takes.py edl.json [--ref N] [--apply | --clear]`** — **shot match**: mede cada take (luma da pele, R/G e B/G, croma) e escreve em cada range o `grade_pre` que o leva à mediana dos takes (ou ao take `--ref`): `exposure` em EV (teto ±0,7), `colorchannelmixer` para o branco, `eq=saturation`. Só acima do que o olho vê (3% luma, 2% branco, 6% croma). O `grade_pre` roda ANTES do look no `render.py`: primeiro casar, depois estilizar.
- **`grade_split.py cut.mp4 --matte fg.webm --bg "…" [--fg "…"] [--strength 0.8]`** — **power window rastreada**: um look para o fundo, outro para a pessoa, com o alpha do `person_matte.py` (a máscara segue a pessoa e tem borda de cabelo). Roda sobre o `cut.mp4` depois da Fase 1; o original fica em `.pre_split.mp4`. O uso clássico: fundo mais escuro e dessaturado para a pessoa saltar.
- **`reframe.py <final.mp4> --to 1:1 [--to 16:9] [--to 9:16] [--to 4:5] [--out-dir <edit>/formats] [--smooth 1.2] [--headroom 0.42]`** — **auto reframe**: o mesmo vídeo em outra proporção com a janela seguindo o rosto (YuNet a cada 4 quadros, caminho suavizado), não um crop central. De vertical para 16:9 a janela usa a largura toda e só sobe/desce; de 16:9 para vertical usa a altura toda e anda de lado. Roda DEPOIS da Fase 2 (legenda e capa viajam dentro da janela; um canto pode sair — confira com `contact_sheet.py`). Sai em `<edit>/formats/<stem>_1x1.mp4` etc.
- **`qc_final.py <edit>/final.mp4 [--platform reels|tiktok|shorts] [--premium]`** — **QC de entrega, o último gate antes de enviar** (2026-09-01): loudness I/LRA/true peak contra o alvo, quadros pretos, quadros congelados (≥2 s falha, 0,5–2 s avisa), níveis ilegais (Y<8 / Y>245), cada cue do `captions.json` contra a fala do áudio final (cue em silêncio, adiantada >300 ms, atrasada >700 ms), e **zona segura**: compara `final.mp4` com `cut.mp4` para achar onde a Fase 2 desenhou e quanto disso cai onde a interface do app fica por cima (coluna de ícones, faixa inferior, topo). Exit ≠ 0 = não envie; escreve `verify/qc_final.json`. Roda junto com o `review_final.py`: um assiste, o outro mede.
- **`retention.py <edit>/transcripts/cut.json [--candidates transcripts/<fonte>.json] [--ledger ~/Videos/retencao.jsonl --project X [--metrics …]]`** — **inteligência de retenção** (2026-09-01): gancho 0–10 com o porquê (densidade, ar morto antes da primeira palavra, número, pergunta, "você", contraste), ritmo por janela de 5 s contra a mediana do próprio vídeo (arrasto, silêncio), pausa mais longa, fecho (fala até o fim? CTA? frase completa?) e, com `--candidates`, as frases da FONTE que dariam gancho, pontuadas — para VOCÊ julgar e propor uma variante. `--ledger` grava as heurísticas do vídeo numa JSONL global; `--metrics` amarra a elas os números reais do Metricool.
- **`studio_doctor.py [--project <projeto>] [--json]`** — o que falta NESTA
  máquina, com o conserto escrito em cada linha. Checa ffmpeg/ffprobe, o venv e
  os pacotes, Node 18+, o modelo Parakeet, espaço em disco, a instalação
  compartilhada do Remotion e as dependências do projeto. Três estados:
  `faltando` impede uma função (exit ≠ 0), `aviso` funciona pior, `ok` funciona.
  **Não instala nada** — mexer na máquina é decisão do usuário.
- **`studio_pipeline.py --root <projeto> --action treat`** — a cadeia técnica do
  Studio sobre o EDL proposto: mede nível de voz, limpa o diálogo **com o gate
  do `check_audio` mandando** (reprovou → renderiza SEM limpeza e diz por quê,
  nunca com um WAV pior), liga estabilização só quando a tremida MEDIDA passa de
  0,35 px/quadro, e casa a cor entre tomadas escrevendo `grade_pre`. Grava
  `studio-pipeline/treatment.json` com o que foi aplicado e o que ficou
  bloqueado, e abre revisão nova — tratar muda o plano, então a aprovação
  anterior morre.
- **`script_align.py --script <roteiro> --transcript <t1.json> [t2.json …]`** —
  casa cada LINHA do roteiro com a transcrição e PROPÕE as tomadas. Linha
  gravada mais de uma vez volta com todas, ordenadas por semelhança e depois
  por menos vício de fala; linha que não foi gravada volta marcada; fala que
  existe e não está no roteiro volta como improviso. **Não escolhe sozinho e
  não decide borda** — os tempos são os das palavras, e quem manda em borda
  continua sendo o `speech_regions.py` (regras 4 e 5). Exit ≠ 0 quando há linha
  não encontrada. Roda no passo 2, junto do pré-scan, quando existe roteiro.
- **`fillers.py <edit>/edl.json [--apply [--only 1,3]] [--no-weak]`** — vícios de fala ("é", "né", "hum"; "tipo/assim/então" só isolados por pausa), repetições ("que que"), falsas partidas (frase curta reiniciada) e regiões de fala ÓRFÃS (som sem palavra no transcript, a falsa partida que o Whisper esconde). Lista com id e contexto; `--apply` divide os ranges nas bordas das palavras com 30 ms de folga (regra 4). Órfãs nunca são cortadas sozinhas: transcreva isolado e decida. Roda no passo 2 (pré-scan), antes de fechar o EDL.
Trilha de IMAGEM (post, carrossel, capa, thumbnail — 2026-09-10). Leia **`references/imagem.md`** quando o pedido for imagem estatica e nao video. Dois caminhos: **proprio** (padrao, gratis, offline) e **Canva via MCP** (quando depende do acervo de template dele, ou quando ele vai editar na mao depois). **O gate e do edvid nos dois** — o que sai do Canva volta e passa pelo mesmo `qc_image.py`.
- **`carousel.py <edit>/transcripts/cut.json --video cut.mp4 [--slides 6]`** — do corte aprovado para um esboco de `post-data.json`: pontua cada frase por densidade, numero, pergunta, contraste e "voce", e propoe capa + miolo + CTA com o instante do proprio video como fundo. **Propoe e lista; a escolha e editorial.** Quebra por PONTUACAO, nao por silencio: depois da Fase 1 o silencio ja foi removido (medido: 1 pausa >= 0,5 s num corte de 53 s, e quebrar por silencio dava 2 frases para o video inteiro).
- **`post_render.py <edit>/post-data.json [--formatos 4x5 1x1 9x16 16x9]`** — o `render.py` da imagem: o post inteiro descrito em JSON vira JPG em 1080x1350 / 1080x1080 / 1080x1920 / 1280x720. PIL, nao Remotion — para quadro estatico o Remotion so acrescenta Node e segundos por imagem. Escreve tambem `<imagem>.boxes.json` com onde cada texto caiu, que e o que o gate le.
- **`qc_image.py <edit>/post [--plataforma instagram|tiktok]`** — **GATE da imagem, exit != 0 = nao publique**: contraste WCAG do texto contra o fundo REAL sob a caixa, zona coberta pela interface do app (faixa de baixo, topo, coluna de icones), **texto em cima do rosto** (a frase para no cabelo — regra dele) e fonte pequena demais. Escreve `qc_image.json`.
- **`canva_brief.py <edit>/post-data.json --briefing | --receber <url>`** — ponte do caminho B. Monta o pedido para o `generate-design` e traz o arquivo exportado de volta para a pasta. Nao chama o Canva: ferramenta MCP quem chama e o agente. **Verificar a conexao com uma chamada de leitura antes** — o conector pode estar declarado e nao conectado.
- **`cover.py <final.mp4|cut.mp4> --text "…" [--accent-word X] [--window 0 15] [--at t]`** — capa do Reel: escolhe o melhor quadro por olho aberto (FAN), nitidez, tamanho e centro do rosto, e compõe a frase do gancho em Poppins ExtraBold com contorno (palavra de destaque em Playfair itálico dourada). Sai `cover.jpg` (9:16) e `cover_4x5.jpg` (feed). Imprime os 5 melhores instantes para você discordar.
- **`clipper.py transcripts/<fonte>.json --source <fonte> [--min 40 --max 75 --top 3]`** — de uma gravação longa, os N trechos que dão Reel: janelas de frase a frase pontuadas por gancho, densidade, número/pergunta/contraste, CTA e fecho em pontuação. Esboços de EDL em `<edit>/clips/clip_N/` + `clips.md`. Lista e pontua; a escolha é editorial.
- **`beats.py trilha.mp3 [--snap edit-data.json [--apply]]`** — batidas da trilha (fluxo espectral → tempo → grade) e ajuste do que é MOVÍVEL (flashes `transitions[].at`, `sfxCues[].at`, `graphics[].start`) para a batida mais próxima em ±120 ms. O corte não se move (é da fala). Diz também quantos cortes cairiam em batida se a trilha fosse deslocada.
- **`broll_suggest.py <edit>/edl.json [--apply-ledger]`** — para cada frase do corte, até 5 clipes do acervo local (`~/Videos/stock-medico`, pastas por tema) por palavra em comum; frases sem cobertura viram a lista de compras, já cruzada com o `PEDIDOS.md`; itens em aberto que já têm material no acervo são apontados (e marcados `[x]` com `--apply-ledger` — quem marca é o agente). Sai `<edit>/broll_suggest.md`. Roda no passo 10b antes de pedir qualquer coisa.
- **`diagnostics.py <edit>`** — junta audio_clean/check_audio, shot_check, match_takes e qc_final em `<edit>/diagnostics.json`, com os instantes já na linha do tempo do corte; o preview desenha o painel "Diagnóstico" a partir dele. Rode depois de cada gate, antes de abrir ou atualizar o preview.
- **`detect_color.py <video> [--json]`** — resolves NORMAL vs LOG from the file instead of asking — metadata first, image statistics when the metadata is silent (common: a transcode drops the tags). Returns profile, **confidence**, evidence and the `grade` to apply. Only `confidence: low` should send you back to the user; the identification detail is in `references/log-grade.md`.
- **`render.py <edl.json> -o cut.mp4 --no-subtitles [--audio-clean] [--stabilize] [--voice-master] [--keep-resolution] [--jobs N] [--no-jcut] [--jcut-lead N] [--jcut-tail-trim N]`** — per-segment extract (grade + fades, **parallel**) → **J-cut overlap assembly (default)** or lossless concat → optional voice master → loudnorm. Writes `jcut_timeline` into the EDL: the real output positions, which is what everything downstream must index off. Short-form fps is automatic: **30fps for 30fps+ sources, else 24** (longform keeps source fps via `--keep-resolution`). Set `edit-data.json` `fps` to match the resulting `cut.mp4`. **`--audio-clean`** (ou `"audio_clean": true` / `{"denoise": "demucs"}` no EDL) troca o som de cada segmento pelo WAV limpo do `audio_clean.py`, extraído pelo mesmo range, com os mesmos fades e o mesmo `gain_db`: a Hard Rule 2 não muda, só a entrada de áudio. **`--stabilize`** (ou `"stabilize": true` / `{"mode": "smooth"}` no EDL) faz o mesmo com a IMAGEM: os segmentos saem da cópia estabilizada, o som continua vindo da fonte ou do WAV limpo. Só use quando `stabilize.py --report` mostrar tremida acima de ~0,35 px/quadro; em tripé é zoom de graça.
- **`verify_cut.py <edl.json> <cut.mp4> [--min-silence 1.2]`** — numeric self-eval: duration, per-junction pop/clipped-word probes, dead air, black frames, clipping, **and range level balance** (each range's RMS vs the median range; `LOW-LEVEL` under −4 dB). ~350 tokens of text instead of N images. The range-balance line is the convergence test for a `gain_db` fix.
- **`check_luts.py <video> --edit-dir <edit> [--port N] [--quick]`** — health gate for the LUT picker, run right after `lut_thumbs.py`. Verifies `.cube` files parse, `lut3d` applies each one to the real video, every `LUT_CATALOG` id has a decodable thumbnail, and the server serves them (`--port`). Exits non-zero with one line per problem. `lut_thumbs.py` reporting success proves none of this: generation and delivery fail independently.
- **`grade.py <in> -o <out>`** — grade presets/raw filters. **`--candidates "a=<filter>;b=<preset>;original=" --frame <t> -o cmp.png`** renders N looks on the SAME frame into one labeled montage.
- **`timeline_view.py <video> <start> <end>`** — filmstrip+waveform PNG for ONE flagged spot, not a scan tool.
- **`contact_sheet.py <video> --times t1 t2 … -o sheet.png`** — N frames in one labeled grid; the way to eyeball several moments **you already know**.
- **`watch_video.py <video> [--mode scene|keyframe|uniform] [--times t1 t2 …] [--start/--end] [--max-frames 24]`** — "what is IN this footage?" when you *don't* know where to look: scene detection + perceptual dedup → labeled contact sheets in `edit/verify/watch_<stem>/`, one Read per sheet. For visual inventory of unknown material, and for surveying `cut.mp4` beyond verify_cut's numbers. `--times` pins transcript-cue frames: deictic moments from `takes_packed.md` ("olha isso", "como você pode ver") are LOW visual change and invisible to scene detection — pin them to decide B-roll/callout/zoom placement in Phase 2.

Phase 2/3 helpers (captions, face tracking, image search, music) are listed in
the track reference you load after the gate. One of them is not optional:

- **`caption_edit.py <captions.json> [--duration-ms N] [--outro-start-ms N] [--drop-after-ms N] [--apply]`**
  — o outro lado do `caption_fix.py`: TEMPO, divisão e junção de bloco, mais as
  invariantes que o render não checa. Separa **erro** (bloco vazio, tempo
  invertido, sobreposição, legenda passando do vídeo ou por cima do
  encerramento — exit ≠ 0) de **aviso** cosmético (palavra curta demais para o
  realce do karaokê pegar; artigos de 20ms existem e não bloqueiam). Funções:
  `retime`, `split`, `merge`, `shift` (é o que ressincroniza depois de um corte
  novo) e `drop_after`. **Rodado nas legendas reais do canal em 2026-09-12:
  achou 90 blocos vazios seguidos num projeto** — tempo sem texto na metade do
  vídeo, invisível até existir gate.
- **`caption_fix.py <edit> [--targets …] [--apply]`** — aplica os `textFixes[]`
  do preview a `transcripts/cut.json` e `remotion/public/captions.json`. Sem
  `--apply` só mostra o que faria. Mesma contagem de palavras → tempos
  intactos; contagem diferente → redistribuição por comprimento dentro do
  intervalo original, declarada na saída como aproximação. Corrigir o texto
  NUNCA move a legenda: o usuário está consertando o que foi ouvido, não
  quando foi dito.
- **`seam_check.py <video> --at T --band-h N --focus-y N --zoom Z`** — a costura
  cruza o alto da cabeça? Mede o topo da cabeça na fonte e aplica a
  transformação do template (`(y_src − focusY) * zoom + bandH` — **o `+ bandH`
  é o termo que inverte a conclusão se esquecido**). Exit ≠ 0 quando o efeito
  não acontece. Só `layout: top`; o `bottom` é recusado em vez de chutado.
- **`split_band.py <clipe…> [--frame-width N]`** — o `bandH` de cada clipe para
  a costura cair na borda inferior dele, que é o padrão de divisão do Formato 1
  generalizado para qualquer proporção. Avisa quando o valor sai do padrão (aí
  o `focusY` precisa ser recalibrado num still). Não calcula `focusY`.
- **`check_inserts.py <edit-data.json> [--min-motion 0.3]`** — **gate obrigatório
  antes de todo render da Fase 2.** Prova, por número, que cada insert de vídeo
  TOCA (não congelou por estar fora de uma `<Sequence>` ou por ser mais curto que
  a janela) e que ele cabe na faixa sem ser ampliado. Os dois defeitos são
  silenciosos e atravessaram um render inteiro até o usuário apontar
  (2026-08-16); ele pediu a verificação como tarefa fixa. Exit ≠ 0 = não renderize.

Interface:
- **`opencut_bridge.py serve --edit-dir <edit> [--port 4840]`** — abre o corte numa timeline do OpenCut e recebe os ajustes de volta no `edl.json` (com backup e resumo do que mudou). `status --edit-dir <edit>` mostra a última devolução. Detalhes e limites: `references/opencut.md`.
- **`preview_server.py --root <edit> [--port 4820]`** — serves the standard preview interface (see the Preview interface section). App code lives at `assets/preview/` and is IMMUTABLE.

## Preview interface (standard — launch it at the start of every edit)

**New video is the default:** `/` opens the library and the “Criar projeto e adicionar vídeos” form, never C014 or another previous project automatically. Ask for a project name and let the user select MOV/MP4/M4V/WEBM files (up to 8 GiB each). The browser copies only the selected files into a new isolated folder under `--library`; it never moves or reorganizes Desktop/Downloads. With exactly one imported video, the browser immediately submits the fixed automatic Phase-1 strategy and the server starts transcription, technical cut, preview render and verification in its durable background queue. Multiple videos open the source sequence and wait for an editorial strategy. Existing projects remain accessible by explicit choice. To show an existing edit deliberately, get its link from `/api/projects` or `/projects` and open `/p/<id>/`.

**Organizing the shelf (2026-09-11):** each card carries pin, rename and archive.
Pinned projects sort above everything else; renaming rewrites `state.json`'s own
`project` field (one project, one name — no second name to drift); archiving only
hides the card, behind an "Arquivados (N)" disclosure that can restore it, and
**never touches a file on disk**. Those two flags live in `<library>/.edvid-library.json`,
which is shelf state, not project state — copy a project folder elsewhere and it
carries its edit, not someone's ordering. `POST /api/projects/update` with
`{id, pinned?, archived?, name?}` is the one route. A root passed as `--root` that
has no `state.json` is no longer listed as a project: it is the placeholder the
server was pointed at, and listing it produced a permanent "PRECISA DE ATENÇÃO"
card that nothing could fix.

**Project library and recovery:** pass `--library <videos-library>` to `preview_server.py` to list existing projects at `/projects`. The default library is the active edit directory's parent. Each project opens at `/p/<id>/`; those URLs keep simultaneous tabs independent. Never copy another project's state over the active project to switch projects.

The preview distinguishes a first cut that does not exist yet, missing media in an existing project, processing and failures. Use "Buscar vídeos na biblioteca" to select an existing cut or final video, then "Localizar e recuperar". Recovery copies that file into the edit directory and backs up state; it does not edit or move the selected original. Never substitute raw footage for an approved cut. Recovery does not rebuild lost media. Pending edits and running work must finish before recovery.

`render.py`, the transcription CLI and the automatic Preview queue publish operation reports in `<edit>/.processing/`. The preview reports live work and interrupted/failed workers without inventing a percentage. The automatic queue claims only explicit single-source `automatic` requests, serializes work, records each stage in `agent-requests`, resumes interrupted active jobs after restart and leaves scripts, adjustments and multi-source selections to the agent. The existing phase-approval rules and host-specific save/apply flow below still apply.

Transcription cache entries are validated by source SHA-256, resolved source path, language and model. A changed source or parameters, an invalid JSON cache or a legacy entry without this identity triggers regeneration; unchanged inputs reuse the result. Failed transcription preserves the previous JSON. Never manually delete cached transcripts to force routine refresh.


Every edit session gets the same interactive interface in the user's preview panel: a video-editor timeline (video track with filmstrip + audio track with waveform), a live playhead that scrubs the render in real time, per-take trim handles and take removal, and — from Phase 2 — caption and insert tracks. The layout follows the source aspect on its own: **vertical** sources put a tall player on the right with the transport + timeline on the left; **horizontal** sources keep the player stacked above the timeline. Dark glass, Edvid brand. **Never build a UI per session** — feed the standard interface with `state.json`. Editing `assets/preview/` is allowed only when the user asks for a UI change; it is shared, so the improvement lands for every project.

**Launch (do this when a session starts, even before the first render — the UI shows a waiting state):**
1. Write `<edit>/state.json`:
   ```json
   {"project": "Nome — C0000", "phase": 1, "video": "cut.mp4", "edl": "edl.json",
    "captions": "remotion/public/captions.json", "editData": "remotion/public/edit-data.json",
    "finalVideo": "final.mp4", "fps": 24, "message": "Fase 1 — cortando",
    "sourceDurations": {"C0000": 1038.5},
    "awaitingStyle": false,
    "style": {"edit": "split", "captions": "karaoke",
              "elements": {"tracking": false, "zoomAuto": true, "zoomCuts": true,
                           "flashCut": true, "musicAI": false}}}
   ```
   (`captions`/`editData`/`finalVideo` only when they exist; the Fase-2 tab plays `finalVideo` — the render WITH captions/inserts — while Fase 1 plays the clean cut; `sourceDurations` lets the UI clamp take extensions; `awaitingStyle`/`style` drive the Estilo tab below. **`zoomAuto`, `zoomCuts` and `flashCut` are always `true`** — fixed elements, not picks; see the Estilo tab section.)
2. Select the runtime adapter; never invoke another host's tools.

   - **Claude Code:** ensure `.claude/launch.json` has the config (adjust `--root` per session). Use the shared environment that contains WhisperX, not the system Python: `{"name": "edvid-preview", "runtimeExecutable": "sh", "runtimeArgs": ["-c", "exec '<skill>/.venv/bin/python' '<skill>/helpers/preview_server.py' --root '<edit>' --port \"$PORT\""], "autoPort": true, "port": 4820}`. Run `preview_start` with name `edvid-preview`, then arm `Monitor(command="'<skill>/.venv/bin/python' '<skill>/helpers/watch_edits.py' '<edit>'", description="escolhas e marcações salvas no preview", persistent=true)` **in the same turn**.
   - **Codex desktop / CLI:** start `uv run python helpers/preview_server.py --root '<edit>' --port 4820` as a background local process when the environment can keep it alive. Once it responds, use the available browser tool to open `http://127.0.0.1:4820` in the in-app Browser automatically and leave that tab on the preview. Do not assume `preview_start`, `Monitor`, or `.claude/launch.json` exists. If the Browser capability or a persistent local process is unavailable, give the user the command and local URL instead. After showing the preview, tell the user to save and reply in this task. On every subsequent user message, before any other work, check for `preview_edits.json` and `preview_style.json`; read, validate, apply, then remove only `preview_edits.json`.

   A preview save must always lead to an agent-visible action: single-source automatic cuts run in the server queue; Claude Code uses the persistent watcher for editorial requests and Codex uses the user's next task message as that notification boundary.

When `--host 0.0.0.0` exposes the Preview to the local network, the server prints a bootstrap URL with a random token and requires its secure session cookie plus same-origin requests for every mutation. Share only that one-time link with the user's own device. Loopback `127.0.0.1` remains local-only.

**Preview aberto e vazio para sempre = permissão, não render.** On macOS the
privacy layer guards `~/Documents`, `~/Desktop`, `~/Downloads` and iCloud Drive:
an app that was never granted Files-and-Folders access gets `PermissionError
[Errno 1] Operation not permitted` writing `state.json`, and the UI then waits
on a file that will never appear. `preview_server.py` refuses to start on an
unwritable root and prints the fix — read that output instead of re-rendering.
**If the user says the permissions are already enabled, the answer is to restart
the Mac**: the permission cache goes stale and shows the toggle on while still
denying. Confirmed in production; nothing in Settings fixed it.

**Keep state.json fresh** — bump `phase` and `message` at each milestone (cut rendered, cut approved, Phase 2 rendered…). The UI polls and hot-reloads by itself; waveform + filmstrip regenerate automatically when cut.mp4 changes.

The timeline shows one track per KIND: markers, captions, video, audio (the mix),
**A1 / A2** (the J-cut takes), **text** overlays (hook), **images** (inserts + any
data-driven CustomGraphics windows), soundtrack. Anything you leave in code instead
of data simply will not appear.

**A1 / A2** are the J-cut takes, folded inside the audio track behind a caret that
only appears when the EDL carries a `jcut_timeline`. The hatched orange head on a
block is the lead — how much voice arrives before that take's picture.

**What the user can do in the UI:** scrub, trim take edges, delete takes, drag
insert/hook chips — and **mark correction ranges**: park the needle, press `M`
(or the IN button), move to the end of the problem, press `M` again — the note box
opens centred over the timeline — then type what should change. Many ranges per pass. Zoom: the slider is anchored on the needle, trackpad pinch
on the pointer. Shortcuts live behind the **?** button at the bottom right.

### The Estilo tab (between Fase 1 and Fase 2)

The cut is approved and nothing about the LOOK of Fase 2 is decided. **Do not ask
the style questions in chat** — the gate screen exists so the user SEES what each
style does, and a chat list of names asks them to choose blind. Set
`"awaitingStyle": true` in `state.json`; the UI opens its own tab and
`watch_edits.py` notifies you when they save `<edit>/preview_style.json`.

**Zoom e flash não estão nesse gate (decisão do usuário, 2026-08-16).**
`zoomAuto`, `zoomCuts` and `flashCut` stopped being options: they are fixed on
every video, appear as locked "sempre" chips in the tab, and the FIRST
`edit-data.json` written for Fase 2 already carries the camera zooms and the
`transitions[]` flashes. Never ask about them and never render a Fase 2 without
them.

The catalog of options and what each pick means is in the track reference, which
you read next anyway — **`references/shortform.md`**. Short-form only: the gate
has no longform vocabulary yet, so on a longform job skip `awaitingStyle` and ask
the layer questions in chat.

**Regra de layout do preview (2026-09-01, depois de uma regressão).** A
interface cabe na janela inteira sem rolagem de página (`body` é
`overflow: hidden`). Quem tem prioridade de altura é, nesta ordem: a
**timeline** (piso de 176px — é o instrumento de trabalho), o **transporte** e
o **player**. Painéis novos NÃO entram como terceira linha da `.stage`: viram
gaveta recolhível dentro da coluna do editor, nascem fechadas com um resumo de
uma linha no cabeçalho, e ao abrir tiram espaço do PLAYER, nunca da timeline.
Foi exatamente o erro cometido ao acrescentar o painel Diagnóstico: numa janela
de 881px de altura a timeline foi parar no pixel 857 e o diagnóstico no 1067,
ambos fora da tela. Ao mexer no layout, meça `document.documentElement.scrollHeight <= innerHeight`
e a posição da timeline nos DOIS modos (retrato e paisagem) e com as gavetas
abertas e fechadas — o retrato inverte os papéis do flex (lá quem cresce é a
coluna do editor, não o player).

**Faixa de transcrição e painel Diagnóstico (2026-09-01).** A interface tem
uma faixa com cada palavra do corte (lê `transcripts/cut.json`, ou
`captions.json` quando só ele existe): ele clica numa palavra e noutra, a
barra oferece "cortar este trecho", e o save traz `textCuts[]`. Para a faixa
existir na Fase 1, **transcreva o `cut.mp4` logo depois do render**
(`transcribe.py cut.mp4 --edit-dir <edit>` → `transcripts/cut.json`; é o
mesmo arquivo que a Fase 2 já usa). Abaixo da timeline, o painel Diagnóstico
mostra o que os gates mediram, lido de `diagnostics.json`: **rode
`diagnostics.py <edit>` depois de cada gate** (check_audio, shot_check,
match_takes, qc_final) — sem ele o painel não aparece, e a agulha vai para a
borda apontada com um clique.

**When the user saves timeline edits**, the UI writes `<edit>/preview_edits.json`
(never touches edl.json) and `watch_edits.py` notifies you automatically. To apply:
- `textCuts[]` (2026-09-01, edição pelo texto) — trechos que ele riscou na
  faixa de transcrição do preview: `{start, end, renderedStart, renderedEnd,
  text}`. Cada um é um corte DENTRO de um take: mapeie o par rendered → fonte
  (jcut_timeline/segments.json), divida o range nas bordas das palavras com
  30 ms de folga e valide com `speech_regions.py` — exatamente o que o
  `fillers.py --apply` faz, e ele aceita a mesma lista via `--from-preview`.
- `textFixes[]` (2026-09-11, correção de texto da legenda) — palavras que a
  transcrição ouviu errado (nome de remédio, termo médico), cada uma
  `{renderedStart, renderedEnd, start, end, from, to}`. **Aplique com
  `caption_fix.py <edit> --apply`** — é correção de TEXTO, nunca de tempo:
  mesma contagem de palavras preserva cada timing ao milissegundo, contagem
  diferente redistribui dentro do MESMO intervalo e o helper diz que
  redistribuiu. Depois disso, regenere as legendas e re-renderize a **Fase 2**
  (o `cut.mp4` não muda — nada aqui mexe no EDL). Correção vazia é recusada:
  apagar fala é corte (`fillers.py --from-preview`), não correção.
- `notes[].media.layout` (2026-09-11) — **a tela dividida agora é criada na
  interface**, não descrita no chat. Quatro valores, e cada um é um destino
  diferente no `edit-data.json`:
  - `fullscreen` → insert full-bleed, como sempre.
  - `split-top` → `splitInserts[]` com `layout: "top"` (arte em cima).
  - `split-bottom` → `splitInserts[]` com `layout: "bottom"` (arte embaixo).
    **A divisão aqui é a larga** (192px de dissolução, não 100) — pedido dele em
    2026-09-11, medido do vídeo de referência. Já é o padrão do template para
    `bottom`, não precisa passar `seamBlend`.
  - `behind` → `behindVideos[]`, B-roll no quadro inteiro atrás da pessoa —
    o caso RARO, não o que ele chama de "atrás da cabeça".
  Com `front: true` (padrão em `split-*`), gere o matte da janela com
  `person_matte.py` e ponha o `matte` no `splitInsert`: é a soma dos dois
  efeitos que ele pediu em 16/08 — a cabeça sobe NA FRENTE da arte e a costura
  dissolve atrás dela. `front: false` é faixa reta. `split` sozinho é apelido
  histórico de `split-top` e já sobe para o nome novo na validação.
  **A costura segue o padrão do Formato 1, sempre** (instrução dele,
  2026-09-11): a arte é desenhada com `bandH + SEAM_BLEND` e os últimos 100px
  dissolvem, então a junção cai na BORDA DE BAIXO do próprio clipe — sem
  sombra, sem linha reta — quando `bandH = altura natural do clipe a 1080 de
  largura − 100`. Rode **`split_band.py <clipe>`** em vez de fazer a conta: 16:9
  dá os 508 do preset; um clipe 1080×860 dá 760, que foi a calibragem de
  enquadramento fechado. Os dois números são a MESMA regra, não exceções.
  `focusY` continua medido num still — ele depende de onde a cabeça está na
  FONTE, não no clipe, e mudar `bandH` obriga a recalculá-lo. A interface não
  pede número nenhum.
  **E a costura tem que passar atrás do ALTO da cabeça dele** (regra repetida em
  16/08 e 11/09: *"a divisão fica atrás da parte superior da minha cabeça como
  se eu estivesse na frente"*). Ter `matte` não basta: com o `focusY` 400 do
  layout padrão o cabelo para ABAIXO da faixa e o quadro fica idêntico a uma
  faixa reta — o render conclui e o `check_inserts.py` aprova. Rode
  **`seam_check.py <cut.mp4> --at <início da janela> --band-h N --focus-y N
  --zoom Z`**: ele mede onde o topo da cabeça cai e devolve FAIXA RETA /
  RASPANDO / OK / BAIXA DEMAIS. A fração aprovada por ele é ~0.40.
- `takeChoices[]` (2026-09-12) — a tomada que ELE escolheu para cada linha do
  roteiro, na gaveta "Tomadas do roteiro": `{line, text, take, source, start,
  end, score}`. A gaveta lê `studio-pipeline/alignment.json` (escrito pelo
  `script_align.py`) e só desenha — **o preview nunca escreve `edl.json`**.
  Para aplicar: monte o EDL na ordem das linhas, e **valide cada borda com
  `speech_regions.py`** antes de renderizar, porque os tempos do alinhamento
  são os das palavras e não têm a folga da regra 5. Linha marcada `missing` não
  vira range; leve a lista delas para ele como pergunta, não invente take.
- `notes[]` — free-text correction requests, each with `start`/`end` on the draft
  timeline plus `renderedStart`/`renderedEnd` on the current `cut.mp4`, and the
  `phase` tab the user was on. Use the RENDERED pair to find the moment in the
  existing render. These are instructions in the user's words — read them, then do
  the edit they describe (re-cut, re-grade, swap an insert, fix a caption…).
- `edl.changes` / `edl.removed` — validate each new edge against
  `speech_regions.py` (warn if an edge clips a word — the user's intent wins, but
  say so), update `edl.json`, re-render, `verify_cut.py`.
- `editData` — insert/hook/behind timings → edit-data.json → re-render Phase 2.
- `image` (+ `imageChanged: true`) — Fase-1 grade sliders (Brilho/Contraste/
  Saturação/Nitidez/Suavização de pele/Tom de pele/Sombras/Realces) **and/or**
  `image.lut` (a LUT filter id, or `"none"`), only present when at least one
  moved. See "Fase-1 image sliders" and "LUT filters" below for the mapping —
  build the grade string, set `edl.json`'s `grade`, re-render Fase 1 (not
  Fase 2), `verify_cut.py`.

Then delete `preview_edits.json` and update `state.json`.

---

# PHASE 1 — Clean cut + color grade

Goal: best take of every beat, cut on silence, graded image, clean `cut.mp4` for approval. No text, no graphics.

0. **Repositório em dia — antes de qualquer coisa (2026-09-10).** Esta skill vive em `~/.agents/skills/edvid`, que É um repo git privado (`origin` = `geovanejunior92-debug/edvid`). Claude e Codex trabalham na MESMA instalação e os dois empurram, então a cópia local pode estar velha. Antes da transcrição: `git -C <skill> fetch origin main` e `git -C <skill> status -sb`. Atrás do remoto → `git pull --ff-only origin main` e só então comece. **Divergiu** (commit local E remoto) → **pare e avise**; nunca mescle no escuro no meio de uma edição. Editar com uma versão velha custa calibragem já aprovada — altura da capa, costura da tela dividida, som de encerramento, tudo mora neste arquivo. E **ao terminar qualquer alteração NA SKILL, commite e empurre na mesma sessão**: pedido permanente do usuário, não pergunte de novo.

1. **Inventory.** URL source? `ingest_url.py` first (`--section` when only a range of a longform video matters). `ffprobe` every source. `transcribe_batch.py` (or `transcribe.py`) → `pack_transcripts.py` → read `takes_packed.md`. Note dimensions/orientation and whether it looks flat/LOG. Material you can't picture from the transcript → `watch_video.py` for a one-Read visual survey.
2. **Pre-scan** `takes_packed.md` for verbal slips, mis-speaks, and dead-air-stretched words (Whisper stretches a word's end across silence — verify long "phrases" against `speech_regions.py`/waveform before trusting them). **Then run `voice_levels.py` on every source** — the transcript is level-blind, so an inaudible passage reads exactly like a normal one. Anything it flags is a decision to make BEFORE the EDL: boost it with `gain_db`, or cut the take entirely. **Depois do `voice_levels.py`, rode `audio_clean.py` em cada fonte e `check_audio.py` em seguida (2026-09-01)** — é o padrão, não opção: toda Fase 1 renderiza com `--audio-clean` a menos que o gate falhe (aí renderize sem, e diga por quê). Material com música, trânsito ou outra voz por baixo: `--denoise demucs`. O A/B (`<stem>.ab.wav`) vai junto com o corte no gate, em uma linha: "áudio limpo, ouça o A/B se quiser conferir".
3. **Converse.** Describe what you see; ask questions shaped by the material (content type, target length/aspect, pacing, must-keep/must-cut). No fixed checklist.
4. **Detect the colour profile — do NOT ask.** Run `detect_color.py <source>`. **Depois, `scopes.py --edl` e `match_takes.py --apply` (2026-09-01):** os takes chegam ao look já casados em exposição, branco e croma; um take estourado ou esmagado aparece aqui, em número, antes de qualquer montagem de candidatos. Com `grade` definido, ponha `skin_protect` no EDL com o `hue` que o `scopes.py` mediu — é o padrão para look de saturação/temperatura forte (o Premium e os LUTs frios), opcional no look neutro.
   The answer is in the file; asking put a measurable question on the user.
   - **`rec709` (normal)** → no grade. `"grade": ""`. A standard profile already
     carries its look; "improving" it loses the match with the user's other material.
   - **LOG / HLG / PQ** → apply the helper's `grade` field and say so in one line.
     Apple Log uses its approved preset; any other LOG gets an expansion **measured
     from that footage**, not a guessed vendor curve.
   - **`confidence: low`** → the ONLY case that still asks. It means the statistics
     are ambiguous — a bright, shadowless scene has the same lifted black floor as
     a LOG curve. Show what was measured, then ask.
   Still show the `--candidates` montage before committing a LOG grade: detection
   picks the curve, the user picks the look.
5. **Propose the cut strategy** (4–8 sentences: shape, takes, cut direction, grade direction, length estimate). **Wait for confirmation.**
5b. **Antes de renderizar, `shot_check.py edl.json` (2026-09-01).** O corte foi
   escolhido pelo som; este passo confere o que o som não vê: borda em piscada
   ou em gesto (aplique o deslocamento sugerido, que fica dentro da folga da
   regra 5, e confira que não entrou dentro de palavra com `speech_regions.py`),
   take mais claro/escuro ou mais quente/frio que os outros (anote — o casamento
   de cor consome isso), pulo de enquadramento. Um CHECK de borda se corrige no
   EDL agora, antes de gastar render. Um CHECK de take vira nota no gate, não
   bloqueio.
6. **Execute.** Produce `edl.json` (schema below; editor sub-agent brief for multi-take). Set cut edges from `speech_regions.py`, not raw Whisper times. Render: `render.py edl.json -o cut.mp4 --no-subtitles --audio-clean` (+`--voice-master` if wanted; longform: `--keep-resolution`). **The J-cut runs by default** — see below; you do not ask for it and you do not configure it per project.
7. **Self-eval (numeric first).** `verify_cut.py edl.json cut.mp4` (longform: `--min-silence 1.2`). Clean → done. Flags → `timeline_view` ONLY the flagged junctions, fix, re-render. Cap 3 loops, then surface remaining flags to the user.
8. **Generate the LUT thumbnails** (only if not already present for this
   project): `lut_thumbs.py cut.mp4 --out-dir <edit>/.preview_cache/luts`. A
   project that skips this shows the LUT picker with blank/flat swatches
   instead of real thumbnails — easy to forget since nothing errors, do it
   every time as part of opening the gate, not only when someone notices it's
   missing (confirmed missed once, 2026-08-16). **This runs BEFORE step 10,
   not after** — the picker lives in the Fase-1 tab the user is about to open,
   so thumbnails written after the cut is shown arrive too late to be part of
   what they are reviewing.
9. **Verify the picker actually works** — `check_luts.py cut.mp4 --edit-dir
   <edit> --port <preview port>`. **A gate: do not show the cut until this
   exits 0.** It checks the four things that each broke the picker in
   production and that `lut_thumbs.py`'s own "32 thumbnails" success line does
   NOT cover: the `.cube` files parse, ffmpeg's `lut3d` really applies each
   one to THIS video, every id in `LUT_CATALOG` has a decodable JPEG on disk,
   and the preview server actually serves them over HTTP. Never treat
   `lut_thumbs.py` exiting 0 as proof the user will see thumbnails — the
   chronic blank-picker bug (2026-08-16) had generation succeeding every
   single time while the browser showed 33 empty cards.
9c. **Corte com 3+ takes: suba a ponte do OpenCut junto (2026-09-01).** Rode
   `opencut_bridge.py serve --edit-dir <edit>` em background e inclua a URL que
   ela imprime na mesma mensagem do gate, como segunda opção depois do preview:
   uma linha, sem vender. Ele pediu explicitamente que isso não dependa de ele
   lembrar que existe. **Com 1 ou 2 takes, não suba e não mencione** — reordenar
   não é possível e o segundo link só suja o momento da aprovação. **No Formato 1
   também não** — o preset é entrega pronta, e um link a mais é uma escolha a
   mais que ele pediu para não existir ali. A ponte cai
   sozinha na porta seguinte se outra já estiver no ar, então dois cortes abertos
   ao mesmo tempo não colidem. Se a devolução vier, ela reescreve `edl.json`
   sozinha: volte pro passo 7 (`verify_cut.py`) e re-renderize. Detalhes e
   limites em `references/opencut.md`.
10. **Show `cut.mp4` and wait for approval.** The phase gate. **Antes de mostrar (2026-09-01):** `transcribe.py cut.mp4 --edit-dir <edit>` (a faixa de transcrição clicável do preview lê `transcripts/cut.json`; a Fase 2 reaproveita) e `diagnostics.py <edit>` (o painel Diagnóstico). Sem os dois, o preview mostra o corte mas não o que foi medido nem deixa cortar pelo texto.
10a. **Passo de SOM, entre o corte e a aba Estilo (2026-08-17).** A entrega
   pós-corte já leva corte, zoom, transições e flash — e agora leva os efeitos
   sonoros junto. Rode `sfx_plan.py <edit-dir>`, revise a lista proposta contra
   o conteúdo (é proposta, não veredito) e só então mostre. O catálogo é a SOMA
   do pacote antigo com o novo (typing, shutter, UI, riser, hit) — nada foi
   substituído. Regras, níveis e o porquê: **`references/sfx-catalogo.md`**.
   Duas coisas que o helper já respeita e você não deve desfazer: ele TROCA o
   som de uma transição que já soa, em vez de empilhar um segundo efeito, e só
   acrescenta cue novo onde há silêncio.

10b-pre. **Buscar na Shutterstock, baixar as prévias, ASSISTIR, e escolher o
   clipe necessário (tarefa fixa, 2026-08-17; autorização reafirmada em
   2026-09-12).** O conector da Shutterstock é somente leitura: busca e mostra
   prévia, mas não licencia nem baixa por API. O download licenciado é feito
   pelo agente no site autenticado, sem nova confirmação por clipe. O fluxo:
   1. Buscar cada item da lista (frases descritivas em inglês funcionam melhor).
   2. **Baixar as prévias com marca d'água** (`previewMp4` do resultado) das 2
      candidatas de cada item — ele autorizou explicitamente.
   3. **Assistir**: 3 frames por clipe numa folha por item, lida contra a frase
      daquela janela. Prévia é para ESCOLHER; nunca entra na edição.
   4. Quando houver dúvida editorial, entregar **2 opções por item, com link e
      leitura de cada uma**, e deixar ELE decidir. Começou em 5 (2026-08-17) e ele reduziu para 2 no mesmo dia:
      *"a partir de agora nao precisa mais fazer 5 videos, somente 2 videos"*.
      Duas boas valem mais que cinco medianas — escolha as duas melhores em vez
      de listar tudo que a busca devolveu.
   5. **Apagar as prévias** depois da análise (pedido dele). As folhas de
      contato podem ficar — são leves e mostram o que foi analisado.
   6. Depois da escolha — ou diretamente, quando a marcação for inequívoca —
      baixar o licenciado pelo site, guardar no acervo com o ID e usar a cópia
      do projeto. Só interromper se aparecer cobrança extra, mudança de plano
      ou licença ambígua. Nunca usar a prévia no render.

10b. **Hand over the B-roll shopping list** (standing step, 2026-08-16 — user
   request: "quero que voce sempre faça isso depois da fase 1 Corte, quando
   for para fase 2"). Once the cut is approved, before/alongside opening the
   Estilo tab, give the user ONE table: every planned insert window, the words
   spoken there, and what to search for. They shop while you build, instead of
   discovering at delivery that the art is wrong. Three rules that are the
   whole point:
   - **Read the library and the ledger FIRST.** For this user that is
     `~/Videos/stock-medico/` (with `PEDIDOS.md`). Anything already in the
     acervo is reused, never re-requested; anything already listed in
     `PEDIDOS.md` from a previous video is NOT asked for again, even when the
     new video has a similar beat. Re-asking for a clip they already bought is
     pure re-work and reads as not paying attention.
   - **No duplicate rows inside one list.** Two moments about tiredness share
     one clip; do not send them shopping twice for the same thing.
   - **Append the new (deduplicated) rows to `PEDIDOS.md`** so the next video
     inherits the memory. The ledger lives with the library, not the project —
     a project-local list dies with the project and the dedup stops working.
11. **Open the Estilo tab** — `"awaitingStyle": true` in `state.json`, and let the
   user pick the editing style, the caption style and the edit elements in the UI
   (see "The Estilo tab"). Do NOT ask this in chat. Only then read the track
   reference: **`references/shortform.md`** or **`references/longform.md`**.

## J-cut — the default Phase-1 cleanup

Takes are OVERLAPPED, not butted. The outgoing take's audio runs to its natural
end; the incoming take's audio starts `lead` frames earlier **on its own track**
and the two are summed; the incoming PICTURE starts where the outgoing audio ends,
skipping `lead` frames of its own head. The voice arrives before the face.

Why it is the default: a straight concat leaves a beat of silence at every
junction — the outgoing take keeps its trailing pad and the incoming one starts
with its own. Measured on a real 3-take edit: **130ms and 140ms**. Small on paper,
a clear pause in the room. The J-cut removes it and the takes interlock.

Defaults, in `render.py`: **lead 5 frames**, **tail trim up to 2 frames**.
Override per project with `"jcut": {"lead_frames": N, "tail_trim_frames": N}`;
turn it off with `"jcut": false` or `--no-jcut` (single-range EDLs skip it anyway).

Three things that are not obvious:

- **Tighten with the TAIL, not the lead.** A bigger lead also pushes the picture
  deeper into the incoming take's speech, which reads as entering mid-word. The
  tail trim tightens the seam and leaves the picture entry alone. Measured: 5f
  lead alone gave 62/46ms of interlock; adding a 2f tail trim doubled it to
  129/112ms with the picture still entering 140ms into the speech.
- **The tail trim is measured, never blind.** `render.py` reads the silence
  actually present at the end of each range and trims at most that (keeping 10ms).
  A fixed 2 frames would eventually decapitate a word on a take that ends tight.
- **Sync is by construction:** `video_in = audio_in + lead` and
  `video_offset = audio_offset + lead`. Break that pairing and the take drifts.

`render.py` writes a `jcut_timeline` block into the EDL — the real output
positions. Everything downstream (preview timeline, `segments.json`, Phase-2
overlays) must index off THAT, not off the sum of the ranges: the J-cut output is
shorter than `Σ(end−start)`, so summing places every take after the first too late.

## Color grade

Reason about the image, don't preset-blind. Mental model ASC CDL: per channel `out = (in*slope + offset)**power`, then saturation. Applied per-segment at extraction (Hard Rule 7).

- **Iterate on ONE frame via a candidates montage, and let the user choose:**
  `grade.py <src> --candidates "punch=eq=contrast=1.15:saturation=1.25;suave=…;original=" --frame <t> -o edit/verify/grades.png` — one image, all looks labeled, side by side. Only render the full cut once the grade is locked.
- **Build from spaceless filters** so the string survives the EDL: `eq=…`, `colorbalance=…`, `colorlevels=…`. No `curves` with spaces (breaks filtergraph parsing).
- **The grade always runs at 8-bit.** `render.py` prepends `format=yuv420p` to the
  grade segment of the vf chain, because ffmpeg's `colorlevels` is broken on 9–14
  bit RGB — on a 10-bit source it collapses the frame to a constant TV black
  (measured `YAVG=64/1023`, `YBITDEPTH=1` on an iPhone Apple Log ProRes) while
  behaving correctly at 8- and 16-bit. `curves`, `colorbalance`, `hue` and `eq` are
  bit-depth-safe. Keep that guard in front of any new grade caller.
- **Standard/Rec.709** → light corrective or none. A user `.cube` goes first as `lut3d=`.

### LOG / HDR sources

`detect_color.py` resolves the profile and returns the `grade` to apply, so the
normal path needs nothing here. When it returns LOG/HLG/PQ, reports
`confidence: low`, or you are adding a vendor preset, **read
`references/log-grade.md`** — it carries the identification table (Apple Log has
no tag that names it), the Apple Log preset's two load-bearing details, and why
the grade must run at 8-bit.

Still show the candidates montage and get a pick — a preset is a starting point,
not permission to skip the approval.
- **Skin is the guardrail.** The moment skin goes orange/magenta/clipped, back off. Check a mid-shot face at each step.
- **Relative tweaks** ("+1 exposure", "mais saturação") → nudge that one term, re-montage the same frame, show again.
- **Rec.709 is the only color space allowed to leave Phase 1.** `render.py` handles
  this (tonemaps HDR, converts wide-gamut SDR, tags every output bt709/tv) — but
  VERIFY on the rendered cut: `ffprobe -v error -select_streams v:0
  -show_entries stream=color_space,color_primaries,color_range cut.mp4` must read
  bt709 / bt709 / tv. Anything else means a second interpretation is still alive
  downstream: Chrome (Remotion's decoder in Phase 2) re-reads those tags and
  silently re-grades the image — typically ~1.2 gamma darker with a hue shift — so
  the Phase-2 render stops matching the cut the user approved. Phone/mirrorless
  sources routinely write bt2020 primaries with `color_transfer=unknown`; that is
  wide-gamut SDR, **not** HDR, and an HDR-only check will miss it.

### Fase-1 image sliders (manual grade controls, 2026-08-15, moved from Estilo)

**Live in the Fase-1 "Corte" tab, not Estilo** — moved there the same day per
user request, so the sliders sit next to the player instead of a separate
screen: color grading is conceptually Fase-1 work anyway (Hard Rule 7), and
seeing the effect while dragging beats a blind pick-then-check-later flow.
The panel (`#imgAdjustPanel` in `assets/preview/index.html`) shows only when
`S.tab === 1`; ALL 8 sliders get an **instant preview** on the `<video>`
element itself (`applyImagePreview()` in `app.js`) — updated 2026-08-15 per
user request ("quero ver a mudança ao vivo... sem precisar salvar"). Brightness/
contrast/saturation map ~1:1 to CSS `filter()` and are exact; the other 5 have
no honest 1:1 CSS equivalent, so they're a **labelled approximation**, not the
real ffmpeg grade — the panel's own note says so, and the real result still
only lands after Salvar re-renders Fase 1:
- `skinSmooth` → `blur()` over the WHOLE frame (the real `smartblur` targets
  skin only — this softens hair/background too).
- `skinWarmth` → `hue-rotate()` toward orange/blue — a visible proxy for
  `colortemperature`, not channel-accurate.
- `shadows`/`highlights` → `brightness()`/`contrast()` nudges, **deliberately
  reproducing the real filter's own coupling limitation**: `highlights` only
  visibly does anything once `shadows` has also moved (mirrors why
  `gamma_weight` needs a non-zero `gamma` — see below). A preview that let
  `highlights` alone do something would promise a result Salvar can't deliver.
- `sharpness` → CSS `filter()` has no unsharp/convolve primitive, so this is
  the one slider that needs a real SVG filter: a `<feConvolveMatrix>`
  (`ensureSharpenFilter()` in `app.js`) built once and updated in place per
  drag, referenced via `url(#edvidSharpen)` in the CSS filter string.

Saving now rides the **same "Salvar ajustes" button and payload as any other
Fase-1 correction** (`type: "timeline-edits"`, written to
`preview_edits.json` — NOT `preview_style.json`, which is Estilo-only and a
different screen/moment per the file's own docstring). 8 sliders (Brilho,
Contraste, Saturação, Nitidez, Suavização de pele, Tom de pele, Sombras,
Realces/iluminação; ranges in `IMAGE_ADJUSTMENTS` in `app.js`) contribute an
`image: {brightness, contrast, saturation, sharpness, skinSmooth,
skinWarmth, shadows, highlights}` block (each 0 at rest) plus
`imageChanged: true` to that payload **only when at least one slider moved
from its last-saved value** — same dirty-tracking pattern as EDL ranges
(`S.imageOrig` is the snapshot, refreshed on load and after each save).
`imageChanged` in `preview_edits.json` means: build the filter chain below,
set it as `edl.json`'s `grade`, and **re-render Fase 1** — same file, same
step, as any other correction in that save (an EDL edge move and an image
tweak can arrive in the same `preview_edits.json`, applied together).

**Slider → filter mapping** (space-free, 8-bit-safe filters only, per the
Color-grade rules above):

```python
LUTS_DIR = Path(__file__).resolve().parent / "assets" / "preview" / "luts"  # relative to SKILL.md's own dir

def image_style_to_grade(img):
    b, c, s = img['brightness'], img['contrast'], img['saturation']
    sharp, smooth = img['sharpness'], img['skinSmooth']
    warmth, sh, hl = img['skinWarmth'], img['shadows'], img['highlights']
    lut = img.get('lut', 'none')
    parts = []
    # brightness/contrast/saturation/shadows/highlights all ride one eq= call
    eq = []
    if b: eq.append(f"brightness={b/100:.3f}")
    if c: eq.append(f"contrast={1 + c/100:.3f}")
    if s: eq.append(f"saturation={1 + s/100:.3f}")
    if sh: eq.append(f"gamma={1 - sh/100*0.3:.3f}")           # + lifts shadows
    if hl: eq.append(f"gamma_weight={max(0.2, 1 - hl/100*0.6):.3f}")  # + protects highlights from the gamma shift above
    if eq: parts.append("eq=" + ":".join(eq))
    if warmth: parts.append(f"colortemperature=temperature={6500 - warmth*30:.0f}")
    if sharp: parts.append(f"unsharp=5:5:{sharp/100*1.5:.3f}")
    if smooth: parts.append(f"smartblur={smooth/100*3:.2f}:{smooth/100*0.8:.3f}:0")
    # LUT last — a creative look applied on top of already-corrected footage,
    # not a replacement for the corrections above. See "LUT filters" below.
    # id != filename for a couple of entries (the & in two .cube names got
    # sanitized to _ for the id) — look up `file` in LUT_CATALOG (app.js), do
    # NOT assume `f"{lut}.cube"`, or those two resolve to a file that doesn't exist.
    if lut and lut != 'none':
        filename = LUT_CATALOG_FILES[lut]  # id -> file, mirrors LUT_CATALOG in app.js
        parts.append(f"lut3d={(LUTS_DIR / filename).as_posix()}")
    return ",".join(parts)  # "" when every slider is at rest — grade stays whatever Fase 1 already had
```

Ranges were chosen conservatively (e.g. contrast/saturation only reach 0.5–1.5
at the slider extremes) precisely so a full-range drag doesn't blow out the
image — **still show the candidates montage** (`grade.py --candidates`)
before committing, same as any other grade decision. Verified 2026-08-15: all
five example filter strings (brightness/contrast/saturation combo, shadows+
highlights combo, warmth+skin-smooth combo, sharpen) rendered cleanly via
`grade.py --candidates` with no ffmpeg errors and no blown-out/artifacted
results at moderate slider values.

`shadows`/`highlights` use `eq`'s `gamma`/`gamma_weight` instead of `curves`
to keep the Hard Rule 2 space-free constraint — coarser than a real tone
curve, but safe to parse. **`gamma_weight` is NOT an independent highlights
control** — per ffmpeg's own docs it "reduces the effect of gamma on bright
areas," i.e. it only *modulates* the `gamma` value's own effect; with
`shadows` at 0 (gamma stays 1.0, an identity curve), moving `highlights`
alone does nothing, because there is no gamma shift left to weight. This is a
real limitation of the `eq` filter, not a bug — document it to the user if
they move only the highlights slider and ask why nothing changed. (First
draft of this mapping used a parameter named `gamma_weak`, which does not
exist on `eq` and errors immediately — `ffmpeg -h filter=eq` is the source of
truth for parameter names, not assumption.) If a future session needs true
curve-shaped, independent shadow/highlight control, that requires solving the
`curves`-filter space problem first (e.g. building the point list into a
`.cube` LUT file instead of an inline string).

### LUT filters (DaVinci/CapCut/Premiere-style picker, 2026-08-15)

31 `.cube` files (a free cinema pack the user provided) live in the shared
`assets/preview/luts/` — same "standing skill asset, every project" pattern as
the Remotion template. `STYLE_CATALOG`-adjacent `LUT_CATALOG` in `app.js` maps
`id → {name, file}`; the id is NOT always the filename stem (two `.cube` names
have a literal `&`, sanitized to `_` for the id) — always look the real
filename up in `LUT_CATALOG`/`LUT_CATALOG_FILES`, never assume `f"{id}.cube"`.

**Thumbnails are real, not generic swatches**: `helpers/lut_thumbs.py <video>
--out-dir <edit>/.preview_cache/luts` grades one actual frame of THIS
project's own footage through every `.cube` (ffmpeg `lut3d`, same filter the
real grade uses) and writes `<id>.jpg` + a `none.jpg` (ungraded, for the
"Nenhum" card) — run this once per project (any frame is fine; a mid-video
one is the default) so the picker in `assets/preview/index.html`'s `#optLut`
grid has something to show. `app.js` fetches them from `/media/.preview_cache/
luts/<id>.jpg` (server root = the edit dir, per `preview_server.py`).

**Live preview is exact, not an approximation like the sliders** — a genuine
WebGL2 3D-texture lookup (`LUT_ENGINE` in `app.js`): `.cube` fetched from
`/assets/luts/<file>` (served straight from the skill's `assets/preview/`,
`APP_DIR` in `preview_server.py`), parsed client-side, uploaded as a
`TEXTURE_3D`, sampled per-pixel against the live `<video>` frame (uploaded as
a `TEXTURE_2D` every animation frame) in a fragment shader — same table the
ffmpeg `lut3d` filter applies server-side, so there is nothing to fake here
unlike brightness/sharpness/etc. Two bugs found only by testing in the actual
browser, not by reasoning about the code (do that gate: DevTools/`gl.getError()`
before calling a WebGL feature done):
- **`gl.texImage3D` threw `INVALID_OPERATION` (1282) on every LUT** — WebGL's
  default `UNPACK_ALIGNMENT` is 4, and a `.cube`'s RGB (3 bytes/texel) data at
  a non-multiple-of-4 size (33 is the common cube edge in this pack) doesn't
  align, so the driver expects a larger padded buffer than what's given.
  Fix: `gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)` immediately before
  `texImage3D`, restored to 4 right after (the video's RGBA uploads are
  already 4-aligned and don't need it). Diagnosed by isolating the draw call
  in the live page via `javascript_tool` and reading `gl.getError()` after
  each step — not by staring at the shader source.
- **The LUT grid rebuilt its 32 `<img>` tags from scratch on every `poll()`
  tick (~2s)**, which cancels whatever was still mid-load and restarts it —
  with 32 thumbnails none of them ever finished (`naturalWidth` stayed 0
  forever, confirmed live). Fix: build the grid ONCE; later calls to
  `renderLutGrid()` just toggle the `.on` class on the existing cards. Same
  failure class as the earlier `imageDirty()` null-crash — anything called
  from the poll cycle has to be safe to call repeatedly with no side effect
  when nothing actually changed.

**Pacote "CC" — 7 LUTs recriados de uma referência (2026-08-17).** O usuário
mandou um vídeo mostrando sete filtros do CapCut (4K, Qualidade II, Bokeh,
Laranja Azul, Baile de Formatura, Ensolarado, Café Escuro) e pediu que
entrassem no acervo. Eles não existem como arquivo, mas o vídeo mostra a MESMA
pessoa, na mesma sala e na mesma luz, com um filtro por trecho — então a
diferença entre trechos É o filtro. Os `.cube` saíram daí: casamento de
histograma por canal contra o trecho mais neutro, mais um ganho de saturação
medido (script em `scratchpad/build_luts.py`, método descrito no comentário do
`LUT_CATALOG`). **É recriação, não o arquivo original** — diga isso se ele
comparar lado a lado com o CapCut. `cc_bokeh` é parcial por natureza: o filtro
original também desfoca o fundo, e desfoque não cabe num LUT.

Ao acrescentar LUT novo, **o id tem que ser igual ao nome do arquivo** —
`lut_thumbs.py` nomeia a miniatura pelo arquivo, e um id diferente gera card
vazio. O `check_luts.py` pega isso, mas só com `--port` apontando para o
servidor do projeto CERTO: um servidor rodando em outro projeto devolve 404 e
parece defeito do LUT quando é alvo errado (custou uma rodada em 2026-08-17).

Saving rides the same `image`/`imageChanged` payload as the sliders — `lut`
is just another key in that object (`'none'` at rest). See
`image_style_to_grade()` above for how it becomes `lut3d=` in the grade string.

If the resulting grade is applied on top of an existing LOG/detect_color grade
(e.g. after `detect_color.py` already picked something), chain them with a
comma rather than replacing — same as any manual nudge on top of an auto-pick.

**Portrait-mode transport overflow (fixed 2026-08-15):** moving the image
panel into `#editorCol` narrowed the column (~316px in portrait, player takes
the rest). The `.transport` bar (play/mute, times, mark button, the 130px
zoom slider, fit) needs ~550px in one row; with `body.portrait .editor-col
.transport{align-self:stretch; width:auto}` and no `min-width:0`, a flex item
never shrinks below its content's min-content size even when stretched, so
the excess just overflowed past `.editor-col`'s right edge and bled visually
over the video preview — user-reported as "o zoom que fica acima do vídeo
aumenta a janela de edição de corte." Root-caused via
`transport.scrollWidth` (546) vs `.clientWidth` (314) in the live preview,
not by eyeballing CSS. Fixed in `app.css` by adding `min-width:0;
flex-wrap:wrap` to that rule (same "let it grow its own row, `.timeline-panel`
absorbs it" pattern as the image panel itself) plus a tighter `gap`/`padding`
so it settles on 2 rows instead of 3 — 3 rows pushed total content height
~2px past the viewport (body has no scroll). If transport gains more controls
later, re-check `scrollWidth` vs `clientWidth` at 300–320px width before
assuming it still fits.

## Voice EQ + mastering (optional Phase-1 audio polish)

Opt-in: `render.py … --voice-master` or `"voice_master": true` in the EDL. Runs after compositing, before loudnorm. Chain (`VOICE_MASTER_CHAIN` in render.py): highpass 80 → mud cut −2.5dB@200 → compressor (3:1, −20dB, makeup 3) → presence +2.5dB@3.2k → air +3dB@9k shelf → deesser → limiter 0.95.

Tune per voice: brighter → raise treble/3.2k; warmer → back those off, lift ~200Hz; more "radio" → lower threshold / raise ratio; more natural → ratio 2, threshold −24dB. **Verify:** `ffmpeg -i cut.mp4 -af astats -vn -f null -` → Flat factor 0, peak < 0dB; loudnorm summary ≈ −14 LUFS / TP ≤ −1. Then let the user hear it.

## Cut craft

- Silences ≥ 400ms are the cleanest cuts; 150–400ms usable with a check; < 150ms unsafe.
- Preserve peaks (laughs, punchlines, emphasis) — extend past a punchline to include the reaction.
- Every cut must work on audio AND video.

**Fine-comb the silences — Whisper times are NOT cut edges:**
- Onsets drift early (bakes dead air at a segment head); ends stretch across silence (a 4s "phrase" may be 1s of talk); restarts get collapsed into one stretched word (the doubled take is invisible in text but audible).
- Fix: edges from `speech_regions.py` — start → region onset −30ms, end → offset +50–80ms (the trail keeps the word's decay; cutting at the offset clips the last sibilant). Inside merged speech blocks, place the edge by eye on a fine `timeline_view`.
- If the user flags a gap/clip after render, re-run `speech_regions.py` around that timestamp — don't nudge blindly.
- **A stretched word can hide a false start, and the stretch also mis-attributes every word around it.** When "de" spans 6.16→8.64, the words the source transcript places on either side may belong to *different takes* — the speaker trailed off, paused, and restarted the whole sentence. The text shows one clean sentence; the audio holds two attempts.
- **Never conclude a range is missing content from the SOURCE transcript's word times.** Extract the exact range and transcribe it in isolation — no surrounding context for the LM to complete from. A model reading the full file completes from context; the same model on a 3-second extract cannot. If the answer changes a deliverable (a caption rewrite, dropping a take), also check the range against `speech_regions.py` and the waveform — agreement between the isolated transcript and the acoustics is what makes it trustworthy.
- **Rotation:** phone clips are often stored landscape with a ±90° display-matrix; render.py handles it — don't force dimensions.

**Menos cortes, com ar entre eles (2026-08-17, para TODAS as edições).**
Ele recebeu um corte de 10 takes num take contínuo de 70s e a leitura foi:
*"mal termino de falar e já está começando outro"*. Duas causas somadas —
cortar TODA pausa interna (o corte vira uma sequência sem respiração) e o J-cut
apertando ainda mais o que sobrou. O que fazer:
- Cortar só nas fronteiras REAIS de frase. Pausa interna curta é respiração, não
  gordura: tirar todas deixa o vídeo ofegante.
- Bordas mais generosas: −40ms na entrada, **+120ms na saída** (a fala termina
  antes de o próximo take entrar).
- `jcut` com `lead_frames: 3` e `tail_trim_frames: 0` quando o material for uma
  fala contínua. Medido: caiu de 208ms para 125ms de encavalamento, e de 9 para
  5 junções em 63s.

**Level the takes — presence is not audibility:**
- People drop their voice on asides, parentheticals and sentence tails ("além de, *claro*, …"). It sounds natural in the room and disappears on a phone speaker. The transcript is perfect, so nothing in the text pipeline flags it.
- Find it with `voice_levels.py --edl edl.json`: it reports each range's average AND the worst low run inside it, and suggests a `gain_db`. Size the gain off the **worst run**.
- Fix it per-range with `gain_db`, never with a global compressor.
- Confirm with `verify_cut.py`'s range-balance line. Target a ~2 dB spread between ranges — that is levelled. Driving it to 0 dB flattens the delivery and lifts room tone for nothing.
- Room tone is the real ceiling on a boost, not clipping. Before committing a large gain, compare the boosted take's internal pause against a pause elsewhere in the cut; if the boosted one is now the louder pause, back off.

## Editor sub-agent brief (multi-take selection)

```
You are editing a <type> video. Pick the best take of each beat and assemble
chronologically by beat, not clip order.
INPUTS: takes_packed.md; narrative context (2 sentences); speaker note;
expected structure (archetype or invent); verbal slips to avoid; target runtime.
Archetypes: launch (HOOK→PROBLEM→SOLUTION→BENEFIT→EXAMPLE→CTA); tutorial
(INTRO→SETUP→STEPS→GOTCHAS→RECAP); interview (Q→A→FOLLOWUP…); essay
(COLD-OPEN→THESIS→POINTS→COUNTER→CONCLUSION→CTA); vlog; or invent.
RULES: edges on word boundaries; pad 30–200ms; prefer ≥400ms silences; keep
unavoidable slips only if no better take (note in "reason"); if over budget,
drop a beat or trim tails and report.
OUTPUT (JSON array, no prose):
[{"source":"C0103","start":2.42,"end":6.85,"beat":"HOOK","quote":"…","reason":"…"}]
```

For a single long source (longform), the main context can pick cuts directly from `takes_packed.md`; for sources > ~30 min, delegate to the sub-agent so the full transcript never enters the main context.

## EDL format (Phase 1)

```json
{
  "version": 1,
  "sources": {"C0103": "/abs/path/C0103.MP4"},
  "grade": "eq=contrast=1.06:saturation=1.05",
  "voice_master": true,
  "audio_clean": true,
  "stabilize": false,
  "skin_protect": {"hue": 18, "strength": 0.6},
  "jcut": {"lead_frames": 5, "tail_trim_frames": 2},
  "ranges": [
    {"source": "C0103", "start": 2.42, "end": 6.85, "beat": "HOOK",
     "quote": "…", "reason": "…", "gain_db": 0,
     "speed": 1.0, "freeze_end": 0, "grade_pre": "exposure=exposure=+0.2",
     "chapter": "Only on longform section openers"}
  ],
  "total_duration_s": 87.4
}
```

`grade`: preset name, raw filter, or `"auto"` — normally whatever `detect_color.py`
returned. `chapter` fields feed `chapters.py` (longform).

`jcut`: optional. **Omit it and the J-cut runs with the defaults** (lead 5f, tail
trim up to 2f); `false` butt-joins instead. After a render, `render.py` adds a
`jcut_timeline` array — the real per-take video/audio offsets in the output. That
block, not `Σ(end−start)`, is the timeline Phase 2 and the preview must use.

`grade_pre` (por range) e `skin_protect` (no EDL, 2026-09-01): a cor por
take e a proteção de pele. `grade_pre` é o filtro de casamento escrito pelo
`match_takes.py`, aplicado ANTES do `grade`. `"skin_protect": {"hue": 18,
"strength": 0.6}` é um qualificador HSV centrado no tom de pele MEDIDO
(`scopes.py` sugere o `hue`): o look inteiro roda e a pele volta 60% ao que era
antes dele — saturação alta e LUT frio param de deixar o rosto laranja ou
cinza, sem rastreio, porque a seleção é por cor. Só existe quando há `grade`.

`speed` / `freeze_end` (2026-09-01): tempo por range. `"speed": 0.5` é câmera
lenta com interpolação por fluxo óptico (`minterpolate`, não slideshow) e som
em `atempo` (tom preservado); `2` acelera. `"freeze_end": 0.8` segura o último
quadro por 0,8 s, em silêncio — o "congela na palavra" antes de um corte seco.
Os dois mudam a duração de SAÍDA do take (fades e `total_duration_s` seguem a
saída), e **desligam o J-cut naquele render**: o overlap assume que a saída dura
o mesmo que o range. Use em take sem fala (B-roll, pausa dramática); em fala,
`speed` abaixo de 0,8 vira voz de gravação lenta mesmo com o tom preservado.

`gain_db`: per-range level correction in dB, sized by `voice_levels.py`. Applied at
extraction, before the edge fades, with a limiter on any boost so a loud syllable
inside a quiet take cannot clip. This is the fix for an under-level take — not a
global compressor, which would pump the good takes to rescue the bad one.
Cap around +12 dB: past that the room tone rises with the voice and the take
starts sounding like a different microphone.

---

# PHASE 2 + 3 — read the track reference (after the gate)

The cut is approved and the user picked the style in the UI (`preview_style.json`)
→ load **one** file and build exactly what was picked:

- **Vertical / Reels / TikTok / Shorts → read `references/shortform.md`.** Karaoke captions, static hook headline, dynamic camera, inserts, behind-the-subject, SFX, soundtrack.
- **Horizontal / YouTube / tutorial / vlog → read `references/longform.md`.** Retention cut is there too (read it BEFORE Phase 1 on longform jobs), B-roll, lower-thirds, chapter cards, callouts, .srt + chapters, soundtrack.

**"Tela dividida formato padrão 2" → `assets/presets/formato-2.json`.** Arte em
cima com dissolução LARGA (bandH 874 + 192 de dissolução) e **sem matte**: a
arte termina de sumir exatamente onde a cabeça começa, e é isso que põe a pessoa
na frente. Não misture com o Formato 1, que chega ao mesmo efeito por outro
caminho (dissolução de 100 + matte da pessoa). Calibre o `focusY` com
`seam_check.py … --seam-blend 192`: o alvo é o topo da cabeça cair dentro da
dissolução. O preset registra o que foi MEDIDO do vídeo de referência (geometria,
cor, som) e o que continua sendo decisão dele (tipografia).

**"Edição com tela dividida FORMATO 1" (ou só "formato 1") → leia
`references/formato-1-tela-dividida.md` e siga à risca.** É um formato NOMEADO
por ele (haverá outros): preset pronto em `assets/presets/formato-1.json`, zero
perguntas de estilo, `awaitingStyle: false`, a única interação é a lista de
B-roll a baixar. Termina obrigatoriamente com `review_final.py` — ele pediu que
o vídeo seja assistido 100% antes de ser entregue.

**This user's aesthetic-medicine content (@drgeovanejunior) → ALSO read
`references/style-premium-editorial.md`, on top of shortform.md, unless they
explicitly ask for a different look.** A standing preset (2026-08-15, built
from a detailed brief + direct frame analysis of a reference creator's real
Reels): warm-restrained color grade, stacked title cards with a script-font
accent word, centered ExtraBold dialogue captions, -16 LUFS voice mastering,
HEVC 2-pass delivery export. Every piece is real code (grade preset,
Remotion components, render.py flags), not just prose — the reference file
has the exact pointers. Don't re-derive this style from scratch each time;
read the file.

**Gráficos de dado** (`graphics` no edit-data: lower third, número que conta, lista, antes/depois, citação, barra, callout) estão em `references/shortform.md` → "Biblioteca de gráficos"; use antes de escrever qualquer JSX no `CustomGraphics.tsx`. Both tracks: scaffold with one `cp -R` of the template, describe the video in `public/edit-data.json`, verify with montage stills, render, loudnorm, deliver `edit/final.mp4`. **Antes de entregar, `qc_final.py final.mp4` (e `--platform` do destino): só entrega com exit 0, e o que falhar volta para a camada que causou.** Load the `remotion-best-practices` skill when writing any Remotion code (CustomGraphics).

## Retenção — o laço com o público (2026-09-01)

1. **Antes de fechar o EDL**, `retention.py` no transcript da fonte (`--candidates`)
   entra na conversa do passo 3: se a heurística achou um gancho melhor que o
   começo natural do material, proponha como variante — ele decide.
2. **Depois do render da Fase 1**, `retention.py transcripts/cut.json` (transcreva
   o `cut.mp4` se ainda não houver): gancho, arrasto, ar morto e fecho vão para
   o gate em uma linha cada, só o que estiver fora do normal. Grave com
   `--ledger ~/Videos/retencao.jsonl --project <nome>`.
3. **Uma semana depois de publicado**, o Metricool (MCP, brand `drgeovanejunior`)
   devolve por Reel: `reelsViewRate` (IGRE28, % que passou dos 3 s — é o
   gancho), `averageWatchTime` (IGRE24, segundos — é a retenção; divida pela
   duração do corte), `views`, `saved`, `shares`. `retention` (IGRE27) veio
   nulo em 2026-09-01 — não conte com ele. Case pelo texto da legenda/data e
   amarre à ledger com `--metrics viewRate=…,avgWatch=…,views=…`.
4. **Ao começar um corte novo**, leia a ledger: com dez vídeos é estatística
   fraca, com cinquenta começa a dizer que tipo de gancho e que ritmo seguram
   ESTE público. Até lá, a heurística é manual de retenção, e diga isso.

## Memory — `project.md`

Append one section per session at `<edit>/project.md`:

```markdown
## Session N — YYYY-MM-DD
**Phase reached:** …  **Strategy:** …
**Decisions:** takes, cuts, grade (LOG?), layer choices + why
**Outstanding:** deferred items
```

On startup, read it if it exists and summarize the last session in one sentence before asking whether to continue.

## Anti-patterns
- Every mistake under **Cut craft** — Whisper times as edges, cutting at a word's
  offset, judging level by the transcript, sizing `gain_db` off a range average,
  chasing the low-run numbers to zero, fixing one quiet take with a global
  compressor. They are stated there as procedure; this is the reminder that they
  are also the way Phase 1 goes wrong.
- Committing a grade without the one-frame candidates montage + user pick.
- Shipping a `cut.mp4` that is not tagged bt709/tv — Phase 2 will re-interpret it and the approved grade drifts.
- Butt-joining the takes. The J-cut is the default; `--no-jcut` is a deliberate exception, not a shortcut.
- Tightening a J-cut seam by raising the lead. That buys tightness by shoving the picture deeper into the incoming take's speech. Trim the outgoing TAIL instead.
- A fixed tail trim. It must be bounded by the silence actually measured at that range's end, or it eventually cuts a word off.
- `adelay` in milliseconds when placing overlapped audio, or `-shortest` on the mux. `adelay`'s integer-ms rounding leaves the mix a fraction short of the video and `-shortest` then amputates whole FRAMES of picture — and whether it bites depends on which way the numbers round, so it passes by luck until it doesn't. Delay in samples (`=NS`), and pin the length with `-t`.
- Re-transcribing cached sources; re-rendering Phase 1 when only Phase 2 changed.
- In Claude Code, launching the preview without arming `watch_edits.py` in the same turn. In Codex, failing to read saved preview edits on the next user message. This
  is the one failure mode where the user reasonably believes they handed you a
  decision and you never got it — the toast says saved, the file is written, and
  no one is reading it.
- Applying `preview_edits.json` blindly — validate new edges against `speech_regions.py` first (flag clipped words to the user).
- Asking "NORMAL ou LOG?", or assuming the profile without running `detect_color.py`. It reads the answer off the file; ask only on `confidence: low`.
