/* Edvid instalável: o service worker guarda SÓ a casca de terceiros (fontes do
   Google e bibliotecas do cdnjs, que têm versão fixa na URL). Página, código do
   edvid, vídeos e dados vêm SEMPRE do Mac: nenhuma atualização fica escondida
   atrás de cache. Sem o Mac no ar, a navegação mostra uma página que diz isso,
   em vez do erro do navegador. Trocar CASCA apaga o cache antigo. */
const CASCA = 'edvid-casca-v1';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CASCA).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())));

const FORA = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#000">
<title>Edvid — sem conexão</title><style>
body{margin:0;min-height:100svh;display:grid;place-items:center;background:#000;color:#F1F9F4;
font:16px/1.55 Manrope,system-ui,-apple-system,sans-serif;padding:24px;box-sizing:border-box}
main{max-width:520px}p.e{font:500 12px/1 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.08em;color:#8E9691}
h1{font:700 clamp(34px,9vw,56px)/1 Onest,system-ui,sans-serif;letter-spacing:-.035em;margin:16px 0 24px}
em{font-style:normal;color:#E11D2E}button{min-height:52px;padding:8px 24px;border:0;border-radius:999px;
background:#E11D2E;color:#fff;font:600 16px Manrope,system-ui,sans-serif;box-shadow:0 0 60px rgba(225,29,46,.35)}
</style></head><body><main><p class="e">EDVID · SEM CONEXÃO</p><h1>O Mac não <em>respondeu.</em></h1>
<p>O edvid roda no seu Mac. Confira se ele está ligado, acordado e com a Tailscale conectada, e tente de novo.</p>
<p><button onclick="location.reload()">Tentar de novo</button></p></main></body></html>`;

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const u = new URL(req.url);
  const terceiro = /(^|\.)cdnjs\.cloudflare\.com$|^fonts\.(googleapis|gstatic)\.com$/.test(u.hostname);
  if (terceiro) {
    e.respondWith(caches.open(CASCA).then((c) => c.match(req).then((r) => r || fetch(req).then((res) => {
      if (res.ok || res.type === 'opaque') c.put(req, res.clone());
      return res;
    }))));
    return;
  }
  if (req.mode === 'navigate' && u.origin === self.location.origin) {
    // Mac desligado = falha de rede; Mac ligado com o edvid fora = 502/503/504 da
    // própria Tailscale. Os dois casos mostram a mesma explicação.
    const fora = () => new Response(FORA, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    e.respondWith(fetch(req).then((res) => (res.status >= 502 && res.status <= 504 ? fora() : res)).catch(fora));
  }
  // todo o resto do edvid: rede, sempre (o navegador nem consulta este worker)
});
