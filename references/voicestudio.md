# VOICESTUDIO — locução gerada num vídeo

Leia este arquivo quando ele pedir locução, narração ou voz gerada num vídeo
("coloca uma narração", "gera a locução desse roteiro"). Sem esse pedido, nada
daqui roda: `render.py`, trilha, efeitos e o volume padrão não mudam.

Instalação, vozes e regras de licença estão na skill `voicestudio`. Este arquivo
cobre só a entrada na edição.

## Fluxo

1. Gerar o áudio dentro do projeto:

   ```bash
   python helpers/voiceover.py gen --edit-dir <edit> --file roteiro.txt --name locucao --stop-after
   ```

   Sai em `<edit>/voiceover/locucao.wav`. Vozes: `pf_dora` (padrão), `pm_alex`,
   `pm_santa`. Não sobrescreve sem `--force`.

2. Mixar sobre o vídeo, depois do corte e da aceleração:

   ```bash
   python helpers/voiceover.py mix --video cut.mp4 --voiceover <edit>/voiceover/locucao.wav --at 12.3 -o cut_locucao.mp4
   ```

   Uma cópia nova sai com o vídeo intacto. A locução chega no volume da voz da
   fonte, e o som original cai 12 dB (`--duck-db`) só enquanto ela fala, com rampa
   de 0,15 s. `--replace-audio` descarta o som original. Se a locução passar do fim
   do vídeo, o comando recusa em vez de cortar a fala.

3. Ouvir o trecho e abrir o Preview como em toda edição.

## Regras

- **Aceleração:** o 1,07× vale para o corte montado (`speed_post.py`, passo 7b do `SKILL.md`). A locução mixada depois não
  acelera de novo; `--speed` em `gen` só se ele pedir outro ritmo.
- **Voz dele:** clonar só com o sim dele para aquele uso, sempre local. As vozes
  padrão são sintéticas; não apresentar locução sintética como fala dele.
- **Termos médicos:** nome de remédio pode sair errado na pronúncia. Ouvir antes de
  entregar e, se errar, reescrever o termo como se fala no `--text`.
- **Volume:** a regra de nunca entregar abaixo da fonte continua; conferir o LUFS
  impresso pelo `mix`.

## Licença

O VoiceStudio é AGPL-3.0 e fica em processo separado, acessado por HTTP via
`vs.py`, com nada dele copiado no edvid. O padrão é o Kokoro (Apache-2.0). O
modelo padrão do VoiceStudio, OmniVoice, é não comercial e não entra em vídeo
publicado.
