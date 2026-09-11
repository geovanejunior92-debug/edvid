/* Shared editor shell. Moves existing controls without duplicating their state. */
(() => {
  const sidebar = document.createElement('aside');
  sidebar.className = 'workspace-tools glass';
  sidebar.setAttribute('aria-label', 'Ferramentas de edição');
  const title = document.createElement('h2');
  title.className = 'workspace-title';
  title.textContent = 'Mesa de edição';
  sidebar.append(title);
  for (const selector of ['#tabs', '.project-status', '#imgAdjustPanel', '#styleSetup', '#diagPanel']) {
    sidebar.append(document.querySelector(selector));
  }
  const help = document.createElement('div');
  help.className = 'workspace-guide';
  help.innerHTML = '<strong>Edite com Astra ou Claude</strong><p>Marque um intervalo na timeline e descreva o ajuste. Salve as marcações e volte à conversa para aplicar.</p><span>Espaço · reproduzir &nbsp; M · marcar trecho</span>';
  sidebar.append(help);
  document.querySelector('main').before(sidebar);
  document.body.classList.add('workspace-editor');
})();
