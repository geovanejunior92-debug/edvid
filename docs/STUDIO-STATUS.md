# Edvid Studio — estado da implementação

Aplicativo local próprio sobre o motor compartilhado entre Astra e Claude. A versão local 0.2 acrescenta acabamento manual, exportação com QC e revisão, além do corte técnico e Treblo; **ainda não há paridade integral com o aplicativo comercial**.

| Área | Disponível |
|---|---|
| Aplicativo Mac | Janela WebKit, seletores Finder, biblioteca persistente de pastas |
| Fila | Inspeção FFprobe, proxy, pipeline técnico e música; cancelamento de processos descendentes |
| Entrada | Fonte de vídeo, roteiro salvo como referência e idioma da transcrição |
| Corte técnico | WhisperX, proposta por pausas acústicas, intervalos visíveis, aprovação vinculada à revisão/hash |
| Render do corte | Staging, detecção de cor, shot_check e verify_cut; bloqueio quando os gates reprovam |
| Ajustes | Trims, remoções e cortes por texto com validação acústica, histórico de EDL e nova aprovação |
| Acabamento local | Legendas manuais/JSON, título, insert local em tela cheia ou divisão simples e trilha com ganho/fades/ducking |
| Exportação local | H.264 SDR Rec.709 e AAC; saída versionada, QC automático e aprovação visual separada |
| Música | Treblo instrumental, duração sugerida, consulta de conexão/saldo, confirmação de créditos, player e recuperação por taskId |
| Claude e Astra | Mesma instalação canônica; não equivale a chat de IA dentro do aplicativo |
| Instalação | Assinatura ad-hoc local, dependente do motor e das dependências deste Mac |

## Limites que continuam abertos

- O roteiro é armazenado; ainda não guia seleção semântica. A proposta por pausas não escolhe os melhores trechos pela narrativa.
- O corte gerado é um preview técnico. O pipeline novo não substitui todos os gates de áudio, cor/LUT, acabamento e revisão integral exigidos pela skill para entrega final.
- Ajustes executam trims, remoções e cortes por texto compatíveis com as bordas acústicas. Seleções que exigiriam apagar fala vizinha são rejeitadas; notas livres ainda dependem de interpretação do agente.
- O acabamento local é um subconjunto manual: não incorpora os efeitos dinâmicos completos, matte atrás da cabeça, logo/encerramento e todos os presets do Formato 1. O fluxo Remotion existente é preservado. Importação de legendas aceita JSON; SRT e edição avançada de múltiplos inserts ainda não estão completos na UI.
- Geração Treblo está integrada, mas uma geração paga real não foi executada nesta validação. Consulta autenticada de saldo funcionou; geração/download foram testados com respostas simuladas.
- Chat Codex/Claude/Gemini, outros provedores de imagem/vídeo, Canva, publicação/agendamento social e biblioteca de estilos ainda exigem implementação/autenticação próprias.
- Developer ID, notarização, instalador independente e atualizador assinado permanecem pendentes. O usuário escolheu continuar com instalação local.

## Evidência e referências

Os testes cobrem contratos de API/fila, aprovação, troca da fonte, caminhos confinados, staging e recuperação de música. Os testes de codec com padrões sintéticos foram bloqueados pelos gates visuais/de cor: isso valida o bloqueio, não uma entrega final bem-sucedida. A revisão visual é dos controles do Studio, não de um vídeo final do usuário.

Consulte [STUDIO-FINISH.md](STUDIO-FINISH.md) para o acabamento local e [PARIDADE.md](PARIDADE.md) para a matriz comercial, [BASELINE-ORIGINAL.md](BASELINE-ORIGINAL.md) para os comportamentos anteriores que devem ser preservados e [TREBLO.md](TREBLO.md) para uso e recuperação de música.

Validação desta ampliação: 70 testes passaram com ResourceWarning tratado como erro. Layout dos novos controles conferido no navegador em 1280 px e 820 px, incluindo os intervalos de aprovação e Treblo. Consulta de saldo pela interface autenticou sem geração paga. Revisão independente corrigiu EDL após J-cut, taxa de quadros real, ciclo de aprovação e cancelamento de música.

## Validação da versão local 0.2

95 testes passaram; a proteção final dos rascunhos foi conferida também na interface, alternando entre projetos e verificando que o texto foi preservado e o render antigo continuou bloqueado. Um projeto sintético de quatro segundos foi salvo, aprovado e exportado pela UI, com título, legenda, insert e música; o QC passou e a saída permaneceu aguardando revisão visual. Duas exportações idênticas também preservaram arquivos separados. O novo shell Swift compilou e a assinatura ad-hoc foi verificada. Controles e player foram conferidos em 1280 px e 820 px. Isso comprova o fluxo local testado, não a paridade integral nem a qualidade editorial de vídeos reais.
