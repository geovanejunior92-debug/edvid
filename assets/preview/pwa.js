/* Instalação como app (celular). Só registra em contexto seguro (HTTPS pela
   Tailscale, ou localhost); updateViaCache 'none' faz o navegador buscar o sw.js
   novo a cada abertura, então uma versão nova do worker entra na hora. */
(() => {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  if (new URLSearchParams(location.search).get('embedded') === '1') return; // dentro do app nativo, não
  // registra já: esperar o 'load' deixava a biblioteca (miniaturas, esfera)
  // segurar o registro por vários segundos
  navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' })
    .then((reg) => reg.update())
    .catch(() => {});
})();
