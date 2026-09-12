# Edvid Studio — estado da implementação

Aplicativo local próprio sobre o motor compartilhado entre Astra e Claude. A versão local 0.3 usa a mesma biblioteca e a mesma mesa de edição da versão web, acrescenta Fase 2 Remotion, acabamento manual, exportação com QC e revisão, além do corte técnico e Treblo; **ainda não há paridade integral com o aplicativo comercial**.

| Área | Disponível |
|---|---|
| Aplicativo Mac | Janela WebKit, seletores Finder, biblioteca visual com miniaturas e editor web compartilhado |
| Biblioteca | Busca, fixar, renomear, arquivar e restaurar usam o mesmo estado no web e no aplicativo |
| Fila | Inspeção FFprobe, proxy, pipeline técnico, Remotion, acabamento e música; cancelamento de processos descendentes |
| Entrada | Fonte de vídeo, roteiro salvo como referência e idioma da transcrição |
| Corte técnico | WhisperX, proposta por pausas acústicas, intervalos visíveis, aprovação vinculada à revisão/hash |
| Render do corte | Staging, detecção de cor, shot_check e verify_cut; bloqueio quando os gates reprovam |
| Ajustes | Trims, remoções e cortes por texto com validação acústica, histórico de EDL e nova aprovação |
| Acabamento local | Legendas manuais/JSON, título, insert local em tela cheia ou divisão simples e trilha com ganho/fades/ducking |
| Exportação local | H.264 SDR Rec.709 e AAC; saída versionada, QC automático e aprovação visual separada |
| Música | Treblo instrumental, duração sugerida, consulta de conexão/saldo, confirmação de créditos, player e recuperação por taskId |
| Claude e Astra | Mesma instalação canônica; não equivale a chat de IA dentro do aplicativo |
| Instalação | Assinatura ad-hoc local, dependente do motor e das dependências deste Mac |

## Acrescentado em 2026-09-11/12 (Claude)

| Área | Disponível |
|---|---|
| Fase 2 (Remotion) | `studio_phase2.py`: painel no app, scaffold sem sobrescrever, dependências compartilhadas, validação de `edit-data.json`, `check_inserts` antes e `qc_final` depois, aprovação por revisão+hash e revisão integral do arquivo antes da entrega |
| Corte editorial | `align-script` casa roteiro e transcrição; propõe tomadas, marca linha não gravada e aponta improviso. Gaveta "Tomadas do roteiro" no editor para a escolha |
| Tratamento técnico | `treat`: nível de voz, limpeza com gate próprio, estabilização por tremida medida, casamento de cor entre tomadas, e relatório do que ficou bloqueado |
| Biblioteca | web e nativa passaram a usar o MESMO identificador e o mesmo arquivo de marcas; fixar/arquivar valem nos dois lados |

## Limites que continuam abertos

- O roteiro guia o alinhamento e expõe alternativas de tomada, mas a decisão semântica ainda usa limiares heurísticos. Sem roteiro, a proposta por pausas não escolhe os melhores trechos pela narrativa.
- O corte gerado é um preview técnico. O pipeline novo não substitui todos os gates de áudio, cor/LUT, acabamento e revisão integral exigidos pela skill para entrega final.
- Ajustes executam trims, remoções e cortes por texto compatíveis com as bordas acústicas. Seleções que exigiriam apagar fala vizinha são rejeitadas; notas livres ainda dependem de interpretação do agente.
- O acabamento local continua sendo um perfil manual separado. A Fase 2 Remotion agora roda no aplicativo, mas o Studio ainda não cria sozinho todos os dados e assets do Formato 1, como matte, inserts pesquisados, logo e encerramento. Importação de legendas aceita JSON; SRT e criação avançada de múltiplos inserts ainda não estão completas na UI.
- Geração Treblo está integrada, mas uma geração paga real não foi executada nesta validação. Consulta autenticada de saldo funcionou; geração/download foram testados com respostas simuladas.
- Chat Codex/Claude/Gemini, outros provedores de imagem/vídeo, Canva, publicação/agendamento social e biblioteca de estilos ainda exigem implementação/autenticação próprias.
- Developer ID, notarização, instalador independente e atualizador assinado permanecem pendentes. O usuário escolheu continuar com instalação local.

## Evidência e referências

Os testes cobrem contratos de API/fila, aprovação, troca da fonte, caminhos confinados, staging e recuperação de música. Os testes de codec com padrões sintéticos foram bloqueados pelos gates visuais/de cor: isso valida o bloqueio, não uma entrega final bem-sucedida. A revisão visual é dos controles do Studio, não de um vídeo final do usuário.

Consulte [STUDIO-FINISH.md](STUDIO-FINISH.md) para o acabamento local e [PARIDADE.md](PARIDADE.md) para a matriz comercial, [BASELINE-ORIGINAL.md](BASELINE-ORIGINAL.md) para os comportamentos anteriores que devem ser preservados e [TREBLO.md](TREBLO.md) para uso e recuperação de música.

Validação desta versão: **307 testes passaram**. O layout foi conferido visualmente com a biblioteca, miniaturas, navegação estreita, painel de ferramentas, timeline e player vertical. Um render Remotion completo sintético em 1080×1920 produziu 48 quadros a 24 fps. O gate recusou corretamente o padrão sintético por níveis e zona segura; o teste separado confirmou que o motor renderizou o vídeo inteiro. A correção também fixou todas as dependências Remotion em 4.0.482, pois a faixa aberta de `layout-utils` havia instalado 4.0.520 e impedia qualquer render real.

## Validação histórica da versão local 0.2

95 testes passaram; a proteção final dos rascunhos foi conferida também na interface, alternando entre projetos e verificando que o texto foi preservado e o render antigo continuou bloqueado. Um projeto sintético de quatro segundos foi salvo, aprovado e exportado pela UI, com título, legenda, insert e música; o QC passou e a saída permaneceu aguardando revisão visual. Duas exportações idênticas também preservaram arquivos separados. O novo shell Swift compilou e a assinatura ad-hoc foi verificada. Controles e player foram conferidos em 1280 px e 820 px. Isso comprova o fluxo local testado, não a paridade integral nem a qualidade editorial de vídeos reais.
