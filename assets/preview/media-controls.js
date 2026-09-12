/* The same structured request is carried with the existing timeline note. */
(() => {
  // O template tem TRÊS tratamentos de tela dividida, não um. 'split' sozinho
  // obrigava o agente a perguntar qual no chat — que é exatamente a fricção
  // que marcar o intervalo na timeline devia eliminar. Mantido como apelido
  // histórico de 'split-top' para payload antigo continuar válido.
  const LAYOUTS = ['fullscreen', 'split-top', 'split-bottom', 'behind'];
  const canonicalLayout = (layout) => (layout === 'split' ? 'split-top' : layout);
  function normalize(kind, layout, file = '', provider = 'agent', front = true) {
    if (kind === 'note') return null;
    if (!['image', 'video', 'file'].includes(kind)) throw new Error('Tipo de mídia inválido');
    layout = canonicalLayout(layout);
    if (!LAYOUTS.includes(layout)) throw new Error('Enquadramento inválido');
    const result = {kind, layout, status: 'requested'};
    // "eu na frente da faixa" é o padrão dele para tela dividida (matte da
    // pessoa por cima da arte, costura dissolvendo atrás da cabeça).
    if (layout.startsWith('split')) result.front = !!front;
    if (kind === 'file') {
      if (!file.trim()) throw new Error('Escolha um arquivo do projeto');
      result.file = file.trim();
    } else {
      if (!['agent', 'shutterstock'].includes(provider)) throw new Error('Provedor inválido');
      result.provider = provider;
    }
    return result;
  }
  if (typeof module !== 'undefined') module.exports = {normalize};
  if (typeof window === 'undefined') return;
  const $ = id => document.getElementById(id);
  function update() {
    const kind = $('noteMediaKind').value;
    $('noteLayoutField').hidden = kind === 'note';
    $('noteFrontField').hidden = kind === 'note' || !$('noteMediaLayout').value.startsWith('split');
    $('noteFileField').hidden = kind !== 'file';
    $('noteGenerationHint').hidden = !['image', 'video'].includes(kind);
    $('noteProviderField').hidden = !['image', 'video'].includes(kind);
    $('noteText').placeholder = kind === 'note' ? 'Descreva o ajuste neste trecho…' : 'Descreva a cena e como ela deve aparecer…';
  }
  window.noteMediaControls = {
    load(media) {
      $('noteMediaKind').value = media?.kind || 'note';
      $('noteMediaLayout').value = canonicalLayout(media?.layout) || 'fullscreen';
      $('noteMediaFront').checked = media?.front !== false;
      $('noteMediaFile').value = media?.file || '';
      $('noteMediaProvider').value = media?.provider || 'shutterstock';
      update();
    },
    read() { return normalize($('noteMediaKind').value, $('noteMediaLayout').value, $('noteMediaFile').value, $('noteMediaProvider').value, $('noteMediaFront').checked); },
  };
  $('noteMediaKind').addEventListener('change', update);
  $('noteMediaLayout').addEventListener('change', update);
  $('noteBrowseAssets').addEventListener('click', async () => {
    const button = $('noteBrowseAssets'); button.disabled = true;
    const select = $('noteAssetList'); select.replaceChildren(new Option('Selecione um arquivo', ''));
    try {
      const response = await fetch('api/insert-assets'); const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Reabra o preview no servidor atualizado.');
      for (const item of result.assets) select.append(new Option(item, item));
      $('noteAssetStatus').textContent = result.assets.length ? `${result.assets.length} arquivo(s)` : 'Nenhum arquivo encontrado na pasta ou em assets/.';
    } catch (error) { $('noteAssetStatus').textContent = error.message; }
    finally { button.disabled = false; }
  });
  $('noteAssetList').addEventListener('change', event => { if (event.target.value) $('noteMediaFile').value = event.target.value; });
  update();
})();
