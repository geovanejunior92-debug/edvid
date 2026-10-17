/* Esfera 3D de fundo (assinatura visual do estilo "Painel da Clínica").
   Só na biblioteca: atrás do player ela atrapalharia julgar cor e movimento.
   Three.js r128 via cdnjs; sem ele (offline), a página segue sem esfera. */
(() => {
  'use strict';
  const THREE = window.THREE;
  const canvas = document.getElementById('esfera');
  if (!THREE || !canvas) return;
  const calmo = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const celularMq = matchMedia('(max-width: 700px)');
  const celular = celularMq.matches;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: !celular, alpha: true, powerPreference: 'low-power' });
  } catch (e) { return; } // sem WebGL: sem esfera
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, celular ? 1.5 : 2));
  renderer.setClearColor(0x000000, 0);
  const cena = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.z = 7;

  // ruído simplex 3D (Ashima/Stefan Gustavson), duas oitavas, deslocando pela normal
  const NOISE = `
    vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
    vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
    vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
    vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
    float snoise(vec3 v){
      const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
      vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
      vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
      vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
      i=mod289(i);
      vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
      float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;
      vec4 j=p-49.0*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
      vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
      vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
      vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
      vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
      vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
      vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
      p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
      vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
      return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
    }`;
  const VERT = `
    uniform float uTempo, uForca, uDensidade;
    varying float vRuido; varying vec3 vNormal; varying vec3 vVista;
    ${NOISE}
    void main(){
      vec3 p = position * uDensidade;
      float n = snoise(p + vec3(uTempo)) + 0.5 * snoise(p * 2.0 + vec3(uTempo * 1.3));
      vRuido = n;
      vec3 deslocado = position + normal * n * uForca;
      vec4 mv = modelViewMatrix * vec4(deslocado, 1.0);
      vNormal = normalize(normalMatrix * normal);
      vVista = normalize(-mv.xyz);
      gl_Position = projectionMatrix * mv;
    }`;
  const FRAG = `
    uniform vec3 uVermelho, uPapel; uniform float uOpacidade, uFresnel, uBase;
    varying float vRuido; varying vec3 vNormal; varying vec3 vVista;
    void main(){
      float f = pow(1.0 - abs(dot(normalize(vNormal), normalize(vVista))), uFresnel);
      vec3 cor = mix(uVermelho, uPapel, smoothstep(0.15, 1.1, vRuido) * 0.55);
      gl_FragColor = vec4(cor, (uBase + f) * uOpacidade);
    }`;
  const comuns = {
    uTempo: { value: 0 }, uForca: { value: 0.10 }, uDensidade: { value: 1.15 },
    uVermelho: { value: new THREE.Color('#E11D2E') }, uPapel: { value: new THREE.Color('#F1F9F4') },
    uOpacidade: { value: celular ? 0.5 : 0.8 },
  };
  const material = (fresnel, base, extra) => new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: { ...comuns, uFresnel: { value: fresnel }, uBase: { value: base } }, ...extra,
  });
  const geo = new THREE.IcosahedronGeometry(1, celular ? 16 : 34);
  const grupo = new THREE.Group();
  const fio = new THREE.Mesh(geo, material(1.6, 0.18, { wireframe: true }));
  const brilho = new THREE.Mesh(geo, material(2.4, 0.0, { side: THREE.BackSide }));
  brilho.scale.setScalar(1.06);
  grupo.add(fio, brilho);
  cena.add(grupo);

  // ---------- tamanho ----------
  function ajusta() {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  ajusta();
  addEventListener('resize', () => { ajusta(); escolheSecao(true); });

  // ---------- onde fica: data-esfera="x,y,escala" por seção ----------
  const alvo = { x: 0, y: 0, s: 1 };
  const pos = { x: 0, y: 0, s: 0.6 };
  const secoes = [...document.querySelectorAll('[data-esfera]')];
  let secaoAtual = null;
  function lerAlvo(sec) {
    const raw = (celularMq.matches && sec.dataset.esferaCelular) || sec.dataset.esfera;
    const [x, y, s] = raw.split(',').map(Number);
    return { x, y, s };
  }
  function vaiPara(sec, imediato) {
    const a = lerAlvo(sec);
    Object.assign(alvo, a);
    if (imediato || calmo) { Object.assign(pos, a); return; }
    if (window.gsap) window.gsap.to(pos, { x: a.x, y: a.y, s: a.s, duration: 1.8, ease: 'expo.out', overwrite: true });
  }
  function escolheSecao(forca) {
    const meio = innerHeight / 2;
    let melhor = secoes[0], dist = Infinity;
    for (const s of secoes) {
      const r = s.getBoundingClientRect();
      const d = r.top <= meio && r.bottom >= meio ? 0 : Math.min(Math.abs(r.top - meio), Math.abs(r.bottom - meio));
      if (d < dist) { dist = d; melhor = s; }
    }
    if (melhor && (melhor !== secaoAtual || forca)) { secaoAtual = melhor; vaiPara(melhor, false); }
  }
  if (secoes.length) { secaoAtual = secoes[0]; vaiPara(secoes[0], true); pos.s = calmo ? alvo.s : alvo.s * 0.6; }
  addEventListener('scroll', () => escolheSecao(false), { passive: true });

  // ---------- agitação: mais coisa pedindo atenção, mais ruído ----------
  const agit = { forca: 0.10, vel: 0.22 };
  function agita(stats) {
    const n = Math.min(Number(stats?.atencao || 0) + Number(stats?.revisar || 0) * 0.5, 6) / 6;
    const f = 0.10 + n * 0.12, v = 0.22 + n * 0.35;
    if (window.gsap && !calmo) window.gsap.to(agit, { forca: f, vel: v, duration: 2, ease: 'power2.out' });
    else { agit.forca = f; agit.vel = v; }
  }
  addEventListener('edvid:stats', (e) => agita(e.detail));
  if (window.EDVID_STATS) agita(window.EDVID_STATS);

  // ---------- arrastar com mouse ou dedo; ao soltar, volta com mola ----------
  const arrasto = { x: 0, y: 0 };
  let pegando = null;
  if (!calmo) {
    canvas.addEventListener('pointerdown', (e) => {
      pegando = { x: e.clientX, y: e.clientY, ax: arrasto.x, ay: arrasto.y };
      canvas.setPointerCapture(e.pointerId);
      window.gsap?.killTweensOf(arrasto);
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!pegando) return;
      arrasto.y = pegando.ay + (e.clientX - pegando.x) * 0.008;
      arrasto.x = pegando.ax + (e.clientY - pegando.y) * 0.008;
    });
    const solta = () => {
      if (!pegando) return;
      pegando = null;
      if (window.gsap) window.gsap.to(arrasto, { x: 0, y: 0, duration: 1.6, ease: 'elastic.out(1, .55)' });
      else { arrasto.x = 0; arrasto.y = 0; }
    };
    canvas.addEventListener('pointerup', solta);
    canvas.addEventListener('pointercancel', solta);
  }

  // ---------- laço ----------
  let tempo = 0, giro = 0, ultimo = performance.now(), rodando = false;
  function quadro(agora) {
    const dt = Math.min(0.05, (agora - ultimo) / 1000);
    ultimo = agora;
    tempo += dt * agit.vel;
    giro += dt * 0.06;
    const max = Math.max(1, document.documentElement.scrollHeight - innerHeight);
    const rolagem = (scrollY / max) * 2.2 * Math.PI * 2;
    comuns.uTempo.value = tempo;
    comuns.uForca.value = agit.forca;
    if (!window.gsap && !calmo) { // sem gsap: aproxima na mão
      pos.x += (alvo.x - pos.x) * 0.05; pos.y += (alvo.y - pos.y) * 0.05; pos.s += (alvo.s - pos.s) * 0.05;
    }
    grupo.position.set(pos.x, pos.y, 0);
    grupo.scale.setScalar(pos.s);
    grupo.rotation.set(0.35 + arrasto.x, giro + rolagem + arrasto.y, 0);
    renderer.render(cena, camera);
    if (rodando) requestAnimationFrame(quadro);
  }
  function liga() {
    if (rodando || calmo) return;
    rodando = true; ultimo = performance.now(); requestAnimationFrame(quadro);
  }
  function desliga() { rodando = false; }
  document.addEventListener('visibilitychange', () => (document.hidden ? desliga() : liga()));

  canvas.classList.add('viva');
  if (calmo) { // parada: um quadro só
    comuns.uForca.value = 0.10;
    grupo.position.set(alvo.x, alvo.y, 0); grupo.scale.setScalar(alvo.s); grupo.rotation.set(0.35, 0.6, 0);
    renderer.render(cena, camera);
    addEventListener('resize', () => renderer.render(cena, camera));
  } else {
    if (window.gsap) window.gsap.to(pos, { s: alvo.s, duration: 1.8, ease: 'expo.out' });
    liga();
  }
})();
