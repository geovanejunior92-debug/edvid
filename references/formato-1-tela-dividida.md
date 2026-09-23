# FORMATO 1 — tela dividida (@drgeovanejunior)

**Gatilho:** o usuário diz *"edição com tela dividida formato 1"* (ou só
"formato 1"). A partir daí este arquivo É o brief. Ele espera o vídeo
**totalmente pronto**, sem perguntas de estilo — a única coisa que ele fornece
são os clipes de B-roll que faltarem.

Aprovado em 2026-08-17 no vídeo "Tireoide — 4 hábitos", depois de quatro rodadas
de correção dele. Cada valor abaixo é uma decisão que já foi ajustada e aceita:
**copiar, não re-derivar.** Haverá outros formatos no futuro; este é o 1.

## O que NÃO se pergunta

Nada disto vai para a aba Estilo, nada disto é escolha: legenda, cor de
destaque, capa, logo, encerramento, flashes, zoom, altura da faixa. Já está
decidido. `state.json` sai com `awaitingStyle: false`. A ÚNICA interação com ele
durante a edição é a lista de B-roll a baixar (e só do que faltar no acervo).

## A receita

Base: `assets/presets/formato-1.json` → copiar para
`<edit>/remotion/public/edit-data.json` e preencher os campos `PREENCHER`.
Os valores fixos estão lá; o que segue é o porquê e o que varia.

| Camada | Valor fixo | Varia por vídeo |
|---|---|---|
| Base | layout 1080×1920 renderizado na resolução do `cut.mp4` (4K = `--scale 2`), fps da fonte (60), câmera `zooms [1.14,1.2,1.12,1.22]`, `pushIn 0.04` | `durationSec` |
| Capa | `hookStacked`: entra em `offsetY 0.30`, desliza para `0.155` (1,0s→1,9s), some em **4,0s**; branco com a palavra-chave em **`#3b82f6`**; tamanhos 112/66/112/92 | as 4 linhas |
| Logo | `brand/logo-transparente.png`, centralizada na **borda inferior**, `width 520`, `bottom 120`, até **4,0s** | — |
| Legenda | `stacked`, `stackedOffsetY 0.30`, `fontScale 0.92`, `accent` e `pencilColor` **`#3b82f6`** | — |
| Tela dividida | `bandH 508` + blend 100 = 608 (altura natural de um 16:9), `fit cover`, `layout top`, `focusY 560`, `matte` por janela, `zoomPulse` alternando | as janelas e os clipes |
| Transições | `variant "corte"` na entrada, `variant "saida"` (intensity 0.85) na saída | derivado das janelas |
| Som de encerramento | `outro-swell.mp3` **na transição** que leva à tela azul (`at ≈ outro.startSec − 0,2s`), volume ~0.6, e a última transição SEM `sfx` próprio | — |
| Encerramento | fundo **`#071d33`** (azul escuro), letras douradas `#d4b25f`, 2,6s, **sem fade de saída** | `startSec` |
| Áudio | trilha 0.07, áudio do Remotion (preserva os SFX), loudnorm −14 LUFS | — |

Três amarrações que quebram se mexidas isoladamente:

- **`bandH` e `focusY` andam juntos.** A pessoa é posicionada a partir da faixa
  (`(y_src − focusY) × zoom + bandH`). Mudou um, recalcule o outro e confira num
  still.
- **A costura é a borda inferior do CLIPE.** Por isso `bandH` é a altura natural
  do 16:9 e `fit` é `cover`. Qualquer preenchimento atrás do clipe (blur, preto)
  vira "sombra" — foi rejeitado explicitamente.
- **A primeira tela dividida nunca antes de 4s**, porque a capa ocupa até lá.
  Pode ser depois (alguns segundos, conforme o conteúdo), nunca antes.

## O fluxo, do corte à entrega

1. **Fase 1 normal** — corte, `voice_levels`, grade, `verify_cut`, LUTs. Sem
   novidade aqui.
1b. **Som (2026-08-17).** `sfx_plan.py <edit-dir>` — o formato 1 sai com efeito
   sonoro como complementação: onde a transição já soa, o som é TROCADO
   (shutter na entrada da janela, whoosh na saída); onde há silêncio, entram
   acentos novos (capa saindo, riser antes de um ponto forte, hit na virada,
   whoosh na tela final). Revisar a proposta contra o conteúdo — riser em cima
   de frase morna soa manipulador. Catálogo e níveis:
   `references/sfx-catalogo.md`.

2. **B-roll: reconciliar o acervo ANTES de escolher.** Ler
   `~/Videos/stock-medico/` e `PEDIDOS.md`, marcar `[x]` o que já chegou (é
   trabalho do agente), e só então montar a lista do que falta.
3. **ASSISTIR cada candidato.** 3 frames por clipe (15/50/85% da duração) numa
   folha ordenada, lida contra a frase daquela janela. Depois de recortar,
   amostrar de novo — o recorte pode cair fora do assunto. Se nada servir,
   **pedir download**; não aproveitar o que está perto. (Regra criada porque
   entrou um homem comendo sanduíche sob a fala "tanta gente toma remédio e
   continua cansada".)
   Armadilha: nos recortes, `-ss` vai **depois** do `-i` (eles saem com um
   keyframe só e o seek de entrada devolve arquivo vazio, sem erro claro).
4. **Um matte por janela** (`person_matte.py`, frame 0 = início da janela).
   ~7,5s de processamento por 60 frames; barato.
5. **Preencher o preset** e derivar as transições.
6. **Gate dos inserts** — `check_inserts.py`, exit ≠ 0 = não renderiza.
7. **Render** → loudnorm → `final.mp4`. **Antes de renderizar, copie o
   `cut.mp4` atual para `remotion/public/`** — refazer a Fase 1 sem recopiar
   monta a Fase 2 inteira sobre o corte VELHO, com legenda e janelas no lugar
   errado e nenhum erro na tela. Aconteceu em 2026-08-17; hoje o
   `review_final.py` compara as durações e reprova.
8. **Revisão de 100% antes de entregar** — `review_final.py <edit>`: cobertura
   visual do vídeo inteiro em folhas de contato + checagem numérica (movimento
   por janela, capa/logo/encerramento, áudio, sincronia, duração). **Abrir todas
   as folhas.** O número não vê legenda errada nem arte fora de contexto.
   Só depois disso entregar.

## O que a revisão de 100% já pegou

Ela não é cerimônia — no primeiro uso pegou a tela final desaparecendo nos
últimos frames (tinha fade de saída, e o vídeo reaparecia por baixo). Um defeito
que passou por três renders e por várias folhas de contato esparsas.

## Histórico das correções que formaram o formato

Cada uma custou um render; estão aqui para não voltarem:

- Faixa reta em cima → a cabeça tem que **passar na frente** da arte, mantendo a
  divisão (não é trocar um efeito pelo outro).
- `fit: contain` com fundo escuro → virou sombra na costura.
- Insert fora de `<Sequence>` → congelava no último frame em toda janela que não
  começasse perto do zero.
- Sem `zoomPulse` → dezenas de segundos sem variação de enquadramento.
- Volta seca da tela dividida → flash de saída próprio.
- Laranja do template → **azul** `#3b82f6`; petróleo do encerramento → **azul
  escuro** `#071d33`.

## Dois defeitos que só o olho pegava — agora são teste (2026-08-20)

No vídeo 01 (Mounjaro) os números deram tudo certo e a revisão visual achou dois
erros que teriam ido ao ar:

1. **Linha da capa cortada na largura.** "que ninguém comenta" virou
   "ue ninguém coment" — 19 caracteres em `size 100` não cabem em 1080.
   Limite medido: **15 caracteres em size 100**; acima disso a linha encolhe
   proporcionalmente (`size = 1500 / nº de caracteres`). O `review_final.py`
   agora reprova antes do render.

2. **Nome de remédio corrompido pela transcrição.** "do Mounjaro" saiu
   "do mongeiro". Junto com "A dona do Ozempic" → "A dona Dozenpich"
   (2026-08-19), viraram `references/termos-medicos.json`: grafia certa → formas
   erradas já vistas. O gate varre `captions.json`, `caption-cues.json` e
   `transcripts/cut.json`. **Acrescentar ali toda vez que um erro novo aparecer** —
   é o que faz o dicionário valer alguma coisa.

O resto da revisão de 100% continua obrigatório: gate nenhum vê enquadramento
feio nem arte fora de contexto.

## Três correções dele em 2026-08-23 (Vídeo 05)

- **Som de finalização entra na transição, não antes.** A tabela dizia "~1s antes
  da tela azul"; ele ouviu e reprovou: *"veio muito antecipado"*. O swell começa
  junto com a última transição e resolve DENTRO da tela azul. Pediu para valer em
  todo vídeo, não só no formato 1.
- **O assunto do insert tem que ocupar a largura da faixa.** A cabeça dele fica no
  terço central e engole qualquer clipe com assunto centralizado — sobra a
  periferia, que quase sempre é fundo. Recorte fechando no assunto até ele encostar
  nas bordas, e conferir num still com a máscara por cima. Custou dois
  reenquadramentos no clipe da balança.
- **Logo no rodapé, e cuidado com repostagem.** A logo/selo entra na borda inferior
  e fica fixa, sem encostar na legenda. Em vídeo JÁ PUBLICADO a fonte costuma trazer
  o próprio selo queimado mais ou menos ali: os dois se sobrepõem e nenhum fica
  legível. Checar os primeiros segundos antes de ligar a camada.
- **Volume da entrega.** Se a fonte vem acima de −12 LUFS, entregar em −10 LUFS /
  TP −1, não nos −14 padrão. Ele compara com o original antes de postar.

## A faixa não é um valor fixo: depende do enquadramento da FONTE (2026-08-23)

`bandH 508` / `focusY 560` foi calibrado num vídeo de plano médio. Numa fonte que
já é close (cabeça ocupando a metade de cima do quadro), esses valores produzem o
defeito que ele apontou no Vídeo 05: a cabeça engole a faixa e sobra do B-roll uma
lasca no canto superior direito. Não é bug do componente — é o preset encontrando
outro enquadramento.

Os dois parâmetros andam juntos e o efeito é somado:
`y_pessoa = (y_fonte − focusY) × zoom + bandH`. Subir `bandH` aumenta a faixa **e**
empurra a pessoa para baixo; baixar `focusY` empurra a pessoa para baixo sem mexer
na faixa.

Para uma fonte em close, o par que fecha as DUAS coisas — faixa legível e legenda
inteira — foi **`bandH 860` + `focusY 640`** (faixa total 960 com o blend).

**A legenda desce junto.** A camada re-desenha o vídeo com o enquadramento da
faixa, então `bandH` e `focusY` deslocam a legenda queimada exatamente como
deslocam a cabeça. Com `bandH 760 / focusY 400` a faixa ficava ótima e a segunda
linha da legenda saía do quadro — defeito que ele apontou. Calibre sempre num
still de uma legenda de **duas linhas dentro de uma janela**; a de uma linha cabe
com folga e esconde o problema. `npx remotion still Reels out/s.png --frame=N`
custa segundos e é a única forma de ver isso.

Consequência: **o clipe da faixa tem que ser exportado na proporção da faixa**, não
em 16:9. Com `bandH 860` são 1080×960 (proporção 1,125). Um clipe 16:9 nesse espaço é
ampliado pelo `fit: cover` e perde largura, com perda de nitidez. Recorte a fonte
1920×1080 em 1215×1080 e escale para 1080×960.

## Capa: para no cabelo, não no rosto (2026-08-23)

`offsetY 0.26 → offsetYEnd 0.07`, substituindo o `0.30 → 0.155` do preset. Em
fonte de close o valor antigo põe as linhas em cima dos olhos e da boca. Ele pediu
a correção **para todas as edições**. Não descer abaixo de ~0,06: mais alto encosta
na barra superior do Reels.

## Três correções dele em 2026-09-23 (Vídeo 06)

- **A costura cruza o TERÇO SUPERIOR da cabeça, pegando só parte do cabelo.**
  *"A divisão está abaixo da minha orelha; essa linha deve ficar no terço
  superior da minha cabeça."* A "fração 0,40" do `seam_check.py` é medida a
  partir da caixa do DETECTOR DE ROSTO, que começa na testa e ignora o cabelo.
  Numa fonte em plano médio isso pôs a costura a 52–59% da cabeça real, nos
  olhos. Meça o topo do cabelo pelo alfa da máscara (`person_matte.py`, primeiro
  quadro da janela) e use `focusY = topo + 0,13 × (queixo − topo)`. A costura
  cai em source-y = focusY, qualquer que seja o zoom ou o bandH.
- **Legenda stacked não se move com `captions.windows`.** Quando a pessoa desce
  no quadro, a legenda cai na boca. Ajuste por janela: `bandH` 700 e
  `zoomPulse` para o queixo ficar em ~1330 e a base do vídeo cobrir até 1920
  (`z ≥ 1220 / (1920 − focusY)`, com zoom-base ~1,3 do SplitFrame).
- **Sem trilha com batida marcada.** A `trilha.mp3` reaproveitada dos projetos
  anteriores tem chimbal a 130 bpm e virou um "tic tic tic" embaixo da fala.
  Sem uma trilha ambiente, `soundtrack.enabled: false`; os SFX com par visual
  continuam.
- **Cor da fonte intacta.** Ele pediu o vídeo "sem LUT (alteração de cor)":
  `grade` vazio no EDL, sem `skin_protect`. Cor só quando ele pedir.
