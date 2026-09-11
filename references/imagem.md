# TRILHA DE IMAGEM — post, carrossel, capa, thumbnail

Leia este arquivo quando o pedido for **imagem estática**, não vídeo: post de feed, carrossel, story parado, thumbnail de YouTube. É irmão de `shortform.md` e `longform.md`.

Dois caminhos, e a regra de qual usar é a parte que importa.

## A regra de decisão

**Caminho A — próprio (padrão).** Grátis, offline, sem conta. Use quando:
- a imagem deriva de um vídeo que a skill já cortou (capa, carrossel do Reel, thumbnail)
- a marca tem que bater exata com o vídeo — mesma fonte, mesma cor, mesmo look
- é lote: dez capas, carrossel de dez slides, variação de formato

**Caminho B — Canva (MCP).** Use quando:
- o pedido depende do acervo de template ou elemento gráfico do Canva
- ele vai continuar editando na mão depois e precisa do arquivo aberto lá
- é peça fora do repertório: apresentação, PDF, impresso
- ele pediu Canva explicitamente

**Em dúvida: A.** O Canva entra quando agrega algo que o local não faz.

**O gate é do edvid nos dois casos.** O que sai do Canva volta para a pasta do projeto e passa pelo mesmo `qc_image.py`. Design bonito que entra na faixa de baixo do Instagram continua reprovado.

## Por que PIL e não Remotion

O `cover.py` já compõe capa com Pillow + OpenCV. Para quadro **estático**, o Remotion só acrescenta Node, um processo de render e segundos de espera por imagem — paga-se o preço de um motor de vídeo para produzir um PNG. A Fase 2 continua sendo Remotion; a trilha de imagem, não.

## O fluxo (caminho A)

```
1. carousel.py      transcript do corte → esboço de post-data.json
2. VOCÊ reescreve   o texto é fala transcrita, não copy
3. post_render.py   post-data.json → JPGs por formato + sidecar de caixas
4. qc_image.py      GATE. exit ≠ 0 = não publique
5. mostrar          só depois do gate passar
```

`post-data.json` vive na pasta do projeto, ao lado do `edl.json`. Slide novo se escreve no JSON, nunca no código.

### Schema

```json
{
  "projeto": "nome",
  "formatos": ["4x5", "1x1", "9x16", "16x9"],
  "marca": {"fundo": "#071d33", "texto": "#ffffff", "destaque": "#d4b25f"},
  "slides": [
    {"tipo": "capa",   "titulo": "…", "destaque": "palavra",
     "fundo": {"video": "cut.mp4", "at": 4.0}},
    {"tipo": "texto",  "titulo": "…", "corpo": "…"},
    {"tipo": "imagem", "corpo": "…", "fundo": {"arquivo": "insert.jpg"}},
    {"tipo": "cta",    "titulo": "…", "corpo": "…"}
  ]
}
```

Fundo aceita `{"video": …, "at": …}`, `{"arquivo": …}` ou `{"cor": "#…"}`. Sem fundo, usa a cor da marca.

### O que o gate checa

| Checagem | Falha quando |
|---|---|
| contraste | menor que 4.5:1 do texto contra o fundo real sob a caixa (contorno preto rebaixa para aviso) |
| zona segura | texto entra na faixa que a interface do app cobre — baixo, topo, coluna de ícones |
| rosto | texto cobre mais de 12% do rosto. **A frase para no cabelo, nunca sobre o rosto** |
| fonte | menor que 26px, que não se lê no telefone |

O gate lê o sidecar `<imagem>.boxes.json` que o `post_render.py` escreve. Ele não adivinha onde o texto caiu — reconhecer texto na imagem renderizada erraria justamente sobre foto, que é onde o problema acontece.

## O fluxo (caminho B)

```
1. VERIFICAR a conexão   list-brand-kits antes de qualquer coisa
2. canva_brief.py --briefing   monta o pedido a partir do post-data.json
3. generate-design       devolve CANDIDATOS — ele escolhe
4. create-design-from-candidate
5. read-design / edit-design   transação: aplicar, comparar miniatura, commit
6. get-export-formats → export-design
7. canva_brief.py --receber <url>   traz para a pasta do projeto
8. qc_image.py           o mesmo gate
```

**Regras que não se dobram:**

1. Leitura antes de escrita. Em 2026-09-10 o conector estava configurado e devolvia `Connection closed` — **declarado não é o mesmo que conectado**. Se falhar, pare e peça para conectar; não improvise.
2. Brand Kit: perguntar qual, nunca escolher sozinho.
3. `generate-design` devolve candidatos. Mostre as opções — mesma regra das 2 opções por item da Shutterstock.
4. `commit` do `edit-design` é **irreversível**. Confirme antes.
5. `export-design` só depois de `get-export-formats`. Chutar formato falha.
6. Nunca publicar, nunca comprar, nunca mexer em conta.

Arquivo vindo do Canva não tem sidecar de caixas: o gate checa rosto e zona segura, mas não mede contraste, porque não sabe onde o texto está. Isso é limitação real, não bug.

## Coisas medidas que você não deve redescobrir

**Depois do corte, não existe silêncio.** Um `cut.mp4` de 53 s tinha UMA pausa ≥ 0,5 s — é para isso que serve a Fase 1. Quebrar frase por silêncio, como o `pack_transcripts.py` faz na fonte bruta, devolvia 2 frases para o vídeo inteiro. Na saída da Fase 1 a fronteira é a **pontuação**; silêncio só como desempate, com limiar baixo.

**O texto do carrossel é fala transcrita, não copy.** O `carousel.py` propõe e pontua; quem escreve é você. Slide com frase de transcrição crua lê como legenda de vídeo perdida no feed.

**A imagem tem que ter a cor do vídeo.** Post e Reel do mesmo assunto aparecem juntos no perfil. Se o LUT do vídeo não for aplicado à capa, o feed fica descasado — e isso só aparece quando já está publicado.
