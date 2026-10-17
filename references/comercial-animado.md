# Comercial animado no estúdio de edição

Trilha do edvid para um **comercial sem gravação**: textos curtos, cenas animadas,
efeitos e trilha gerados no navegador, no estilo dos comerciais da Apple, tocando
dentro de uma interface de editor (visor em cima, linha do tempo com faixas embaixo,
painel do Claude explicando cada cena). Use quando ele pedir "comercial animado",
"comercial estilo Apple", "estúdio de edição", "interface de edição", "linha do tempo
do Claude" ou um vídeo de marca sem filmagem.

**Não é a Fase 1/2.** Vídeo gravado por ele continua no fluxo normal do edvid (corte,
gate, Remotion). Esta trilha não tem transcrição, EDL nem gate de corte: o gate aqui
é o roteiro.

Origem: o motor é o da skill gratuita "Estúdio de edição" (Amanda Diniz, Divos da
IA), em `assets/comercial/estudio.html`. A adaptação (2026-10-17) manteve o motor e
acrescentou três coisas: fontes locais da marca, exportação direta em MP4 e quadros
de conferência. O convite para o curso pago que a skill original fazia foi retirado:
o edvid já edita os vídeos gravados.

## O que mudou em relação à skill original

| Original | No edvid |
|---|---|
| Editar o bloco `PROJETO` dentro do HTML | Escrever `ficha.json`; `comercial.py build` injeta |
| Conferir "de cabeça" (cenas contínuas, 6 palavras, cronômetro) | `comercial.py check`: erro de máquina, exit ≠ 0 |
| Só dá para ver dando play | `comercial.py still`: folha de quadros em ~3 s |
| Filmar a tela com o celular para ter o vídeo | `comercial.py render`: MP4 1080p ou 4K, 30/60 fps, som em −14 LUFS |
| Fonte do Google Fonts (depende de internet e oscilava no export) | `fontes.arquivos` com as fontes da marca em `assets/fonts` |
| Paleta âmbar genérica | Preset do consultório: `assets/comercial/ficha-drgeovane.json` |

## Fluxo

1. **Briefing, uma pergunta por vez, só o que faltar.** Para o @drgeovanejunior a marca,
   as cores e a fonte já estão no preset: não pergunte. Pergunte o tema/oferta do
   comercial, a frase que resume e se quer o gancho do cronômetro ("me dá 20 segundos",
   que segura quem assiste até o fim). Duração padrão: 28 s (faixa 20–35).
2. **Roteiro para aprovação.** Tabela `Tempo | Cena | Texto na tela | Por quê`, seguindo
   a estrutura abaixo. Textos passam pelo humanizer antes de aparecer. Espere o "pode
   montar".
3. **Montar.** Copie o preset para `~/Videos/comerciais/<nome>/ficha.json`, preencha, e:
   ```
   uv run python helpers/comercial.py build ~/Videos/comerciais/<nome>/ficha.json --out ~/Videos/comerciais/<nome>
   uv run python helpers/comercial.py still ~/Videos/comerciais/<nome>
   ```
   Leia `verify/sheet.png` (um quadro no meio de cada cena) antes de mostrar. Texto
   cortado, cena vazia ou fonte errada aparecem ali. `--at 3.2 6.6` para instantes
   específicos (transições, o zero do cronômetro).
4. **Mostrar.** `build --abrir` abre no Chrome (o motor usa filtros de canvas que o
   Safari desenha diferente). Espaço dá play.
5. **Ajustes.** Ele fala do jeito dele ("a cena 4 tá grande"). Mude só a ficha, rode
   `build` de novo e peça ⌘R. Mudou um tempo? Ajuste cenas vizinhas, textos e sons
   juntos; o `check` acusa o que ficou desencaixado.
6. **Entregar.** Duas saídas, e ele escolhe:
   - **MP4 do comercial:** `comercial.py render <pasta> [--fps 60] [--escala 2] [--hevc]`.
     PNG por quadro, x264 CRF 16, bt709/tv, som em duas passagens de loudnorm.
     Medido: 28 s a 30 fps em 67 s (`--jpg` faz em 37 s com perda leve).
   - **Gravar a interface** (o vídeo "olha o Claude editando"): Chrome em tela cheia,
     brilho no máximo, celular levemente de lado (de frente aparecem listras), foco
     travado na tela. Dois takes: um com **M** (o Claude monta a edição na frente da
     câmera e dá play sozinho), outro com **H** e Espaço. Atalhos: Espaço play, M
     montagem, H só visor e barra, F tela cheia, S som, L repetir.

**Formato:** o motor desenha 1920×1080. Não há versão vertical. Para Reels, o MP4 16:9
entra como insert/tela dividida de outro vídeo, ou ele grava a interface na vertical
com o celular.

## Regras

1. **Só a ficha muda.** O motor (`assets/comercial/estudio.html`) é compartilhado e
   testado; mexer nele vale para todo comercial futuro e só a pedido dele.
2. **Só a marca dele.** Nada de logo, nome ou produto de outra empresa. "Estilo Apple"
   é o jeito de editar.
3. **Até 6 palavras por tela**, frase com ponto final. O `check` bloqueia acima disso.
4. **Conteúdo médico:** sem promessa de resultado, sem antes/depois, sem "você
   sente…/você tem…". Lista e números só com o que ele confirmou (os três itens do
   preset são exemplo de forma, não fato). Vitrine segue a regra do Instagram: o foco
   é estética médica e procedimentos.
5. **Encerramento da marca:** a cena `assinatura` usa o monograma "G" em dourado sobre
   o petróleo, com `Dr. Geovane Júnior` e `CRM-PE 28037 · RQE 13075`. O arquivo
   `~/Videos/marca-drgeovane/logo/logo-transparente.png` é um cartão de perfil
   (avatar + @, texto cinza), ilegível a 260 px: não use como logo aqui.
6. **Antes de mostrar:** `check` com exit 0 e a folha do `still` lida.

## A ficha

JSON puro. Campos:

| Campo | O que é |
|---|---|
| `estudio` | nome no canto da interface (`"Edvid"`) |
| `marca`, `titulo` | marca e título do projeto no topo |
| `pedido` | o pedido como ele falou; aparece no painel do Claude |
| `duracao` | segundos (20–35) |
| `cores` | `fundo`, `texto`, `destaque`, `acento`, `suave`, `claro`, sempre `#rrggbb` |
| `fontes` | `titulo`, `peso`, `texto`; `arquivos: {"Poppins": "Poppins-ExtraBold.ttf"}` procura ao lado da ficha e depois em `assets/fonts`. Fonte local atende todos os pesos e tira o Google Fonts da disputa |
| `cronometro` | `{segundos, aparece, comeca, zera, some}` ou `null`; `zera = comeca + segundos`, `some ≈ zera + 1,6`, som `destrava` no `zera` |
| `trilha` | `tom` `maior`/`menor`, `volume` (0,16; 0 tira), `pausa: [ini, fim]` |
| `imagens` | `{chave: arquivo}`; o `build` copia para a pasta como `<chave>.<ext>` |
| `cenas`, `textos`, `sons` | abaixo |

### Cenas

`{"id": "S01", "nome": "…", "tipo": "…", "ini": 0, "fim": 1.2, "params": {…}, "nota": "…"}`.
Contínuas de 0 até `duracao`. A `nota` é a decisão de edição em uma frase; aparece no
painel do Claude.

| Tipo | Mostra | `params` |
|---|---|---|
| `rolagem` | feed passando | `{"parado": true}` congela e desfoca |
| `fundo` | brilho da marca | `{"estilo": "brilho"\|"escuro"\|"claro"}`; `claro` inverte |
| `numero` | número gigante vazado | `{"texto": "20"}` |
| `anel` | relógio de marcas | `{"marcas": 20, "progresso": "cronometro"}` |
| `particulas` | brilhos subindo | `{"quantidade": 70}` |
| `foto` | foto com zoom lento | `{"imagem": "produto", "lado": "direita"\|"centro"\|"cheia", "zoom": [1, 1.07], "moldura": true}` |
| `lista` | itens com check | `{"itens": [...]}` até 4, até 4 palavras |
| `contador` | número contando | `{"ate": 1200, "prefixo": "+", "sufixo": "", "casas": 0}` |
| `medidor` | ponteiro subindo | `{"valor": 9, "max": 12, "unidade": "bar"}` |
| `notificacoes` | cards chegando | `{"itens": [["Agenda", "Reunião em 5 min"], …]}` até 4 |
| `linhas` | linhas de luz | `{}` |
| `assinatura` | logo ou monograma | `{"imagem": "logo"}` ou `{"monograma": "G"}` |

### Textos

`{"ini", "fim", "linhas": [1 ou 2], "tam", "destaque": [linha, "final da linha"], "cor", "alinhar": "esq", "x", "y", "sub"}`.
Dentro de uma cena, entrando 0,05–0,15 s depois dela. `tam` 120–160 para frase,
200–260 para uma palavra; duas linhas até 140. `cor`: `claro` (padrão), `escuro` (sobre
`fundo claro`), `grad` (assinatura), `suave` (rótulo). Rótulo embaixo de número:
`"y": 760, "tam": 60`.

### Sons

`{"t": 2.0, "tipo": "whoosh"}`: `rolagem` (com `dur`) junto da abertura, `baque` no
"Calma.", `whoosh` 0,2 s antes de cada troca, `entra` quando o cronômetro aparece,
`revelacao` 0,5 s antes da primeira revelação, `notificacoes` no começo dessa cena,
`impacto` 0,5 s antes da cena `claro`, `destrava` no zero, `assinatura` na última cena,
`ding` avulso. Tudo sintetizado no navegador; a regra de "som com par visual" do edvid
já está atendida porque cada som cai numa troca de cena.

## Estrutura que funciona

1. 0–1 s `rolagem`; 1–2,2 s `rolagem` parada com "Calma."
2. Gancho: "Me dá 20 segundos." com `numero`, cronômetro entrando.
3. Ponte: frase que amarra o tempo a algo do serviço ("É o tempo de ouvir você.").
4. Revelação: `foto` ou `particulas` com o nome e uma linha.
5. 3 a 5 provas, uma ideia por cena, 2–3 s cada (`lista`, `contador`, `medidor`, `foto`).
6. Quebra: `notificacoes` ("O resto pode esperar.").
7. Pergunta e resposta: "Vale 20 segundos?" e, na cena `claro`, "Vale." com `pausa` da trilha.
8. Zero do cronômetro: "Pronto. Pode rolar agora." com `destrava`.
9. `assinatura`, 2–3 s.

Sem cronômetro: tire 2, 3 e 8 e comece pela promessa.
