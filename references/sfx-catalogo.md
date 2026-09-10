# Catálogo de efeitos sonoros — o pacote inteiro, antigo + novo

Criado em 2026-08-17 a partir de uma referência que o usuário mandou (33s
ensinando sete usos de efeito sonoro), **medida** e não apenas assistida. Regra
que ele deu junto: *"adicione ao seu acervo de edição como SOMA, para melhorar o
leque de opções e não para substituir os que você já tem"*. Nada do pacote
antigo saiu.

## Quando cada efeito entra

As sete regras da referência, na ordem em que ela ensina:

| Efeito | Momento | Arquivo |
|---|---|---|
| **keyboard / typing** | algo sendo DIGITADO na tela | `typing.mp3`, `key.mp3` |
| **clicks** | qualquer coisa APARECENDO na tela | `click.mp3`, `click1/2.mp3`, `pop.mp3` |
| **camera shutter** | cortes rápidos e transições | `shutter.mp3` |
| **UI sounds** | uma ANIMAÇÃO aparecendo | `ui-blip.mp3`, `ui-tap.mp3` |
| **whoosh** | zoom in / zoom out, entradas e saídas | `whoosh.mp3`, `whoosh-long.mp3` |
| **hits** | DEPOIS de revelar algo importante | `hit.mp3`, `hit-soft.mp3` |

Duas coisas que a referência mostra e que a lista acima não diz:

- **O riser começa ANTES do momento e resolve em cima dele.** Medido: 1,23s de
  varredura terminando exatamente na palavra. Riser em cima do fato chega tarde.
- **O hit vem DEPOIS da revelação, não junto.** E é um por vídeo: na referência
  ele é o pico do áudio inteiro, com 1,68s contando a cauda.

## Níveis (medidos na referência, contra a voz dela)

| Efeito | Nível vs voz | Leitura |
|---|---|---|
| hit da revelação | **+10 dB** | é o pico do vídeo, de propósito |
| riser, typing | **+8 dB** | altos, mas espalhados no tempo |
| shutter, whoosh | **−1 a +1 dB** | no nível da fala |
| UI | **−6 a −25 dB** | detalhe quase subliminar |

A lógica: **quanto mais raro o efeito, mais alto ele entra.** UI aparece toda
hora e fica baixo; o hit acontece uma vez e estoura. Copiar essa proporção
importa mais que copiar os valores absolutos.

## O pacote em disco

`assets/shortform/public/sfx/` — vai junto no `cp -R` do template.

**Antigo** (`generate_sfx.py`): `whoosh`, `pop`, `click`, `click1`, `click2`,
`cut-click`, `tictac`, `caption-click`, `caption-scratch`.
**Novo** (`generate_sfx_extra.py`, 2026-08-17): `typing`, `key`, `shutter`,
`ui-blip`, `ui-tap`, `hit`, `hit-soft`, `whoosh-long`.

**`whoosh-rev` está BANIDO (2026-09-03, pedido do usuário).** Ele ouviu o efeito
na saída da capa e mandou tirar e não usar mais, em nenhum vídeo. Fora do
catálogo do `sfx_plan.py`, fora do gerador e fora da regra da capa. Mesmo status
do riser: **não reintroduzir**, nem com outro nome, nem em outro gatilho. O
arquivo continua nos projetos antigos para não quebrar o render deles.

Todos sintetizados, sem licença de terceiros. O gerador é determinístico
(semente fixa): rodar de novo produz o mesmo pacote.

## Como entra na edição

Os efeitos são **dado**, não código: `sfxCues` no `edit-data.json`, tocados pelo
componente `SfxCues`. Assim eles aparecem já na entrega pós-corte e seguem até o
render final sem serem remontados.

```json
"sfxCues": [
  {"at": 27.93, "src": "sfx/riser.mp3", "volume": 0.42, "dur": 1.6,
   "label": "tensão antes do ponto"}
]
```

**Helper:** `uv run python helpers/sfx_plan.py <edit-dir> [--dry-run]
[--intensidade 1.0]`. Ele PROPÕE a partir do EDL, das janelas e do transcript —
a escolha final é de quem edita. Revise a lista contra o conteúdo antes de
renderizar; um riser em cima de uma frase morna soa manipulador.

**Ele não empilha som onde já existe.** As transições já tocavam um clique; o
helper TROCA esse som (shutter na entrada da janela, whoosh na saída) em vez de
somar um segundo efeito em cima. Cues novos só entram em pontos silenciosos —
capa saindo, tensão, revelação, tela final. Isso é exatamente o que ele pediu:
*"adicionar em pontos que não tem efeito sonoro ainda"*.

## Onde isso entra no fluxo

**Depois do corte, antes da aba Estilo.** A entrega pós-corte já leva corte,
zoom, transições e flash; agora leva o som também (pedido dele, 2026-08-17).
Ordem: Fase 1 → `sfx_plan.py` → render da prévia → ele assiste → aba Estilo →
Fase 2.

No **formato 1** isso é automático e não se pergunta: o preset já entra com as
transições sonorizadas e os acentos nos pontos silenciosos, ajustando ao
conteúdo daquele vídeo.

## Dose: 20–30% do pacote novo, nunca 100%

Correção dele em 2026-08-17, depois de eu trocar TODOS os efeitos de uma edição
pelos novos: *"eu falei que poderia adicionar para usar às vezes em uma edição
ou outra, mas não substituir 100% dos efeitos. Tente fazer só 20-30% de mudança
e somente se for interessante."*

A base continua sendo a paleta antiga (clique no corte, whoosh na saída). O
pacote novo entra em **2 ou 3 pontos por vídeo**, onde acrescenta de verdade —
um shutter numa entrada de janela, o hit na revelação, o swell no encerramento.

E menos é mais: a mesma edição levou *"muito cheio de efeitos sonoros, causando
muita poluição"*. Três acentos em 60s bastam. **Riser repetido é o pior
ofensor** — ele não entendeu três risers e perguntou o que eram (5s, 22s, 32s).
Riser só quando o conteúdo REALMENTE constrói tensão, no máximo um por vídeo.

## Pacote 2 (2026-08-17) — medido de uma segunda referência

Ela usa um vocabulário mais BRILHANTE. Três formas novas, sintetizadas a partir
da medição (não extraí o áudio dela — é biblioteca licenciada por ela):

| Arquivo | Medido na referência | Uso |
|---|---|---|
| `outro-swell.mp3` | 0,98s, tonal (planura 0,001), cresce até 630ms, centróide 900→3300 Hz | **som de encerramento**, entre o fim da fala e a tela final |
| `whoosh-bright.mp3` | 0,58s, 54% da energia acima de 8 kHz, centróide caindo 8200→3500 | transição mais brilhante que o whoosh antigo |
| `riser-deep.mp3` | 1,55s, 29% de graves, cresce até o fim e resolve | virada longa |

O `outro-swell` é padrão do formato 1: entra ~1s antes da tela azul.


## Riser — banido (2026-08-20)

Pedido dele, ouvindo o riser aos 13s do vídeo "Sono e cérebro": *"retirar efeito
sonoro no segundo 13 e excluir ele do acervo. não usar mais."* `riser.mp3` foi
apagado do template compartilhado e o bloco que o colocava automaticamente saiu
do `sfx_plan.py`. `riser-long.mp3` e `riser-deep.mp3` continuam em disco mas
NENHUMA variante entra sozinha — só se ele pedir um riser por nome. Não
reintroduzir "tensão antes do ponto" com outro arquivo: o que ele rejeitou foi o
efeito, não o arquivo.
