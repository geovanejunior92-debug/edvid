# Formato 3: reação em tela dividida

Pedido do usuário em 2026-11-08. A pessoa aparece reagindo ao vídeo de outra pessoa.

## Estrutura
1. **Entrada:** fala curta dele na metade de baixo; conteúdo mudo em cima, com cartão de citação.
2. **Meio:** conteúdo em cima, com o áudio dele; a pessoa ouvindo embaixo, sem som próprio.
3. **Saída:** tela cheia, com a fala de encerramento. É o fim do vídeo: **sem tela azul final**.

## Regras
- **Divisão:** no centro da tela, com dissolução larga (y 874 a 1066 em 1920; 1748 a 2132 em 4K).
- **Passagem:** o vídeo de cima fica transparente na parte de baixo e se funde com a imagem da pessoa, sem borda, sombra ou faixa escura. Sem matte.
- **Troca para a saída:** clarão `saida` com whoosh baixo, a única transição do formato. Sem flash no fim da fala de entrada.
- **Conteúdo maior que o trecho ouvindo:** esse trecho entra em laço, sem repetir a fala, com fusão curta só no painel de baixo.
- **Entrada e saída:** sempre da mesma roupa. O script recusa a mistura.
- **Identificação e pedido para seguir:** cortar do conteúdo os trechos em que a pessoa, profissional de saúde ou não, se identifica (nome, profissão, cargo, perfil) ou pede para seguir. Vale em qualquer ponto do vídeo. Transcrever com tempo por palavra antes de montar, cortar a frase inteira e conferir se o que sobra continua fazendo sentido. Nome ou perfil só escrito na tela não sai com esse corte: avisar o usuário.
- **Capa:** manter o texto e a posição da capa do conteúdo original durante a entrada. Ela é extraída da abertura e volta por cima de tudo; a pessoa desce o necessário para a capa não cobrir os olhos.
- **Conteúdo dentro de outra montagem:** usar só a pessoa original. A fala e a saída do outro reator saem, e o que vaza do fundo dele fica fora da dissolução.
- **Sem zoom no conteúdo:** pedido dele em 2026-11-09. Sempre a largura inteira do vídeo, porque o zoom cortava a pessoa (vídeos 06, 08 e 12 do primeiro lote). Para esconder o que vaza, ajustar `moldura`, nunca ampliar. Logo do conteúdo que sobrar fica: avisar o usuário.
- **Identificação do médico:** durante a fala da entrada e da saída, e só nelas, mostrar na parte de baixo, em fonte fina e discreta: `Dr. Geovane Júnior` e `CRM - PE 28037`.
- **Velocidade:** 1,07× no vídeo inteiro, com o tom preservado.
- **Resolução:** 4K vertical, a das entradas e saídas.

## Entrega
Cada vídeo editado vai com uma legenda para o post: breve, direta e sem sinais de texto de IA. Passar pelo `humanizer` antes de entregar e usar só o que é dito no conteúdo, sem inventar fato, número ou nome.

## Como montar
```bash
python helpers/reacao.py job.json -o saida.mp4
```
O job traz `conteudo`, `ini`, `fim`, `intro_fim`, `cortes`, `capa` (`box` ou `rect`, em pixels de 720x1280), `palavras`, `troca`, `entrada` e `saida`. Conferir `capa` e o texto da legenda em cada vídeo.

`moldura` é opcional e ajusta um vídeo sem zoom: `y` (linha do original em que o recorte começa, para tirar faixa preta ou subir o rosto), `fade_ini` e `fade_fim` (dissolução em 4K; `fade_fim` termina antes de o outro reator aparecer), `topo_cabeca` e `leg_y`. Boca na dissolução: subir com `y` ou começar a dissolução mais abaixo. Conteúdo com legenda própria no meio da imagem: `sem_legenda`, em vez de escrever por cima. A biblioteca fica fora do repositório, em `~/Videos/reacoes/biblioteca.json`.

## Estado
Em uso: lote de 20 vídeos em 2026-11-08, com quadros de cada um revisados. Áudio medido, mas não ouvido por inteiro.

## Armadilhas
- Conteúdo pode ter cartão próprio logo depois da abertura: use `cartao_ate` ou `cartao2` no job, senão ele fica por baixo da legenda nova.
- Pessoa que anda pela largura ou close em que a boca cai na dissolução: conferir quadros de vários momentos, não só do começo.
- Texto da legenda vem da transcrição: corrigir com `troca`, e deixar o trecho sem legenda quando a fala não estiver clara.
