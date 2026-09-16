# Preset PRO — foto e vídeo

## Comando padrão

`/deblur /skinpro /relight /colorgrade /enhance`

Este mesmo conjunto de comandos vale para **foto e vídeo**.

## Objetivo visual

O resultado deve parecer **o arquivo original muito bem tratado**, natural, nítido e profissional — nunca uma imagem ou vídeo recriado por IA.

A fidelidade é regra padrão. Não é necessário acrescentar `/fidelity`.

## Semântica dos comandos

- `/deblur`: recuperar nitidez, foco aparente e microdetalhes sem alterar identidade ou geometria.
- `/skinpro`: retoque profissional e discreto de pele/rosto, preservando textura real, poros, barba, cabelo e características individuais. Evitar pele plástica.
- `/relight`: melhorar exposição e distribuição de luz, abrir sombras e controlar altas luzes, preservando a aparência natural da cena.
- `/colorgrade`: equilibrar temperatura, contraste e cores com acabamento profissional, mantendo tons de pele naturais.
- `/enhance`: melhoria técnica global e conservadora de detalhes, clareza, resolução aparente e qualidade.

## Regra de fidelidade

Por padrão, preservar ao máximo: identidade e traços faciais, expressão, formato do rosto, corpo e proporções, pose, cabelo/barba, roupas, acessórios, textos/logos, objetos, cenário, enquadramento e composição. Não adicionar, remover ou reconstruir elementos sem solicitação explícita.

Comandos deliberadamente transformadores, como `/bodytone`, `/backgroundblur` ou `/cinematic`, autorizam somente a transformação específica solicitada.

## Foto

Aplicar os cinco tratamentos de forma conservadora. A prioridade é parecer uma captura original feita com equipamento/iluminação melhores e pós-produção profissional.

## Vídeo

Aplicar a mesma intenção visual dos cinco comandos, porém com **consistência temporal obrigatória**. Usar tracking/propagação temporal quando disponível e evitar processamento independente destrutivo de cada frame.

Evitar:

- flicker de luz, cor, textura ou nitidez;
- rosto/identidade mudando entre frames;
- pele, barba ou cabelo oscilando;
- deformação corporal ou alteração de proporções;
- sharpening/denoise excessivos;
- reconstruções generativas desnecessárias;
- variações artificiais no fundo, roupas ou objetos.

O vídeo final deve parecer **o mesmo vídeo original, apenas muito bem tratado**.

## Intensidade

Os nomes dos comandos representam intenção de edição, não percentuais matemáticos garantidos. Quando houver controles numéricos no pipeline, usar intensidades conservadoras por padrão e permitir override explícito do usuário, por exemplo `/skinpro 10` ou `/relight 30`.

## Claude / Edvid

Esta referência faz parte do comportamento do Edvid. Quando o usuário escrever
`videopro` — sozinho ou dentro de um pedido de edição — interpretar
automaticamente como o preset PRO acima. A sequência completa
`/deblur /skinpro /relight /colorgrade /enhance` continua sendo um atalho
equivalente. Detectar se a entrada é foto ou vídeo e aplicar as regras
correspondentes.
