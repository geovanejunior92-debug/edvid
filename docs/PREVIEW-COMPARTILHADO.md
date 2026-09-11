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

Para roteiro, importe `.txt`/`.md` ou cole o texto. Para corte com IA, descreva a intenção. **Salvar pedido para o agente** grava um arquivo independente em `edit/agent-requests/`, com fontes na ordem escolhida e status `pending`. A UI mostra o histórico e consulta respostas a cada 15 segundos. Volte à conversa do agente e peça a execução dos pedidos do projeto. Não há modelo ou sessão de chat em execução dentro do preview; não confundir salvamento com início automático do corte. O agente consulta os pedidos conforme o SKILL.md compartilhado e registra a resposta somente após trabalhar.

Esta parte exige um novo processo de `preview_server.py` (novas rotas); atualizar apenas a aba de um servidor antigo não carrega código Python novo. As mudanças anteriores apenas de CSS/JS não tinham essa exigência.
