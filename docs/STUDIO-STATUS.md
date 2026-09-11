# Edvid Studio — escopo da versão 0.1

Esta é a primeira versão local do aplicativo próprio, construída sobre o motor compartilhado. Não é uma reprodução completa do Edvid comercial.

| Área | Escopo desta versão |
|---|---|
| Aplicativo Mac | Janela própria WebKit, seleção pelo Finder, compilação Swift |
| Projetos | Registro local persistente de pastas e reabertura |
| Revisão | Acesso ao preview/editor já existente no motor |
| Processamento | Fila local serial para inspeção de mídia e proxy leve, com cancelamento |
| Diagnóstico | Disponibilidade do Python, FFmpeg e FFprobe, resultados de tarefas |
| Claude e Astra | Mesmos arquivos do motor canônico; não é uma sessão de IA embutida |
| Distribuição | Build local com assinatura ad-hoc; requer motor e dependências neste Mac |

## Próximas etapas ainda não entregues

- Fluxo de transcrição, criação de EDL e render final operável inteiramente pela interface.
- Timeline completa com todas as operações do aplicativo comercial, desfazer/refazer e testes de intercâmbio.
- Integrações de geração de vídeo, imagem e trilha com autenticação individual.
- Instagram, Metricool e Meta com agendamento, prevenção de duplicações e confirmação de publicação.
- Biblioteca de estilos aprendidos a partir de referências, com proveniência.
- Editor de imagens integrado aos helpers existentes e integração autenticada com Canva.
- Empacotamento independente, Developer ID, notarização e atualizador assinado.
- Auditoria comparativa completa das funções comerciais e testes de desempenho em projetos grandes.

O proxy é uma cópia leve para navegação, não o vídeo final de máxima qualidade. Não substitui o original nem comprova SDR Rec.709 de entrega. As regras de cor, áudio, aprovação e revisão de qualidade da skill continuam valendo para o render final.

## Verificação desta entrega

- Build Swift compilado e assinatura ad-hoc verificada.
- 25 testes Python passaram, com ResourceWarning tratado como erro: inclui os testes existentes de projetos e os novos testes do Studio.
- Verificação visual na janela normal e na janela mínima de 820 px: biblioteca, seletor Finder, preview vertical e controles de fila.
- Teste manual de fechar/reabrir preservou projeto e análise concluída; análise real com ffprobe e proxy real com FFmpeg foram executados em vídeo sintético de três segundos.
- Revisão independente de código corrigiu recuperação de mídia por projeto, sobrevivência da fila a falha de limpeza e descarregamento de mídia ao trocar projeto.
- Os testes não equivalem à revisão de um vídeo final do usuário nem à validação de todas as funções do editor legado.
