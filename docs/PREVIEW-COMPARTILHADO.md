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
