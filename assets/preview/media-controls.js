/* The same structured request is carried with the existing timeline note. */
(() => {
  function normalize(kind, layout, file = '', provider = 'agent') {
    if (kind === 'note') return null;
    if (!['image', 'video', 'file'].includes(kind)) throw new Error('Tipo de mídia inválido');
    if (!['fullscreen', 'split'].includes(layout)) throw new Error('Enquadramento inválido');
    const result = {kind, layout, status: 'requested'};
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
    $('noteFileField').hidden = kind !== 'file';
    $('noteGenerationHint').hidden = !['image', 'video'].includes(kind);
    $('noteProviderField').hidden = !['image', 'video'].includes(kind);
    $('noteText').placeholder = kind === 'note' ? 'Descreva o ajuste neste trecho…' : 'Descreva a cena e como ela deve aparecer…';
  }
  window.noteMediaControls = {
    load(media) {
      $('noteMediaKind').value = media?.kind || 'note';
      $('noteMediaLayout').value = media?.layout || 'fullscreen';
      $('noteMediaFile').value = media?.file || '';
      $('noteMediaProvider').value = media?.provider || 'shutterstock';
      update();
    },
    read() { return normalize($('noteMediaKind').value, $('noteMediaLayout').value, $('noteMediaFile').value, $('noteMediaProvider').value); },
  };
  $('noteMediaKind').addEventListener('change', update);
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
