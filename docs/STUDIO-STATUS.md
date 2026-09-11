# Edvid Studio — estado da implementação

Aplicativo local próprio sobre o motor compartilhado entre Astra e Claude. A ampliação desta entrega acrescenta controles de corte técnico e Treblo; **ainda não há paridade integral com o aplicativo comercial**.

| Área | Disponível |
|---|---|
| Aplicativo Mac | Janela WebKit, seletores Finder, biblioteca persistente de pastas |
| Fila | Inspeção FFprobe, proxy, pipeline técnico e música; cancelamento de processos descendentes |
| Entrada | Fonte de vídeo, roteiro salvo como referência e idioma da transcrição |
| Corte técnico | WhisperX, proposta por pausas acústicas, intervalos visíveis, aprovação vinculada à revisão/hash |
| Render do corte | Staging, detecção de cor, shot_check e verify_cut; bloqueio quando os gates reprovam |
| Ajustes | Aplicação dos textCuts do preview, histórico de EDL e nova aprovação após alterações |
| Música | Treblo instrumental, duração sugerida, consulta de conexão/saldo, confirmação de créditos, player e recuperação por taskId |
| Claude e Astra | Mesma instalação canônica; não equivale a chat de IA dentro do aplicativo |
| Instalação | Assinatura ad-hoc local, dependente do motor e das dependências deste Mac |

## Limites que continuam abertos

- O roteiro é armazenado; ainda não guia seleção semântica. A proposta por pausas não escolhe os melhores trechos pela narrativa.
- O corte gerado é um preview técnico. O pipeline novo não substitui todos os gates de áudio, cor/LUT, acabamento e revisão integral exigidos pela skill para entrega final.
- Ajustes cobrem textCuts e histórico de EDL; trim genérico, remoções e notas ainda não têm execução completa nesse pipeline.
- Legendas, textos, efeitos, tela dividida, inserts, trilha na mixagem e exportação final permanecem no motor/preview existente, sem todo o fluxo conectado aos novos controles.
- Geração Treblo está integrada, mas uma geração paga real não foi executada nesta validação. Consulta autenticada de saldo funcionou; geração/download foram testados com respostas simuladas.
- Chat Codex/Claude/Gemini, outros provedores de imagem/vídeo, Canva, publicação/agendamento social e biblioteca de estilos ainda exigem implementação/autenticação próprias.
- Developer ID, notarização, instalador independente e atualizador assinado permanecem pendentes. O usuário escolheu continuar com instalação local.

## Evidência e referências

Os testes cobrem contratos de API/fila, aprovação, troca da fonte, caminhos confinados, staging e recuperação de música. Os testes de codec com padrões sintéticos foram bloqueados pelos gates visuais/de cor: isso valida o bloqueio, não uma entrega final bem-sucedida. A revisão visual é dos controles do Studio, não de um vídeo final do usuário.

Consulte [PARIDADE.md](PARIDADE.md) para a matriz comercial, [BASELINE-ORIGINAL.md](BASELINE-ORIGINAL.md) para os comportamentos anteriores que devem ser preservados e [TREBLO.md](TREBLO.md) para uso e recuperação de música.

Validação desta ampliação: 70 testes passaram com ResourceWarning tratado como erro. Layout dos novos controles conferido no navegador em 1280 px e 820 px, incluindo os intervalos de aprovação e Treblo. Consulta de saldo pela interface autenticou sem geração paga. Revisão independente corrigiu EDL após J-cut, taxa de quadros real, ciclo de aprovação e cancelamento de música.
