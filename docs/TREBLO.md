# Treblo no Edvid Studio

O painel de música gera trilhas instrumentais pela API oficial Treblo v3. A chave fica no processo Python, nunca na interface, no projeto ou no repositório. Usa `TREBLO_API_KEY` do ambiente ou do `.env` da instalação compartilhada.

1. Abrir um projeto no Studio.
2. No painel Treblo, testar a conexão. A consulta de saldo não cria uma geração.
3. Descrever gênero, instrumentos, andamento e clima. Definir intervalo desejado em múltiplos de 30 segundos; a duração é uma orientação ao modelo.
4. Confirmar o uso de créditos e solicitar a trilha.
5. A fila acompanha o processo; ao concluir, o áudio fica em `edit/music` e pode ser ouvido no painel. Gerar a música não a mistura automaticamente no vídeo.

Cancelar interrompe a espera local. A API pode continuar processando e cobrar a geração; o Studio não promete estorno. O identificador remoto fica no manifesto ao lado do áudio. Fechar/reabrir não reenvia tarefas antigas.

Se ocorrer falha depois de registrar um `task_id`, o helper aceita `--resume` com esse identificador para consultar e baixar a tarefa existente, sem criar outra. Se a conexão cair antes de receber o identificador, conferir o histórico na Treblo antes de gerar de novo. Nenhuma geração POST é repetida automaticamente.

O download aceita apenas HTTPS em domínios Treblo e verifica se o arquivo contém áudio antes de entregar. Mudança de CDN para outro domínio exige revisão da integração. O áudio original e os arquivos existentes não são substituídos.

Referência consultada: https://treblo.com/developers/docs (2026-09-11).

Validação real desta configuração: consulta autenticada de saldo funcionou. Testes de geração usam respostas simuladas e validação de arquivos; nenhuma música paga foi solicitada no teste de integração.
