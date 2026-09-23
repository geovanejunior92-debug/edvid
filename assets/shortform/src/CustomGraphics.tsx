/**
 * CustomGraphics — the ONE file you edit in Phase 2, and ONLY when a spoken
 * word calls for a bespoke motion graphic instead of a stock image (e.g.
 * "animações" → animated shapes, "roteiro" → a typewriter script sheet,
 * "gráfico" → a growing chart). Everything else is data in edit-data.json.
 *
 * Default: renders nothing. To add graphics, build components here (worked
 * examples below — same upper-zone card motif as the image inserts) and mount
 * them in <CustomGraphics/> with their own <Sequence from/durationInFrames>.
 *
 * Timings: get the payoff word's timestamp from the cut transcript and land
 * the animation on it. Keep 0.5–2s per accent; whoosh on entry, pop on shapes.
 *
 * fps: the render runs at the SOURCE's fps (60 for the iPhone). Write every
 * duration as a frame count at 30fps wrapped in F() — `const F = useF();` at
 * the top of the component, before any early return — or drive frame-based
 * motion off `toBase(frame, fps)`. A bare `8` plays twice as fast at 60fps.
 */
import React from 'react';
import {
  AbsoluteFill,
  Sequence,
  Img,
  OffthreadVideo,
  Loop,
  staticFile,
  interpolate,
  Easing,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {loadFont} from '@remotion/google-fonts/Poppins';
import {loadFont as loadAlexBrush} from '@remotion/google-fonts/AlexBrush';
import {loadFont as loadLora} from '@remotion/google-fonts/Lora';
// Playfair italic — a palavra de destaque da CAPA, a mesma face que a legenda
// stacked usa. Capa e legenda dividem a identidade tipográfica (pedido de
// 2026-08-16, a partir da referência): sans pesado branco + uma serifada
// itálica, sem laranja.
import {loadFont as loadPlayfair} from '@remotion/google-fonts/PlayfairDisplay';
import {loadFont as loadHand} from '@remotion/google-fonts/ArchitectsDaughter';
import {loadFont as loadMarker} from '@remotion/google-fonts/PermanentMarker';
import {loadFont as loadPatrick} from '@remotion/google-fonts/PatrickHand';
import {loadFont as loadCaveat} from '@remotion/google-fonts/Caveat';
// DynamicVideo = o wrapper de câmera do template (zoom por corte + push-in +
// tracking). BehindVideos usa ele para o matte da pessoa herdar exatamente a
// mesma câmera do vídeo-base.
import {DynamicVideo, Sfx} from './Main';
import {toBase, useF} from './fps';
import editData from '../public/edit-data.json';
// Cues re-hosted at the bottom of the frame while a split window is up (see
// SplitCaptionsBottom). Statically imported, so the file must ALWAYS exist —
// write `[]` when the video has no split windows, exactly like track.json.
import captionsSplitData from '../public/captions_split.json';

// 300/800 added 2026-08-15 for TitleCards (Light connectors / ExtraBold key
// words) — the other worked examples below only ever needed 400/600/900.
const {fontFamily} = loadFont('normal', {weights: ['300', '400', '600', '800', '900']});
// Script accent face for TitleCards' anchor word (see "premium editorial"
// style, 2026-08-15) — a flowing cursive, NOT Playfair-italic (that's an
// elegant serif italic already used elsewhere, a different, more formal
// register). Alex Brush ships one weight only (400), like Bebas/Anton.
const {fontFamily: scriptFamily} = loadAlexBrush('normal', {weights: ['400']});
// Serif face for the re-hosted split captions — matches the `scatter`
// ("Disperso") style's own Lora, so moving the caption does not change how it
// looks. 400 for ordinary words, 700 italic for the long "hero" word.
const {fontFamily: loraFamily} = loadLora('normal', {weights: ['400', '700']});
const {fontFamily: playfairFamily} = loadPlayfair('italic', {weights: ['700', '900']});
const {fontFamily: handFamily} = loadHand('normal', {weights: ['400']});
const {fontFamily: markerFamily} = loadMarker('normal', {weights: ['400']});
const {fontFamily: patrickFamily} = loadPatrick('normal', {weights: ['400']});
const {fontFamily: caveatFamily} = loadCaveat('normal', {weights: ['400', '700']});
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// ============ MOUNT POINT (edit this) ==========================================
// STYLE "TELA DIVIDIDA" (split screen) — driven by edit-data.json `splitInserts`.
// Leave the array out and this renders nothing, as before.
type SplitInsert = {
  src: string;
  // 'image' (default, omit the field for the old behavior) or 'video' — real
  // motion in the band (2026-08-16, for AI-generated video B-roll, screen
  // recordings, etc.). Always muted — the only audio track is cut.mp4's.
  kind?: 'image' | 'video';
  // Generate/trim the clip to match (end-start) in the first place so this
  // is rarely needed. Only set this when the source clip's own length is
  // shorter than the window and you want it to loop rather than freeze on
  // its last frame — the clip's OWN duration in frames COUNTED AT 30fps
  // (seconds × 30, whatever the clip's or the render's fps; scaled through
  // F() like every other count here). OffthreadVideo has no native `loop`
  // prop; this drives a wrapping `<Loop>`.
  loopFrames?: number;
  start: number;
  end: number;
  fit?: 'cover' | 'contain';
  bandH?: number;
  layout?: 'top' | 'bottom';
  // Ken-Burns da ARTE dentro da faixa (padrão 0.03). Serve para arte que se
  // move pouco por natureza — uma animação médica 3D lenta passa no conteúdo
  // mas quase não muda de frame. Subir aqui dá vida à faixa sem trocar o clipe
  // por outro fora do assunto (2026-08-20).
  artZoom?: number;
  // Largura da dissolução na costura, em px. Padrão SEAM_BLEND (100) = Formato
  // 1, onde a junção cai na borda do próprio clipe. O Formato 2 usa ~192: a
  // dissolução é larga o bastante para ATRAVESSAR o alto da cabeça, e é isso
  // que faz a pessoa "estar na frente" sem matte nenhum (medido no vídeo de
  // referência, 2026-09-11). Por janela, não global: os dois formatos coexistem.
  seamBlend?: number;
  // ProRes 4444 com alfa gerado por person_matte.py para ESTA janela — põe a
  // pessoa na frente da faixa (ver SplitFrame). Sem ele, faixa reta como antes.
  matte?: string;
  // Sobrepõem o par zoom/focusY do layout. Com matte, a pessoa PRECISA subir
  // até cruzar a costura (senão a faixa fica reta acima dela e o recorte não
  // aparece); `focusY` MAIOR sobe a pessoa. Medir num still, nunca chutar:
  // um ponto y_src da fonte cai em (y_src - focusY) * zoom + bandH.
  zoom?: number;
  focusY?: number;
  // Alterna aproximação/afastamento de uma janela para a outra (ex.: 1.06 numa,
  // 0.96 na seguinte). Sem isso a tela dividida fica com enquadramento fixo do
  // começo ao fim e o vídeo "não tem zoom nenhum".
  zoomPulse?: number;
};

// Two variants of one idea — both PIN THE FACE to a fixed region and give the
// rest of the frame to the image:
//   'top'    "Tela dividida"   — art on top, head raised underneath
//   'bottom' "Tela dividida 2" — head held high, art underneath
// The zoom/focus pair is what pins the face and is NOT interchangeable between
// them. `focusY` is a SOURCE y that lands at the top of the video window, so a
// point y_src renders at (y_src - focusY) * zoom.
//   top:    the head must be lifted out of the source's headroom → zoom in hard.
//   bottom: that headroom is the point — it is what puts the face under the
//           frame edge instead of in the middle.
// MEASURE THE SOURCE before trusting these numbers: ffmpeg a frame out of
// cut.mp4, read the hair-top and chin y, and set focusY so the head lands where
// the user asked. The values below fit a head ~660px tall starting at y 455.
const LAYOUT = {
  top: {zoom: 1.25, focusY: 400},
  bottom: {zoom: 1.0, focusY: 225},
} as const;

// A cut transition: a light beam whips across the frame while a short flash
// blooms, with a click on the cut. Data, not JSX — `transitions` in
// edit-data.json — so the windows stay visible to the preview timeline and
// retimeable without touching code.
// Efeitos sonoros avulsos, fora dos que já vêm colados na legenda e no flash de
// corte. São DADO (`sfxCues` no edit-data.json) para aparecerem já na entrega
// pós-corte — junto com zoom, transições e flash — e seguirem até o render
// final sem serem remontados. Catálogo e regras de uso:
// references/sfx-catalogo.md
type SfxCue = {at: number; src: string; volume?: number; dur?: number; label?: string};

const SfxCues: React.FC<{items: SfxCue[]}> = ({items}) => {
  const {fps} = useVideoConfig();
  return (
    <>
      {items.map((c, i) => (
        <Sequence
          key={`${c.src}-${i}`}
          from={Math.max(0, Math.round(c.at * fps))}
          durationInFrames={Math.max(1, Math.round((c.dur ?? 3) * fps))}
          layout="none"
        >
          <Sfx src={c.src} volume={c.volume ?? 0.5} />
        </Sequence>
      ))}
    </>
  );
};

type CutFlash = {
  at: number;
  intensity?: number;
  sfx?: string;
  volume?: number;
  // 'saida' = fim de uma janela de tela dividida (clarão curto, sem facho).
  variant?: 'corte' | 'saida';
};

// BEHIND-THE-SUBJECT com vídeo — o B-roll não é faixa, é o FUNDO INTEIRO, com
// a pessoa recortada por cima. **NÃO é o padrão do usuário e NÃO é o que ele
// chama de "atrás da cabeça"** (este comentário afirmava o contrário até
// 2026-09-11, contradizendo o shortform.md e repetindo a troca que ele já
// tinha corrigido em 16/08). O padrão dele é `splitInserts[]` COM `matte`: a
// divisão das telas permanece e a cabeça sobe na frente da faixa. Use isto
// aqui só quando ele pedir fundo inteiro, sem divisão. Cada janela precisa de
// um matte próprio (`person_matte.py`), cujo frame 0 é o início da janela.
type BehindVideo = {
  src: string; // B-roll que vai ao fundo
  kind?: 'video' | 'image';
  matte: string; // ProRes 4444 com alfa, gerado por person_matte.py
  start: number;
  end: number;
  fit?: 'cover' | 'contain';
  loopFrames?: number;
  // Só para depurar o alinhamento do matte: 0 esconde o B-roll e deixa ver o
  // vídeo-base por baixo da pessoa recortada. Desalinhado = borda fantasma.
  bgOpacity?: number;
};

export const CustomGraphics: React.FC = () => {
  const d = editData as unknown as {
    splitInserts?: SplitInsert[];
    behindVideos?: BehindVideo[];
    transitions?: CutFlash[];
    titleCards?: TitleCard[];
    hookStacked?: HookStacked;
    outro?: Outro;
    logo?: Logo;
    sfxCues?: SfxCue[];
    graphics?: Graphic[];
  };
  const splits = d.splitInserts ?? [];
  const graphics = d.graphics ?? [];
  const behind = d.behindVideos ?? [];
  const hookStacked = d.hookStacked?.enabled === false ? null : d.hookStacked ?? null;
  const flashes = d.transitions ?? [];
  const titleCards = d.titleCards ?? [];
  return (
    <>
      {splits.length ? <SplitScreen items={splits} /> : null}
      {splits.length ? <SplitCaptionsBottom items={splits} /> : null}
      {behind.length ? <BehindVideos items={behind} /> : null}
      {flashes.length ? <CutFlashes items={flashes} /> : null}
      {d.sfxCues?.length ? <SfxCues items={d.sfxCues} /> : null}
      {titleCards.length ? <TitleCards items={titleCards} /> : null}
      {graphics.length ? <Graphics items={graphics} /> : null}
      {hookStacked ? <HookStackedCard cfg={hookStacked} /> : null}
      {d.logo?.enabled ? <LogoOpening cfg={d.logo} /> : null}
      {/* por último: a tela de encerramento cobre tudo, inclusive legenda */}
      {d.outro?.enabled ? <OutroCard cfg={d.outro} /> : null}
    </>
  );
};

// ============ BIBLIOTECA DE GRÁFICOS (item 8, 2026-09-01) =====================
// Gráficos de dado, não de código: `graphics` no edit-data.json, um objeto por
// gráfico com `kind` e os campos daquele tipo. Todos usam o quadro GLOBAL
// (nada de <Sequence> — ver a nota em SplitCaptionsBottom), entram com fade +
// deslize e um whoosh, e saem com fade. Zona: acima do rosto (topo) para os
// cartões, rodapé para o lower third — a mesma divisão dos inserts e do hook.
//
//   lowerThird  {start,end,name,role?,accent?}          "Dr. Geovane Júnior / Nutrologia — CRM…"
//   stat        {start,end,value,label,accent?}         número grande que conta até o valor
//   list        {start,end,title?,items[],accent?}      itens entrando um a um, com marcador
//   compare     {start,end,left:{title,value},right:{…}} dois cartões lado a lado (antes/depois)
//   quote       {start,end,text,source?}                citação com aspas grandes
//   progress    {start,end,label,from,to,suffix?}       barra que enche de `from` a `to`
//   callout     {start,end,text,x,y}                    pílula com anel pulsante num ponto (0–1)
//
// `sfx: false` desliga o whoosh de entrada de um gráfico. Cores: `accent` aceita
// um nome da TITLE_ACCENT_PALETTE (dourado, azul…) ou um hex.
type GraphicBase = {kind: string; start: number; end: number; accent?: string; sfx?: boolean};
type GLowerThird = GraphicBase & {kind: 'lowerThird'; name: string; role?: string; y?: number}; // y: fração do topo (padrão 0.60, acima da zona da legenda)
type GStat = GraphicBase & {kind: 'stat'; value: string; label: string};
type GList = GraphicBase & {kind: 'list'; title?: string; items: string[]};
type GCompare = GraphicBase & {
  kind: 'compare';
  left: {title: string; value: string};
  right: {title: string; value: string};
};
type GQuote = GraphicBase & {kind: 'quote'; text: string; source?: string};
type GProgress = GraphicBase & {kind: 'progress'; label: string; from: number; to: number; suffix?: string};
type GCallout = GraphicBase & {kind: 'callout'; text: string; x: number; y: number};
type GAnotacao = GraphicBase & {
  kind: 'anotacao';
  y?: number;                 // fração do topo onde o bloco começa (padrão 0.055)
  align?: 'center' | 'left';
  cps?: number;               // caracteres por segundo (padrão 34)
  typeSfx?: boolean;          // som de digitação por linha (padrão true)
  lines: {
    text: string;
    at: number;               // segundo do cut em que ESTA linha começa a ser escrita
    style?: 'normal' | 'caps' | 'marker';
    font?: 'hand' | 'marker' | 'patrick' | 'caveat';
    size?: number;
    underline?: boolean;      // sublinhado desenhado, cresce junto com o texto
    mark?: string;            // trecho com grifo marca-texto
    color?: string;
  }[];
};
type Graphic = GLowerThird | GStat | GList | GCompare | GQuote | GProgress | GCallout | GAnotacao;

// Contagens de quadros a 30fps; F() converte para o fps real (ver fps.ts).
const G_ENTER = 8; // frames de entrada (~270ms)
const G_EXIT = 6;
const G_TOP = 300; // topo da zona dos cartões (px, quadro 1080x1920)
const G_SIDE = 84;
const G_CARD_BG = 'rgba(8, 12, 20, 0.72)';
const G_WHOOSH = 'whoosh.mp3'; // <Sfx> já prefixa 'sfx/' — o 'sfx/whoosh.mp3' antigo dava 404

const gAccent = (name?: string) => {
  if (!name) return TITLE_ACCENT_FALLBACK;
  if (name.startsWith('#')) return name;
  return (TITLE_ACCENT_PALETTE as Record<string, string>)[name] ?? TITLE_ACCENT_FALLBACK;
};

// Progresso 0–1 de entrada/saída e o quadro local do gráfico, a partir do
// quadro global. `null` fora da janela.
const useGraphicWindow = (g: GraphicBase) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const F = useF();
  const a = Math.round(g.start * fps);
  const b = Math.round(g.end * fps);
  if (frame < a || frame >= b) return null;
  const local = frame - a;
  const enter = interpolate(local, [0, F(G_ENTER)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
  const exit = interpolate(local, [b - a - F(G_EXIT), b - a], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return {local, enter, exit, opacity: Math.min(enter, exit), total: b - a, fps, F};
};

// Conta de 0 ao número dentro de `value` ("70%", "R$ 1.200", "3x") mantendo o
// texto em volta; sem dígitos, mostra o texto direto.
const countUp = (value: string, t: number) => {
  const m = value.match(/(\d+(?:[.,]\d+)?)/);
  if (!m) return value;
  const raw = m[1];
  const decimals = (raw.split(/[.,]/)[1] ?? '').length;
  const target = parseFloat(raw.replace(',', '.'));
  const now = target * t;
  const txt = now.toFixed(decimals).replace('.', raw.includes(',') ? ',' : '.');
  return value.replace(raw, txt);
};

const GraphicSfx: React.FC<{g: GraphicBase}> = ({g}) => {
  const {fps} = useVideoConfig(); // 24 ou 30: nunca fixe — o corte de câmera 24p rende a 24
  if (g.sfx === false) return null;
  return (
    <Sequence from={Math.round(g.start * fps)} durationInFrames={Math.round(fps * 0.7)}>
      <Sfx src={G_WHOOSH} volume={0.12} />
    </Sequence>
  );
};

const LowerThirdEl: React.FC<{g: GLowerThird}> = ({g}) => {
  const w = useGraphicWindow(g);
  if (!w) return null;
  const x = interpolate(w.enter, [0, 1], [-60, 0]);
  const accent = gAccent(g.accent);
  // Padrão a 60% da altura: abaixo dos cartões, ACIMA de onde as legendas
  // (karaoke, stacked e scatter) vivem — medido num still, o rodapé a 560 px
  // caía em cima da legenda scatter (2026-09-01).
  const top = Math.round((g.y ?? 0.6) * 1920);
  return (
    <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'flex-start', paddingTop: top, paddingLeft: G_SIDE}}>
      <div
        style={{
          display: 'flex',
          alignItems: 'stretch',
          gap: 22,
          opacity: w.opacity,
          transform: `translateX(${x.toFixed(1)}px)`,
          filter: 'drop-shadow(4px 6px 18px rgba(0,0,0,0.45))',
        }}
      >
        <div style={{width: 10, borderRadius: 5, background: accent}} />
        <div style={{display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
          <div style={{fontFamily, fontWeight: 800, fontSize: 56, color: '#fff', lineHeight: 1.05, letterSpacing: -0.5}}>
            {g.name}
          </div>
          {g.role ? (
            <div style={{fontFamily, fontWeight: 300, fontSize: 34, color: 'rgba(255,255,255,0.85)', marginTop: 6}}>
              {g.role}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const CardShell: React.FC<{opacity: number; enter: number; children: React.ReactNode; align?: 'center' | 'left'}> = ({
  opacity,
  enter,
  children,
  align = 'center',
}) => (
  <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center', paddingTop: G_TOP}}>
    <div
      style={{
        width: 1080 - 2 * G_SIDE,
        background: G_CARD_BG,
        borderRadius: 34,
        padding: '44px 52px',
        opacity,
        transform: `translateY(${((1 - enter) * 40).toFixed(1)}px) scale(${(0.96 + 0.04 * enter).toFixed(3)})`,
        textAlign: align,
        boxShadow: '0 18px 50px rgba(0,0,0,0.4)',
        backdropFilter: 'blur(6px)',
      }}
    >
      {children}
    </div>
  </AbsoluteFill>
);

const StatEl: React.FC<{g: GStat}> = ({g}) => {
  const w = useGraphicWindow(g);
  if (!w) return null;
  const t = interpolate(w.local, [0, Math.min(w.F(36), w.total - w.F(4))], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
  return (
    <CardShell opacity={w.opacity} enter={w.enter}>
      <div style={{fontFamily, fontWeight: 900, fontSize: 168, color: gAccent(g.accent), lineHeight: 1, letterSpacing: -4}}>
        {countUp(g.value, t)}
      </div>
      <div style={{fontFamily, fontWeight: 400, fontSize: 44, color: '#fff', marginTop: 14, lineHeight: 1.2}}>{g.label}</div>
    </CardShell>
  );
};

const ListEl: React.FC<{g: GList}> = ({g}) => {
  const w = useGraphicWindow(g);
  if (!w) return null;
  const stagger = w.F(7);
  const accent = gAccent(g.accent);
  return (
    <CardShell opacity={w.opacity} enter={w.enter} align="left">
      {g.title ? (
        <div style={{fontFamily, fontWeight: 800, fontSize: 52, color: '#fff', marginBottom: 22, lineHeight: 1.1}}>{g.title}</div>
      ) : null}
      {g.items.map((item, i) => {
        const p = interpolate(w.local, [w.F(G_ENTER) + i * stagger, w.F(G_ENTER) + i * stagger + w.F(6)], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing: Easing.out(Easing.cubic),
        });
        return (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 22,
              opacity: p,
              transform: `translateX(${((1 - p) * -30).toFixed(1)}px)`,
              marginTop: i ? 16 : 0,
            }}
          >
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 22,
                background: accent,
                color: '#0a0f18',
                fontFamily,
                fontWeight: 900,
                fontSize: 28,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: '0 0 auto',
              }}
            >
              {i + 1}
            </div>
            <div style={{fontFamily, fontWeight: 500, fontSize: 42, color: '#fff', lineHeight: 1.2}}>{item}</div>
          </div>
        );
      })}
    </CardShell>
  );
};

const CompareEl: React.FC<{g: GCompare}> = ({g}) => {
  const w = useGraphicWindow(g);
  if (!w) return null;
  const accent = gAccent(g.accent);
  const box = (side: {title: string; value: string}, hot: boolean, delay: number) => {
    const p = interpolate(w.local, [w.F(delay), w.F(delay) + w.F(8)], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    });
    return (
      <div
        style={{
          flex: 1,
          background: hot ? accent : 'rgba(255,255,255,0.08)',
          borderRadius: 26,
          padding: '34px 22px',
          opacity: p,
          transform: `scale(${(0.9 + 0.1 * p).toFixed(3)})`,
          textAlign: 'center',
        }}
      >
        <div style={{fontFamily, fontWeight: 400, fontSize: 34, color: hot ? '#0a0f18' : 'rgba(255,255,255,0.8)'}}>
          {side.title}
        </div>
        <div style={{fontFamily, fontWeight: 900, fontSize: 92, color: hot ? '#0a0f18' : '#fff', lineHeight: 1.05, marginTop: 8}}>
          {side.value}
        </div>
      </div>
    );
  };
  return (
    <CardShell opacity={w.opacity} enter={w.enter}>
      <div style={{display: 'flex', gap: 22}}>
        {box(g.left, false, 2)}
        {box(g.right, true, 10)}
      </div>
    </CardShell>
  );
};

const QuoteEl: React.FC<{g: GQuote}> = ({g}) => {
  const w = useGraphicWindow(g);
  if (!w) return null;
  return (
    <CardShell opacity={w.opacity} enter={w.enter}>
      <div style={{fontFamily: playfairFamily, fontStyle: 'italic', fontWeight: 900, fontSize: 150, color: gAccent(g.accent), lineHeight: 0.6, marginTop: 30}}>
        “
      </div>
      <div style={{fontFamily: playfairFamily, fontStyle: 'italic', fontWeight: 700, fontSize: 54, color: '#fff', lineHeight: 1.25, marginTop: 10}}>
        {g.text}
      </div>
      {g.source ? (
        <div style={{fontFamily, fontWeight: 300, fontSize: 32, color: 'rgba(255,255,255,0.75)', marginTop: 22}}>— {g.source}</div>
      ) : null}
    </CardShell>
  );
};

const ProgressEl: React.FC<{g: GProgress}> = ({g}) => {
  const w = useGraphicWindow(g);
  if (!w) return null;
  const t = interpolate(w.local, [w.F(G_ENTER), Math.min(w.F(G_ENTER) + w.F(40), w.total - w.F(4))], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });
  const value = g.from + (g.to - g.from) * t;
  const pct = Math.max(0, Math.min(1, g.to > 0 ? value / Math.max(g.to, g.from) : 0));
  const accent = gAccent(g.accent);
  return (
    <CardShell opacity={w.opacity} enter={w.enter} align="left">
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
        <div style={{fontFamily, fontWeight: 600, fontSize: 42, color: '#fff'}}>{g.label}</div>
        <div style={{fontFamily, fontWeight: 900, fontSize: 60, color: accent}}>
          {Math.round(value)}
          {g.suffix ?? ''}
        </div>
      </div>
      <div style={{height: 26, borderRadius: 13, background: 'rgba(255,255,255,0.12)', marginTop: 22, overflow: 'hidden'}}>
        <div style={{width: `${(pct * 100).toFixed(1)}%`, height: '100%', borderRadius: 13, background: accent}} />
      </div>
    </CardShell>
  );
};

const CalloutEl: React.FC<{g: GCallout}> = ({g}) => {
  const w = useGraphicWindow(g);
  if (!w) return null;
  const pulse = 1 + 0.08 * Math.sin((w.local / w.fps) * Math.PI * 2 * 1.2);
  const accent = gAccent(g.accent);
  const cx = g.x * 1080;
  const cy = g.y * 1920;
  return (
    <AbsoluteFill style={{opacity: w.opacity}}>
      <div
        style={{
          position: 'absolute',
          left: cx - 70 * pulse,
          top: cy - 70 * pulse,
          width: 140 * pulse,
          height: 140 * pulse,
          borderRadius: '50%',
          border: `6px solid ${accent}`,
          boxShadow: `0 0 30px ${accent}`,
          transform: `scale(${w.enter.toFixed(3)})`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: Math.min(1080 - 420, Math.max(30, cx - 200)),
          top: cy + 90 * pulse + 16,
          background: accent,
          color: '#0a0f18',
          fontFamily,
          fontWeight: 800,
          fontSize: 36,
          padding: '12px 26px',
          borderRadius: 999,
          transform: `translateY(${((1 - w.enter) * 20).toFixed(1)}px)`,
          maxWidth: 420,
        }}
      >
        {g.text}
      </div>
    </AbsoluteFill>
  );
};

// --- anotação manuscrita (estilo caderno, 2026-09-03) ---------------------
// Bloco de texto que é ESCRITO letra a letra e ACUMULA linha a linha, como
// alguém anotando à mão enquanto fala. Cada linha tem seu próprio `at`; o bloco
// inteiro sai em fade no `end`. Sublinhado e grifo crescem junto com o texto,
// então nunca aparecem antes da palavra que marcam.
const AN_HAND = handFamily;
const AN_MARKER = markerFamily;
const AN_MARK_BG = 'rgba(240, 200, 40, 0.85)';
const AN_TYPE_SFX = 'typing.mp3'; // <Sfx> já prefixa 'sfx/'

const AnotacaoLine: React.FC<{
  ln: GAnotacao['lines'][number];
  cps: number;
  fps: number;
  frame: number;
  blockOpacity: number;
}> = ({ln, cps, fps, frame, blockOpacity}) => {
  const txt = ln.style === 'caps' || ln.style === 'marker' ? ln.text.toUpperCase() : ln.text;
  const startF = Math.round(ln.at * fps);
  const dur = Math.max(1, (txt.length / cps) * fps);
  if (frame < startF) return null;
  const shown = Math.min(txt.length, Math.floor(((frame - startF) / dur) * txt.length) + 1);
  const visible = txt.slice(0, shown);
  const done = shown >= txt.length;
  const size = ln.size ?? (ln.style === 'marker' ? 62 : ln.style === 'caps' ? 58 : 52);
  const fam =
    ln.font === 'patrick' ? patrickFamily :
    ln.font === 'caveat' ? caveatFamily :
    ln.font === 'marker' ? AN_MARKER :
    ln.font === 'hand' ? AN_HAND :
    ln.style === 'marker' ? AN_MARKER : AN_HAND;

  // grifo: só sob a parte JÁ escrita do trecho marcado
  let body: React.ReactNode = visible;
  if (ln.mark) {
    const m = ln.style === 'caps' || ln.style === 'marker' ? ln.mark.toUpperCase() : ln.mark;
    const i = txt.indexOf(m);
    if (i >= 0 && shown > i) {
      const pre = visible.slice(0, i);
      const mid = visible.slice(i, Math.min(shown, i + m.length));
      const post = visible.slice(Math.min(shown, i + m.length));
      body = (
        <>
          {pre}
          <span style={{background: AN_MARK_BG, color: '#101418', padding: '0 8px', borderRadius: 4, boxDecorationBreak: 'clone'}}>{mid}</span>
          {post}
        </>
      );
    }
  }

  return (
    <div style={{position: 'relative', display: 'inline-block', margin: '0 0 6px'}}>
      <div
        style={{
          fontFamily: fam,
          fontSize: size,
          color: ln.color ?? '#ffffff',
          lineHeight: 1.25,
          letterSpacing: ln.style === 'marker' ? 1 : 0.5,
          textShadow: '0 2px 10px rgba(0,0,0,0.75), 0 0 2px rgba(0,0,0,0.6)',
          opacity: blockOpacity,
          whiteSpace: 'pre-wrap',
        }}
      >
        {body}
      </div>
      {ln.underline ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            bottom: 2,
            height: 4,
            width: `${(shown / txt.length) * 100}%`,
            background: ln.color ?? '#ffffff',
            borderRadius: 3,
            opacity: blockOpacity * (done ? 0.95 : 0.8),
            transform: 'rotate(-0.4deg)',
          }}
        />
      ) : null}
    </div>
  );
};

const AnotacaoEl: React.FC<{g: GAnotacao}> = ({g}) => {
  const w = useGraphicWindow(g);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (!w) return null;
  const cps = g.cps ?? 34;
  const align = g.align ?? 'center';
  return (
    <>
      <AbsoluteFill
        style={{
          justifyContent: 'flex-start',
          alignItems: align === 'center' ? 'center' : 'flex-start',
          paddingTop: (g.y ?? 0.055) * 1920,
          paddingLeft: G_SIDE,
          paddingRight: G_SIDE,
        }}
      >
        <div style={{display: 'flex', flexDirection: 'column', alignItems: align === 'center' ? 'center' : 'flex-start', textAlign: align}}>
          {g.lines.map((ln, i) => (
            <AnotacaoLine key={i} ln={ln} cps={cps} fps={fps} frame={frame} blockOpacity={w.opacity} />
          ))}
        </div>
      </AbsoluteFill>
      {g.typeSfx === false
        ? null
        : g.lines.map((ln, i) => {
            const txt = ln.style === 'normal' || !ln.style ? ln.text : ln.text.toUpperCase();
            const d = Math.max(1, Math.round((txt.length / cps) * fps));
            return (
              <Sequence key={`s${i}`} from={Math.round(ln.at * fps)} durationInFrames={d}>
                <Sfx src={AN_TYPE_SFX} volume={0.22} />
              </Sequence>
            );
          })}
    </>
  );
};

export const Graphics: React.FC<{items: Graphic[]}> = ({items}) => (
  <>
    {items.map((g, i) => {
      const key = `${g.kind}-${i}`;
      switch (g.kind) {
        case 'lowerThird':
          return <React.Fragment key={key}><GraphicSfx g={g} /><LowerThirdEl g={g} /></React.Fragment>;
        case 'stat':
          return <React.Fragment key={key}><GraphicSfx g={g} /><StatEl g={g} /></React.Fragment>;
        case 'list':
          return <React.Fragment key={key}><GraphicSfx g={g} /><ListEl g={g} /></React.Fragment>;
        case 'compare':
          return <React.Fragment key={key}><GraphicSfx g={g} /><CompareEl g={g} /></React.Fragment>;
        case 'quote':
          return <React.Fragment key={key}><GraphicSfx g={g} /><QuoteEl g={g} /></React.Fragment>;
        case 'progress':
          return <React.Fragment key={key}><GraphicSfx g={g} /><ProgressEl g={g} /></React.Fragment>;
        case 'callout':
          return <React.Fragment key={key}><GraphicSfx g={g} /><CalloutEl g={g} /></React.Fragment>;
        case 'anotacao':
          // sem GraphicSfx: o som desta é a digitação, não o whoosh de cartão
          return <AnotacaoEl key={key} g={g} />;
        default:
          return null;
      }
    })}
  </>
);

// ============ CUT FLASH =======================================================
// Starts BEFORE the cut and peaks on it. A transition that begins on the cut
// frame reads as a flash after the fact; leading it by two frames makes the
// light look like the thing that caused the change.
// `at` is the cut time exactly as segments.json states it — VIDEO_LAG lines it
// up with the frame the picture actually changes on, same as the split windows.
// Frame counts at 30fps, scaled through F() — at 60fps the lead is 4 frames,
// still the same ~67ms before the cut.
const FLASH_LEAD = 2; // frames before the cut
const FLASH_LEN = 7; // total, ~230ms

const CutFlashes: React.FC<{items: CutFlash[]}> = ({items}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const F = useF();
  const lead = F(FLASH_LEAD);
  const len = F(FLASH_LEN);

  const active = items.find((it) => {
    const c = Math.round(it.at * fps) + VIDEO_LAG;
    return frame >= c - lead && frame < c - lead + len;
  });
  if (!active) return null;

  const c = Math.round(active.at * fps) + VIDEO_LAG;
  const k = active.intensity ?? 1;
  const p = (frame - (c - lead)) / (len - 1); // 0..1 pela janela

  // SAÍDA da tela dividida: um clarão curto e simétrico, SEM o facho lateral.
  // A volta para a tela cheia estava seca e lia como imperfeição (pedido do
  // usuário, 2026-08-16) — e repetir aqui o mesmo facho dos cortes tiraria o
  // sentido dele, que é marcar troca de layout. Por isso é outro desenho:
  // clarão + respiro de escala, mais rápido que o de entrada.
  if (active.variant === 'saida') {
    const pop = interpolate(frame, [c - F(2), c, c + F(3)], [0, 0.62 * k, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return (
      <AbsoluteFill style={{pointerEvents: 'none'}}>
        <AbsoluteFill
          style={{
            backgroundColor: '#fff',
            opacity: pop,
            mixBlendMode: 'screen',
            filter: `blur(${(1 - pop) * 8}px)`,
          }}
        />
        <Sequence from={c - F(1)} durationInFrames={F(8)} layout="none">
          <Sfx src={active.sfx ?? 'whoosh.mp3'} volume={active.volume ?? 0.5} />
        </Sequence>
      </AbsoluteFill>
    );
  }

  // beam sweeps left→right, brightest as it crosses centre
  const x = interpolate(p, [0, 1], [-1.35 * width, 1.35 * width]);
  const beam = interpolate(p, [0, 0.35, 1], [0, 1 * k, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  // the bloom is short and lands ON the cut, not spread across the window
  const bloom = interpolate(frame, [c - F(1), c, c + F(2)], [0, 0.5 * k, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <AbsoluteFill style={{backgroundColor: '#fff', opacity: bloom, mixBlendMode: 'screen'}} />
      <AbsoluteFill style={{overflow: 'hidden'}}>
        <div
          style={{
            position: 'absolute',
            top: '-30%',
            left: 0,
            width: width * 0.46,
            height: '160%',
            transform: `translateX(${x.toFixed(1)}px) rotate(-18deg)`,
            background:
              'linear-gradient(90deg,rgba(255,255,255,0) 0%,rgba(255,255,255,0.95) 50%,rgba(255,255,255,0) 100%)',
            opacity: beam,
            mixBlendMode: 'screen',
            filter: 'blur(16px)',
          }}
        />
      </AbsoluteFill>
      <Sequence from={c} durationInFrames={F(10)} layout="none">
        <Sfx src={active.sfx ?? 'cut-click.mp3'} volume={active.volume ?? 0.9} />
      </Sequence>
    </AbsoluteFill>
  );
};

// ============ SPLIT SCREEN ("tela dividida") ==================================
// Art on top, the talking head re-drawn underneath, seam at the subject's hairline.
//
// ONE always-mounted layer, NOT a <Sequence> per window. The obvious version wraps
// each window in <Sequence from> + <OffthreadVideo startFrom>, and that samples
// cut.mp4 ONE FRAME BEHIND the base video: on the first frame of the split you
// still see the previous take, so the layout appears to change before the picture
// does. Mounted flat with no startFrom, this layer decodes the same frame the base
// layer does, and the window edges land exactly on the cut.
// Seam blend (2026-08-15): the image band doesn't hard-cut into the video —
// it fades to transparent over the last BLEND px, revealing the video that is
// now ALWAYS rendered full-bleed underneath (previously the video's own div
// was cropped to its complementary region and simply wasn't there behind the
// band, so nothing existed to blend into). This is the "fusão, com
// transparência" look the user referenced from a CapCut/Edits gradient-mask
// split tutorial: a soft dissolve AT THE SEAM, not a crossfade between takes
// over time. The image itself is sized to bandH+BLEND (not bandH) so it has
// real content to fade FROM in that zone, instead of fading empty space.
//
// v1 used BLEND=140 with the legibility darkening below left untouched (fixed
// 110px, capped 0.75, ending exactly at bandH) — tested on a real project and
// it read as "péssimo": the darkening hit its max right where the mask was
// still ~opaque, so that row painted as a flat muddy stripe, then the reveal
// below it showed at low alpha with no darkening at all — two unrelated fades
// butted end to end instead of moving together, over a window wider than
// what the reference actually showed (its blend read as tight, not a big
// foggy port-hole). v2 shrank the window to 60 and eased the darkening into a
// dip — user's next read: "a divisão está bem nítida, como uma linha reta
// ... gostaria que fosse em transparência como em máscara ou camadas, usado
// no CapCut". Two things were fighting a clean mask read: 60px is not much
// room on a 1080-wide frame, and the darkening — even eased — is a SEPARATE
// color effect on top of the alpha mask, and a second gradient reads as an
// edge of its own no matter how it's shaped. v3 dropped the darkening
// rectangle entirely and jumped to BLEND=280 — user's read: "melhorou muito"
// but now "a imagem de cima ficou muito grande ... pegou metade da tela" (280
// makes the band+blend container 1030px, 54% of a 1920 frame — genuinely too
// much) "e cortou minha cabeça" — that part was a SEPARATE real bug (see the
// OffthreadVideo `top` comment below), not a BLEND side effect. v4 (current):
// BLEND=100 — soft and wide enough to read as a real mask dissolve, without
// dominating the frame. Caption legibility over the art still has its own
// text-shadow per caption style (see SimpleCaptions.tsx / StackedCaptions.tsx)
// — that was never this rectangle's only source of contrast.
const SEAM_BLEND = 100;

// Largura da dissolução por LAYOUT. 'top' mantém os 100 do Formato 1, onde a
// junção cai na borda do próprio clipe e a pessoa passa na frente por matte.
// 'bottom' usa a divisão larga que ele pediu em 2026-09-11 ("para a arte em
// baixo quero a divisão dessa forma", apontando o vídeo de referência): 192px,
// medidos naquele vídeo. Um `seamBlend` explícito na janela vence os dois — é
// assim que o Formato 2 usa 192 com a arte em CIMA.
const LAYOUT_BLEND: Record<'top' | 'bottom', number> = {top: SEAM_BLEND, bottom: 192};

const SplitFrame: React.FC<{
  src: string;
  kind: 'image' | 'video';
  loopFrames?: number;
  bandH: number;
  fit: 'cover' | 'contain';
  progress: number;
  layout: 'top' | 'bottom';
  // Matte da pessoa (person_matte.py), frame 0 = início DESTA janela. Com ele
  // a divisão continua existindo, mas a cabeça passa NA FRENTE da faixa e a
  // costura dissolve atrás dela — as duas coisas juntas, que é o pedido do
  // usuário (2026-08-16, com duas referências visuais). Sem matte, o
  // comportamento é o de antes: faixa reta por cima de tudo.
  matte?: string;
  windowFrom?: number; // frame absoluto em que a janela começa
  windowDur?: number;
  zoomOverride?: number;
  focusYOverride?: number;
  // Degrau de zoom DESTA janela (1 = neutro). É o que faz o zoom in/out
  // acontecer também durante a tela dividida — a câmera do template não chega
  // aqui, porque o SplitFrame redesenha o vídeo por conta própria. Sem isso o
  // vídeo passa dezenas de segundos sem variação nenhuma de enquadramento.
  zoomPulse?: number;
  artZoom?: number;
  // Largura da dissolução DESTA janela; ver o campo homônimo em SplitInsert.
  seamBlend?: number;
}> = ({src, kind, loopFrames, bandH, fit, progress, layout, matte, artZoom, windowFrom, windowDur, zoomOverride, focusYOverride, zoomPulse, seamBlend}) => {
  const F = useF();
  // slow Ken-Burns so the band is not a dead still
  const artScale = 1 + 0.03 * progress;
  const zoomBase = zoomOverride ?? LAYOUT[layout].zoom;
  const focusYBase = focusYOverride ?? LAYOUT[layout].focusY;
  // degrau da janela + push-in lento dentro dela
  const zoom = zoomBase * (zoomPulse ?? 1) * (1 + 0.035 * progress);
  // O zoom tem que acontecer EM TORNO DO ROSTO, senão mudar a escala empurra a
  // cabeça para fora da costura. Ancorando um ponto da fonte (o rosto, ~260px
  // abaixo do focusY do enquadramento) a posição dele na tela não muda.
  const anchor = focusYBase + 260;
  const focusY = anchor - ((anchor - focusYBase) * zoomBase) / zoom;
  const blend = seamBlend ?? LAYOUT_BLEND[layout];
  const bandWithBlend = bandH + blend;
  const solidPct = (bandH / bandWithBlend) * 100;
  const blendPct = (blend / bandWithBlend) * 100;
  // 'top': art at [0, bandH], fades out downward into the video below.
  // 'bottom': art at [1920-bandH, 1920], fades out upward into the video above.
  const bandTop = layout === 'top' ? 0 : 1920 - bandWithBlend;
  const mask =
    layout === 'top'
      ? `linear-gradient(180deg, #000 0%, #000 ${solidPct}%, transparent 100%)`
      : `linear-gradient(180deg, transparent 0%, #000 ${blendPct}%, #000 100%)`;

  return (
    <AbsoluteFill style={{backgroundColor: '#0a0a0c'}}>
      {/* Always full-bleed now — the seam blend needs the real video sitting
          behind the WHOLE band, not just its own complementary region. Before
          this, the video's OWN container was positioned at `top: videoTop`
          (bandH for 'top' layout) and `-focusY*zoom` was relative to THAT
          origin. Going full-bleed moved the container's origin to 0 without
          adjusting the inner offset to match — the video silently jumped up
          by `bandH` px, cropping the head out (caught 2026-08-15 on a real
          project: "cortou minha cabeça"). Adding back the old per-layout
          origin here restores the exact same framing as before full-bleed. */}
      <div style={{position: 'absolute', left: 0, top: 0, width: 1080, height: 1920, overflow: 'hidden'}}>
        <OffthreadVideo
          src={staticFile('cut.mp4')}
          muted
          style={{
            position: 'absolute',
            width: 1080 * zoom,
            height: 1920 * zoom,
            left: -(1080 * (zoom - 1)) / 2,
            top: (layout === 'top' ? bandH : 0) - focusY * zoom,
          }}
        />
      </div>

      <div
        style={{
          position: 'absolute',
          left: 0,
          top: bandTop,
          width: 1080,
          height: bandWithBlend,
          overflow: 'hidden',
          WebkitMaskImage: mask,
          maskImage: mask,
        }}
      >
        {/* O clipe da faixa PRECISA estar dentro de uma Sequence: sem ela o
            OffthreadVideo é indexado pelo tempo da COMPOSIÇÃO, então uma janela
            que começa aos 55s pede o segundo 55 de um clipe de 5s, passa do fim
            e CONGELA no último frame. Só a primeira janela (que começa perto do
            zero) parecia funcionar — foi assim que o defeito passou batido até o
            usuário apontar "estão praticamente estáticos" (2026-08-16).
            Diferente do cut.mp4 da camada de baixo, aqui a Sequence é o certo:
            o arquivo é próprio da janela e tem que tocar do seu frame 0. */}
        <Sequence from={windowFrom ?? 0} durationInFrames={windowDur ?? 1} layout="none">
          {/* Fundo desfocado do PRÓPRIO clipe: deixa a faixa cheia sem precisar
              ampliar/cortar o vídeo. Antes o `cover` esticava um 16:9 numa faixa
              de 1080x850 e o resultado saía com "proporções maiores do que o
              normal, fugindo da visualização". */}
          {fit === 'contain' && kind === 'video' ? (
            <OffthreadVideo
              src={staticFile(src)}
              muted
              style={{
                position: 'absolute',
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                filter: 'blur(34px) brightness(0.55)',
                transform: 'scale(1.12)',
              }}
            />
          ) : null}
          {kind === 'video' ? (
            loopFrames ? (
              <Loop durationInFrames={F(loopFrames)}>
                <OffthreadVideo
                  src={staticFile(src)}
                  muted
                  style={{width: '100%', height: '100%', objectFit: fit, scale: String(artScale)}}
                />
              </Loop>
            ) : (
              <OffthreadVideo
                src={staticFile(src)}
                muted
                style={{width: '100%', height: '100%', objectFit: fit, scale: String(artScale)}}
              />
            )
          ) : (
            <Img
              src={staticFile(src)}
              style={{width: '100%', height: '100%', objectFit: fit, scale: String(artScale)}}
            />
          )}
        </Sequence>
      </div>

      {/* A pessoa, recortada, POR CIMA da faixa — mesmo enquadramento do vídeo
          da camada 1 (o par zoom/focusY do layout), senão ela desgruda de si
          mesma. É isso que faz a arte passar por trás da cabeça mantendo a
          divisão das telas. */}
      {matte && windowFrom !== undefined ? (
        <Sequence from={windowFrom} durationInFrames={windowDur ?? 1} layout="none">
          <div style={{position: 'absolute', left: 0, top: 0, width: 1080, height: 1920, overflow: 'hidden'}}>
            <OffthreadVideo
              src={staticFile(matte)}
              transparent
              muted
              style={{
                position: 'absolute',
                width: 1080 * zoom,
                height: 1920 * zoom,
                left: -(1080 * (zoom - 1)) / 2,
                top: (layout === 'top' ? bandH : 0) - focusY * zoom,
              }}
            />
          </div>
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};
/* v3 removed the separate legibility-darkening rectangle that used to live
   here (see the SEAM_BLEND comment above for why) — if a future caption style
   genuinely needs extra contrast over the art band, give it its own
   text-shadow/background-clip treatment in that caption component rather
   than reviving a rectangle that fights the mask. */

// OffthreadVideo draws the source frame at or before frame/fps; on an exact frame
// boundary that lands one frame LATE, so the decoded picture changes one
// composition frame after the index says it should. Measured, not guessed: with
// the split disabled, the camera zoom (index-driven) steps at frame 350 while the
// take itself changes at 351. Delay the layout by the same frame or the split
// visibly precedes the cut.
export const VIDEO_LAG = 1;

export const SplitScreen: React.FC<{items: SplitInsert[]}> = ({items}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // frame-indexed, not seconds: the window edges ARE cut frames
  const active = items.find((it) => {
    const a = Math.round(it.start * fps) + VIDEO_LAG;
    const b = Math.round(it.end * fps) + VIDEO_LAG;
    return frame >= a && frame < b;
  });
  if (!active) return null;
  const a = Math.round(active.start * fps) + VIDEO_LAG;
  const b = Math.round(active.end * fps) + VIDEO_LAG;
  return (
    <SplitFrame
      src={active.src}
      kind={active.kind ?? 'image'}
      loopFrames={active.loopFrames}
      bandH={active.bandH ?? 750}
      fit={active.fit ?? 'cover'}
      layout={active.layout ?? 'top'}
      progress={clamp((frame - a) / Math.max(1, b - a), 0, 1)}
      matte={active.matte}
      artZoom={active.artZoom}
      windowFrom={a}
      windowDur={b - a}
      zoomOverride={active.zoom}
      focusYOverride={active.focusY}
      zoomPulse={active.zoomPulse}
      seamBlend={active.seamBlend}
    />
  );
};

// ============ CAPA (hook) COM A TIPOGRAFIA DA LEGENDA ==========================
// O hook do template pinta laranja fixo nos estilos `realce`/`misto` e não
// mistura duas faces. A capa pedida é a MESMA identidade da legenda stacked:
// sans pesado branco + UMA palavra em serifada itálica, tudo branco. Por isso
// ela vive aqui, dirigida por `hookStacked` no edit-data.json (com
// `hook.enabled: false`, senão as duas capas se sobrepõem).
type HookLine = {
  text: string;
  // 0 = Poppins Black itálico · 1 = Poppins regular menor · 2 = Playfair itálico
  // (a palavra de destaque) · 3 = Poppins ExtraBold — mesma escala de estilos da
  // legenda stacked, para capa e legenda lerem como a mesma família.
  style: 0 | 1 | 2 | 3;
  size?: number;
  color?: string; // sobrepõe a cor do bloco — a palavra de destaque em azul
};
type HookStacked = {
  enabled?: boolean;
  endSec: number;
  lines: HookLine[];
  offsetY?: number; // 0–1 da altura, centro do bloco (padrão 0.30)
  // Para onde o bloco DESLIZA depois de entrar. A capa nasce na altura de
  // leitura e sobe para liberar o rosto (pedido de 2026-08-16) — ela fica no ar
  // até `endSec`, e a primeira tela dividida só começa depois disso.
  offsetYEnd?: number;
  slideStartSec?: number;
  slideDurSec?: number;
  color?: string;
};

// Tela de encerramento da marca: fundo azul-petróleo, texto dourado centralizado.
// Padrão permanente do usuário desde 2026-08-16 (substituiu o card preto/branco).
type Outro = {
  enabled?: boolean;
  startSec: number;
  durationSec: number;
  lines: string[];
  bg?: string;
  color?: string;
};

// Contagens a 30fps, convertidas por F().
const HOOK_ENTER = 5; // frames de subida por linha
const HOOK_STAGGER = 3; // frames entre uma linha e a próxima

const HookStackedCard: React.FC<{cfg: HookStacked}> = ({cfg}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const F = useF();
  const end = Math.round(cfg.endSec * fps);
  if (frame >= end) return null;
  const color = cfg.color ?? '#ffffff';
  const out = interpolate(frame, [end - F(8), end], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  // deslize: entra na altura de leitura e sobe para liberar o rosto
  const y0 = cfg.offsetY ?? 0.3;
  const y1 = cfg.offsetYEnd ?? y0;
  const slideA = Math.round((cfg.slideStartSec ?? 0.9) * fps);
  const slideB = slideA + Math.round((cfg.slideDurSec ?? 0.8) * fps);
  const offsetY = interpolate(frame, [slideA, slideB], [y0, y1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const faces: React.CSSProperties[] = [
    {fontFamily, fontWeight: 900, fontStyle: 'italic'},
    {fontFamily, fontWeight: 400, fontStyle: 'normal'},
    {fontFamily: playfairFamily, fontWeight: 900, fontStyle: 'italic'},
    {fontFamily, fontWeight: 800, fontStyle: 'normal'},
  ];
  return (
    <AbsoluteFill
      style={{
        alignItems: 'center',
        justifyContent: 'center',
        paddingBottom: `${(0.5 - offsetY) * 2 * 100}%`,
        opacity: out,
      }}
    >
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', lineHeight: 1.02}}>
        {cfg.lines.map((ln, i) => {
          const t0 = i * F(HOOK_STAGGER);
          const p = interpolate(frame, [t0, t0 + F(HOOK_ENTER)], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          });
          return (
            <div
              key={i}
              style={{
                ...faces[ln.style],
                color: ln.color ?? color,
                fontSize: ln.size ?? (ln.style === 1 ? 74 : 104),
                opacity: p,
                transform: `translateY(${(1 - p) * 26}px)`,
                filter: 'drop-shadow(0 5px 10px rgba(0,0,0,0.55)) drop-shadow(0 2px 3px rgba(0,0,0,0.55))',
                textAlign: 'center',
                whiteSpace: 'nowrap',
              }}
            >
              {ln.text}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ============ LOGO DA MARCA (abertura) =========================================
// Padrão de marca: entra no começo, centralizada na BORDA INFERIOR, abaixo da
// legenda, e sai junto com a capa. Entrada e saída em transparência.
// A logo entregue tem 478x153 px — não passar de ~600px de largura, acima disso
// ela amolece (ver a memória de marca).
type Logo = {enabled?: boolean; src: string; endSec: number; width?: number; bottom?: number};

const LogoOpening: React.FC<{cfg: Logo}> = ({cfg}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const F = useF();
  const end = Math.round(cfg.endSec * fps);
  if (frame >= end) return null;
  const op = Math.min(
    interpolate(frame, [0, F(12)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
    interpolate(frame, [end - F(12), end], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
  );
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-end', pointerEvents: 'none'}}>
      <Img
        src={staticFile(cfg.src)}
        style={{
          width: cfg.width ?? 520,
          marginBottom: cfg.bottom ?? 120,
          opacity: op * 0.95,
          filter: 'drop-shadow(0 3px 10px rgba(0,0,0,0.5))',
        }}
      />
    </AbsoluteFill>
  );
};

// ============ TELA DE ENCERRAMENTO DA MARCA ====================================
// Azul-petróleo com letras douradas, centralizado, minimalista. Entra e sai em
// transparência para não bater como um corte seco no fim da fala.
// Azul ESCURO (2026-08-17, correção dele — o petróleo anterior era claro demais).
const OUTRO_BG = '#071d33';
const OUTRO_GOLD = '#d4b25f';

const OutroCard: React.FC<{cfg: Outro}> = ({cfg}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const F = useF();
  const a = Math.round(cfg.startSec * fps);
  const b = a + Math.round(cfg.durationSec * fps);
  if (frame < a || frame >= b) return null;
  const local = frame - a;
  // Entra em transparência e FICA. Sem fade de saída: a v4 tinha um, e nos
  // últimos frames o card ficava translúcido, deixando o vídeo reaparecer por
  // baixo — o vídeo tem que TERMINAR na tela da marca (pego na revisão de 100%,
  // 2026-08-17).
  const fade = interpolate(local, [0, F(10)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const rise = interpolate(local, [0, F(16)], [18, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: cfg.bg ?? OUTRO_BG,
        alignItems: 'center',
        justifyContent: 'center',
        opacity: fade,
      }}
    >
      <div style={{textAlign: 'center', transform: `translateY(${rise}px)`}}>
        {cfg.lines.map((ln, i) => (
          <div
            key={i}
            style={{
              fontFamily,
              color: cfg.color ?? OUTRO_GOLD,
              fontWeight: i === 0 ? 600 : 300,
              fontSize: i === 0 ? 74 : 40,
              letterSpacing: i === 0 ? '0.01em' : '0.06em',
              marginTop: i === 0 ? 0 : 26,
            }}
          >
            {ln}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ============ BEHIND-THE-SUBJECT (B-roll ATRÁS da pessoa) ======================
// Ordem das camadas dentro da janela: B-roll cobrindo o quadro inteiro → pessoa
// recortada por cima. O vídeo-base fica escondido pelo B-roll, então o que
// precisa bater é a PESSOA: o matte recebe a mesma câmera do template via
// <DynamicVideo>, senão ela desgruda do fundo na entrada e na saída da janela.
// `frameOffset` existe exatamente para isso — o arquivo de matte começa no
// frame 0 da SUA janela, e sem o deslocamento ele tocaria do início do vídeo.
const BehindVideos: React.FC<{items: BehindVideo[]}> = ({items}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const F = useF();
  // Mesma indexação por frame do SplitScreen: as bordas da janela SÃO cortes.
  const active = items.find((it) => {
    const a = Math.round(it.start * fps) + VIDEO_LAG;
    const b = Math.round(it.end * fps) + VIDEO_LAG;
    return frame >= a && frame < b;
  });
  if (!active) return null;
  const a = Math.round(active.start * fps) + VIDEO_LAG;
  const b = Math.round(active.end * fps) + VIDEO_LAG;
  const progress = clamp((frame - a) / Math.max(1, b - a), 0, 1);
  const artScale = 1 + 0.03 * progress; // Ken-Burns lento, o fundo não fica morto
  const fit = active.fit ?? 'cover';
  const bgOpacity = active.bgOpacity ?? 1;
  const art =
    (active.kind ?? 'video') === 'video' ? (
      active.loopFrames ? (
        <Loop durationInFrames={F(active.loopFrames)}>
          <OffthreadVideo
            src={staticFile(active.src)}
            muted
            style={{width: '100%', height: '100%', objectFit: fit, scale: String(artScale)}}
          />
        </Loop>
      ) : (
        <OffthreadVideo
          src={staticFile(active.src)}
          muted
          style={{width: '100%', height: '100%', objectFit: fit, scale: String(artScale)}}
        />
      )
    ) : (
      <Img
        src={staticFile(active.src)}
        style={{width: '100%', height: '100%', objectFit: fit, scale: String(artScale)}}
      />
    );

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{opacity: bgOpacity}}>{art}</AbsoluteFill>
      <DynamicVideo src={active.matte} frameOffset={-a} transparent />
    </AbsoluteFill>
  );
};

// ============ WORKED EXAMPLE 1: editing timeline being cut + caption tracks =====
// For "os cortes, as legendas e as animações" — a mini editor UI: playhead
// sweeps and splits the video track, caption chips pop in, shapes pop last.
const TL_W = 800;
const TL_H = 378;
const PAD = 46;
const INNER = TL_W - PAD * 2;

// Worked examples are written in 30fps frames throughout (wobbles included), so
// they rescale the CLOCK instead of every literal: `f` and `total` are in 30fps
// units at any render fps (see toBase in fps.ts).
const TimelineInner: React.FC<{totalFrames: number}> = ({totalFrames: totalReal}) => {
  const {fps} = useVideoConfig();
  const f = toBase(useCurrentFrame(), fps);
  const totalFrames = toBase(totalReal, fps);
  const appear = interpolate(f, [0, 9], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const exit = interpolate(f, [totalFrames - 7, totalFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const rise = interpolate(appear, [0, 1], [26, 0]);

  // playhead sweeps, bar splits into 3
  const gap = interpolate(f, [6, 16], [0, 16], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const pieceW = (INNER - gap * 2) / 3;
  const playX = interpolate(f, [0, 16], [0, INNER], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const playOp = interpolate(f, [0, 2, 15, 19], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center'}}>
      <Sfx src="whoosh.mp3" />
      <div style={{width: TL_W, height: TL_H, marginTop: 105, borderRadius: 28, background: '#15171c', border: '1px solid #262a31', boxShadow: '0 18px 50px rgba(0,0,0,0.5)', opacity: appear * exit, scale: String(interpolate(appear, [0, 1], [0.93, 1])), translate: `0px ${rise}px`, padding: PAD, boxSizing: 'border-box', position: 'relative', fontFamily}}>
        {/* window dots */}
        <div style={{display: 'flex', gap: 12}}>
          {['#ff5f57', '#febc2e', '#28c840'].map((c) => (<div key={c} style={{width: 16, height: 16, borderRadius: 999, background: c}} />))}
        </div>

        {/* VIDEO track — being cut */}
        <div style={{position: 'absolute', left: PAD, top: 92, width: INNER, height: 62}}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{position: 'absolute', left: i * (pieceW + gap), width: pieceW, height: 62, borderRadius: 10, background: 'linear-gradient(180deg,#5b8dff,#3f6fe0)', boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.15)'}} />
          ))}
          <div style={{position: 'absolute', left: playX, top: -8, width: 3, height: 78, background: 'white', opacity: playOp, boxShadow: '0 0 8px rgba(255,255,255,0.8)'}} />
        </div>

        {/* LEGENDAS track — caption chips appear */}
        <div style={{position: 'absolute', left: PAD, top: 188, width: INNER, height: 46}}>
          {[0, 1, 2, 3].map((k) => {
            const ap = interpolate(f, [16 + k * 5, 24 + k * 5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.back(1.5))});
            return (
              <div key={k} style={{position: 'absolute', left: k * (INNER / 4), width: INNER / 4 - 14, height: 46, borderRadius: 9, background: '#33e0a3', opacity: Math.min(1, ap), scale: String(Math.max(0.01, ap)), display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 6, padding: '0 12px', boxSizing: 'border-box'}}>
                <div style={{height: 6, width: '80%', borderRadius: 4, background: 'rgba(0,0,0,0.55)'}} />
                <div style={{height: 6, width: '55%', borderRadius: 4, background: 'rgba(0,0,0,0.4)'}} />
              </div>
            );
          })}
        </div>

        {/* ANIMAÇÕES track — shapes pop */}
        <div style={{position: 'absolute', left: PAD, top: 270, width: INNER, height: 60, display: 'flex', gap: 20, alignItems: 'center'}}>
          {[0, 1, 2, 3].map((k) => {
            const ap = interpolate(f, [34 + k * 4, 42 + k * 4], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.back(1.8))});
            const rot = Math.sin((f + k * 7) * 0.2) * 20;
            const colors = ['#ffffff', '#ffd23f', '#ff5f9e', '#5b8dff'];
            const rounds = [999, 12, 6, 999];
            return (<div key={k} style={{width: 52, height: 52, background: colors[k], borderRadius: rounds[k], opacity: Math.min(1, ap), scale: String(Math.max(0.01, ap)), rotate: `${rot}deg`}} />);
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const TimelineGraphic: React.FC<{startSec: number; endSec: number}> = ({startSec, endSec}) => {
  const {fps} = useVideoConfig();
  const from = Math.round(startSec * fps);
  const duration = Math.round((endSec - startSec) * fps);
  return (
    <Sequence from={from} durationInFrames={duration} layout="none">
      <TimelineInner totalFrames={duration} />
    </Sequence>
  );
};

// ============ WORKED EXAMPLE 2: script sheet with typewriter text ===============
// For "ela leu o roteiro" — a tilted paper card, lines typing in with a cursor.
const ScriptInner: React.FC<{totalFrames: number; lines: string[]}> = ({totalFrames: totalReal, lines}) => {
  const {fps} = useVideoConfig();
  const f = toBase(useCurrentFrame(), fps);
  const totalFrames = toBase(totalReal, fps);
  const appear = interpolate(f, [0, 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const exit = interpolate(f, [totalFrames - 7, totalFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const cps = 1.7; // chars per 30fps frame

  return (
    <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center'}}>
      <Sfx src="whoosh.mp3" />
      <div style={{width: 640, height: 420, marginTop: 100, borderRadius: 16, background: '#f4f1e8', boxShadow: '0 22px 55px rgba(0,0,0,0.5)', opacity: appear * exit, scale: String(interpolate(appear, [0, 1], [0.94, 1])), rotate: '-2deg', translate: `0px ${interpolate(appear, [0, 1], [26, 0])}px`, padding: 46, boxSizing: 'border-box', fontFamily}}>
        <div style={{fontWeight: 900, fontSize: 26, letterSpacing: 3, color: '#c2492b'}}>ROTEIRO</div>
        <div style={{height: 4, width: 90, background: '#c2492b', borderRadius: 3, marginTop: 10, marginBottom: 30}} />
        {lines.map((line, i) => {
          const startLocal = 10 + i * 12;
          const shown = clamp(Math.floor((f - startLocal) * cps), 0, line.length);
          const isTyping = shown > 0 && shown < line.length;
          const cursor = isTyping && Math.floor(f / 6) % 2 === 0 ? '|' : '';
          return (
            <div key={i} style={{fontWeight: 400, fontSize: 32, color: '#2b2b2b', lineHeight: 1.5, minHeight: 40}}>
              {line.slice(0, shown)}
              <span style={{color: '#c2492b'}}>{cursor}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const ScriptGraphic: React.FC<{startSec: number; endSec: number; lines: string[]}> = ({startSec, endSec, lines}) => {
  const {fps} = useVideoConfig();
  const from = Math.round(startSec * fps);
  const duration = Math.round((endSec - startSec) * fps);
  return (
    <Sequence from={from} durationInFrames={duration} layout="none">
      <ScriptInner totalFrames={duration} lines={lines} />
    </Sequence>
  );
};

// ============ WORKED EXAMPLE 3: playful shapes pop (for "animações") ============
const Shape: React.FC<{i: number; color: string; round: number}> = ({i, color, round}) => {
  const {fps} = useVideoConfig();
  const frame = toBase(useCurrentFrame(), fps);
  const appear = interpolate(frame, [i * 3, i * 3 + 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.back(1.6))});
  const pulse = 1 + 0.16 * Math.sin((frame + i * 6) * 0.28);
  const rot = Math.sin((frame + i * 8) * 0.12) * 22;
  return (
    <div
      style={{
        width: 92,
        height: 92,
        background: color,
        borderRadius: round,
        opacity: appear,
        scale: String(appear * pulse),
        rotate: `${rot}deg`,
        boxShadow: '0 10px 30px rgba(0,0,0,0.35)',
      }}
    />
  );
};

const ShapesInner: React.FC<{totalFrames: number}> = ({totalFrames: totalReal}) => {
  const {fps} = useVideoConfig();
  const frame = toBase(useCurrentFrame(), fps);
  const totalFrames = toBase(totalReal, fps);
  const exit = interpolate(frame, [totalFrames - 7, totalFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const rise = interpolate(frame, [0, 8], [24, 0], {extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  return (
    <AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'center'}}>
      <Sfx src="pop.mp3" volume={0.12} />
      <div style={{marginTop: 210, display: 'flex', gap: 34, opacity: exit, translate: `0px ${rise}px`}}>
        <Shape i={0} color="white" round={46} />
        <Shape i={1} color="#33e0a3" round={20} />
        <Shape i={2} color="white" round={8} />
      </div>
    </AbsoluteFill>
  );
};

export const ShapesGraphic: React.FC<{startSec: number; endSec: number}> = ({startSec, endSec}) => {
  const {fps} = useVideoConfig();
  const from = Math.round(startSec * fps);
  const duration = Math.round((endSec - startSec) * fps);
  return (
    <Sequence from={from} durationInFrames={duration} layout="none">
      <ShapesInner totalFrames={duration} />
    </Sequence>
  );
};

// ============ TITLE CARDS ("premium editorial" stacked cards, 2026-08-15) =====
// The signature of the "premium editorial" style — built from direct frame
// analysis of a reference creator's real Reels, not just a written brief
// (see references/style-premium-editorial.md). Stacked 2-4 line cards, one
// line per weight role:
//   'light'  small connector words — Poppins Light (300), white ~80% opacity
//   'bold'   the key word — Poppins ExtraBold (800), full white, LARGEST
//   'script' ONE accent word/phrase — Alex Brush cursive, a per-card color,
//            negative margin so it overlaps the line above it (only mark the
//            ONE line meant to read as the signature accent — not every card
//            needs one; the reference doesn't put one on every card either)
// Lines build up with a short stagger (each fades in over ENTER frames, ~165ms
// apart) then the whole card holds until `end` and cuts INSTANTLY — no exit
// fade, matching "corte seco em 95% das transições" / "movimento gráfico
// mínimo, entrada instantânea ou fade de 4 frames". Drop-shadow only, no
// background box, no outline — "nunca use caixa de fundo colorida".
// paddingBottom:650 + these font sizes keep a typical 3-4 line card inside
// y≈950-1270 on a 1920-tall frame — well clear of both Reels UI exclusion
// zones from the tech spec (top 250px, bottom 420px). A card with unusually
// large text or 4+ lines should be checked against those two numbers again,
// not assumed safe.
// ALWAYS mounted flat, frame read globally — same reasoning as SplitScreen
// above (a <Sequence>-local useCurrentFrame() is relative to the Sequence,
// not the composition, and silently breaks window math; this bit twice
// already this project — see SplitCaptionsBottom's history).
//
// Script accent color is NOT fixed (2026-08-15, user correction — a first
// draft defaulted every project to pink and the user's read was immediate:
// "não quero com letra rosa... quero que a cor não seja fixa, pode mudar de
// um vídeo para outro"). Pick ONE color per project from this palette (or a
// close variant) via `TitleLine.color` — every script line in THAT video
// should agree, but different projects should land on different picks, not
// all default to the same one. TITLE_ACCENT_FALLBACK only covers the case
// where `color` is omitted entirely; don't lean on it as a real choice.
export const TITLE_ACCENT_PALETTE = {
  azul: '#3b82f6',
  vermelho: '#e5484d',
  dourado: '#c9a227',
  verde: '#2f9e5c',
  azulPiscina: '#22b8c4',
} as const;
const TITLE_ACCENT_FALLBACK = TITLE_ACCENT_PALETTE.dourado;

type TitleLine = {text: string; weight?: 'light' | 'bold' | 'script'; color?: string};
type TitleCard = {start: number; end: number; lines: TitleLine[]; align?: 'left' | 'center'};

const TITLE_STAGGER = 5; // frames @30fps between each line's entry (~165ms), via F()
const TITLE_ENTER = 4; // frames to fade in — the brief's "fade de 4 frames, no máximo"

const TitleCardFrame: React.FC<{card: TitleCard; localFrame: number}> = ({card, localFrame}) => {
  const F = useF();
  const centered = card.align === 'center';
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: centered ? 'center' : 'flex-start',
        paddingBottom: 650,
        paddingLeft: 72,
        paddingRight: 72,
      }}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          textAlign: centered ? 'center' : 'left',
          filter: 'drop-shadow(6px 6px 20px rgba(0,0,0,0.45))',
        }}
      >
        {card.lines.map((ln, i) => {
          const start = i * F(TITLE_STAGGER);
          const op = interpolate(localFrame, [start, start + F(TITLE_ENTER)], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const isScript = ln.weight === 'script';
          const isBold = ln.weight === 'bold';
          return (
            <div
              key={i}
              style={{
                opacity: op,
                fontFamily: isScript ? scriptFamily : fontFamily,
                fontWeight: isScript ? 400 : isBold ? 800 : 300,
                color: isScript ? (ln.color ?? TITLE_ACCENT_FALLBACK) : isBold ? '#ffffff' : 'rgba(255,255,255,0.8)',
                fontSize: isScript ? 88 : isBold ? 118 : 54,
                lineHeight: isScript ? 1.05 : 1.08,
                letterSpacing: isBold ? -1 : 0,
                marginTop: isScript ? -22 : 0, // overlaps the line above — the brief's "ligeiramente sobreposta"
              }}
            >
              {ln.text}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const TitleCards: React.FC<{items: TitleCard[]}> = ({items}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const active = items.find((c) => {
    const a = Math.round(c.start * fps);
    const b = Math.round(c.end * fps);
    return frame >= a && frame < b;
  });
  if (!active) return null;
  const a = Math.round(active.start * fps);
  return <TitleCardFrame card={active} localFrame={frame - a} />;
};

// ============ SPLIT CAPTIONS (re-hosted to the bottom) ========================
// While a split window is up the head is re-framed smaller and lower, and the
// caption's normal band lands ON the face. This re-hosts the caption to the
// very bottom of the frame, a little smaller, for the duration of ANY split
// window — then the template's own caption takes over again outside them.
//
// Why a bespoke component instead of `captions.windows`: that override is
// implemented as a paddingBottom hook and only the paddingBottom-based styles
// (karaoke/simples/serifada/classica) read it. The `scatter` style positions
// via `scatterOffsetY` and has NO per-window hook, so `windows` is a silent
// no-op there — verified before/after on real stills, position identical.
//
// The workflow that feeds it (see references/shortform.md): copy the cues that
// fall inside the split windows into public/captions_split.json, BLANK those
// same cues in captions.json (keep their timing, set text to "") so the
// built-in caption stops drawing over the face, and this draws them instead.
// captions_split.json must exist even when empty (`[]`) — it is a static
// import and webpack fails the build otherwise, same as track.json.
//
// Keeps the SAME scatter look, not a plain fade (user correction, 2026-08-15 —
// the first version was a simple fade and read as a different caption style):
// lowercase Lora, ordinary words FADE only, one long word per cue (>=7 letters)
// resolves out of a heavy blur at 1.62x and dissolves back into blur on exit,
// positions hashed off the cue index for a ragged drift.
type SplitCue = {text: string; startMs: number; endMs: number};

// Deterministic per-word hash. NEVER Math.random(): Remotion renders frames
// independently, so a true random re-rolls the layout every frame and the text
// shakes — the same warning the scatter style carries in the track reference.
const hashOffset = (seed: number, range: number) => {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return (x - Math.floor(x) - 0.5) * 2 * range;
};

// No <Sequence> wrapper. useCurrentFrame() inside one is LOCAL to the sequence
// (0 at its own start), while these cues carry absolute ms on the cut.mp4
// timeline — wrapped, the comparison never matches and NOTHING renders, with
// no error. This bit twice; SplitScreen and CutFlashes read the global frame
// for the same reason.
export const SplitCaptionsBottom: React.FC<{
  items: {start: number; end: number}[];
  fontSize?: number;
  paddingBottom?: number;
}> = ({items, fontSize = 54, paddingBottom = 170}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const nowMs = (frame / fps) * 1000;

  // Generalised to N windows (the first version handled only splitInserts[0],
  // which silently dropped the caption fix on every window after the first).
  const win = items.find((w) => nowMs >= w.start * 1000 && nowMs < w.end * 1000);
  if (!win) return null;
  const winEndMs = win.end * 1000;

  const cues = captionsSplitData as SplitCue[];
  let active: SplitCue | null = null;
  let activeIndex = -1;
  for (let i = 0; i < cues.length; i++) {
    const c = cues[i];
    if (!c.text) continue;
    const next = cues[i + 1];
    const cueEndMs = next ? Math.min(next.startMs, winEndMs) : winEndMs;
    if (nowMs >= c.startMs && nowMs < cueEndMs) {
      active = c;
      activeIndex = i;
      break;
    }
  }
  if (!active) return null;

  const word = active.text.trim();
  const isHero = word.replace(/[^\p{L}]/gu, '').length >= 7;
  const localMs = nowMs - active.startMs;
  const cueDurMs = active.endMs - active.startMs;

  const fadeIn = interpolate(localMs, [0, 90], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const fadeOut = interpolate(localMs, [Math.max(0, cueDurMs - 120), cueDurMs], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = Math.min(fadeIn, fadeOut);

  const blurIn = isHero
    ? interpolate(localMs, [0, 220], [18, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 0;
  const blurOut = isHero
    ? interpolate(localMs, [Math.max(0, cueDurMs - 200), cueDurMs], [0, 14], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 0;
  const blurPx = Math.max(blurIn, blurOut);
  const scale = isHero
    ? interpolate(localMs, [0, 220], [1.62, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 1;

  const raggedX = hashOffset(activeIndex, 30);

  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', pointerEvents: 'none'}}>
      <div
        style={{
          fontFamily: loraFamily,
          fontWeight: isHero ? 700 : 400,
          fontStyle: isHero ? 'italic' : 'normal',
          fontSize: isHero ? fontSize * 1.15 : fontSize,
          background: 'linear-gradient(180deg, #fbfaf6 0%, #cfc9ba 100%)',
          WebkitBackgroundClip: 'text',
          backgroundClip: 'text',
          color: 'transparent',
          textAlign: 'center',
          lineHeight: 1.25,
          opacity,
          filter: blurPx > 0.1 ? `blur(${blurPx.toFixed(1)}px)` : undefined,
          transform: `translateX(${raggedX.toFixed(1)}px) scale(${scale.toFixed(3)})`,
          paddingBottom,
          maxWidth: 780,
          textTransform: 'lowercase',
        }}
      >
        {word}
      </div>
    </AbsoluteFill>
  );
};
