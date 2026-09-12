# Preview compartilhado — atualização de 11/09/2026

Astra e Claude usam assets/preview da mesma instalação. Esta atualização é do editor no navegador, não do aplicativo desktop.

- Mesa lateral com Corte, Estilo e Visual, recuperação de mídia, ajustes de imagem/LUTs e diagnóstico.
- Vídeo e timeline permanecem na área de edição. Abrir Estilo mantém o corte visível como referência; as opções não são uma simulação renderizada da Fase 2.
- Layout lateral para vídeo vertical em tela larga, empilhado na janela menor e com rolagem em telas estreitas.
- Os mesmos IDs, listeners, salvamento, gates e atalhos continuam no motor existente. Não existe chat embutido: salve os ajustes e retorne à conversa com o agente.

Recarregue a página para receber os arquivos novos. O servidor existente serve os assets da instalação canônica; não é necessário encerrar a sessão do Claude.

## Limites atuais

Esta entrega reorganiza a interface. Não implementa toda a paridade comercial, provedores externos ou todas as funções manuais do Studio no preview. As capacidades e pendências anteriores permanecem descritas em STUDIO-STATUS.md. A tela de recuperação não recria um cut.mp4 ausente e não substitui automaticamente um corte aprovado por proxy comprimido.

## Verificação

JavaScript passou na verificação de sintaxe; layout com vídeo sintético e Estilo aberto verificado a 1280x820 e 820x680. A mídia sintética não é um projeto ou entrega do usuário.

## Fontes e pedidos no editor

O painel Vídeos e conversa lista os vídeos diretamente na pasta do projeto (acima de `edit/`). Não move nem reorganiza arquivos e não percorre subpastas. Links de arquivos que já estão nessa pasta são aceitos. A seleção e a ordem ficam no pedido; o preview dos originais usa um player separado, sem modificar o corte aprovado ou sua EDL.

Selecione vídeos, use as setas para ordenar e abra **Ver sequência original**. Os blocos representam arquivos inteiros, com largura uniforme; não são formas de onda nem cortes por duração. O player passa ao próximo arquivo selecionado ao terminar. Use **Voltar ao corte** para retornar à edição.

Para um único vídeo, **Iniciar corte automático** grava o pedido em `edit/agent-requests/` e o próprio servidor coloca o trabalho na fila. Ele transcreve em português, cria a proposta técnica por pausas, registra a aprovação vinculada à revisão e ao hash, renderiza um preview e verifica o corte. O histórico mostra fila, transcrição, proposta, render, conclusão ou erro e é atualizado a cada três segundos. O modo automático é aprovação explícita somente dessa estratégia técnica de Fase 1; não aprova acabamento, legendas, inserts nem a Fase 2.

Roteiro, ajuste e seleção com vários vídeos continuam sendo pedidos editoriais para Astra ou Claude. Nesses casos, a UI preserva fontes e ordem no mesmo diretório, com status `pending` ou `awaiting_agent`, sem fingir que uma sessão de IA está rodando dentro do Preview.

Cada envio recebe uma chave de idempotência preservada enquanto a resposta não chega. Esse estado sobrevive a uma recarga da página: ao voltar, o envio é retomado sem criar dois pedidos iguais. O servidor devolve o pedido existente numa repetição, e um claim durável por processo impede duas instâncias do Preview de renderizarem o mesmo pedido. A fila recupera estados ativos após queda, mas não executa pedidos editoriais antigos. Projetos que já entraram na Fase 2 não são recortados automaticamente, porque isso deixaria acabamento e vídeo final ligados a outro corte.

Links de arquivos continuam disponíveis para revisão e pedidos editoriais. O automático exige um arquivo real dentro da pasta do projeto; quando a fonte é um link, o pedido aguarda o agente copiá-la com segurança antes de cortar.

Esta parte exige um novo processo de `preview_server.py` (novas rotas); atualizar apenas a aba de um servidor antigo não carrega código Python novo. As mudanças anteriores apenas de CSS/JS não tinham essa exigência.

Com `--host 0.0.0.0`, o servidor gera um token de abertura, troca-o por um cookie de sessão e exige mesma origem em toda alteração. Use o link impresso pelo servidor somente no dispositivo do usuário. Em `127.0.0.1`, o Preview continua restrito ao próprio Mac.

## Mídia por intervalo

No corte carregado, marque IN e OUT com **M** ou pelo botão da timeline. A marcação permite ajuste por texto, imagem por IA, clipe por IA e arquivo do projeto, em tela cheia ou dividida. A busca de arquivos lista mídia na raiz do projeto e nas pastas assets/ e edit/assets/, sem mover arquivos. Salve a marcação e depois **Salvar ajustes**.

O arquivo preview_edits.json preserva start/end, renderedStart/renderedEnd e phase; `notes[].media` contém kind, layout, file (local) ou provider (IA), e status=requested. O agente deve ler estes campos junto da descrição, respeitar o intervalo e os gates existentes, gerar/buscar/importar a mídia e renderizar pelo fluxo Remotion. A marcação não altera o vídeo antes disso. A fase é capturada ao criar a nota, mesmo se o usuário mudar de aba antes de salvar.

Shutterstock está disponível como provedor preferido no pedido, com link para https://www.shutterstock.com/ai-video-generator/. O conector disponível ao agente expõe busca de stock, não geração; não há API de geração Shutterstock integrada ao botão. O usuário informou em 11/09/2026 que seu plano é ilimitado para banco e geração de imagens/vídeos; informação declarada, sem inspeção da assinatura nesta entrega. Não presumir cobrança adicional nem adquirir complemento sem confirmação.

## Título e mixagem

A aba Estilo inclui título editável (até 180 caracteres), aplicado às miniaturas, e ganhos relativos por faixa: voz, trilha e efeitos. A galeria de legendas usa duas colunas. Salvar estilo grava headlineText e audioMix.voiceDb/musicDb/sfxDb; watch_edits inclui esses campos no resumo para o agente.

`helpers/preview_mix.py` valida as escolhas, atualiza somente hook.lines de um edit-data.json existente (preserva tempo, logo e demais propriedades) e/ou mistura stems de áudio separados em WAV novo, com ganhos em dB, duração da voz, sem normalização automática do amix. Sem --apply, apenas descreve o plano. Título vazio preserva o texto anterior. A ativação/estilo do hook continua no fluxo existente.

Para mixar, indicar --style, --voice, opcionais --music e --sfx, --output novo.wav e --apply. As entradas devem ser as faixas isoladas da mixagem-base; não aplicar repetidamente sobre saídas já ajustadas. Isso não separa instrumentos ou vozes de áudio pronto. O helper não substitui loudness/sincronismo/QC da entrega: usar a mixagem no remux final, medir e revisar. Limiter pode atuar em picos; ganho pedido não equivale a loudness garantido. Os sliders não alteram separadamente o áudio misturado que já está no player.

## Abertura e vídeo novo

A raiz `/` abre a biblioteca com criação de projeto e seletor de vídeos. O nome gera uma pasta única dentro da biblioteca configurada. Os vídeos selecionados são copiados, sem mover os originais; nomes repetidos não sobrescrevem arquivos. Limite: 8 GiB por arquivo MOV, MP4, M4V ou WEBM. Envios interrompidos removem apenas o arquivo temporário incompleto; importações concluídas permanecem.

Com um único vídeo, o projeto novo inicia transcrição e primeiro corte antes de abrir a sequência original. Com vários vídeos, ele abre a seleção sem iniciar um corte editorial às cegas. Projetos anteriores abrem apenas quando escolhidos, pelo endereço `/p/<id>/`. Reinicie servidores antigos para carregar a fila Python; recarregar a aba sozinho não atualiza o processo do servidor.
