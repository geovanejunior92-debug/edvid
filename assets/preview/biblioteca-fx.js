/* Movimento da biblioteca (estilo "Painel da Clínica"): entrada dos blocos,
   contagem dos números, selo de atualização e cursor seguidor.
   Só na biblioteca. A tela de edição não carrega este arquivo. */
(() => {
  'use strict';
  const calmo = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const celular = matchMedia('(max-width: 700px)').matches;
  const mouse = matchMedia('(hover: hover) and (pointer: fine)').matches;
  if (!calmo) document.documentElement.classList.add('js-fx');

  // eyebrow com a data de hoje: "SÁB, 17 DE OUTUBRO · BIBLIOTECA LOCAL"
  const hoje = new Date();
  const dia = hoje.toLocaleDateString('pt-BR', { weekday: 'short' }).replace('.', '');
  const mes = hoje.toLocaleDateString('pt-BR', { month: 'long' });
  const eyebrow = document.getElementById('eyebrow');
  if (eyebrow) eyebrow.textContent = `${dia}, ${hoje.getDate()} de ${mes} · biblioteca local`.toUpperCase();

  // ---------- entrada: sobe 30px com fade, escalonada dentro da seção ----------
  const passo = celular ? 0.04 : 0.07;
  const vistos = new IntersectionObserver((entradas) => {
    for (const e of entradas) {
      if (!e.isIntersecting) continue;
      e.target.classList.add('visto');
      vistos.unobserve(e.target);
    }
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
  function prepara(lista) {
    lista.forEach((el, i) => {
      el.style.setProperty('--atraso', `${(Math.min(i, 7) * passo).toFixed(2)}s`);
      if (calmo) el.classList.add('visto'); else vistos.observe(el);
    });
  }
  document.querySelectorAll('.library-view > section').forEach((s) => prepara([...s.querySelectorAll(':scope > .rv, :scope > .kpis > .rv')]));

  // ---------- números: contam do zero em 1,6 s ----------
  const atual = {};
  let primeira = true;
  function conta(stats) {
    for (const el of document.querySelectorAll('[data-kpi]')) {
      const k = el.dataset.kpi, alvo = Number(stats[k] || 0);
      const de = atual[k] ?? 0;
      atual[k] = alvo;
      if (calmo || !window.gsap) { el.textContent = alvo; continue; }
      const o = { v: de };
      window.gsap.to(o, {
        v: alvo, duration: 1.6, ease: 'power3.out', delay: primeira ? 0.4 : 0,
        onUpdate: () => { el.textContent = Math.round(o.v); },
      });
    }
    primeira = false;
  }

  // ---------- selo "ATUALIZADO 17/10 14:33" (âmbar quando o dado envelhece) ----------
  const selo = document.getElementById('selo');
  let lidoEm = 0;
  function carimba() {
    if (!selo) return;
    lidoEm = Date.now();
    const d = new Date(lidoEm);
    const p = (n) => String(n).padStart(2, '0');
    selo.querySelector('b').textContent = `ATUALIZADO ${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
    selo.classList.remove('velho');
  }
  setInterval(() => { if (lidoEm && Date.now() - lidoEm > 10 * 60 * 1000) selo?.classList.add('velho'); }, 30000);

  window.EdvidFX = {
    atualiza(stats) {
      conta(stats);
      carimba();
      window.dispatchEvent(new CustomEvent('edvid:stats', { detail: stats }));
    },
    revela(container) {
      if (!container) return;
      const cards = [...container.querySelectorAll(':scope > .card:not(.rv), :scope > .project-card:not(.rv)')];
      cards.forEach((c) => c.classList.add('rv'));
      prepara(cards);
    },
  };
  // a primeira leitura pode ter chegado antes deste arquivo
  if (window.EDVID_STATS) window.EdvidFX.atualiza(window.EDVID_STATS);
  window.EdvidFX.revela(document.getElementById('projects'));

  // ---------- cursor seguidor (só com mouse) ----------
  if (mouse && !calmo) {
    const c = document.getElementById('cursor');
    let x = -100, y = -100, cx = -100, cy = -100;
    addEventListener('pointermove', (e) => {
      if (e.pointerType !== 'mouse') return;
      x = e.clientX; y = e.clientY; c.classList.add('on');
      c.classList.toggle('grande', !!e.target.closest('a, button, summary, label, input, .card, .project-card'));
    });
    document.addEventListener('pointerleave', () => c.classList.remove('on'));
    (function segue() {
      cx += (x - cx) * 0.22; cy += (y - cy) * 0.22;
      c.style.transform = `translate3d(${cx}px, ${cy}px, 0)`;
      requestAnimationFrame(segue);
    })();
  }
})();
