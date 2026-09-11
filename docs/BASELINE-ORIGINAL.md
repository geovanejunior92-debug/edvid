# Referência do edvid anterior à ampliação do Studio

Fonte indicada pelo usuário e lida no navegador em 2026-09-11: [Mapa do Edvid, por Claude](https://claude.ai/code/artifact/2c1fb965-3ae6-45a7-aa2a-6892fcf342ba).

O relatório se apresenta como atualizado em 11/09/2026 e inclui `studio_server.py` em construção. Portanto é uma referência da skill e suas calibragens, não uma prova de uma versão imutável anterior a qualquer modificação. Os números de helpers e filtros são afirmações do relatório, sujeitos à versão do disco.

## Comportamentos a preservar

- Áudio orienta corte; limites acústicos, palavras completas, buffers, J-cut, extração por segmento e concatenação.
- Inventário/transcrição local, distinção Parakeet não alinhado versus WhisperX alinhado, pré-scan de voz e limpeza condicionada ao gate de qualidade.
- Detecção de perfil de cor, medição e correspondência entre tomadas; conferência visual/acústica das bordas.
- Proposta e aprovação antes de executar; verificação numérica antes de inspeção de imagens; miniaturas e teste dos LUTs antes de oferecer escolha.
- Preview com timeline, waveform, transcrição, marcações e diagnóstico; corte aprovado antes do acabamento de Fase 2.
- Fase 2 descrita em JSON/Remotion; legendas na área segura, câmera dinâmica, matte de pessoa e costura fundida da tela dividida.
- Inserts que realmente se movem e têm resolução adequada; trilha manual ou Treblo, com efeitos visuais sincronizados sem deslocar a fala.
- Capa, formatos sociais, QC de entrega e revisão integral; resultado reprovado não é entrega pronta.
- Trilha paralela de imagem: post, carrossel, capa, QC e Canva quando autenticado.
- Calibragens pessoais existentes no SKILL.md/references/memórias continuam valendo. Uma função nova do Studio não deve substituí-las por defaults genéricos.

## Limite da automação inicial do Studio

Uma proposta técnica por pausas não substitui seleção narrativa feita por um agente. Um preview renderizado não prova, sozinho, que passaram todos os gates editoriais, de áudio, cor e entrega. A matriz de paridade deve registrar essas diferenças e somente declarar fluxo completo após testes correspondentes.
