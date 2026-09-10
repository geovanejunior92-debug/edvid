# OPENCUT — ajuste fino do corte numa timeline de verdade

Leia este arquivo quando o usuário quiser **mexer no corte arrastando clipe**
("quero ajustar na timeline", "abre no OpenCut", "deixa eu mexer nas bordas")
em vez de descrever o ajuste no chat.

## O que muda e o que NÃO muda

O OpenCut não substitui o pipeline. Ele decide UMA coisa: **onde cada take
começa e termina**. Cor, J-cut, fades de 30ms, `gain_db`, concat lossless,
Fase 2 em Remotion — tudo continua sendo do `render.py`. O `edl.json` segue
sendo a fonte da verdade; o OpenCut é só uma forma de editá-lo com a mão em vez
de com prosa.

Por isso a ida e a volta são baratas: o que trafega é a lista de ranges, não o
vídeo renderizado.

## Primeiro: o preview do edvid já faz parte disso

A interface padrão do preview já tem alças de trim por take e remoção de take,
e o que ela salva (`edl.changes` / `edl.removed`) é validado contra
`speech_regions.py` antes de virar `edl.json`. **Para "esse take entra tarde
demais" ou "tira o último take", o caminho continua sendo o preview** — é mais
curto, e é o único dos dois que avisa quando a borda nova corta uma palavra.

O OpenCut entra onde o preview não vai:

- **Reordenar takes.** O preview edita bordas e remove; não troca a ordem.
- **Recuperar material que ficou de fora.** No preview você arrasta a borda
  scrubando o `cut.mp4` — o material descartado não está lá para ser visto. No
  OpenCut o clipe carrega a fonte inteira, então esticar um take mostra
  exatamente o que está entrando.
- **Trabalho fora do fluxo do edvid.** É um editor completo, local e do usuário:
  serve para qualquer coisa que não seja um Reel do pipeline.

**Não vale** quando o pedido é sobre conteúdo ou som — trocar de take, escolher
outra frase, corrigir nível, mudar grade. Isso é decisão de edição e volta pro
método normal do SKILL.md. Também não vale para Fase 2: legenda, insert, tela
dividida e trilha são Remotion, e nada disso existe no bundle.

**A borda continua sendo sua.** O OpenCut não conhece `speech_regions.py`, não
sabe o que é limite de palavra e deixa cortar no meio de uma sílaba sem avisar.
Depois de toda devolução, rode `verify_cut.py` no `edl.json` novo antes de
re-renderizar — a Hard Rule 4 (nunca cortar dentro de uma palavra) não se
suspende porque o corte veio de um arraste.

## Pré-requisitos

- OpenCut instalado em `~/Developer/opencut` (versão *classic* — a única com
  editor funcionando; ver "Qual repositório" no fim).
- Servidor de desenvolvimento no ar em `localhost:3000`. No Claude Code:
  `preview_start` com o nome `opencut` (config já em `~/.claude/launch.json`).
- Um `edl.json` aprovado, ou pelo menos gerado, em `<edit>/`.

## Quando ela sobe sozinha

Desde 2026-09-01 a ponte **não depende de o usuário pedir**. No gate da Fase 1,
quando o corte tem **3 ou mais takes**, o passo 9c manda subir a ponte junto e
mandar a URL na mesma mensagem do gate, como segunda opção depois do preview —
uma linha, sem vender. Com 1 ou 2 takes, e em qualquer job de Formato 1, não
sobe e não se menciona: reordenar não existe ali e o link extra só disputa
atenção com a aprovação do corte.

Fora disso, ele pode pedir a qualquer momento ("abre na timeline") e o ciclo
abaixo é o mesmo.

## O ciclo

1. **Suba a ponte** (deixe rodando em background — é ela que recebe a volta):

   ```
   python3 helpers/opencut_bridge.py serve --edit-dir <edit> [--port 4840]
   ```

   Ela lê o `edl.json`, faz `ffprobe` em cada fonte, escreve
   `<edit>/opencut/bundle.json` e imprime a URL de importação. Se a porta
   estiver ocupada — normalmente outra ponte, de outro projeto — ela desce pra
   próxima livre e avisa qual pegou. Nunca reusa a porta ocupada: importaria o
   projeto errado.

2. **Mande ele abrir a URL impressa** — `http://localhost:3000/edvid?bundle=…` —
   e clicar em **Importar**. O navegador baixa as fontes pro OPFS e monta o
   projeto: um clipe por range, na ordem, com o `beat` como nome do clipe. Cai
   direto no editor.

3. **Ele arrasta.** Bordas, ordem, clipe removido — o que quiser.

4. **Ele volta em `/edvid` e clica em Devolver.** A ponte reescreve o
   `edl.json`, com backup em `edl.json.bak-<timestamp>`, e imprime take a take
   o que mudou:

   ```
   edl.json reescrito: 5 → 4 takes, 47.8s (backup: edl.json.bak-20260901-205350)
      1. HOOK: início -0.30s, fim +0.00s → [2.12, 6.85]
      2. PONTO 1: início +0.00s, fim -0.50s → [12.00, 18.00]
      — REMOVIDO CTA [30.00, 34.00]
   ```

   Se você não estiver olhando o stdout da ponte na hora, pegue depois com
   `opencut_bridge.py status --edit-dir <edit>`.

5. **Re-renderize normalmente:** `verify_cut.py` → `render.py edl.json -o
   cut.mp4` → gate. O ciclo pode repetir sem reimportar: o projeto continua no
   OpenCut e o botão Devolver continua valendo.

## O que a ponte preserva (e por quê)

`grade`, `voice_master`, `jcut`, `sources` voltam intactos — o OpenCut não os
conhece e não tem como opinar sobre eles.

`beat`, `quote`, `reason`, `gain_db` e `chapter` **não se perdem**: cada range
devolvido herda os do range original com maior sobreposição temporal na mesma
fonte. Um take arrastado meio segundo continua sendo o mesmo HOOK, com o mesmo
`gain_db`. Um clipe criado do zero na timeline volta sem esses campos, marcado
com `"reason": "range novo, criado no OpenCut"` — e aparece como `NOVO` no
resumo, justamente para você decidir se ele merece um `beat`.

## Limites conhecidos

- **Um sentido de cada vez para a Fase 2.** O bundle leva as fontes originais,
  não o `cut.mp4` graduado. É de propósito: editar sobre o corte já renderizado
  faria o ajuste de borda perder o material adjacente, que é exatamente o que
  você quer poder recuperar ao arrastar.
- **Sem áudio separado.** O bundle monta uma trilha de vídeo só. Trilhas de
  áudio adicionadas no OpenCut são ignoradas na volta.
- **Fontes grandes viajam inteiras** pro OPFS do navegador (uma cópia por
  projeto importado). Para uma fonte longa, corte antes com
  `ingest_url.py --section`.
- **Mídia de fora do edvid bloqueia a volta.** Se ele arrastar um arquivo dele
  pra timeline, a devolução falha com mensagem explícita em vez de inventar um
  range — o `edl.json` só sabe falar das fontes que ele declara.

## Onde as peças moram

| Peça | Caminho |
|---|---|
| Ponte (bundle + servidor + merge de volta) | `helpers/opencut_bridge.py` |
| Página de import/export dentro do OpenCut | `~/Developer/opencut/apps/web/src/app/edvid/page.tsx` |
| Bundle gerado, por projeto | `<edit>/opencut/bundle.json` |
| Resumo da última devolução | `<edit>/opencut/last_return.json` |

## Qual repositório

`opencut-app/opencut` está em reescrita: hoje o `/editor` dele é literalmente
uma página com "Coming soon". O editor que funciona é
`opencut-app/opencut-classic`, e é ele que está em `~/Developer/opencut` — o
clone da reescrita fica em `~/Developer/opencut-next`, só para acompanhar.

Quando a reescrita entregar o que promete no README (servidor MCP, modo
headless, API de editor), a ponte muda de forma: em vez de página web +
IndexedDB, vira chamada de ferramenta direto. O contrato — `edl.json` manda,
OpenCut só mexe em borda — continua o mesmo.
