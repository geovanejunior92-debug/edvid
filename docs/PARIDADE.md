# Plano de paridade do Edvid Studio

Data da auditoria: 11 de setembro de 2026.

**Retrato da versão 0.1 antes desta ampliação.** A matriz abaixo registra a lacuna inicial e os testes de aceite. O estado vigente, incluindo corte técnico, revisões de EDL e Treblo, está em [STUDIO-STATUS.md](STUDIO-STATUS.md). Esses acréscimos ainda não completam os aceites de narrativa, acabamento e entrega final.

## Conclusão

O motor Edvid já cobre grande parte das funções demonstradas no aplicativo comercial, mas o Edvid Studio 0.1 ainda não oferece paridade de uso. Hoje, o Studio cadastra projetos, seleciona mídia, mostra o original, executa `ffprobe`, cria proxy e abre o editor legado. O editor legado permite revisar uma edição que já existe, ajustar intervalos e salvar pedidos em `preview_edits.json` ou `preview_style.json`. Ele não cria a edição inicial nem aplica sozinho os pedidos salvos.

Portanto, contar helpers não mede paridade. Uma função só deve ser considerada entregue no Studio quando o usuário consegue iniciá-la na interface, acompanhar o processamento, revisar o resultado, corrigir ou desfazer a ação e concluir o projeto sem abrir Terminal nem depender de uma resposta posterior do chat.

A matriz comercial consultada registra 17 funções. O motor cobre 15 delas de forma total ou substancial e duas parcialmente. Na interface própria, apenas biblioteca de projetos e marcações de revisão têm fluxo utilizável, embora as marcações ainda precisem de aplicação externa. Transcrição, criação de EDL, efeitos, fontes visuais, legendas, música e render final não possuem fluxo completo no Studio.

Esta análise usa apenas a matriz de funções, o código próprio, a documentação e os testes do motor. Não examina nem copia código proprietário. Também não presume recursos, APIs, autenticação ou direitos associados a uma assinatura comercial.

## Critério de estado

- **Motor**: existe helper, schema ou template capaz de produzir o resultado.
- **Revisão**: o Studio ou o editor legado consegue mostrar ou registrar ajustes sobre um resultado já preparado.
- **Studio E2E**: a interface cria a entrada, dispara uma tarefa, mostra progresso e erros, persiste o estado, permite revisão e produz a saída final.
- **Aceite**: teste mínimo necessário para promover a função a Studio E2E.

## Matriz acionável das 17 funções

| # | Função e evidência | Capacidade existente no motor | Entrada atual | O que falta no Studio | Teste de aceite E2E |
|---:|---|---|---|---|---|
| 1 | Corte limpo por IA. Demonstrado nas aulas. | `transcribe.py`, `pack_transcripts.py`, `speech_regions.py`, `voice_levels.py`, `fillers.py`, EDL e `render.py`. | Terminal ou agente. O preview só abre um `edl.json` já existente. | Ação "Criar corte", seleção da fonte, transcrição, proposta de EDL, aprovação, tarefa de render e aplicação de ajustes salvos. | Importar fonte com erros e pausas, gerar proposta, aprovar, renderizar `cut.mp4`, remover ou aparar um take na timeline, aplicar e reproduzir o novo corte sem Terminal. |
| 2 | Roteiro como guia do corte. Demonstrado nas aulas. | Contexto narrativo existe no fluxo do agente, mas não há campo formal nem algoritmo documentado para alinhar roteiro e transcript. | Nenhuma entrada própria. | Campo de roteiro, armazenamento no projeto, alinhamento com palavras da transcrição, indicação dos trechos encontrados e tratamento de linhas não encontradas. | Colar um roteiro com uma linha omitida e outra regravada; o Studio deve propor os takes corretos, avisar a omissão e manter o texto salvo ao reabrir. |
| 3 | J-cut. Demonstrado nas aulas. | `render.py` usa J-cut por padrão e aceita `--no-jcut`, `--jcut-lead` e `--jcut-tail-trim`; grava `jcut_timeline` no EDL. | Apenas configuração em CLI ou EDL. O preview mostra A1/A2 quando esses dados já existem. | Controle antes do render, valores seguros, preview da junção e persistência por projeto. | Alternar J-cut, renderizar as duas versões e confirmar em três junções que o áudio começa antes da imagem sem cortar palavra nem criar silêncio indevido. |
| 4 | Zoom automático. Demonstrado nas aulas. | `zoomAuto` existe no catálogo e no template de Fase 2. | Aparece no código do seletor de estilo, mas foi retirado do conjunto clicável. | Chave visível, intensidade, preview fiel e escrita em `edit-data.json`. | Ativar, renderizar e medir escala crescente no trecho escolhido; desativar e confirmar escala constante. |
| 5 | Zoom nos cortes. Demonstrado nas aulas. | `zoomCuts` existe no catálogo e no template de Fase 2. | Também está oculto no seletor atual. | Chave visível, intensidade e aplicação automática nas fronteiras do EDL. | Em um corte com quatro segmentos, ativar o recurso e confirmar mudança de escala nas três fronteiras, sem salto fora da área segura. |
| 6 | Flash na transição. Demonstrado nas aulas. | `transitions[]` no `edit-data.json` e render Remotion. | Visível apenas quando o projeto já contém os dados. | Chave geral, edição por corte, duração, preview e sincronização com efeitos sonoros. | Ligar flash em duas fronteiras, desligar em uma, renderizar e confirmar os eventos nos tempos escolhidos e dentro da tolerância audiovisual. |
| 7 | Legendas com presets. Demonstrado nas aulas. | `captions_for_remotion.py`, `caption_style.py` e oito estilos, três animados. O editor mostra faixa de legendas e demos de estilo quando os dados já existem. | Escolha de preset no gate de estilo; geração e render continuam fora do Studio. | Ação de gerar legendas alinhadas, editor de texto e tempo, preset, idioma, correção de palavras, regeneração e render. | Transcrever fala em português, corrigir uma palavra, trocar preset, ajustar um cue e renderizar; `qc_final.py` deve aprovar alinhamento e zona segura. |
| 8 | Headline e texto. Demonstrado nas aulas. | Hook, fontes, estilos, acento e faixas de texto existem em `edit-data.json` e no template. | Seletor de headline no gate de estilo; faixas existentes aparecem na timeline. | Criar, editar, reposicionar, definir intervalo e apagar texto dentro do Studio. | Criar headline de duas linhas, trocar fonte e cor, mover o fim na timeline, salvar, reabrir e renderizar com o mesmo conteúdo. |
| 9 | Tela dividida, inclusive pessoa sobre o conteúdo. Demonstrado nas aulas. | `person_matte.py`, `face_track.py`, `splitInserts`, `splitVideos`, behind-subject e template do Formato 1. | Elementos existentes aparecem como camadas ajustáveis; não há criação pela interface. | Criar intervalo, escolher layout, fonte, mídia e modo atrás da pessoa; gerar matte; mostrar progresso e fallback quando o rosto não for encontrado. | Marcar um intervalo, escolher vídeo local, gerar matte e renderizar a pessoa à frente do conteúdo, sem cobrir rosto nem criar borda instável. |
| 10 | Trilha por arquivo. Demonstrado nas aulas. | `soundtrack.file` no template e pipeline de áudio. A timeline mostra uma faixa somente leitura quando já existe. | Edição manual de dados ou agente. | Importação de MP3/WAV, trim, volume, fades, mute e substituição na timeline. | Importar faixa maior que o vídeo, ajustar entrada, saída e volume, reabrir o projeto e renderizar com loudness aprovado. |
| 11 | Trilha por IA. Demonstrado nas aulas. | `treblo_music.py <prompt> -o <arquivo> --length-min N --length-max N`; a API exige múltiplos de 30 segundos. | Somente CLI, com chave fora do Studio. | Provedor claramente identificado, autenticação solicitada apenas no primeiro uso, prompt, duração validada, custo ou consentimento quando aplicável, geração, audição e descarte. | Sem credencial, o botão deve explicar o requisito sem iniciar cobrança. Com credencial de teste, gerar, ouvir, aceitar e inserir uma faixa; erro remoto deve deixar a fila em falha, não em sucesso. |
| 12 | Inserir imagem ou vídeo, por escolha manual ou busca. Demonstrado nas aulas. | `pexels_search.py`, `google_images.py`, `wikimedia_images.py`, acervo local e `check_inserts.py`. O preview permite mover e aparar inserts já cadastrados. | Helpers separados e edição manual de `edit-data.json`. | Botão adicionar, origem "Arquivo" ou "Busca", resultados com licença e proveniência, download, intervalo, enquadramento e remoção. | Adicionar uma imagem local e um vídeo de busca, arrastar ambos na timeline, reabrir, renderizar e passar `check_inserts.py`. |
| 13 | Geração de vídeo por IA, citada na matriz como Higgsfield. | O fluxo pode usar uma integração externa disponível ao agente, mas não há rota no Studio nem contrato local do projeto. | Fora do Studio. | Seletor de provedor somente para integrações instaladas, autenticação por provedor, prompt, parâmetros, consentimento para gasto, importação e proveniência. | Sem integração, a UI deve mostrar indisponível. Com integração autorizada, gerar um clipe, importar para o projeto e inserir na timeline sem expor credenciais. |
| 14 | Marcações na timeline. Demonstrado nas aulas. | O preview tem marca IN/OUT pela tecla M, texto, remoção e grava `notes[]` com tempos do rascunho e do render. | Funciona no editor legado aberto pelo Studio. | Aplicação rastreável, estado "pendente/aplicada", vínculo com histórico e navegação entre marcações. | Criar duas marcações, reabrir, aplicar uma alteração, manter a outra pendente e navegar até ambas com tempos preservados. |
| 15 | Renderizar. Demonstrado nas aulas. | `render.py` produz o corte; Remotion produz Fase 2; `verify_cut.py`, `review_final.py` e `qc_final.py` verificam as saídas. | Não existe tarefa `render` na fila do Studio. O servidor aceita apenas `probe` e `proxy`. | Botões de preview e final, presets de entrega, progresso real, cancelamento, logs resumidos, gates automáticos e abertura do arquivo concluído. | Renderizar preview e final, cancelar um render sem deixar arquivo parcial, retomar explicitamente, falhar quando o QC reprovar e abrir a saída aprovada pelo Studio. |
| 16 | Biblioteca de projetos. Demonstrado nas aulas. | `ProjectRegistry` persiste `projects.json`; o app adiciona pastas, cria `edit/`, reabre e mostra disponibilidade. | Studio 0.1. | Remover ou arquivar entrada, busca, miniatura, estado do projeto, mídia ativa, último render e migração de schema. | Cadastrar três projetos, reiniciar, buscar, detectar uma pasta movida, recuperar mídia e remover apenas a entrada da biblioteca sem apagar arquivos. |
| 17 | Chaves de API do usuário. Demonstrado nas aulas. | Helpers leem credenciais do ambiente conforme a integração. | Não há tela de contas ou provedores no Studio. | Armazenamento no Keychain, status por provedor, testar conexão, revogar, nunca registrar segredo em `queue.json`, logs ou projeto. | Salvar uma credencial de teste no Keychain, validar, reiniciar, usar a integração, revogar e confirmar por varredura que nenhum segredo foi gravado em arquivos do Studio. |

## Recursos adicionais mostrados nas capturas do usuário

As capturas acrescentam funções de interface que não devem ser confundidas com as 17 linhas da matriz:

| Recurso visto | Estado atual | Requisito de paridade |
|---|---|---|
| Chat com seletor de provedor | Ausente. O Studio não contém sessão de IA embutida. | Definir se o chat será um coordenador local ou uma integração autenticada. Mostrar apenas provedores realmente disponíveis. Nunca prometer assinatura, modelo ou API sem contrato verificado. |
| Chaves de estilo para J-cut, zoom automático, zoom de corte, flash e face tracking | O motor contém as capacidades, mas o seletor atual não expõe todas. `zoomAuto` e `zoomCuts` constam no catálogo e estão deliberadamente fora do conjunto clicável. | Um painel de efeitos com estado persistido, parâmetros seguros, preview e indicação clara de quais etapas exigem novo processamento. |
| Intervalos marcados para tela dividida ou tela cheia | O preview tem marcações genéricas e exibe inserts existentes. | Transformar uma seleção IN/OUT em um bloco visual com tipo, fonte, mídia, camada, enquadramento e controles de início e fim. |
| Fonte de imagem ou vídeo por IA ou manual | Helpers e integrações existem de forma separada. | Um fluxo único de adicionar mídia, com origem, proveniência, autorização, preview, download e inserção. |
| Presets e edição de texto de legenda | Presets aparecem no gate de estilo; texto e tempo não são editáveis de ponta a ponta. | Editor de cue, busca, correção, divisão e junção, com preview do preset real. |
| Timeline com várias camadas | O editor mostra notas, palavras, legendas, vídeo, áudio A1/A2, texto, inserts e música quando os arquivos já existem. | Criar e editar as camadas, não apenas visualizá-las. Definir bloqueio, visibilidade, mute, seleção, ordem e conflitos. |
| Desfazer e refazer | Ausentes. O menu nativo oferece copiar, colar, recortar e selecionar tudo, sem undo/redo próprio do projeto. | Pilha de comandos persistente para toda mutação editorial. Desfazer não pode depender do histórico do campo de texto do navegador. |

## Entradas reais disponíveis hoje

### Studio 0.1

- `POST /api/projects`: registra ou cria a pasta do projeto.
- `GET /api/projects`: lista a biblioteca persistente.
- `POST /api/jobs`: aceita somente `probe` e `proxy`.
- `POST /api/jobs/<id>/cancel`: cancela tarefa enfileirada ou em execução.
- `GET /api/jobs` e `GET /api/diagnostics`: mostram fila e dependências.
- `/project-media/<id>`: reproduz mídia que esteja dentro do projeto.
- `/editor/<id>/`: monta o editor legado para o `edit/` daquele projeto.

### Editor legado

- `POST api/save` grava `preview_edits.json` ou `preview_style.json`.
- `preview_edits.json` pode conter trims, takes removidos, notas, cortes por texto, ajuste de imagem e tempos de inserts.
- A interface nunca altera `edl.json` diretamente. Um agente precisa validar as bordas contra `speech_regions.py`, aplicar a alteração, renderizar e apagar o pedido consumido.
- O editor não possui rota para transcrição, criação de EDL, geração de assets, render final ou aplicação automática dos ajustes.

### Helpers principais que devem virar tarefas do Studio

| Etapa | Comando existente |
|---|---|
| Transcrição precisa | `uv run python helpers/transcribe.py <video> --edit-dir <edit> --language pt --model large-v3-turbo` |
| Transcrição rápida para leitura | `uv run python helpers/parakeet.py <video> --edit-dir <edit>`; a saída `/UNALIGNED` não serve para karaoke nem para fechar borda de corte. |
| Visão compacta | `uv run python helpers/pack_transcripts.py --edit-dir <edit>` |
| Bordas acústicas | `uv run python helpers/speech_regions.py <video>` |
| Nível de voz e sugestão por take | `uv run python helpers/voice_levels.py <video> --edit-dir <edit> --edl <edit>/edl.json` |
| Limpeza de diálogo | `uv run python helpers/audio_clean.py <video> --edit-dir <edit> --denoise rnnoise` |
| Corte renderizado | `uv run python helpers/render.py <edit>/edl.json -o <edit>/cut.mp4 --no-subtitles` |
| Verificação do corte | `uv run python helpers/verify_cut.py <edit>/edl.json <edit>/cut.mp4` |
| Legenda Remotion | `uv run python helpers/captions_for_remotion.py --transcript <edit>/transcripts/cut.json -o <edit>/remotion/public/captions.json` |
| Preset stacked | `uv run python helpers/caption_style.py --transcript <edit>/transcripts/cut.json -o <edit>/remotion/public/caption-cues.json` |
| Rastreio de rosto | `uv run python helpers/face_track.py <video> -o <arquivo.json>` |
| Recorte da pessoa | `uv run python helpers/person_matte.py <video> -o <matte.webm>` |
| Trilha por IA | `uv run python helpers/treblo_music.py <prompt> -o <trilha.mp3> --length-min <múltiplo-de-30> --length-max <múltiplo-de-30>` |
| Busca Pexels | `uv run python helpers/pexels_search.py <consulta> --out-dir <pasta> --type image\|video --orientation portrait` |
| Busca Wikimedia | `uv run python helpers/wikimedia_images.py <consulta> --out-dir <pasta>` |
| Validação de inserts | `uv run python helpers/check_inserts.py <edit-data.json>` |
| Revisão visual | `uv run python helpers/review_final.py <edit>` |
| QC de entrega | `uv run python helpers/qc_final.py <final.mp4> --cut <cut.mp4> --captions <captions.json> --platform reels` |

`timeline_view.py` não deve ser tratado como uma timeline completa. O próprio `--help` marca `--edl` como ainda não implementado. `opencut_bridge.py` oferece intercâmbio com outra aplicação, mas isso não entrega uma timeline própria no Studio.

## Três lotes prioritários

### Lote 1: projeto editável, da fonte ao corte aprovado

Este lote transforma o Studio de biblioteca em editor funcional de Fase 1.

1. Criar um schema versionado por projeto com mídia ativa, roteiro opcional, transcript, EDL, artefatos, estado da etapa e histórico de comandos.
2. Generalizar a fila para tarefas declaradas e seguras: `transcribe`, `pack`, análise acústica, criação de proposta de EDL, `render-cut`, `verify-cut` e aplicação de `preview_edits.json`.
3. Mostrar progresso baseado na etapa e, quando o helper permitir, percentual. Persistir stdout e stderr resumidos sem segredos.
4. Adicionar fluxo "Criar corte": fonte, idioma, roteiro, transcrição, proposta, aprovação, render e revisão.
5. Implementar desfazer e refazer para trim, remoção, restauração e corte por texto. Cada comando deve ser serializável e reversível.
6. Fechar o ciclo do editor: salvar ajuste, validar borda, aplicar ao EDL, renderizar, verificar e atualizar o preview dentro do Studio.

Aceite do lote: um projeto novo entra apenas com um vídeo e termina com `cut.mp4` aprovado, incluindo uma correção de timeline e um desfazer/refazer, sem Terminal e sem mensagem ao chat.

### Lote 2: acabamento visual e áudio com timeline multicamada

1. Expor J-cut, zoom automático, zoom nos cortes, flash e face tracking no painel de efeitos.
2. Permitir criar headline, texto, legenda, imagem, vídeo, tela dividida e trilha. Hoje essas camadas só aparecem quando outro processo já escreveu os dados.
3. Adicionar editor de legenda com texto, tempo, divisão, junção e presets reais.
4. Adicionar fluxo de mídia manual com Finder e fluxo de busca com proveniência e licença.
5. Adicionar volume, fades, mute, visibilidade, bloqueio e ordem de camada.
6. Gerar `edit-data.json`, assets Remotion e preview de Fase 2 dentro da fila.

Aceite do lote: a partir do corte aprovado, criar legenda corrigida, headline, um insert manual, uma tela dividida com matte, música por arquivo e dois efeitos de transição; reabrir o projeto e renderizar o mesmo preview.

### Lote 3: render final, integrações e distribuição confiável

1. Criar tarefas de preview, render final, `review_final.py`, `qc_final.py` e exportação por formato.
2. Bloquear entrega quando um gate reprovar e levar o usuário ao intervalo apontado.
3. Guardar credenciais no Keychain, com status, teste e revogação por provedor.
4. Integrar música e geração de imagem ou vídeo somente quando o provedor estiver instalado e autenticado. Pedir confirmação antes de gasto externo.
5. Adicionar chat ou coordenador somente depois de definir o contrato de segurança, provedor e persistência. O seletor deve refletir capacidades verificadas.
6. Empacotar dependências, assinar com Developer ID, notarizar e implementar atualização assinada.

Aceite do lote: um projeto concluído gera `final.mp4`, passa pelos gates, exporta outra proporção, abre a saída e mantém os segredos fora dos arquivos do projeto e dos logs. A aplicação deve funcionar em uma instalação limpa conforme o modelo de distribuição escolhido.

## Ordem de implementação recomendada

O próximo trabalho deve começar pelo Lote 1. Biblioteca e proxy já estão prontos, mas não criam valor editorial sem transcrição, EDL, aplicação de ajustes e render do corte. O Lote 2 depende do corte aprovado por causa do gate entre as fases. O Lote 3 depende do schema, do histórico e da fila ampliada dos lotes anteriores.

A paridade deve ser atualizada por evidência. Cada linha da matriz só muda para "Studio E2E" depois que o respectivo teste de aceite passar em um projeto temporário e em um projeto real de duração representativa.

## Referências adicionais enviadas pelo usuário

As seis capturas de 11/09/2026 mostram organização em projeto/timeline/preview, seletores de provedor, presets de legenda, intervalos em tela cheia/dividida, trilha e efeitos. Servem como referência de interação, não como autorização para copiar código, credenciais ou marca do produto comercial. A captura de erro de OpenRouter mostra envio de imagem a uma rota sem suporte; adaptadores futuros deverão validar capacidades do modelo antes de aceitar mídia.

O usuário confirmou que não possui Apple Developer e quer continuar com instalação local. Developer ID e notarização ficam fora da entrega local atual; não impedem as melhorias de edição.

A referência detalhada de preservação está em `BASELINE-ORIGINAL.md`, baseada no Mapa do Edvid enviado pelo usuário.

---

# Auditoria 2026-09-11 — Studio 0.2 (Claude)

Refeita contra o CÓDIGO, os TESTES e o comportamento real, não contra nomes de
função. Substitui a leitura de estado da seção anterior, que retratava a 0.1.

## Linha de base medida

| | |
|---|---|
| Motor | commit `1503f53`, `main` = `origin/main`, árvore limpa |
| Suíte completa | **191 testes, todos passando** (29s) |
| Testes do Studio | **70** — `test_studio` 32, `test_studio_pipeline` 24, `test_studio_finish` 13, `test_studio_pipeline_ui` 1 |
| App instalado | `~/Applications/Edvid Studio.app`, versão 0.2.0, ad-hoc |
| Código do app | `EdvidStudio.swift` **146 linhas** — casca WebKit. A lógica é Python |
| Lógica do Studio | `studio_server.py` 833 · `studio_pipeline.py` 732 · `studio_finish.py` 602 |

O relatório anterior mencionava "95 testes específicos do aplicativo". A contagem
real hoje é **70**. Não achei os 25 restantes; pode ser contagem de outra data ou
incluir testes que não são do Studio.

## O que o Studio realmente faz

**Fase 1, completa e sólida.** `studio_pipeline.py` cobre: salvar roteiro,
transcrever (WhisperX), propor corte por pausas, aprovar vinculado a
revisão+hash, renderizar com gates (`detect_color`, `shot_check`, `verify_cut`),
aplicar ajustes do preview com validação acústica das bordas, e desfazer/refazer
por histórico de EDL. Isso é real e está testado.

**Acabamento manual, que NÃO é a Fase 2.** `studio_finish.py` monta um comando
**ffmpeg** com cartões de texto em PNG e legenda queimada. O próprio arquivo
declara que não substitui o projeto Remotion.

## A lacuna estrutural, e é uma só

**O Studio não executa a Fase 2.** Nenhum helper do Studio invoca o Remotion — a
única menção nos 2.167 linhas é a frase que diz que o acabamento manual não o
substitui. Consequência direta:

> **O Formato 1 — o formato de entrega do usuário — não roda dentro do
> aplicativo.** Ele exige Remotion: legenda karaokê, tela dividida com matte,
> zoom e flash da linguagem aprovada, logo, encerramento, efeitos sonoros.
> O caminho de acabamento do Studio produz outro tipo de vídeo.

Isso também colide com a **Hard Rule 10** da skill ("PHASE 2 is Remotion-only —
no ffmpeg/PIL burned text or overlays"). O acabamento manual é legítimo como
perfil próprio e está documentado como tal, mas chamá-lo de paridade seria
errado.

Não é um botão faltando. É a metade de cima do produto.

## Reclassificação das 17 funções da matriz

Motor = existe helper. Studio = o usuário consegue fazer PELA INTERFACE, do
começo ao fim, sem Terminal.

| # | Função | Motor | Studio | Observação medida |
|---:|---|---|---|---|
| 1 | Corte limpo por IA | sim | **sim** | fluxo completo com gates e histórico |
| 2 | Roteiro guia o corte | parcial | **não** | roteiro é salvo, não alinha nem escolhe tomada |
| 3 | J-cut | sim | **não** | padrão no `render.py`; sem controle na interface |
| 4 | Zoom automático | sim | **não** | vive no `edit-data.json`, que o Studio não escreve |
| 5 | Zoom nos cortes | sim | **não** | idem |
| 6 | Flash na transição | sim | **não** | idem |
| 7 | Legendas com presets | sim | **parcial** | o Studio queima legenda por ffmpeg; os 9 presets são do Remotion |
| 8 | Headline e texto | sim | **parcial** | cartão PNG por ffmpeg, não os 5 estilos do template |
| 9 | Tela dividida | sim | **não** | `splitInserts`/matte são Remotion |
| 10 | Trilha por arquivo | sim | **sim** | ganho, fades, ducking |
| 11 | Trilha por IA (Treblo) | sim | **parcial** | saldo autenticado OK; geração paga real nunca executada |
| 12 | Inserir imagem/vídeo | sim | **parcial** | insert local simples; busca e proveniência fora da UI |
| 13 | Vídeo por IA | sim | **não** | sem rota no Studio |
| 14 | Marcações na timeline | sim | **parcial** | marca e aplica; sem estado pendente/aplicada visível |
| 15 | Renderizar | sim | **parcial** | corte e acabamento manual; Fase 2 não |
| 16 | Biblioteca de projetos | sim | **sim** | fixar/renomear/arquivar/desfazer entregues hoje no web |
| 17 | Chaves de API | parcial | **não** | sem tela de contas; sem Keychain |

**Placar honesto: 3 de 17 completas no Studio**, 6 parciais, 8 ausentes. A
contagem anterior ("motor cobre 15 de 17") continua verdadeira e continua não
sendo paridade de uso — é exatamente a distinção que a própria matriz definiu.

## Ordem que isso impõe

A Fase 2 no Studio não é mais um item da lista: é o **pré-requisito** dos itens
4, 5, 6, 7, 8, 9 e 15. Fazer qualquer um deles antes é construir duas vezes.
