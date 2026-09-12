/* Shared editor shell. Moves existing controls without duplicating their state. */
(() => {
  const embedded = new URLSearchParams(location.search).get('embedded') === '1';
  const sidebar = document.createElement('aside');
  sidebar.className = 'workspace-tools glass';
  sidebar.setAttribute('aria-label', 'Ferramentas de edição');

  const toolHead = document.createElement('div');
  toolHead.className = 'workspace-tools-head';
  const title = document.createElement('h2');
  title.className = 'workspace-title';
  title.textContent = embedded ? 'Mesa de edição' : 'Corte';
  toolHead.append(title);
  sidebar.append(toolHead);

  for (const selector of ['#tabs', '.project-status', '#imgAdjustPanel', '#styleSetup', '#diagPanel', '#takesPanel']) {
    const panel = document.querySelector(selector);
    if (panel) sidebar.append(panel);
  }
  const help = document.createElement('div');
  help.className = 'workspace-guide';
  help.innerHTML = '<strong>Edite com Astra ou Claude</strong><p>Marque um intervalo na timeline e descreva o ajuste. Salve as marcações e volte à conversa para aplicar.</p><span>Espaço · reproduzir &nbsp; M · marcar trecho</span>';
  sidebar.append(help);

  const main = document.querySelector('main');
  main.before(sidebar);
  document.body.classList.add('workspace-editor');

  // The native Studio already owns this rail around the embedded editor. The
  // browser gets the same navigation, while both surfaces keep one real set of
  // phase buttons, panels, timeline and player.
  if (embedded) return;

  const rail = document.createElement('aside');
  rail.className = 'workspace-rail glass';
  rail.setAttribute('aria-label', 'Áreas do editor');
  rail.innerHTML = `
    <button class="rail-tool rail-library" type="button" data-tool="library" title="Projetos" aria-label="Voltar aos projetos"><span aria-hidden="true">⌂</span></button>
    <span class="rail-rule" aria-hidden="true"></span>
    <button class="rail-tool active" type="button" data-tool="cut" title="Corte" aria-label="Abrir ferramentas de corte"><span aria-hidden="true">✂</span></button>
    <button class="rail-tool" type="button" data-tool="style" title="Estilo" aria-label="Abrir escolhas de estilo"><span aria-hidden="true">✦</span></button>
    <button class="rail-tool" type="button" data-tool="visual" title="Visual" aria-label="Abrir edição visual"><span aria-hidden="true">▧</span></button>
    <span class="rail-rule" aria-hidden="true"></span>
    <button class="rail-tool rail-context" type="button" data-tool="diagnostics" title="Diagnóstico" aria-label="Abrir diagnóstico"><span aria-hidden="true">≋</span></button>
    <button class="rail-tool rail-context" type="button" data-tool="takes" title="Tomadas" aria-label="Abrir tomadas do roteiro"><span aria-hidden="true">▤</span></button>`;
  sidebar.before(rail);

  const close = document.createElement('button');
  close.className = 'workspace-tools-close';
  close.type = 'button';
  close.title = 'Recolher ferramentas';
  close.setAttribute('aria-label', 'Recolher ferramentas');
  close.textContent = '‹';
  toolHead.append(close);

  const phaseTabs = {
    cut: document.querySelector('.tab[data-tab="1"]'),
    style: document.querySelector('.tab[data-tab="style"]'),
    visual: document.querySelector('.tab[data-tab="2"]'),
  };
  const panels = {
    diagnostics: document.getElementById('diagPanel'),
    takes: document.getElementById('takesPanel'),
  };
  const labels = { cut: 'Corte', style: 'Estilo', visual: 'Visual', diagnostics: 'Diagnóstico', takes: 'Tomadas do roteiro' };
  let selectedTool = 'cut';

  function setDrawer(open) {
    document.body.classList.toggle('workspace-tools-collapsed', !open);
    sidebar.inert = !open;
    sidebar.setAttribute('aria-hidden', String(!open));
  }

  function syncRail() {
    const activePhase = Object.entries(phaseTabs).find(([, tab]) => tab?.classList.contains('active'))?.[0] || 'cut';
    if (!['diagnostics', 'takes'].includes(selectedTool)) selectedTool = activePhase;
    for (const button of rail.querySelectorAll('.rail-tool')) {
      const key = button.dataset.tool;
      if (key === 'library') continue;
      const target = phaseTabs[key] || panels[key];
      const unavailable = phaseTabs[key] ? !!target?.disabled : !target || target.classList.contains('hidden');
      button.disabled = unavailable;
      button.hidden = ['diagnostics', 'takes'].includes(key) && unavailable;
      button.classList.toggle('active', key === selectedTool);
      button.setAttribute('aria-pressed', String(key === selectedTool));
    }
    title.textContent = labels[selectedTool] || labels[activePhase];
  }

  function openTool(key) {
    if (key === 'library') {
      document.getElementById('projectsLink')?.click();
      return;
    }
    const wasOpen = !document.body.classList.contains('workspace-tools-collapsed');
    if (wasOpen && selectedTool === key) {
      setDrawer(false);
      return;
    }
    selectedTool = key;
    setDrawer(true);
    if (phaseTabs[key] && !phaseTabs[key].disabled) phaseTabs[key].click();
    const panel = panels[key];
    if (panel && !panel.classList.contains('hidden')) {
      const toggle = panel.querySelector('.drawer-toggle');
      if (toggle?.getAttribute('aria-expanded') !== 'true') toggle?.click();
      requestAnimationFrame(() => panel.scrollIntoView({block: 'start'}));
    }
    syncRail();
  }

  rail.addEventListener('click', event => {
    const button = event.target.closest('.rail-tool');
    if (button && !button.disabled) openTool(button.dataset.tool);
  });
  close.addEventListener('click', () => setDrawer(false));

  const observer = new MutationObserver(syncRail);
  for (const target of [...Object.values(phaseTabs), ...Object.values(panels)]) {
    if (target) observer.observe(target, {attributes: true, attributeFilter: ['class', 'disabled', 'hidden']});
  }
  syncRail();
})();
