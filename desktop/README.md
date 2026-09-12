# Edvid Studio 0.3 — aplicativo local para Mac

Aplicativo próprio para instalação local. Usa o motor compartilhado em `~/.agents/skills/edvid`; alterações nesse motor passam a valer no aplicativo, no Astra e no Claude. Não modifica `/Applications/Edvid.app` e não contém código extraído do aplicativo comercial.

## Compilar e instalar

Requisitos: macOS, ferramentas de linha de comando Xcode (`swiftc`), instalação compartilhada com `.venv/bin/python`, FFmpeg e FFprobe no PATH. Esta distribuição depende do motor instalado neste Mac.

```bash
bash ~/.agents/skills/edvid/desktop/build.sh "$HOME/Applications"
open "$HOME/Applications/Edvid Studio.app"
```

O build tem assinatura **ad-hoc local**, não Developer ID nem notarização Apple. Não há atualizador automático nesta versão. Para atualizar o shell, recompilar; para atualizar o motor, sincronizar o repositório pelos procedimentos existentes, preservando alterações locais. O aplicativo não faz pull nem instala dependências silenciosamente.

## Dados e diagnóstico

O registro de projetos, fila e log ficam em `~/Library/Application Support/Edvid Studio`. Projetos e originais ficam nas pastas escolhidas. Fechar a janela encerra o motor; trabalho interrompido não deve ser repetido automaticamente. O log de startup é `server.log` nessa pasta.

Para usar um checkout de desenvolvimento, executar o binário com `EDVID_ROOT=/caminho/do/checkout`. O checkout precisa da `.venv/bin/python` existente ou de link para o ambiente compartilhado.

## Astra e Claude

Consultar esta documentação e `helpers/studio_server.py` antes de operar o aplicativo. Não abrir um segundo escritor no mesmo projeto nem alterar arquivos enquanto houver processamento. Continuar usando o lock compartilhado para alterações na skill. Não registrar a URL com token em memória ou logs compartilhados.

A fila cobre inspeção/proxy, transcrição WhisperX, proposta técnica por pausas, aprovação por revisão, preview do corte, Fase 2 Remotion, acabamento e geração instrumental Treblo com confirmação por geração. Consulte `docs/STUDIO-STATUS.md` para os limites: seleção narrativa e a criação automática de todos os assets do Formato 1 ainda dependem do fluxo da skill. A mesa de edição é a mesma da versão web. A trilha gerada fica no projeto; não é inserida automaticamente na mixagem.

O painel de acabamento local inclui seletores Finder específicos para legenda JSON, insert e música. Veja `docs/STUDIO-FINISH.md`. Exportações permanecem pendentes de revisão integral mesmo quando os gates automáticos passam.
