# Acabamento local no Edvid Studio

O painel de acabamento parte de um `edit/cut.mp4` existente. É uma opção de edição manual dentro do aplicativo; o fluxo Remotion e as calibragens do Formato 1 continuam disponíveis na skill compartilhada.

## Sequência de uso

1. Abra o projeto e revise o corte.
2. Configure as camadas disponíveis no painel. Arquivos escolhidos precisam estar dentro da pasta do projeto.
3. Salve a configuração. Ela recebe uma revisão vinculada ao corte e às mídias usadas.
4. Aprove a revisão exibida e mande renderizar.
5. Confira o resultado do QC. Uma reprovação impede a liberação como entrega.
6. Reproduza o vídeo inteiro, confira imagem, texto e som e só então confirme a revisão integral.

As folhas de contato ajudam a inspecionar o vídeo, mas são amostras. Não comprovam que alguém assistiu a todos os quadros ou ouviu todo o áudio.

## Preservação e qualidade

O render usa uma pasta de trabalho própria e preserva o corte, o EDL e os projetos Remotion existentes. Mudanças no corte ou nas mídias invalidam a aprovação correspondente. Nenhum comando desta etapa compra mídia, gera conteúdo em serviço pago ou publica nas redes.

A exportação SDR não deve apenas trocar as etiquetas de um vídeo HDR/LOG. Fontes que precisam de conversão devem passar pelo fluxo de cor antes do acabamento. Não há upscale automático: aumentar a resolução nominal não recupera detalhe que a fonte não contém.

A medição de volume integrado da mixagem não equivale à medição isolada da voz. O tratamento aplicado deve ser descrito pelo que faz, sem prometer recuperação de áudio ou qualidade de cinema a partir de qualquer gravação.

## Funções que não devem ser confundidas

Uma divisão simples de tela não equivale ao matte atrás da cabeça calibrado no Formato 1. Legendas manuais não equivalem à geração de legendas narrativas ou a todos os presets comerciais. Os controles locais não substituem os provedores externos, o agendamento social nem a conta Apple Developer.

Os textos são rasterizados com a fonte compartilhada antes da composição, pois o FFmpeg deste Mac não oferece drawtext/libass. A saída usa H.264 CRF 16, AAC 320 kb/s a 48 kHz e conserva a duração do corte. O alvo de volume integrado parte da fonte medida, com redução da trilha guiada pela voz e limiter sem ganho automático. Isso não equivale a remoção de ruído ou recuperação de áudio danificado.
