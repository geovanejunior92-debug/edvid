/* Source sequence is separate from the approved cut and never changes the EDL. */
(() => {
  sessionStorage.removeItem('edvid-import-v1');
  const tools = document.querySelector('.workspace-tools');
  const pane = document.createElement('section');
  pane.className = 'request-panel';
  pane.innerHTML = `<h2>Vídeos e conversa</h2>
    <button id="source-refresh" class="btn ghost" type="button">Localizar vídeos do projeto</button>
    <div id="source-list"></div>
    <button id="source-open" class="btn ghost" type="button" disabled>Ver sequência original</button>
    <p class="request-hint">Selecione as fontes e defina a ordem antes de pedir o corte.</p>
    <label for="request-mode">Como deseja editar?</label>
    <select id="request-mode"><option value="automatic">Corte automático</option><option value="script">Enviar roteiro</option><option value="adjustment">Ajustar a edição</option></select>
    <input id="request-script-file" type="file" accept=".txt,.md" hidden>
    <button id="request-import" class="btn ghost" type="button">Importar roteiro .txt ou .md</button>
    <label for="request-text">Pedido ou roteiro</label>
    <textarea id="request-text" rows="5" maxlength="30000" placeholder="Descreva o vídeo que você quer ou cole o roteiro…"></textarea>
    <button id="request-send" class="btn primary" type="button">Iniciar corte automático</button>
    <p id="request-status" role="status" aria-live="polite"></p>
    <p class="request-hint">Com um único vídeo, o corte automático começa aqui. Roteiros, ajustes e seleções com vários vídeos ficam para o agente definir a estratégia editorial.</p>
    <div id="request-history" aria-label="Histórico de pedidos"></div>`;
  tools.querySelector('.workspace-guide').before(pane);
  const stage = document.createElement('section');
  stage.className = 'source-stage hidden';
  stage.innerHTML = `<div class="source-sequence"><div class="source-heading"><strong>Sequência original</strong><button id="source-close" class="btn ghost small">Voltar ao corte</button></div><p>Arquivos inteiros · sem cortes aplicados</p><div id="source-timeline"></div></div><video id="source-player" controls playsinline preload="metadata"></video>`;
  document.querySelector('main').prepend(stage);
  const $ = id => document.getElementById(id);
  const requestKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const pendingStorageKey = `edvid-request:${location.pathname}`;
  let pendingRequest = null;
  try { pendingRequest = JSON.parse(sessionStorage.getItem(pendingStorageKey) || 'null'); } catch (_) { sessionStorage.removeItem(pendingStorageKey); }
  let files = [], selected = new Set(), current = null, busy = false;
  const message = text => { $('request-status').textContent = text; };
  function updateRequestAction() {
    $('request-send').textContent = $('request-mode').value === 'automatic' && selected.size === 1
      ? 'Iniciar corte automático' : 'Salvar pedido para o agente';
  }
  async function api(url, options) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível concluir a ação.');
    return result;
  }
  function play(item) {
    current = item.id;
    $('source-player').src = `source-media/${encodeURIComponent(item.id)}`;
    $('source-player').load();
    for (const button of $('source-timeline').children) button.classList.toggle('active', button.dataset.id === current);
  }
  function timeline() {
    const items = files.filter(x => selected.has(x.id));
    $('source-timeline').replaceChildren();
    for (const item of items) {
      const button = document.createElement('button');
      button.className = 'source-clip'; button.dataset.id = item.id;
      button.textContent = item.name; button.title = `Pré-visualizar ${item.name}`;
      button.addEventListener('click', () => play(item));
      $('source-timeline').append(button);
    }
    $('source-open').disabled = !items.length;
    if (current && !selected.has(current)) { $('source-player').pause(); $('source-player').removeAttribute('src'); $('source-player').load(); current = null; }
  }
  function rows() {
    $('source-list').replaceChildren();
    files.forEach((item, index) => {
      const row = document.createElement('div'); row.className = 'source-row';
      const label = document.createElement('label');
      const check = document.createElement('input'); check.type = 'checkbox'; check.checked = selected.has(item.id);
      check.addEventListener('change', () => { check.checked ? selected.add(item.id) : selected.delete(item.id); timeline(); updateRequestAction(); });
      label.append(check, document.createTextNode(item.name)); row.append(label);
      for (const [offset, symbol, name] of [[-1, '↑', 'Mover para cima'], [1, '↓', 'Mover para baixo']]) {
        const button = document.createElement('button'); button.className = 'btn ghost small'; button.textContent = symbol;
        button.setAttribute('aria-label', `${name}: ${item.name}`); button.disabled = index + offset < 0 || index + offset >= files.length;
        button.addEventListener('click', () => { [files[index], files[index + offset]] = [files[index + offset], files[index]]; rows(); timeline(); }); row.append(button);
      }
      $('source-list').append(row);
    });
    if (!files.length) $('source-list').textContent = 'Nenhum vídeo original encontrado na pasta deste projeto.';
    timeline(); updateRequestAction();
  }
  async function history() {
    try {
      const result = await api('api/requests'); $('request-history').replaceChildren();
      const labels = {pending: 'Aguardando o agente', queued: 'Corte na fila', transcribing: 'Transcrevendo vídeo', proposing: 'Montando corte técnico', approving: 'Confirmando estratégia automática', rendering: 'Renderizando e verificando', completed: 'Corte pronto para revisão', failed: 'Corte não concluído', awaiting_agent: 'Aguardando estratégia editorial'};
      for (const item of result.requests.slice(-20)) {
        const card = document.createElement('article');
        const title = document.createElement('strong'); title.textContent = labels[item.status] || `Pedido: ${item.status}`;
        const text = document.createElement('p'); text.textContent = item.text;
        const stamp = document.createElement('small'); stamp.textContent = item.createdAt;
        card.append(title, text, stamp);
        if (typeof item.response === 'string') { const response = document.createElement('p'); response.textContent = item.response; card.append(response); }
        if (typeof item.error === 'string') { const error = document.createElement('p'); error.textContent = item.error; card.append(error); }
        $('request-history').append(card);
      }
    } catch (error) { message(error.message); }
  }
  $('source-refresh').addEventListener('click', async () => {
    $('source-refresh').disabled = true;
    try { const result = await api('api/sources'); files = result.sources; selected = new Set([...selected].filter(id => files.some(x => x.id === id))); rows(); message('Lista atualizada. Nenhum arquivo foi movido.'); if (new URLSearchParams(location.search).get('sources') === '1' && !current) { selected = new Set(files.map(x => x.id)); rows(); if (files.length) $('source-open').click(); } if(pendingRequest?.payload){const payload=pendingRequest.payload;$('request-mode').value=payload.mode;$('request-text').value=payload.text;selected=new Set(payload.sources.filter(id=>files.some(x=>x.id===id)));rows();message('Retomando o envio anterior com segurança…');setTimeout(()=>$('request-send').click(),0);} }
    catch (error) { message(error.message); }
    finally { $('source-refresh').disabled = false; }
  });
  $('source-open').addEventListener('click', () => {
    stage.classList.remove('hidden'); document.body.classList.add('viewing-sources');
    const first = files.find(x => selected.has(x.id)); if (first) play(first);
  });
  $('source-close').addEventListener('click', () => { $('source-player').pause(); stage.classList.add('hidden'); document.body.classList.remove('viewing-sources'); });
  $('source-player').addEventListener('ended', () => {
    const items = files.filter(x => selected.has(x.id)); const index = items.findIndex(x => x.id === current);
    if (index >= 0 && index + 1 < items.length) { play(items[index + 1]); $('source-player').play().catch(() => {}); }
  });
  $('request-import').addEventListener('click', () => $('request-script-file').click());
  $('request-script-file').addEventListener('change', async event => {
    const file = event.target.files[0]; if (!file) return;
    if (file.size > 120000) return message('Roteiro muito grande; importe até 120 KB.');
    const text = await file.text(); if (text.length > 30000) return message('Use até 30 mil caracteres.');
    $('request-text').value = text; $('request-mode').value = 'script'; updateRequestAction();
  });
  $('request-mode').addEventListener('change', updateRequestAction);
  $('request-send').addEventListener('click', async () => {
    if (busy) return;
    busy = true; $('request-send').disabled = true;
    try {
      const mode = $('request-mode').value;
      const payload={mode, text:$('request-text').value.trim() || (mode === 'automatic' ? 'corte automático' : ''), sources:files.filter(x => selected.has(x.id)).map(x => x.id)};
      const fingerprint=JSON.stringify(payload);
      if(!pendingRequest||pendingRequest.fingerprint!==fingerprint)pendingRequest={idempotencyKey:requestKey(),fingerprint,payload};
      sessionStorage.setItem(pendingStorageKey,JSON.stringify(pendingRequest));
      const result = await api('api/requests', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...payload,idempotencyKey:pendingRequest.idempotencyKey})});
      pendingRequest = null; sessionStorage.removeItem(pendingStorageKey); $('request-text').value = ''; await history();
      message(result.request.status === 'queued' ? 'Transcrição e primeiro corte iniciados.' : 'Pedido salvo para o agente.');
    } catch (error) { message(error.message); }
    finally { busy = false; $('request-send').disabled = false; }
  });
  history();
  if (EdvidRequestsModel.shouldRefreshSources(location.search, pendingRequest)) $('source-refresh').click();
  setInterval(() => { if (!document.hidden && !busy) history(); }, 3000);
})();
