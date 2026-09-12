/* Two structural constraints of the timeline gutter, learned the hard way.
   These live here and not in SKILL.md: they matter to whoever EDITS this file,
   not to an agent using the skill, and the skill prompt is resent every turn.

   **Nothing in the ancestor chain of `.track-label` may have `overflow:hidden`** —
   the gutter mask rides `position:sticky` there, and an overflow ancestor makes a
   new scroll container and strands it. That rules out the usual max-height
   accordion; the reveal animates the blocks instead.
   **The panel's `pointerdown` must ignore the gutter.** It falls through to a
   scrub branch that calls `setPointerCapture` on the panel, which retargets the
   following click — a real click on a gutter control was swallowed entirely (while
   a programmatic `.click()` worked, which is what makes it confusing to diagnose)
   and the needle jumped to 0, since the gutter sits left of t=0.
*/
/* Edvid preview — interactive editing timeline.
 * IMMUTABLE app: everything per-session comes from api/state (state.json,
 * edl.json) + gen/* (waveform, thumbs) + media/* (video, captions, edit-data).
 * User adjustments are POSTed to api/save → <edit>/preview_edits.json and
 * applied by the skill (which re-renders and bumps state).
 *
 * Three interaction rules worth knowing before editing this file:
 *  - Tracks are identified by ICON only (ICON.captions/video/audio/inserts/music),
 *    painted into .tl-chip cards. LABEL_W must stay in sync with .track-label's
 *    width. The gutter masks the lanes with .track-label::before painted in
 *    --panel-bg (the panel is a solid surface for exactly this reason), pinned by
 *    native position:sticky. #gutterLine is the divider, pinned by a scroll-driven
 *    CSS timeline on `translate`. Do NOT re-drive either from a JS scroll handler
 *    or a clip-path animation — both lag a frame and the column visibly breathes
 *    while scrolling. JS only publishes --max-scroll (on zoom/resize).
 *  - Correction markers: M (or the transport button) drops an IN, the next M closes
 *    the range and opens the note editor. They ride in S.notes and ship as
 *    payload.notes on save; watch_edits.py turns each save into a chat notification.
 *  - Zoom: the slider is anchored on the needle, trackpad pinch (wheel+ctrlKey)
 *    on the pointer. Both go through applyZoom(pps, t, anchorX) — never on scroll 0.
 *  - Layout follows the SOURCE aspect: portrait clips get body.portrait (player
 *    right at full column height, transport+timeline left), landscape keeps the
 *    stacked layout. #stage keeps the split from swallowing anything below it.
 *  - Timecode uses a MONOSPACE stack: Poppins ships no tabular figures, so
 *    `font-variant-numeric: tabular-nums` silently does nothing and every digit
 *    change resized the readout, shoving the whole transport row sideways.
 *  - No glows anywhere — depth shadows are fine, coloured halos are not.
 *  - The style gate (STYLE_CATALOG → #styleSetup) stands BETWEEN the phases: when
 *    state.awaitingStyle is true it replaces the stage entirely, so the choice of
 *    editing style / caption style / edit elements cannot be skipped. It saves to
 *    <edit>/preview_style.json (never preview_edits.json — different screens,
 *    different moments, one would clobber the other).
 */
'use strict';

// ---------- dom ----------
const EMBEDDED_IN_STUDIO = new URLSearchParams(location.search).get('embedded') === '1';
document.body.classList.toggle('embedded-studio', EMBEDDED_IN_STUDIO);

const $ = (id) => document.getElementById(id);
const video = $('video');
const panel = $('timelinePanel');
const timelineEl = $('timeline');
const rulerCv = $('ruler');
const waveCv = $('wave');
const laneVideo = $('laneVideo');
const laneAudio = $('laneAudio');
const laneCaptions = $('laneCaptions');
const insertTracksEl = $('insertTracks');
const needle = $('needle');
const tooltip = $('tooltip');

// minimal solid icons (design-system consistent — no emoji)
const ICON = {
  play: '<svg viewBox="0 0 16 16"><path d="M4 2.2v11.6c0 .9 1 1.5 1.8 1L15 9.2c.8-.5.8-1.7 0-2.2L5.8 1.2C5 .7 4 1.3 4 2.2z"/></svg>',
  pause: '<svg viewBox="0 0 16 16"><rect x="3" y="2" width="3.6" height="12" rx="1"/><rect x="9.4" y="2" width="3.6" height="12" rx="1"/></svg>',
  vol: '<svg viewBox="0 0 16 16"><path d="M2 6v4h2.8L9 13.4V2.6L4.8 6H2z"/><path d="M11 5.2a3.4 3.4 0 0 1 0 5.6V9.4a2 2 0 0 0 0-2.8V5.2z"/></svg>',
  mute: '<svg viewBox="0 0 16 16"><path d="M2 6v4h2.8L9 13.4V2.6L4.8 6H2z"/><path d="M11.2 6.2l3.6 3.6m0-3.6l-3.6 3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/></svg>',
  // track identity — icons replace text labels (data-icon in index.html)
  captions: '<svg viewBox="0 0 16 16"><rect x="1" y="3" width="14" height="10" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="3.4" y="8.4" width="4.4" height="1.5" rx=".75"/><rect x="8.9" y="8.4" width="3.7" height="1.5" rx=".75"/></svg>',
  video: '<svg viewBox="0 0 16 16"><rect x="1" y="3" width="14" height="10" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M6.5 5.9v4.2c0 .4.44.64.79.42l3.3-2.1a.5.5 0 0 0 0-.85l-3.3-2.1a.5.5 0 0 0-.79.43z"/></svg>',
  audio: '<svg viewBox="0 0 16 16"><path d="M2.4 6.2v3.6h2.4l3.5 2.8V3.4L4.8 6.2H2.4z"/><path d="M10.5 5.7a3.2 3.2 0 0 1 0 4.6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M12.4 3.9a5.7 5.7 0 0 1 0 8.2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  inserts: '<svg viewBox="0 0 16 16"><rect x="1.2" y="3.2" width="13.6" height="9.6" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="5.3" cy="6.6" r="1.15"/><path d="M2.6 11.7l3-2.9a1 1 0 0 1 1.34-.05l1.84 1.58 1.5-1.24a1 1 0 0 1 1.29.02l1.72 1.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  music: '<svg viewBox="0 0 16 16"><path d="M13.1 1.9 6.6 3.5a.8.8 0 0 0-.6.78v6.06a2.25 2.25 0 1 0 1.5 2.12V6.6l5-1.22v3.5a2.25 2.25 0 1 0 1.5 2.12V2.68a.8.8 0 0 0-.9-.78z"/></svg>',
  text: '<svg viewBox="0 0 16 16"><path d="M2 2.6h12v2.5h-1.5V4.1H8.75v8.1h1.6v1.3H5.65v-1.3h1.6V4.1H3.5v1H2V2.6z"/></svg>',
  notes: '<svg viewBox="0 0 16 16"><rect x="1.9" y="1.4" width="1.6" height="13.2" rx=".8"/><path d="M5 2.7h7.6a.6.6 0 0 1 .47.97L11.36 6l1.71 2.33a.6.6 0 0 1-.47.97H5V2.7z"/></svg>',
  flag: '<svg viewBox="0 0 16 16"><rect x="1.9" y="1.4" width="1.6" height="13.2" rx=".8"/><path d="M5 2.7h7.6a.6.6 0 0 1 .47.97L11.36 6l1.71 2.33a.6.6 0 0 1-.47.97H5V2.7z"/></svg>',
};

/* ---------- style catalog (the Fase 1 → Fase 2 gate) ----------
 * The one place that knows which looks Edvid can build. It is APP-level, not
 * session-level: a new editing style or caption style is a new entry here plus
 * its implementation in the track reference — never a per-session UI.
 * The user's pick ships to <edit>/preview_style.json; the skill reads it once,
 * at the gate, and builds Fase 2 from it.
 */
const STYLE_CATALOG = {
  edits: [
    {
      // First on purpose: defaultStyle() takes edits[0], so this is also the
      // default for every new project — a clean full-frame cut, with inserts as
      // something the user opts into.
      id: 'limpa',
      name: 'Limpa',
      mock: `<svg viewBox="0 0 66 118" xmlns="http://www.w3.org/2000/svg">
        <rect x=".5" y=".5" width="65" height="117" rx="7" fill="#0b0e13" stroke="rgba(255,255,255,.12)"/>
        <rect x="3" y="3" width="60" height="112" rx="5" fill="rgba(255,255,255,.05)"/>
        <circle cx="33" cy="48" r="13" fill="rgba(255,255,255,.16)"/>
        <path d="M12 115a21 21 0 0142 0z" fill="rgba(255,255,255,.16)"/>
        <rect x="14" y="14" width="38" height="4.4" rx="2.2" fill="rgba(255,255,255,.5)"/>
        <rect x="20" y="21.5" width="26" height="4.4" rx="2.2" fill="rgba(255,255,255,.3)"/>
        <rect x="12" y="74" width="42" height="11" rx="5.5" fill="#0b0e13" stroke="rgba(9,181,183,.65)"/>
        <rect x="16" y="78.5" width="12" height="2.4" rx="1.2" fill="rgba(9,181,183,.9)"/>
        <rect x="30" y="78.5" width="8" height="2.4" rx="1.2" fill="rgba(255,255,255,.5)"/>
        <rect x="40" y="78.5" width="10" height="2.4" rx="1.2" fill="rgba(255,255,255,.5)"/>
      </svg>`,
    },
    {
      id: 'split',
      name: 'Tela dividida',
      mock: `<svg viewBox="0 0 66 118" xmlns="http://www.w3.org/2000/svg">
        <rect x=".5" y=".5" width="65" height="117" rx="7" fill="#0b0e13" stroke="rgba(255,255,255,.12)"/>
        <rect x="3" y="3" width="60" height="36" rx="5" fill="rgba(255,119,19,.16)"/>
        <circle cx="17" cy="15" r="3.6" fill="rgba(255,119,19,.6)"/>
        <path d="M6 36l11-11a2 2 0 013 0l7 7 5-4a2 2 0 013 0l11 8" fill="none" stroke="rgba(255,119,19,.6)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M3 40.5h60" stroke="rgba(255,255,255,.5)" stroke-width="1.2"/>
        <rect x="3" y="42" width="60" height="73" rx="5" fill="rgba(255,255,255,.05)"/>
        <circle cx="33" cy="70" r="12" fill="rgba(255,255,255,.16)"/>
        <path d="M15 115a18 18 0 0136 0z" fill="rgba(255,255,255,.16)"/>
        <rect x="12" y="35" width="42" height="11" rx="5.5" fill="#0b0e13" stroke="rgba(9,181,183,.65)"/>
        <rect x="16" y="39.5" width="12" height="2.4" rx="1.2" fill="rgba(9,181,183,.9)"/>
        <rect x="30" y="39.5" width="8" height="2.4" rx="1.2" fill="rgba(255,255,255,.5)"/>
        <rect x="40" y="39.5" width="10" height="2.4" rx="1.2" fill="rgba(255,255,255,.5)"/>
      </svg>`,
    },
    {
      id: 'split2',
      name: 'Tela dividida 2',
      mock: `<svg viewBox="0 0 66 118" xmlns="http://www.w3.org/2000/svg">
        <rect x=".5" y=".5" width="65" height="117" rx="7" fill="#0b0e13" stroke="rgba(255,255,255,.12)"/>
        <rect x="3" y="3" width="60" height="65" rx="5" fill="rgba(255,255,255,.05)"/>
        <circle cx="33" cy="24" r="11" fill="rgba(255,255,255,.16)"/>
        <path d="M16 68a17 17 0 0134 0z" fill="rgba(255,255,255,.16)"/>
        <path d="M3 69.5h60" stroke="rgba(255,255,255,.5)" stroke-width="1.2"/>
        <rect x="3" y="71" width="60" height="44" rx="5" fill="rgba(255,119,19,.16)"/>
        <circle cx="17" cy="83" r="3.6" fill="rgba(255,119,19,.6)"/>
        <path d="M6 111l11-11a2 2 0 013 0l7 7 5-4a2 2 0 013 0l11 8" fill="none" stroke="rgba(255,119,19,.6)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <rect x="12" y="58" width="42" height="11" rx="5.5" fill="#0b0e13" stroke="rgba(9,181,183,.65)"/>
        <rect x="16" y="62.5" width="12" height="2.4" rx="1.2" fill="rgba(9,181,183,.9)"/>
        <rect x="30" y="62.5" width="8" height="2.4" rx="1.2" fill="rgba(255,255,255,.5)"/>
        <rect x="40" y="62.5" width="10" height="2.4" rx="1.2" fill="rgba(255,255,255,.5)"/>
      </svg>`,
    },
  ],
  // No names on purpose: the sample headline IS the label. Ids and geometry
  // mirror HL_STYLES in the template's Main.tsx — keep the two in step.
  headlines: [
    {id: 'outline', name: 'Contorno', hl: 'outline'},
    {id: 'card', name: 'Cartão', hl: 'card'},
    {id: 'realce', name: 'Realce', hl: 'realce'},
    {id: 'misto', name: 'Misto', hl: 'misto'},
    // A aparência vem dos controles abaixo do grid, não de um preset: o
    // template ganhou um estilo `personalizada` que lê cor e peso do
    // edit-data.json, para continuar universal em vez de ser editado por vídeo.
    {id: 'personalizada', name: 'Personalizada', hl: 'personalizada'},
    // Last on purpose: defaultStyle() takes headlines[0]. `hlbox` only so the
    // card matches the height of its siblings in this row.
    {id: 'none', name: 'Nenhum', none: true, hlbox: true},
  ],
  // The typeface for the headline picked above — an independent axis, so
  // every card here renders the SAME chosen headline style, just in a
  // different font (and every card above re-renders in the currently chosen
  // font — see the `o.font` branch in radios()). Unlike `headlines`, these DO
  // get a name label: the shapes are identical, so only the type tells them
  // apart. Ids mirror HL_FONTS in the template's Main.tsx.
  headlineFonts: [
    {id: 'poppins', name: 'Impacto', font: 'poppins'},
    {id: 'bebas', name: 'Condensada', font: 'bebas'},
    {id: 'anton', name: 'Cartaz', font: 'anton'},
    {id: 'playfair', name: 'Editorial', font: 'playfair'},
  ],
  captions: [
    {id: 'karaoke', name: 'Karaokê', demo: 'karaoke'},
    {id: 'stacked', name: 'Empilhado', demo: 'stacked'},
    {id: 'scatter', name: 'Disperso', demo: 'scatter'},
    {id: 'simples', name: 'Simples', stat: 'simples'},
    {id: 'serifada', name: 'Serifada', stat: 'serifada'},
    {id: 'classica', name: 'Clássica', stat: 'classica'},
    {id: 'impacto', name: 'Impacto', stat: 'impacto'},
    {id: 'editorial', name: 'Editorial', stat: 'editorial'},
    {id: 'premium', name: 'Premium', stat: 'premium'},
    {id: 'none', name: 'Nenhum', none: true},
  ],
  elements: [
    {
      id: 'tracking',
      name: 'Movimento de tracking',
      def: false,
      icon: '<svg viewBox="0 0 16 16"><path d="M2 5.6V3.4A1.4 1.4 0 013.4 2h2.2M10.4 2h2.2A1.4 1.4 0 0114 3.4v2.2M14 10.4v2.2a1.4 1.4 0 01-1.4 1.4h-2.2M5.6 14H3.4A1.4 1.4 0 012 12.6v-2.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="8" r="2.1"/></svg>',
    },
    // `always: true` = FIXO, não é escolha (decisão do usuário, 2026-08-16:
    // "quero que os flash e zoom deixem de ser opção e fiquem fixo em todos os
    // vídeos após o corte e quando for para fase 2 eles já estejam"). Os três
    // aparecem como chips travados — o usuário continua VENDO o que a edição
    // aplica, mas não clica, o save sempre manda `true`, e a Fase 2 já nasce
    // com eles no edit-data.json (camera.zooms + um `transitions[]` por janela
    // de split). Não devolver para o conjunto clicável.
    {
      id: 'zoomAuto',
      name: 'Automação de zoom in',
      def: true,
      always: true,
      icon: '<svg viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10.6 10.6L14 14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" fill="none"/><path d="M7 5.1v3.8M5.1 7h3.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" fill="none"/></svg>',
    },
    {
      id: 'zoomCuts',
      name: 'Zoom in e out nos cortes',
      def: true,
      always: true,
      icon: '<svg viewBox="0 0 16 16"><rect x="1.2" y="3.4" width="6" height="9.2" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="9.6" y="1.9" width="5.2" height="12.2" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8.4 8h.7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    },
    {
      id: 'flashCut',
      name: 'Flash na transição',
      def: true,
      always: true,
      icon: '<svg viewBox="0 0 16 16"><path d="M3 13.2L13 3.2" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" fill="none"/><path d="M6.6 14L9.4 11.2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none" opacity=".55"/><path d="M6.6 4.8L3.8 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none" opacity=".55"/></svg>',
    },
    {
      id: 'musicAI',
      name: 'Trilha sonora com IA',
      // OFF by default, unlike the other two defaults-on. Those are free; this
      // is the only element in the catalog that needs an account. Pre-ticked, it
      // walked every first-time user into a signup they never asked for, at the
      // exact moment they expected a finished video. The checkbox is still right
      // there and says what it does — that is discovery enough.
      def: false,
      icon: '<svg viewBox="0 0 16 16"><path d="M12.6 1.6L6.9 3a.7.7 0 00-.55.68v5.6a2 2 0 101.35 1.9V5.9l4.4-1.05v2.9a2 2 0 101.35 1.9V2.3a.7.7 0 00-.85-.7z"/><path d="M2.4 2.2l.6 1.5 1.5.6-1.5.6-.6 1.5-.6-1.5-1.5-.6 1.5-.6z"/></svg>',
    },
    {
      id: 'aiVideo',
      name: 'Gerar vídeos por IA',
      // OFF by default, same reasoning as musicAI — this calls a paid
      // generation API and shouldn't fire without the user asking (2026-08-16
      // request). ON: B-roll matched to what's being said gets AI-generated
      // VIDEO by default (user preference: "prefiro vídeos") — see
      // "AI-generated B-roll" in references/shortform.md for placement rules
      // (single-screen: brief cutaway insert; split-screen: fills the image
      // band with real motion now, never over the original video) and for how
      // this element interacts with `aiImage` below when both are on.
      def: false,
      icon: '<svg viewBox="0 0 16 16"><rect x="1.3" y="3" width="13.4" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M6.5 6.2l3.6 2.3-3.6 2.3z" fill="currentColor"/><path d="M1.6 5.2h12.8" stroke="currentColor" stroke-width="1" opacity=".4"/></svg>',
    },
    {
      id: 'aiImage',
      name: 'Gerar imagens por IA',
      // Separate from aiVideo (2026-08-16, user request) — a still-image-only
      // generation element. OFF by default, same paid-API reasoning as its
      // sibling. If BOTH this and aiVideo are on, video is still the default
      // choice per moment — this one only wins when a specific moment reads
      // better as a still (judged per-moment, not a mechanical alternation).
      // See "AI-generated B-roll" in references/shortform.md.
      def: false,
      icon: '<svg viewBox="0 0 16 16"><rect x="1.3" y="2.4" width="13.4" height="11.2" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="5" cy="6.1" r="1.4"/><path d="M2.3 12.2l3.6-4 2.6 2.9 1.8-2 3.4 3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    },
  ],
};

/* Image adjustment sliders — Phase-1 grade controls surfaced in the Estilo tab
 * (2026-08-15, per user request). These apply as a per-segment ffmpeg grade at
 * EXTRACTION time (Hard Rule 7), same as the LOG/Rec.709 grade decision — they
 * are NOT a Fase-2 overlay, so picking one triggers a Fase-1 re-render, not a
 * Fase-2 one. `range` is [min, max]; `def` is both the reset value and what an
 * untouched slider ships as (0 = no change, except sharpness/skinSmooth whose
 * neutral is also 0 but whose range is one-sided).
 */
const IMAGE_ADJUSTMENTS = [
  { id: 'brightness', name: 'Brilho', min: -50, max: 50, def: 0 },
  { id: 'contrast', name: 'Contraste', min: -50, max: 50, def: 0 },
  { id: 'saturation', name: 'Saturação', min: -50, max: 50, def: 0 },
  { id: 'sharpness', name: 'Nitidez', min: 0, max: 100, def: 0 },
  { id: 'skinSmooth', name: 'Suavização de pele', min: 0, max: 100, def: 0 },
  { id: 'skinWarmth', name: 'Tom de pele (frio ↔ quente)', min: -50, max: 50, def: 0 },
  { id: 'shadows', name: 'Sombras', min: -50, max: 50, def: 0 },
  { id: 'highlights', name: 'Realces / iluminação', min: -50, max: 50, def: 0 },
];

/* LUT filter picker (2026-08-15, per user request — DaVinci/CapCut/Premiere-
 * style LUT grid). `file` is the .cube served from the shared
 * assets/preview/luts/ folder (fetched by LUT_ENGINE and applied via a REAL
 * WebGL 3D-texture lookup — not a CSS approximation like the sliders above,
 * since this uses the exact same table the Fase-1 render applies via
 * ffmpeg's `lut3d` filter). `id` must match `lut_id()` in
 * helpers/lut_thumbs.py (non alnum/_/- → `_`) — that script writes
 * `.preview_cache/luts/<id>.jpg`, which is what `thumb` points at below.
 */
const LUT_CATALOG = [
  { id: 'none', name: 'Nenhum', file: null },
  // Baked from PRESETS["premium_editorial"] (helpers/grade.py) via
  // helpers/bake_lut.py — the pointwise color part only (eq/colorbalance/
  // colortemperature/curves); unsharp+grain aren't pointwise so they can't
  // live in a LUT and are left out (2026-08-16, per user request: the
  // "premium editorial" tonality is now an opt-in LUT here, not something
  // applied automatically — video stays at its ORIGINAL tonality unless this
  // is picked). Verified against the direct filter chain: PSNR ~48.9dB
  // (indistinguishable, the gap is only 33-point grid interpolation).
  { id: 'premium', name: 'Premium', file: 'premium.cube' },
  { id: 'cinema_blue_hour', name: 'Cinema Blue Hour', file: 'cinema_blue_hour.cube' },
  { id: 'classic_bw', name: 'Classic B&W', file: 'classic_bw.cube' },
  { id: 'clean_aesthetic', name: 'Clean Aesthetic', file: 'clean_aesthetic.cube' },
  { id: 'cool_blue_steel', name: 'Cool Blue Steel', file: 'cool_blue_steel.cube' },
  { id: 'cozy_amber_indoor', name: 'Cozy Amber Indoor', file: 'cozy_amber_indoor.cube' },
  { id: 'faded_film', name: 'Faded Film', file: 'faded_film.cube' },
  { id: 'golden_hour_punch', name: 'Golden Hour Punch', file: 'golden_hour_punch.cube' },
  { id: 'high_contrast', name: 'High Contrast', file: 'high_contrast.cube' },
  { id: 'misty_film_teal', name: 'Misty Film Teal', file: 'misty_film_teal.cube' },
  { id: 'moody_dark', name: 'Moody Dark', file: 'moody_dark.cube' },
  { id: 'neutro_clean', name: 'Neutro Clean', file: 'neutro_clean.cube' },
  { id: 'teal_orange', name: 'Teal & Orange', file: 'teal_orange.cube' },
  { id: 'vibrant_pop', name: 'Vibrant Pop', file: 'vibrant_pop.cube' },
  { id: 'warm_allpurpose', name: 'Warm All-Purpose', file: 'warm_allpurpose.cube' },
  { id: 'warm_golden_hour', name: 'Warm Golden Hour', file: 'warm_golden_hour.cube' },
  { id: 'FGCineBasic', name: 'FG Cine Basic', file: 'FGCineBasic.cube' },
  { id: 'FGCineBright', name: 'FG Cine Bright', file: 'FGCineBright.cube' },
  { id: 'FGCineCold', name: 'FG Cine Cold', file: 'FGCineCold.cube' },
  { id: 'FGCineDrama', name: 'FG Cine Drama', file: 'FGCineDrama.cube' },
  { id: 'FGCineTealOrange1', name: 'FG Cine Teal & Orange 1', file: 'FGCineTealOrange1.cube' },
  { id: 'FGCineTealOrange2', name: 'FG Cine Teal & Orange 2', file: 'FGCineTealOrange2.cube' },
  { id: 'FGCineVibrant', name: 'FG Cine Vibrant', file: 'FGCineVibrant.cube' },
  { id: 'FGCineWarm', name: 'FG Cine Warm', file: 'FGCineWarm.cube' },
  // Second FG pack variant (different .cube data, confirmed by hash — not a
  // dupe) — " B" distinguishes it from the set right above.
  { id: 'FG_CineBasic', name: 'FG Cine Basic B', file: 'FG_CineBasic.cube' },
  { id: 'FG_CineBright', name: 'FG Cine Bright B', file: 'FG_CineBright.cube' },
  { id: 'FG_CineCold', name: 'FG Cine Cold B', file: 'FG_CineCold.cube' },
  { id: 'FG_CineDrama', name: 'FG Cine Drama B', file: 'FG_CineDrama.cube' },
  { id: 'FG_CineTeal_Orange1', name: 'FG Cine Teal & Orange 1 B', file: 'FG_CineTeal&Orange1.cube' },
  { id: 'FG_CineTeal_Orange2', name: 'FG Cine Teal & Orange 2 B', file: 'FG_CineTeal&Orange2.cube' },
  { id: 'FG_CineVibrant', name: 'FG Cine Vibrant B', file: 'FG_CineVibrant.cube' },
  { id: 'FG_CineWarm', name: 'FG Cine Warm B', file: 'FG_CineWarm.cube' },
  // Recriados de uma referência que o usuário mandou (2026-08-17): sete filtros
  // do CapCut, que não existem como arquivo. O vídeo mostra a MESMA pessoa, na
  // mesma sala e na mesma luz, com um filtro por trecho — então a diferença
  // entre trechos é o filtro, e foi daí que estes .cube saíram (casamento de
  // histograma por canal + saturação medida, script em build_luts.py).
  // SOMA ao acervo: nenhum LUT antigo saiu daqui.
  // "Bokeh" é o único parcial — o filtro original também desfoca o fundo, e
  // desfoque não cabe num LUT; aqui está só a parte de cor dele.
  { id: 'cc_4k', name: 'CC 4K (nitidez)', file: 'cc_4k.cube' },
  { id: 'cc_qualidade2', name: 'CC Qualidade II', file: 'cc_qualidade2.cube' },
  { id: 'cc_bokeh', name: 'CC Bokeh (só cor)', file: 'cc_bokeh.cube' },
  { id: 'cc_laranja_azul', name: 'CC Laranja & Azul', file: 'cc_laranja_azul.cube' },
  { id: 'cc_baile', name: 'CC Baile de Formatura', file: 'cc_baile.cube' },
  { id: 'cc_ensolarado', name: 'CC Ensolarado', file: 'cc_ensolarado.cube' },
  { id: 'cc_cafe_escuro', name: 'CC Café Escuro', file: 'cc_cafe_escuro.cube' },
];

/* ---------- caption previews: the template's animation, not an impression ----
 * Every number here is lifted from the render (Main.tsx Karaoke/Word and
 * StackedCaptions.tsx STACK_MIXED) and scaled by boxWidth/1080, so the preview
 * shows the real proportions, the real faces and the real motion. If the
 * template's caption look changes, change it HERE too — a preview that lies
 * about the style is worse than no preview.
 */
// The "Nenhum" preview. Deliberately not an empty box: an empty card reads as
// "still loading" next to five that render real type. A struck-through frame
// reads as a choice.
const NONE_MARK = '<svg viewBox="0 0 64 34" style="width:64px;height:34px">'
  + '<rect x="1" y="1" width="62" height="32" rx="5" fill="none" '
  + 'stroke="rgba(255,255,255,.22)" stroke-width="1.5" stroke-dasharray="4 3"/>'
  + '<path d="M14 24L50 10" stroke="rgba(255,255,255,.28)" stroke-width="1.5" '
  + 'stroke-linecap="round"/></svg>';

const CAP_TEXT = 'É assim que sua legenda irá aparecer';
const FPS_REF = 30; // the template's reference fps for frame-based timings

// cubic-bezier solver — the stacked style eases on bezier(.16,1,.3,1)
function bez(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const fx = (t) => ((ax * t + bx) * t + cx) * t;
  const dfx = (t) => (3 * ax * t + 2 * bx) * t + cx;
  return (x) => {
    let t = x;
    for (let i = 0; i < 6; i++) {
      const e = fx(t) - x;
      if (Math.abs(e) < 1e-4) break;
      const d = dfx(t);
      if (Math.abs(d) < 1e-6) break;
      t -= e / d;
    }
    return ((ay * t + by) * t + cy) * t;
  };
}
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3); // Easing.out(Easing.cubic)
const easeStack = bez(0.16, 1, 0.3, 1);
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

let capAnims = []; // step(nowSeconds) per visible caption demo

// Karaoke: lines of ≤3 words (captions.maxWords), Poppins 900 white, each word
// rises 34px and fades in over 7 frames; the line is replaced by the next one.
function buildKaraokeDemo(host) {
  const s = host.clientWidth / 1080;
  host.innerHTML = '';
  const wrap = el('div', 'cap-demo', host);
  const words = CAP_TEXT.split(' ');
  const lines = [];
  for (let i = 0; i < words.length; i += 3) lines.push(words.slice(i, i + 3));

  const STEP = 0.26, ENTER = 7 / FPS_REF, HOLD = 0.6;
  const rise = 34 * s;
  const built = [];
  let t = 0;
  for (const ln of lines) {
    const box = el('div', 'kar-line', wrap);
    box.style.fontSize = `${76 * s}px`;
    const spans = ln.map((w) => {
      const sp = el('span', '', box);
      sp.textContent = w;
      sp.style.marginRight = `${18 * s}px`;
      return sp;
    });
    const start = t;
    t = start + (ln.length - 1) * STEP + ENTER + HOLD;
    built.push({ box, spans, start, end: t });
  }
  const cycle = t + 0.3;

  return (now) => {
    const p = now % cycle;
    for (const L of built) {
      const on = p >= L.start && p < L.end;
      L.box.style.display = on ? '' : 'none';
      if (!on) continue;
      L.spans.forEach((sp, j) => {
        const e = easeOutCubic(clamp01((p - (L.start + j * STEP)) / ENTER));
        sp.style.opacity = e;
        sp.style.translate = `0px ${((1 - e) * rise).toFixed(2)}px`;
      });
    }
  };
}

// Stacked: one cue, lines cycling the STACK_MIXED styles (bold-italic gradient →
// regular small → Playfair italic orange). Words rise 46px with a blur that
// resolves; the cue leaves with the blur_up exit.
const STK_LINES = [
  { words: ['É', 'assim'], style: 0 },
  { words: ['que', 'sua', 'legenda'], style: 1 },
  { words: ['irá', 'aparecer'], style: 2 },
];
function buildStackedDemo(host) {
  const s = host.clientWidth / 1080;
  host.innerHTML = '';
  const wrap = el('div', 'cap-demo', host);
  const cue = el('div', 'stk-cue', wrap);

  const STEP = 0.2, ENTER = 8 / FPS_REF, HOLD = 0.8, EXIT = 7 / FPS_REF;
  const rise = 46 * s, blurIn = 5 * s, upY = 55 * s, cueBlur = 14 * s;
  const shadow = `drop-shadow(0 ${(5 * s).toFixed(2)}px ${(9 * s).toFixed(2)}px rgba(0,0,0,0.5))`;
  const all = [];
  let idx = 0;
  for (const L of STK_LINES) {
    const row = el('div', 'stk-line', cue);
    let size = 86;
    if (L.style === 1) size = Math.round(size * 0.72);
    if (L.style === 2) size = Math.round(size * 0.95);
    row.style.fontSize = `${size * s}px`;
    L.words.forEach((w, i) => {
      // the face/gradient belongs to the WORD, like the template's `...ls` spread
      const sp = el('span', `s${L.style}`, row);
      sp.textContent = w + (i < L.words.length - 1 ? ' ' : '');
      all.push({ sp, start: idx * STEP });
      idx++;
    });
  }
  const exitStart = (idx - 1) * STEP + ENTER + HOLD;
  // short gap after the exit: side by side with the karaoke card, a preview that
  // sits blank for half a second reads as broken rather than as a cue boundary
  const cycle = exitStart + EXIT + 0.15;

  return (now) => {
    const p = now % cycle;
    const ex = clamp01((p - exitStart) / EXIT);
    cue.style.opacity = 1 - ex;
    cue.style.translate = `0px ${(-upY * ex).toFixed(2)}px`;
    cue.style.filter = ex > 0.02 ? `blur(${(cueBlur * ex).toFixed(2)}px)` : '';
    for (const w of all) {
      const e = easeStack(clamp01((p - w.start) / ENTER));
      const eb = (1 - e) * blurIn;
      w.sp.style.opacity = e;
      w.sp.style.translate = `0px ${((1 - e) * rise).toFixed(2)}px`;
      w.sp.style.filter = `${eb > 0.06 ? `blur(${eb.toFixed(2)}px) ` : ''}${shadow}`;
    }
  };
}

/* ---------- headline previews: the template's own hook styles ----------------
 * Same contract as the caption demos — these render what `HookInner` renders,
 * scaled from 1080-wide. The two-line break and the size fit run the SAME
 * algorithm as the template (balance by measured width, then fit to safeW), so
 * the preview shows the real break at the real size, not an approximation.
 * HL_STYLES exists on both sides; change one, change the other.
 */
const HEADLINE_TEXT = 'É assim que vai ficar a sua headline';
const HL_MIN = 40;
const HL_STYLES = {
  outline: { weights: [800, 800], cap: 92, safeW: 900, lh: 1.02 },
  card: { weights: [900, 900], cap: 82, safeW: 820, lh: 1.06 },
  realce: { weights: [900, 900], cap: 86, safeW: 830, lh: 1.04 },
  misto: { weights: [400, 900], cap: 98, safeW: 900, lh: 0.98 },
  // espelha a entrada nova do template; os pesos reais vêm de headlineCustom
  personalizada: { weights: [800, 900], cap: 92, safeW: 900, lh: 1.02 },
};
// Headline typeface choices — mirrors HL_FONTS in the template's Main.tsx.
// Bebas Neue / Anton ship weight 400 only; the CSS fontWeight the style asks
// for (800/900) just has no matching cut to switch to, same non-issue noted
// in Main.tsx's HL_FONTS comment.
const HL_FONT_FAMILIES = {
  poppins: "'Poppins',sans-serif",
  bebas: "'Bebas Neue',sans-serif",
  anton: "'Anton',sans-serif",
  playfair: "'Playfair Display',serif",
};
const HL_FONT_ITALIC = { playfair: true };

// Measured in RENDER units (1080-wide), scaled to the box only at the end — the
// template's letterSpacing is -1px at 1080, which is NOT proportional once the
// preview shrinks it, so measuring in preview px would break the fit.
let hlMeter = null;
function measureType(text, size, weight, family, tracking) {
  if (!text) return 0;
  if (!hlMeter) {
    hlMeter = document.createElement('span');
    hlMeter.style.cssText =
      'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:pre;';
    document.body.appendChild(hlMeter);
  }
  hlMeter.style.fontFamily = family || "'Poppins',sans-serif";
  hlMeter.style.letterSpacing = `${tracking == null ? -1 : tracking}px`;
  hlMeter.style.fontSize = `${size}px`;
  hlMeter.style.fontWeight = String(weight);
  hlMeter.textContent = text;
  return hlMeter.offsetWidth;
}
const hlWidth = (text, size, weight, family) => measureType(text, size, weight, family);

// Balance by MEASURED width, not word count: "É assim que vai" and "ficar a sua
// headline" are 4 and 3 words but nearly the same width — counting words breaks
// the line in the wrong place.
function hlTwoLines(text, weights, family) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length < 2) return [words[0] || '', ''];
  let best = [words[0], words.slice(1).join(' ')];
  let bestDiff = Infinity;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(' ');
    const b = words.slice(i).join(' ');
    const d = Math.abs(hlWidth(a, 100, weights[0], family) - hlWidth(b, 100, weights[1], family));
    if (d < bestDiff) { bestDiff = d; best = [a, b]; }
  }
  return best;
}

function hlFit(lines, S, family) {
  const widest = (size) =>
    Math.max(hlWidth(lines[0], size, S.weights[0], family), hlWidth(lines[1], size, S.weights[1], family));
  let size = Math.floor((S.safeW / Math.max(1, widest(100))) * 100);
  size = Math.floor((S.safeW / Math.max(1, widest(size))) * size);
  return Math.max(HL_MIN, Math.min(size, S.cap));
}

// `custom` chega por PARÂMETRO: dentro desta função `S` é o estilo da headline,
// não o estado do app — ler S.style aqui seria ReferenceError na zona morta do
// const abaixo, e o cartão inteiro deixaria de desenhar.
function buildHeadlineDemo(host, styleId, fontId, text = HEADLINE_TEXT, custom = null) {
  const s = host.clientWidth / 1080;
  const base = HL_STYLES[styleId];
  const S = custom ? {...base, weights: [custom.weight1, custom.weight2], cap: custom.maxFontPx} : base;
  const family = HL_FONT_FAMILIES[fontId] || HL_FONT_FAMILIES.poppins;
  host.innerHTML = '';
  const wrap = el('div', 'cap-demo', host);
  const raw = styleId === 'card' ? text.toUpperCase() : text;
  const lines = hlTwoLines(raw, S.weights, family);
  const size = hlFit(lines, S, family) * s;
  const box = el('div', `hl-demo hl-${styleId}`, wrap);
  box.style.fontFamily = family;
  box.style.fontStyle = HL_FONT_ITALIC[fontId] ? 'italic' : 'normal';
  box.style.lineHeight = String(S.lh);
  box.style.letterSpacing = `${-1 * s}px`;

  if (styleId === 'realce') {
    for (const l of lines) {
      if (!l) continue;
      const b = el('div', 'hl-block', box);
      b.style.fontSize = `${size}px`;
      b.style.borderRadius = `${12 * s}px`;
      b.textContent = l;
    }
    return;
  }
  if (styleId === 'card') {
    box.style.borderRadius = `${24 * s}px`;
    box.style.padding = `${28 * s}px ${46 * s}px`;
  }
  if (styleId === 'outline') {
    box.style.webkitTextStroke = `${12 * s}px #000`;
  }
  lines.forEach((l, i) => {
    if (!l) return;
    const d = el('div', '', box);
    d.style.fontSize = `${size}px`;
    d.style.fontWeight = String(S.weights[i]);
    // var(), not a literal — an inline colour would beat the accent variable and
    // this preview would keep painting orange while the others followed the pick
    if (styleId === 'misto') d.style.color = i === 1 ? 'var(--hl-accent)' : '#fff';
    if (custom) d.style.color = i === 1 ? custom.accentColor : custom.color;
    d.textContent = l;
  });
}

// Scatter ("disperso"): serif, lowercase, one word at a time, off-white with a
// slight darkening toward the baseline. Ordinary words FADE only — no movement;
// the one highlighted word resolves out of a blur and dissolves back into it.
// Mirrors ScatterCaptions.tsx: same line rules, same SPREAD, same hash.
const SCAT = { base: 72, hiScale: 1.62, gap: 12, spread: 0.45, safeW: 820 };
const scatHash = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

function buildScatterDemo(host) {
  const s = host.clientWidth / 1080;
  host.innerHTML = '';
  const wrap = el('div', 'cap-demo', host);
  const cue = el('div', 'scat-cue', wrap);

  const words = CAP_TEXT.toLowerCase().split(' ');
  // highlight = longest word of the cue, and only if it carries weight (>6)
  let hiIdx = -1, hiLen = 6;
  words.forEach((w, i) => { if (w.length > hiLen) { hiLen = w.length; hiIdx = i; } });

  // ragged lines of 3–4 words; the highlighted word takes a line of its own
  const lines = [];
  let line = [];
  words.forEach((w, i) => {
    if (i === hiIdx) {
      if (line.length) lines.push(line);
      lines.push([{ w, i, hi: true }]);
      line = [];
      return;
    }
    line.push({ w, i, hi: false });
    if (line.length >= (scatHash(31 + i) > 0.5 ? 4 : 3)) { lines.push(line); line = []; }
  });
  if (line.length) lines.push(line);

  const STEP = 0.22, ENTER = 7 / FPS_REF, HI_ENTER = 10 / FPS_REF, HOLD = 0.9, EXIT = 8 / FPS_REF;
  const all = [];
  lines.forEach((ln, li) => {
    const row = el('div', 'scat-line', cue);
    row.style.gap = `${SCAT.gap * s}px`;
    let w = 0;
    for (const it of ln) {
      const sp = el('span', it.hi ? 'hi' : '', row);
      sp.textContent = it.w;
      sp.style.fontSize = `${(it.hi ? SCAT.base * SCAT.hiScale : SCAT.base) * s}px`;
      all.push({ sp, start: it.i * STEP, hi: it.hi });
      w += sp.offsetWidth + SCAT.gap * s;
    }
    const room = Math.max(0, (SCAT.safeW * s - w) / 2) * SCAT.spread;
    row.style.translate = `${((scatHash(17 + li * 5 + 3) * 2 - 1) * room).toFixed(1)}px 0px`;
  });

  const exitStart = (words.length - 1) * STEP + ENTER + HOLD;
  const cycle = exitStart + EXIT + 0.35;
  const blurIn = 26 * s, blurOut = 30 * s;

  return (now) => {
    const p = now % cycle;
    const out = clamp01((p - exitStart) / EXIT);
    for (const w of all) {
      const t = easeOutCubic(clamp01((p - w.start) / (w.hi ? HI_ENTER : ENTER)));
      w.sp.style.opacity = t * (1 - out);
      if (w.hi) {
        const b = (1 - t) * blurIn + out * blurOut;
        w.sp.style.filter = b > 0.1 ? `blur(${b.toFixed(2)}px)` : '';
      }
    }
  };
}

/* ---------- the five STATIC caption styles -----------------------------------
 * No animation, so no entry in capAnims — built once and left alone. Mirrors
 * SIMPLE_VARIANTS in SimpleCaptions.tsx, including the rule that matters most:
 * lines are grouped by MEASURED WIDTH, capped at maxWords. That is why a long
 * word ends up alone and short ones ride together. `uppercase` measures AND
 * renders uppercase (see wOf) — a CSS-only transform would size the line
 * break budget against the shorter mixed-case text and then paint it wider.
 */
const STATIC_VARIANTS = {
  simples: {family: "'Poppins',sans-serif", weight: 600, size: 82, maxWords: 3, lines: 1, sx: 0.9, sy: 0.9, tracking: -3, maxW: 860},
  serifada: {family: "'Libre Baskerville',serif", weight: 700, size: 84, maxWords: 3, lines: 1, sx: 1, sy: 1, tracking: -1, maxW: 860},
  classica: {family: "'Inter',sans-serif", weight: 500, size: 52, maxWords: 14, lines: 2, sx: 1, sy: 1, tracking: 0, maxW: 840},
  impacto: {family: "'Anton',sans-serif", weight: 400, size: 84, maxWords: 2, lines: 1, sx: 0.94, sy: 1, tracking: 1, maxW: 860, uppercase: true},
  editorial: {family: "'Playfair Display',serif", weight: 900, size: 66, maxWords: 5, lines: 1, sx: 1, sy: 1, tracking: -1, maxW: 860, italic: true},
  // True white (not the shared off-white #f4f1e9) — buildStaticDemo doesn't
  // read a per-variant color today (every other style shares the CSS
  // #f4f1e9), so this one card gets its color forced after the loop below.
  premium: {family: "'Poppins',sans-serif", weight: 800, size: 76, maxWords: 3, lines: 1, sx: 1, sy: 1, tracking: -1, maxW: 820, color: '#ffffff'},
};
const ORPHAN_PT = /^(o|a|os|as|e|é|de|do|da|em|no|na|um|uma|que|se|ao|à|por|com)$/i;

function buildStaticDemo(host, id) {
  const V = STATIC_VARIANTS[id];
  const s = host.clientWidth / 1080;
  host.innerHTML = '';
  const wrap = el('div', 'cap-demo', host);
  const words = CAP_TEXT.split(' ');
  const wOf = (ws) => measureType((V.uppercase ? ws.map((w) => w.toUpperCase()) : ws).join(' '), V.size, V.weight, V.family, V.tracking) * V.sx;

  // the WHOLE sentence, cut into cues exactly as the render would
  const cues = [];
  let cur = [];
  for (const w of words) {
    const trial = [...cur, w];
    if (cur.length && (trial.length > V.maxWords || wOf(trial) > V.maxW * V.lines)) {
      cues.push(cur);
      cur = [w];
    } else {
      cur = trial;
    }
  }
  if (cur.length) cues.push(cur);

  const boxes = cues.map((cue) => {
    let lines = [cue];
    if (V.lines === 2 && cue.length > 1) {
      let best = 1, bestScore = Infinity;
      for (let i = 1; i < cue.length; i++) {
        const score = Math.abs(wOf(cue.slice(0, i)) - wOf(cue.slice(i))) + (ORPHAN_PT.test(cue[i - 1]) ? 200 : 0);
        if (score < bestScore) { bestScore = score; best = i; }
      }
      lines = [cue.slice(0, best), cue.slice(best)];
    }
    const box = el('div', 'stat-demo', wrap);
    box.style.fontFamily = V.family;
    box.style.fontWeight = String(V.weight);
    box.style.fontStyle = V.italic ? 'italic' : 'normal';
    box.style.textTransform = V.uppercase ? 'uppercase' : '';
    box.style.fontSize = `${V.size * s}px`;
    box.style.letterSpacing = `${V.tracking * s}px`;
    box.style.transform = V.sx === 1 && V.sy === 1 ? '' : `scale(${V.sx}, ${V.sy})`;
    if (V.color) box.style.color = V.color;
    for (const ln of lines) el('div', '', box).textContent = ln.join(' ');
    return box;
  });

  // A style with no animation still has a RHYTHM — the cues replacing each other
  // is what the viewer sees. So the card plays the whole sentence, cue by cue,
  // on hard cuts. A single-cue style (the two-line "classica" fits the sentence
  // whole) has nothing to step through and stays still.
  if (boxes.length < 2) return null;
  const HOLD = 0.95;
  const cycle = boxes.length * HOLD;
  return (now) => {
    const i = Math.floor((now % cycle) / HOLD);
    boxes.forEach((b, k) => { b.style.display = k === i ? '' : 'none'; });
  };
}

const CAP_BUILDERS = { karaoke: buildKaraokeDemo, stacked: buildStackedDemo, scatter: buildScatterDemo };

const LABEL_W = 48; // .track-label width (content x offset of lanes)
const MIN_SEG = 0.2; // s
const THUMB_EVERY = 2.0;

// ---------- state ----------
let S = {
  state: {}, // state.json
  rendered: [], // ranges as rendered (from edl.json) — the video's truth
  draft: [], // user-editable copy [{source,start,end,beat,removed,orig:{start,end}}]
  videoDuration: 0,
  fps: 24,
  captions: [], // grouped caption lines [{text,start,end}] (rendered space)
  editData: null, // edit-data.json content (phase 2)
  insertsDraft: [], // editable inserts [{kind,label,start,end,ref,orig}]
  wave: null,
  thumbCount: 0,
  tab: 1,
  pps: 10, // px per second (zoom)
  minPps: 4,
  selected: -1, // selected clip index (draft)
  lastSig: '', // change detection
  savedPending: false,
  notes: [], // correction markers [{id,start,end,text}] — draft-timeline seconds
  // Transcrição clicável (2026-09-01): palavras do CORTE em tempo renderizado
  // (transcripts/cut.json, ou captions.json quando só ele existe).
  words: [], // [{text,start,end}] rendered seconds
  wordSel: null, // {a,b} índices da seleção em curso
  textCuts: [], // [{start,end,text}] rendered seconds — trechos riscados
  textFixes: [], // [{start,end,from,to}] rendered seconds — texto corrigido
  fixing: false, // campo de correção aberto na barra de palavras
  diag: null, // diagnostics.json (helpers/diagnostics.py)
  align: null, // studio-pipeline/alignment.json (helpers/script_align.py)
  takeChoices: {}, // linha do roteiro -> índice da tomada escolhida
  pendingIn: null, // an IN is open, waiting for its OUT
  editingNote: null, // id of the note the editor is bound to
  style: null, // current picks {edit, captions, elements:{…}, note}
  jcut: null, // jcut_timeline from edl.json — real output positions per take
  // A1/A2 live folded inside the audio track. They answer "where is the J-cut",
  // which is a question you ask once — so the default is closed, and the choice
  // is remembered rather than re-made every reload.
  jcutOpen: localStorage.getItem('edvid.jcutOpen') === '1',
};

// Forces every `always: true` element on. Called after ANY merge of an outside
// style object (state.json can be older than this rule and carry
// `flashCut: false`) — the fixed elements are not negotiable from data.
function forceAlwaysOn(elements) {
  for (const e of STYLE_CATALOG.elements) if (e.always) elements[e.id] = true;
  return elements;
}

function defaultStyle() {
  const elements = {};
  for (const e of STYLE_CATALOG.elements) elements[e.id] = e.always ? true : !!e.def;
  const image = {};
  for (const a of IMAGE_ADJUSTMENTS) image[a.id] = a.def;
  image.lut = LUT_CATALOG[0].id; // 'none'
  return {
    edit: STYLE_CATALOG.edits[0].id,
    headline: STYLE_CATALOG.headlines[0].id,
    // só viajam quando `headline === 'personalizada'`
    headlineCustom: {color: '#ffffff', accentColor: '#ff7713', weight1: 800, weight2: 900, maxFontPx: 92, paddingTop: 300},
    headlineFont: STYLE_CATALOG.headlineFonts[0].id,
    captions: STYLE_CATALOG.captions[0].id,
    accent: ACCENT_DEFAULT,
    elements,
    image,
    note: '',
  };
}

const fmt = (t) => {
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, '0')}`;
};
const el = (tag, cls, parent) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (parent) parent.appendChild(e);
  return e;
};

// ---------- draft layout (output-timeline positions) ----------
/* Per-take J-cut geometry, in seconds. `lead` is how far the take's sound runs
 * ahead of its picture; `tail` is what was trimmed off its end. Both are fixed
 * frame counts, so they survive the user trimming a take in the UI. */
function jcutGeom(i) {
  const j = S.jcut && S.jcut[i];
  if (!j) return { lead: 0, tail: 0 };
  return {
    lead: Math.max(0, (j.video_start_in_output || 0) - (j.audio_start_in_output || 0)),
    tail: (j.tail_trim_frames || 0) / (S.fps || 30),
  };
}

/* The draft timeline has to model the J-cut, not just sum the ranges: a take's
 * picture is shorter than its range by the lead it gives up plus the tail it had
 * trimmed. Summing raw ranges made the ruler read 8.07s over a 7.60s render, and
 * every clip after the first sat late by the accumulated lead. Each item also
 * carries its AUDIO placement (aout/adur), which is what the A1/A2 lanes draw —
 * derived here so the lanes follow the user's trims instead of going stale. */
function draftLayout() {
  let t = 0;
  let at = 0;
  return S.draft.map((r, i) => {
    if (r.removed) return { ...r, out: t, dur: 0, aout: at, adur: 0 };
    const g = jcutGeom(i);
    const span = r.end - r.start;
    const adur = Math.max(0, span - g.tail);
    const dur = Math.max(0, adur - g.lead);
    const item = { ...r, out: t, dur, aout: Math.max(0, at - g.lead), adur, lead: g.lead };
    t += dur;
    at = item.aout + adur;
    return item;
  });
}
function renderedLayout() {
  // Under a J-cut the rendered positions come from render.py, not from summing
  // the ranges — the takes overlap in sound and the picture of each one starts
  // a few frames in. Summing here would place every clip after the first too late.
  if (S.jcut && S.jcut.length === S.rendered.length) {
    return S.rendered.map((r, i) => ({
      ...r,
      out: S.jcut[i].video_start_in_output,
      dur: S.jcut[i].video_duration,
    }));
  }
  let t = 0;
  return S.rendered.map((r) => {
    const dur = r.end - r.start;
    const item = { ...r, out: t, dur };
    t += dur;
    return item;
  });
}
const draftTotal = () => draftLayout().reduce((a, r) => a + r.dur, 0);

// draft time → rendered time (for scrubbing the old render while editing)
function draftToRendered(t) {
  const dl = draftLayout();
  const rl = renderedLayout();
  for (let i = dl.length - 1; i >= 0; i--) {
    const d = dl[i];
    if (d.removed || t < d.out) continue;
    const off = Math.min(t - d.out, (rl[i]?.dur ?? d.dur) - 0.02);
    return (rl[i]?.out ?? d.out) + Math.max(0, off);
  }
  return Math.min(t, S.videoDuration);
}
// rendered time → draft time (needle position during playback)
function renderedToDraft(t) {
  const dl = draftLayout();
  const rl = renderedLayout();
  for (let i = rl.length - 1; i >= 0; i--) {
    const r = rl[i];
    if (t < r.out) continue;
    if (dl[i]?.removed) return dl[i].out; // playing removed material → park at its slot
    const off = Math.min(t - r.out, dl[i]?.dur ?? r.dur);
    return (dl[i]?.out ?? r.out) + off;
  }
  return t;
}

// ---------- dirty tracking ----------
function edlDirty() {
  return S.draft.some((r) => r.removed || r.start !== r.orig.start || r.end !== r.orig.end);
}
function insertsDirty() {
  return S.insertsDraft.some((c) => c.start !== c.orig.start || c.end !== c.orig.end);
}
function imageDirty() {
  // dirtyCount() (via poll()) runs on every state check, including before the
  // first successful applyState() — S.style/S.imageOrig are still their
  // initial null/undefined then. Guard, don't crash: a crash here is caught
  // silently by poll()'s try/catch AND skips the `S.lastSig = sig` write, so
  // applyState() never runs on ANY later poll either (the signature never
  // changes) — the whole app gets stuck pre-first-load forever. Confirmed
  // live 2026-08-15 (see Aprendizados in the Segundo Cérebro vault).
  if (!S.style || !S.style.image || !S.imageOrig) return false;
  return IMAGE_ADJUSTMENTS.some((a) => S.style.image[a.id] !== S.imageOrig[a.id])
    || S.style.image.lut !== S.imageOrig.lut;
}
function dirtyCount() {
  let n = S.draft.filter((r) => r.removed || r.start !== r.orig.start || r.end !== r.orig.end).length;
  n += S.insertsDraft.filter((c) => c.start !== c.orig.start || c.end !== c.orig.end).length;
  n += S.notes.length; // each correction marker is an unsaved adjustment too
  n += S.textCuts.length; // cada trecho riscado no texto
  n += S.textFixes.length; // cada correção de texto da legenda
  n += Object.keys(S.takeChoices).length; // cada tomada escolhida no roteiro
  n += imageDirty() ? 1 : 0; // one grade change, however many sliders moved
  return n;
}
function refreshHeader() {
  const n = dirtyCount();
  $('dirtyPill').classList.toggle('hidden', n === 0);
  $('dirtyCount').textContent = n;
  $('btnSave').classList.toggle('hidden', n === 0);
  $('btnDiscard').classList.toggle('hidden', n === 0);
  $('savedPill').classList.toggle('hidden', !(S.savedPending && n === 0));
}

// ---------- data loading ----------
async function poll() {
  try {
    const res = await fetch('api/state');
    const data = await res.json();
    const sig = JSON.stringify([data.state, data.edl, data.mtimes, data.videoDuration, data.health]);
    if (sig !== S.lastSig) {
      const hadEdits = dirtyCount() > 0;
      if (!hadEdits) {
        S.lastSig = sig;
        await applyState(data);
      } else {
        toast('Novo estado disponível — salve ou descarte seus ajustes para atualizar', 4000);
      }
    }
  } catch (e) {
    $('projectHealth').textContent = 'Sem conexão com o editor. Tentando reconectar…';
    $('projectHealth').dataset.status = 'error';
  }
  // Outside the signature check on purpose. The LUT thumbnails appear on disk
  // WITHOUT any state/edl/mtime change (helpers/lut_thumbs.py just writes into
  // .preview_cache/), so hanging this off applyState() means it never runs in
  // the exact situation it exists for. No-ops when nothing is pending.
  LUT_THUMBS.retry();
  setTimeout(poll, 2000);
}

async function applyState(data) {
  S.state = data.state || {};
  S.mtimes = data.mtimes || {};
  S.videoDuration = data.videoDuration || 0;
  S.fps = S.state.fps || 24;
  S.savedPending = !!data.hasPendingEdits || !!data.pendingStyle;

  $('projectName').textContent = S.state.project || 'Edvid';
  const h = data.health || {};
  $('stateMessage').textContent = h.code === 'ready' ? (S.state.message || h.message) : (h.message || '');
  $('projectHealth').textContent = h.message || '';
  $('projectHealth').dataset.status = h.code || 'waiting';
  $('emptyTitle').textContent = h.code === 'missing' ? 'Vamos localizar seu vídeo' : h.code === 'error' ? 'Este projeto precisa de atenção' : h.code === 'processing' ? 'Processamento em andamento' : 'Seu corte ainda não está disponível';
  $('emptyMessage').textContent = h.message || '';
  $('recoveryPanel').classList.toggle('hidden', !h.missing?.length);
  const field = $('recoverField');
  const previous = field.value;
  field.replaceChildren();
  for (const item of h.missing || []) {
    const option = document.createElement('option');
    option.value = item.field;
    option.textContent = (item.field === 'video' ? 'Corte' : 'Versão final') + ': ' + item.name;
    field.append(option);
  }
  if ([...field.options].some(o => o.value === previous)) field.value = previous;

  const ranges = (data.edl && data.edl.ranges) || [];
  // J-cut timeline, written by render.py. Under a J-cut the picture of every take
  // after the first starts a few frames into itself, so the rendered clip is
  // SHORTER than end-start and the takes do not simply abut. Without this the
  // filmstrip and the needle drift a little further at each junction.
  S.jcut = (data.edl && data.edl.jcut_timeline) || null;
  S.rendered = ranges.map((r) => ({ source: r.source, start: +r.start, end: +r.end, beat: r.beat || '' }));
  S.draft = S.rendered.map((r) => ({ ...r, removed: false, orig: { start: r.start, end: r.end } }));
  S.selected = -1;

  // style picks: the skill's copy wins, so applying a change (or reopening the
  // session) shows what is actually rendered — not a stale local selection
  S.style = { ...defaultStyle(), ...(S.state.style || {}), ...(data.pendingStyle || {}) };
  S.style.elements = forceAlwaysOn({ ...defaultStyle().elements, ...((S.state.style || {}).elements || {}) });
  S.style.image = { ...defaultStyle().image, ...((S.state.style || {}).image || {}) };
  S.imageOrig = { ...S.style.image }; // snapshot for dirty-tracking, like EDL ranges' .orig
  $('setupNote').value = S.style.note || '';
  $('headlineText').value = S.style.headlineText || '';
  for (const key of ['voice', 'music', 'sfx']) {
    const gain = S.style.audioMix?.[key + 'Db'] ?? 0;
    $(key + 'Gain').value = gain; $(key + 'GainValue').textContent = `${gain} dB`;
  }
  // The gate used to force-jump to the Estilo tab the moment the skill set
  // `awaitingStyle`. User's read (2026-08-16): after editing, land on the
  // Fase 1 Corte preview first — review the cut, then open Estilo when
  // ready. The tab stays enabled/reachable (see tabS.disabled below), just
  // not auto-selected — S.tab keeps its `1` default from initial state.

  const hasVideo = S.videoDuration > 0;
  $('playerWrap').classList.toggle('hidden', !hasVideo);
  $('editorCol').classList.toggle('hidden', !hasVideo);

  if (hasVideo) {
    updateVideoSrc();
    loadWave();
    loadThumbsMeta();
  }

  // phase 2 data
  const tab2 = document.querySelector('[data-tab="2"]');
  tab2.disabled = (S.state.phase || 1) < 2;
  // Estilo opens when the catalog applies to this job: the skill asked for a
  // pick, or one is already recorded. Before that there is nothing to choose.
  const tabS = document.querySelector('[data-tab="style"]');
  tabS.disabled = !S.state.awaitingStyle && !S.state.style;
  if (tabS.disabled && S.tab === 'style') S.tab = 1;
  document.querySelectorAll('.tab').forEach((x) => {
    x.classList.toggle('active', String(x.dataset.tab) === String(S.tab));
  });
  S.captions = [];
  S.editData = null;
  S.insertsDraft = [];
  if ((S.state.phase || 1) >= 2) {
    if (S.state.captions) {
      try {
        const caps = await (await fetch(`media/${S.state.captions}?v=${Date.now()}`)).json();
        S.captions = groupCaptions(caps);
      } catch (e) { /* absent yet */ }
    }
    if (S.state.editData) {
      try {
        S.editData = await (await fetch(`media/${S.state.editData}?v=${Date.now()}`)).json();
        buildInsertsDraft();
      } catch (e) { /* absent yet */ }
    }
  }

  S.words = [];
  S.wordSel = null;
  S.textCuts = [];
  S.textFixes = [];
  await loadWords();
  S.diag = null;
  try {
    const r = await fetch(`media/diagnostics.json?v=${Date.now()}`);
    if (r.ok) S.diag = await r.json();
  } catch (e) { /* sem diagnóstico ainda */ }
  S.align = null; S.takeChoices = {};
  try {
    // o alinhamento é escrito pelo Studio; o preview só o LÊ e desenha
    const r = await fetch(`media/studio-pipeline/alignment.json?v=${Date.now()}`);
    if (r.ok) S.align = await r.json();
  } catch (e) { /* sem roteiro alinhado ainda */ }

  fitZoom();
  renderAll();
  renderSetup();
  renderImagePanel();
  renderDiag();
  refreshHeader();
}

// Palavras do corte. Fonte primária: transcripts/cut.json (transcribe.py no
// cut.mp4 — {words:[{text,start,end,type}]} em segundos). Reserva: captions.json
// da Fase 2 ({text,startMs,endMs}). Sem nenhum dos dois a faixa não aparece.
async function loadWords() {
  const rel = S.state.transcript || 'transcripts/cut.json';
  try {
    const r = await fetch(`media/${rel}?v=${Date.now()}`);
    if (r.ok) {
      const d = await r.json();
      S.words = (d.words || []).filter((w) => (w.type || 'word') === 'word' && (w.text || w.word))
        .map((w) => ({ text: (w.text || w.word).trim(), start: +w.start, end: +w.end }));
      if (S.words.length) return;
    }
  } catch (e) { /* segue para a reserva */ }
  if (S.state.captions) {
    try {
      const caps = await (await fetch(`media/${S.state.captions}?v=${Date.now()}`)).json();
      S.words = (Array.isArray(caps) ? caps : []).filter((c) => c.text && c.text.trim())
        .map((c) => ({ text: c.text.trim(), start: c.startMs / 1000, end: c.endMs / 1000 }));
    } catch (e) { /* nada */ }
  }
}

// Fase 1 plays the clean cut; Fase 2 plays the Phase-2 render (state.finalVideo)
// when it exists, so captions/inserts are visible. Keeps the playback position.
function updateVideoSrc() {
  const rel = (S.tab === 2 && S.state.finalVideo) ? S.state.finalVideo : (S.state.video || 'cut.mp4');
  const vsrc = `media/${rel}?v=${(S.mtimes && (S.mtimes.finalVideo || S.mtimes.video)) || 0}`;
  if (video.dataset.src === vsrc) return;
  const t = video.currentTime;
  const wasPlaying = !video.paused && !video.ended;
  video.dataset.src = vsrc;
  video.src = vsrc;
  video.currentTime = t;
  if (wasPlaying) video.play();
}

function groupCaptions(caps) {
  // mirror the template: lines of ≤3 words, break on punctuation
  const lines = [];
  let cur = [];
  for (const w of caps) {
    cur.push(w);
    if (cur.length >= 3 || /[.,!?…]$/.test(w.text)) { lines.push(cur); cur = []; }
  }
  if (cur.length) lines.push(cur);
  return lines.map((line) => ({
    text: line.map((w) => w.text.replace(/[.,!?…]+$/, '')).join(' '),
    start: line[0].startMs / 1000,
    end: line[line.length - 1].endMs / 1000,
  }));
}

function buildInsertsDraft() {
  const d = S.editData;
  const list = [];
  if (d.hook && d.hook.enabled) {
    list.push({ kind: 'hook', label: `HOOK — ${(d.hook.lines || []).join(' / ')}`, start: 0, end: d.hook.endSec || 4 });
  }
  (d.inserts || []).forEach((it, i) => {
    list.push({ kind: 'insert', label: (it.src || '').split('/').pop(), start: +it.start, end: +it.end, ref: i });
  });
  // split-layout images (CustomGraphics reads the same array) — they are images
  // like any other insert, so they belong on the image track, not in code
  (d.splitInserts || []).forEach((it, i) => {
    list.push({
      kind: 'split',
      label: it.label || (it.src || '').split('/').pop(),
      start: +it.start, end: +it.end, ref: i,
    });
  });
  // split-layout VIDEO bands — same seam and geometry as splitInserts, but the
  // band plays a clip (generated b-roll, screen capture). Its own array because
  // the renderer mounts it with a different component; on the timeline it is an
  // image-track element like any other.
  (d.splitVideos || []).forEach((it, i) => {
    list.push({
      kind: 'splitvideo',
      label: it.label || (it.src || '').split('/').pop(),
      start: +it.start, end: +it.end, ref: i,
    });
  });
  (d.behind || []).forEach((b, i) => {
    list.push({ kind: 'behind', label: `BEHIND ${b.kind === 'words' ? (b.words || []).map((w) => w.t).join(' ') : (b.src || '').split('/').pop()}`, start: +b.start, end: +b.start + +b.dur, ref: i });
  });
  // held single words in the caption's own visual language (a keyword the viewer
  // must type, an emphasis beat) — text, so they ride the text track next to the
  // hook rather than the image track
  (d.wordAccents || []).forEach((w, i) => {
    list.push({ kind: 'word', label: w.text, start: +w.start, end: +w.end, ref: i });
  });
  S.insertsDraft = list.map((c) => ({ ...c, orig: { start: c.start, end: c.end } }));
}

async function loadWave() {
  try {
    S.wave = await (await fetch('gen/waveform.json')).json();
    drawWave();
  } catch (e) { S.wave = null; }
}
async function loadThumbsMeta() {
  try {
    const meta = await (await fetch('gen/thumbs/meta.json')).json();
    S.thumbCount = meta.count || 0;
    renderClips();
  } catch (e) { S.thumbCount = 0; }
}

// ---------- zoom / layout ----------
function contentWidth() { return LABEL_W + Math.max(draftTotal(), S.videoDuration, 1) * S.pps + 14; }
function fitZoom() {
  const avail = panel.clientWidth - LABEL_W - 40;
  const total = Math.max(draftTotal(), S.videoDuration, 1);
  S.minPps = Math.max(1, avail / total);
  S.pps = S.minPps;
  $('zoom').value = 0;
}
const MAX_PPS = 200;

// Zoom keeping `t` (seconds) parked at `anchorX` (px from the panel's left edge).
function applyZoom(pps, t, anchorX) {
  S.pps = Math.min(MAX_PPS, Math.max(S.minPps, pps));
  const span = Math.log(MAX_PPS / S.minPps);
  $('zoom').value = span > 0 ? Math.round((100 * Math.log(S.pps / S.minPps)) / span) : 0;
  renderAll();
  panel.scrollLeft = Math.max(0, LABEL_W + t * S.pps - anchorX);
  drawRuler();
  drawWave();
  positionNeedle();
}

// Trackpad pinch arrives as a wheel event with ctrlKey set. Anchored on the
// pointer (a direct gesture zooms where the fingers are); the slider stays
// anchored on the needle.
panel.addEventListener('wheel', (e) => {
  if (!e.ctrlKey) return; // plain two-finger scrolling stays untouched
  e.preventDefault();
  const pr = panel.getBoundingClientRect();
  const anchorX = e.clientX - pr.left;
  const t = (panel.scrollLeft + anchorX - LABEL_W) / S.pps;
  applyZoom(S.pps * Math.exp(-e.deltaY * 0.01), Math.max(0, t), anchorX);
}, { passive: false });

function setZoom(v) { // slider 0..100 → minPps..200, anchored on the needle
  const t = renderedToDraft(video.currentTime || 0);
  // viewport x of the needle before the zoom; if it is off-screen, pull it to
  // the middle so zooming always lands on the playhead the user is looking at
  const xBefore = LABEL_W + t * S.pps - panel.scrollLeft;
  const visible = xBefore >= LABEL_W && xBefore <= panel.clientWidth;
  const anchor = visible ? xBefore : LABEL_W + (panel.clientWidth - LABEL_W) / 2;
  applyZoom(S.minPps * Math.pow(MAX_PPS / S.minPps, v / 100), t, anchor);
}

// Lanes are clipped at the gutter (and the divider is positioned) by a
// scroll-driven CSS timeline, so both stay pinned to scrollLeft with zero lag.
// All JS has to publish is the scroll RANGE, which only changes on zoom/resize.
function updateScrollRange() {
  const max = Math.max(0, panel.scrollWidth - panel.clientWidth);
  timelineEl.style.setProperty('--max-scroll', `${max}px`);
}

// ---------- rendering ----------
function renderAll() {
  updateImgDrawerHint();
  renderTakes();
  timelineEl.style.width = `${contentWidth()}px`;
  renderClips();
  renderWords();
  renderJcutAudio();
  renderChips();
  renderNotes();
  drawRuler();
  drawWave();
  updateScrollRange();
  positionNeedle();
}

// ---------- transcrição clicável ----------
const laneWords = $('laneWords');
function renderWords() {
  const has = S.words.length > 0;
  $('trkWords').classList.toggle('hidden', !has);
  laneWords.innerHTML = '';
  if (!has) return;
  const sel = S.wordSel;
  const lo = sel ? Math.min(sel.a, sel.b) : -1;
  const hi = sel ? Math.max(sel.a, sel.b) : -1;
  S.words.forEach((w, i) => {
    const start = renderedToDraft(w.start);
    const end = renderedToDraft(w.end);
    if (end <= start) return; // palavra dentro de take removido no rascunho
    const chip = el('div', 'chip word', laneWords);
    chip.style.left = `${start * S.pps}px`;
    chip.style.width = `${Math.max((end - start) * S.pps, 4)}px`;
    chip.textContent = w.text;
    chip.title = `${w.text}  ${fmt(w.start)}\nclique: início do trecho · clique noutra: fim`;
    chip.dataset.i = i;
    if (i >= lo && i <= hi) chip.classList.add('sel');
    if (S.textCuts.some((c) => w.start >= c.start - 1e-3 && w.end <= c.end + 1e-3)) chip.classList.add('cut');
    const fix = S.textFixes.find((f) => w.start >= f.start - 1e-3 && w.end <= f.end + 1e-3);
    if (fix) { chip.classList.add('fixed'); chip.title = `corrigido para «${fix.to}»`; }
  });
}
laneWords.addEventListener('click', (e) => {
  const chip = e.target.closest('.chip.word');
  if (!chip) return;
  const i = +chip.dataset.i;
  if (!S.wordSel) S.wordSel = { a: i, b: i };
  else if (S.wordSel.a === S.wordSel.b && S.wordSel.a === i) S.wordSel = null; // clique de novo desmarca
  else S.wordSel.b = i;
  renderWords();
  renderWordBar();
});
function renderWordBar() {
  const bar = $('wordBar');
  if (!S.wordSel) { bar.classList.add('hidden'); S.fixing = false; return; }
  const lo = Math.min(S.wordSel.a, S.wordSel.b), hi = Math.max(S.wordSel.a, S.wordSel.b);
  const text = S.words.slice(lo, hi + 1).map((w) => w.text).join(' ');
  $('wordBarText').textContent = `«${text}»  ${fmt(S.words[lo].start)} → ${fmt(S.words[hi].end)}`;
  // Correcting and cutting are different intents on the same selection, so the
  // bar shows one or the other — never both half-armed.
  $('wordBarFix').classList.toggle('hidden', !S.fixing);
  $('wordBarText').classList.toggle('hidden', S.fixing);
  $('wordBarCut').classList.toggle('hidden', S.fixing);
  $('wordBarEdit').classList.toggle('hidden', S.fixing);
  bar.classList.remove('hidden');
}
// Fixing text NEVER moves a timing: the user is correcting what was heard, not
// when it was said. caption_fix.py holds the other half of that contract.
function commitFix() {
  if (!S.wordSel || !S.fixing) return;
  const lo = Math.min(S.wordSel.a, S.wordSel.b), hi = Math.max(S.wordSel.a, S.wordSel.b);
  const from = S.words.slice(lo, hi + 1).map((w) => w.text).join(' ');
  const to = $('wordBarFix').value.trim();
  S.fixing = false;
  if (!to) { toast('Apagar fala é corte, não correção — use "cortar este trecho"', 3400); renderWordBar(); return; }
  if (to !== from) {
    const start = S.words[lo].start, end = S.words[hi].end;
    S.textFixes = S.textFixes.filter((f) => !(f.start >= start - 1e-3 && f.end <= end + 1e-3));
    S.textFixes.push({ start, end, from, to });
    S.textFixes.sort((a, b) => a.start - b.start);
    toast('Texto corrigido — salve os ajustes para aplicar', 2600);
  }
  S.wordSel = null;
  renderWords(); renderWordBar(); refreshHeader();
}
$('wordBarCut').addEventListener('click', () => {
  if (!S.wordSel) return;
  const lo = Math.min(S.wordSel.a, S.wordSel.b), hi = Math.max(S.wordSel.a, S.wordSel.b);
  S.textCuts.push({ start: S.words[lo].start, end: S.words[hi].end,
    text: S.words.slice(lo, hi + 1).map((w) => w.text).join(' ') });
  S.textCuts.sort((a, b) => a.start - b.start);
  S.wordSel = null;
  renderWords(); renderWordBar(); refreshHeader();
  toast('Trecho marcado para cortar — salve os ajustes para aplicar', 2600);
});
$('wordBarEdit').addEventListener('click', () => {
  if (!S.wordSel) return;
  const lo = Math.min(S.wordSel.a, S.wordSel.b), hi = Math.max(S.wordSel.a, S.wordSel.b);
  S.fixing = true;
  renderWordBar();
  const input = $('wordBarFix');
  input.value = S.words.slice(lo, hi + 1).map((w) => w.text).join(' ');
  input.focus(); input.select();
});
$('wordBarFix').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); commitFix(); }
  else if (e.key === 'Escape') { e.preventDefault(); S.fixing = false; renderWordBar(); }
});
$('wordBarFix').addEventListener('blur', commitFix);
$('wordBarCancel').addEventListener('click', () => { S.fixing = false; S.wordSel = null; renderWords(); renderWordBar(); });

// ---------- escolha de tomadas do roteiro ----------
// O alinhamento (script_align.py) PROPÕE; quem escolhe é o usuário. Esta
// gaveta existe porque sem ela o alignment.json era um dado que ninguém via —
// a função ficava tecnicamente pronta e praticamente inutilizável.
function renderTakes() {
  const panel = $('takesPanel'), body = $('takesBody');
  const a = S.align;
  const has = a && Array.isArray(a.lines) && a.lines.length;
  panel.classList.toggle('hidden', !has);
  if (!has) return;
  const s = a.summary || {};
  $('takesHint').textContent =
    `${s.lines || a.lines.length} linhas · ${s.multiple || 0} regravadas · ${s.missing || 0} sem gravação`;
  if (body.classList.contains('hidden')) return; // fechada: não desenha à toa
  body.innerHTML = '';
  for (const item of a.lines) {
    const row = el('div', 'take-line', body);
    const q = el('p', 'take-quote', row);
    const tag = el('span', 'take-status', q);
    tag.dataset.s = item.status;
    tag.textContent = {ok: 'ok', multiple: 'regravada', missing: 'não gravada', curta: 'curta'}[item.status] || item.status;
    const txt = el('b', '', q); txt.textContent = item.text;
    if (!item.candidates || !item.candidates.length) {
      const why = el('span', '', q); why.textContent = ` — ${item.why || ''}`;
      continue;
    }
    const opts = el('div', 'take-opts', row);
    const escolhida = S.takeChoices[item.line] ?? 0;
    item.candidates.forEach((c, i) => {
      const b = el('button', `take-opt${i === escolhida ? ' on' : ''}`, opts);
      b.type = 'button';
      const t = el('span', 't', b);
      t.textContent = `${fmt(c.start)}–${fmt(c.end)}`;
      const meta = el('span', '', b);
      meta.textContent = item.candidates.length > 1
        ? `tomada ${i + 1} · ${Math.round(c.score * 100)}%${c.fillers ? ` · ${c.fillers} vício` : ''}`
        : `${Math.round(c.score * 100)}%`;
      b.addEventListener('click', () => {
        S.takeChoices[item.line] = i;
        // leva a agulha para a tomada escolhida: ouvir é o que decide
        if (Number.isFinite(c.start)) seekDraft(renderedToDraft(c.start));
        renderTakes(); refreshHeader();
      });
    });
  }
  if (a.offScript && a.offScript.length) {
    const off = el('div', 'take-off', body);
    off.textContent = `${a.offScript.length} trecho(s) falados fora do roteiro — improviso, pode ser aproveitável.`;
  }
}

// ---------- painel de diagnóstico ----------
function renderDiag() {
  const panel = $('diagPanel');
  const d = S.diag;
  const has = d && ((d.audio || []).length || (d.edges || []).length || (d.takes || []).length || d.qc);
  panel.classList.toggle('hidden', !has);
  if (!has) return;
  const body = $('diagBody');
  body.innerHTML = '';
  const nEdges = (d.edges || []).length;
  const nFails = ((d.qc || {}).fails || []).length;
  const bits = [];
  if ((d.audio || []).length) bits.push('áudio limpo');
  if (nEdges) bits.push(`${nEdges} borda${nEdges > 1 ? 's' : ''} a conferir`);
  if ((d.takes || []).length) bits.push(`${d.takes.length} takes`);
  if (d.qc) bits.push(nFails ? `QC: ${nFails} falha${nFails > 1 ? 's' : ''}` : 'QC ok');
  $('diagHint').textContent = bits.join(' · ');
  const sec = (title) => { const s = el('div', 'diag-sec', body); const h = el('h4', '', s); h.textContent = title; return s; };
  const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  if ((d.audio || []).length) {
    const s = sec('Áudio limpo');
    for (const a of d.audio) {
      const b = a.before || {}, af = a.after || {};
      const snrB = (b.speech_p75_db != null && b.floor_db != null) ? (b.speech_p75_db - b.floor_db).toFixed(0) : '?';
      const snrA = (af.speech_p75_db != null && af.floor_db != null) ? (af.speech_p75_db - af.floor_db).toFixed(0) : '?';
      const row = el('div', 'diag-note', s);
      row.textContent = `${a.source}: SNR ${snrB} → ${snrA} dB · ${a.breaths} respiração(ões) · ${a.leveled} frase(s) nivelada(s) · ${a.denoise || ''}`;
      if (a.ab) {
        const au = el('audio', '', s);
        au.controls = true; au.preload = 'none';
        au.src = `media/${a.ab}`;
        au.title = '8 s original → 8 s limpo';
      }
    }
  }
  if ((d.edges || []).length) {
    const s = sec('Bordas apontadas (clique para ir)');
    const row = el('div', 'diag-row', s);
    for (const e of d.edges) {
      const c = el('span', 'diag-chip warn', row);
      const shift = e.shift_frames != null ? ` · mover ${e.shift_frames > 0 ? '+' : ''}${e.shift_frames}f` : '';
      c.textContent = `${e.beat || 'take ' + (e.take + 1)} ${e.kind}: ${e.check}${shift}`;
      c.title = `fonte ${e.t_source}s` + (e.t_out != null ? ` · corte ${fmt(e.t_out)}` : '');
      if (e.t_out != null) c.addEventListener('click', () => seekDraft(renderedToDraft(e.t_out)));
    }
  }
  if ((d.takes || []).length) {
    const s = sec('Takes');
    const tb = el('table', 'diag-table', s);
    tb.innerHTML = '<tr><th>take</th><th>luma rosto</th><th>R/G</th><th>B/G</th><th>casado</th><th>avisos</th></tr>';
    const matched = new Map((d.matched || []).map((m) => [m.take, m.grade_pre]));
    for (const tk of d.takes) {
      const tr = el('tr', '', tb);
      const fl = (tk.face_luma != null) ? (tk.face_luma * 100).toFixed(0) : (tk.luma != null ? (tk.luma * 100).toFixed(0) + '*' : '—');
      const flags = (tk.flags || []).map((f) => f.check).join(', ');
      tr.innerHTML = `<td>${esc(tk.beat || tk.take + 1)}</td><td>${fl}</td><td>${tk.rg != null ? tk.rg.toFixed(2) : '—'}</td>` +
        `<td>${tk.bg != null ? tk.bg.toFixed(2) : '—'}</td><td title="${esc(matched.get(tk.take) || '')}">${matched.has(tk.take) ? 'sim' : ''}</td><td>${esc(flags)}</td>`;
    }
  }
  if (d.qc) {
    const s = sec('QC de entrega');
    const row = el('div', 'diag-row', s);
    for (const f of d.qc.fails || []) { const c = el('span', 'diag-chip bad', row); c.textContent = f; }
    for (const w of d.qc.warns || []) { const c = el('span', 'diag-chip warn', row); c.textContent = w; }
    if (!(d.qc.fails || []).length) { const c = el('span', 'diag-chip ok', row); c.textContent = 'pode enviar'; }
    if (d.qc.loudness && d.qc.loudness.I != null) {
      const n = el('div', 'diag-note', s);
      n.textContent = `loudness ${d.qc.loudness.I} LUFS · TP ${d.qc.loudness.TP} dBTP · LRA ${d.qc.loudness.LRA}`;
    }
  }
}
// Gavetas: nascem fechadas (a timeline é o que precisa estar visível), e a
// escolha fica lembrada por painel — abrir a mesma gaveta a cada render é
// exatamente o tipo de atrito que o usuário reclamou.
// Uma classe no body diz ao CSS que alguma gaveta está aberta — é ela que
// manda o player ceder altura em vez de a timeline sair da tela.
function syncDrawerState() {
  const open = ['imgDrawerBody', 'diagBody'].some((id) => {
    const e = $(id);
    return e && !e.classList.contains('hidden') && e.closest('section') &&
           !e.closest('section').classList.contains('hidden');
  });
  document.body.classList.toggle('drawer-open', open);
  requestAnimationFrame(() => { LUT_ENGINE.syncRect(); fitZoom(); renderAll(); });
}

function wireDrawer(toggleId, bodyId, key) {
  const btn = $(toggleId), body = $(bodyId);
  // Nasce fechada, sempre. A memória da sessão anterior fazia o preview abrir
  // com a gaveta em cima do player — exatamente o que o usuário reclamou. A
  // escolha só vale enquanto a aba está aberta.
  const open = sessionStorage.getItem(key) === '1';
  body.classList.toggle('hidden', !open);
  btn.setAttribute('aria-expanded', String(open));
  btn.addEventListener('click', () => {
    const nowOpen = body.classList.toggle('hidden') === false;
    btn.setAttribute('aria-expanded', String(nowOpen));
    sessionStorage.setItem(key, nowOpen ? '1' : '0');
    syncDrawerState();
    requestAnimationFrame(() => { LUT_ENGINE.syncRect(); fitZoom(); renderAll(); });
  });
}
wireDrawer('imgDrawerToggle', 'imgDrawerBody', 'edvid.imgDrawer');
wireDrawer('diagToggle', 'diagBody', 'edvid.diagDrawer');
wireDrawer('takesToggle', 'takesBody', 'edvid.takesDrawer');
syncDrawerState();

// ---------- correction markers ----------
function renderNotes() {
  const lane = $('laneNotes');
  lane.innerHTML = '';
  // Faixa de marcações vazia custava 32px de altura numa janela onde cada
  // pixel sai do player (medido 2026-09-01). Aparece quando há marcação ou um
  // IN aberto; o botão de marcar continua sempre no transporte.
  $('trkNotes').classList.toggle('hidden', S.notes.length === 0 && S.pendingIn == null);
  for (const n of S.notes) {
    const chip = el('div', 'note-chip', lane);
    chip.style.left = `${n.start * S.pps}px`;
    chip.style.width = `${Math.max((n.end - n.start) * S.pps, 10)}px`;
    chip.textContent = n.text || '(sem descrição)';
    chip.title = `${fmt(n.start)} → ${fmt(n.end)}\n${n.text || ''}\n\nclique para editar`;
    chip.dataset.id = n.id;
  }
  if (S.pendingIn != null) {
    const p = el('div', 'note-pending', lane);
    p.style.left = `${S.pendingIn * S.pps}px`;
  }
  const btn = $('btnMark');
  btn.classList.toggle('armed', S.pendingIn != null);
  $('markText').textContent = S.pendingIn != null ? 'OUT' : 'IN';
}

function toggleMark() {
  const t = renderedToDraft(video.currentTime || 0);
  if (S.pendingIn == null) {
    S.pendingIn = t;
    renderNotes();
    toast('IN marcado — leve a agulha ao fim do trecho e marque o OUT', 2600);
    return;
  }
  const start = Math.min(S.pendingIn, t);
  const end = Math.max(S.pendingIn, t);
  if (end - start < 0.05) {
    toast('Trecho curto demais — afaste a agulha do IN', 2200);
    return;
  }
  S.pendingIn = null;
  const note = { id: `n${Date.now()}`, start, end, text: '', phase: S.tab === 2 ? 2 : 1 };
  S.notes.push(note);
  S.notes.sort((a, b) => a.start - b.start);
  renderNotes();
  openNoteEditor(note.id, true);
}

function openNoteEditor(id, isNew) {
  const n = S.notes.find((x) => x.id === id);
  if (!n) return;
  S.editingNote = id;
  $('noteRange').textContent = `${fmt(n.start)} → ${fmt(n.end)}`;
  $('noteText').value = n.text || '';
  window.noteMediaControls.load(n.media);
  $('noteDelete').classList.toggle('hidden', !!isNew);
  // centred over the timeline (where the user's eyes are), then clamped so a
  // short timeline panel cannot push the editor off-screen
  const ed = $('noteEditor');
  ed.classList.remove('hidden');
  const p = panel.getBoundingClientRect();
  const h = ed.offsetHeight;
  const w = ed.offsetWidth;
  const cy = Math.min(
    Math.max(p.top + p.height / 2, h / 2 + 12),
    window.innerHeight - h / 2 - 12,
  );
  const cx = Math.min(Math.max(p.left + p.width / 2, w / 2 + 12), window.innerWidth - w / 2 - 12);
  ed.style.left = `${cx}px`;
  ed.style.top = `${cy}px`;
  $('noteText').focus();
}

function closeNoteEditor() {
  // a brand-new marker with no text is not worth keeping
  const n = S.notes.find((x) => x.id === S.editingNote);
  if (n && !n.text.trim()) S.notes = S.notes.filter((x) => x.id !== n.id);
  S.editingNote = null;
  $('noteEditor').classList.add('hidden');
  renderNotes();
  refreshHeader();
}

// ---------- style setup ----------
const styleName = (group, id) => (STYLE_CATALOG[group].find((o) => o.id === id) || {}).name || '—';
// the accent is a free colour, not a named entry in a list — it names itself
const accentName = (hex) => String(hex || ACCENT_DEFAULT).toUpperCase();
const normHex = (v) => {
  let s = String(v || '').trim().replace(/^#/, '');
  if (/^[0-9a-f]{3}$/i.test(s)) s = s.split('').map((c) => c + c).join(''); // #abc → #aabbcc
  return /^[0-9a-f]{6}$/i.test(s) ? `#${s.toLowerCase()}` : null;
};

/* Which styles actually paint the accent. Kept as data because the honest UI
 * note depends on it: with `karaoke` + `outline` picked, nothing on screen uses
 * the colour, and saying so beats letting the user wonder why the previews did
 * not move. Mirrors the template — update both together. */
const ACCENT_USERS = {headlines: ['realce', 'misto'], captions: ['stacked']};
const ACCENT_DEFAULT = '#ff5200';

function applyAccent() {
  $('styleSetup').style.setProperty('--hl-accent', S.style.accent || ACCENT_DEFAULT);
}

/* One spectral swatch (the OS picker) plus a hex field — no preset row. A grid of
 * canned colours competes with the style cards for attention and still never has
 * the brand colour the user actually wants. */
function renderAccents() {
  const host = $('optAccent');
  host.innerHTML = '';
  const cur = normHex(S.style.accent) || ACCENT_DEFAULT;

  const custom = el('label', 'swatch custom', host);
  custom.title = 'Escolher cor';
  custom.style.setProperty('--swatch-fill', cur);
  const inp = el('input', '', custom);
  inp.type = 'color';
  inp.value = cur;

  const field = el('div', 'hex-field', host);
  el('span', 'hex-hash', field).textContent = '#';
  const hex = el('input', 'hex-input', field);
  hex.type = 'text';
  hex.spellcheck = false;
  hex.maxLength = 7;
  hex.value = cur.slice(1).toUpperCase();
  hex.setAttribute('aria-label', 'Cor de destaque em hexadecimal');

  const commit = (v, {fromHexField} = {}) => {
    const n = normHex(v);
    if (!n) return false;
    S.style.accent = n;
    custom.style.setProperty('--swatch-fill', n);
    inp.value = n;
    if (!fromHexField) hex.value = n.slice(1).toUpperCase();
    applyAccent();   // live — no full rebuild, so dragging the picker stays smooth
    updateAccentNote();
    updateSummary();
    return true;
  };

  inp.addEventListener('input', () => commit(inp.value));
  // typing: accept as soon as it parses, but never fight the user mid-keystroke
  hex.addEventListener('input', () => {
    field.classList.toggle('bad', !normHex(hex.value) && hex.value.trim() !== '');
    commit(hex.value, {fromHexField: true});
  });
  // leaving an unparseable value snaps back rather than silently keeping the old
  // colour behind text that says something else
  hex.addEventListener('blur', () => {
    field.classList.remove('bad');
    hex.value = (normHex(S.style.accent) || ACCENT_DEFAULT).slice(1).toUpperCase();
  });
  hex.addEventListener('keydown', (e) => { if (e.key === 'Enter') hex.blur(); });

  updateAccentNote();
}

/* Image adjustment sliders (brightness/contrast/saturation/sharpness/skin
 * smoothing/skin warmth/shadows/highlights) — Fase-1 panel (moved off the
 * Estilo tab 2026-08-15 so the user sees the effect while the player is
 * right there). Built once, then the input handler mutates S.style.image and
 * the value label directly — no full rebuild per drag, same reasoning as the
 * accent hex field's live update. */
function renderImageAdjustments() {
  const host = $('optImage');
  host.innerHTML = '';
  for (const a of IMAGE_ADJUSTMENTS) {
    const val = S.style.image[a.id] ?? a.def;
    const row = el('div', 'slider-row', host);
    row.dataset.id = a.id;
    const top = el('div', 'slider-top', row);
    el('span', 'slider-label', top).textContent = a.name;
    const readout = el('span', 'slider-value', top);
    readout.textContent = val;
    const input = document.createElement('input');
    input.type = 'range';
    input.min = String(a.min);
    input.max = String(a.max);
    input.step = '1';
    input.value = String(val);
    input.className = 'slider-input';
    row.appendChild(input);
    input.addEventListener('input', () => {
      const n = Number(input.value);
      S.style.image[a.id] = n;
      readout.textContent = n;
      row.classList.toggle('changed', n !== a.def);
      applyImagePreview();
      refreshHeader();
    });
    row.classList.toggle('changed', val !== a.def);
  }
}

// Instant feedback on the player for ALL 8 sliders (2026-08-15, per user
// request — "quero ver a mudança ao vivo... sem precisar salvar"). Brightness/
// contrast/saturation map ~1:1 to CSS filter() and are exact. The other 5 have
// no honest 1:1 CSS equivalent, so this is a labelled APPROXIMATION, not the
// real ffmpeg grade — the note under the panel says so, and the real result
// still only lands after Salvar re-renders Fase 1:
//   - skinSmooth → blur() over the WHOLE frame (the real smartblur targets
//     skin only — this softens hair/background too, just gives a sense of
//     "how much").
//   - skinWarmth → hue-rotate() toward orange (warm) / blue (cool) — a
//     visible proxy for colortemperature, not a channel-accurate match.
//   - shadows/highlights → brightness()+contrast() nudges. Deliberately
//     mirrors the REAL filter's own limitation (see image_style_to_grade in
//     SKILL.md): `highlights` alone does nothing there because gamma_weight
//     only modulates an existing gamma shift, so here too `highlights` only
//     visibly does anything once `shadows` has also moved — consistent
//     behavior beats a preview that promises something Salvar won't deliver.
//   - sharpness → CSS has no unsharp/convolve filter at all, so this is the
//     one slider needing an actual SVG filter (feConvolveMatrix), built once
//     and updated in place by ensureSharpenFilter().
function applyImagePreview() {
  const img = S.style.image;
  const b = 1 + (img.brightness || 0) / 100;       // CSS brightness() is a multiplier around 1
  const c = 1 + (img.contrast || 0) / 100;
  const s = 1 + (img.saturation || 0) / 100;
  const smooth = img.skinSmooth || 0;
  const warmth = img.skinWarmth || 0;
  const sh = img.shadows || 0;
  const hl = img.highlights || 0;
  const sharp = img.sharpness || 0;

  const parts = [];
  if (b !== 1) parts.push(`brightness(${b.toFixed(3)})`);
  if (c !== 1) parts.push(`contrast(${c.toFixed(3)})`);
  if (s !== 1) parts.push(`saturate(${s.toFixed(3)})`);
  if (smooth) parts.push(`blur(${(smooth / 100 * 2.2).toFixed(2)}px)`);
  // Pure hue-rotate() swings skin toward magenta on the warm side (it rotates
  // ALL hues uniformly around the wheel, so "warmer" doesn't come out warmer
  // — it comes out shifted). A touch of sepia (pulls everything toward
  // orange/brown first) plus a smaller rotation reads as warm/cool without
  // the magenta cast; saturate compensates for sepia's own desaturation.
  if (warmth > 0) {
    parts.push(`sepia(${(warmth / 100 * 0.35).toFixed(3)})`);
    parts.push(`saturate(${(1 + warmth / 100 * 0.15).toFixed(3)})`);
    parts.push(`hue-rotate(${(-warmth / 50 * 4).toFixed(1)}deg)`);
  } else if (warmth < 0) {
    parts.push(`hue-rotate(${(-warmth / 50 * 6).toFixed(1)}deg)`);
    parts.push(`saturate(${(1 + Math.abs(warmth) / 100 * 0.08).toFixed(3)})`);
  }
  if (sh) {
    parts.push(`brightness(${(1 + (sh / 100) * 0.12).toFixed(3)})`);
    parts.push(`contrast(${(1 - Math.abs(sh / 100) * 0.06).toFixed(3)})`);
    if (hl) parts.push(`contrast(${(1 - (hl / 100) * 0.10).toFixed(3)})`); // coupled, see comment above
  }
  ensureSharpenFilter(sharp); // always updates the kernel, even at 0 (identity)
  if (sharp) parts.push('url(#edvidSharpen)');

  video.style.filter = parts.join(' ');
}

// One <feConvolveMatrix> reused across drags — a 3x3 unsharp-style kernel
// (center weight rises, neighbors go negative) blended toward identity at
// amount=0 so it's always safe to reference. Range kept gentle (k up to
// ~0.9) — a "real" unsharp radius/amount pair doesn't translate directly to
// a single 3x3 kernel, so this is a visible-sharpening proxy, not a match
// for ffmpeg's `unsharp` filter.
let sharpenMatrixEl = null;
function ensureSharpenFilter(amount) {
  if (!sharpenMatrixEl) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.style.cssText = 'position:absolute;overflow:hidden;pointer-events:none;';
    svg.innerHTML = '<filter id="edvidSharpen" x="-5%" y="-5%" width="110%" height="110%">'
      + '<feConvolveMatrix id="edvidSharpenMatrix" order="3" preserveAlpha="true" kernelMatrix="0 0 0 0 1 0 0 0 0"/>'
      + '</filter>';
    document.body.appendChild(svg);
    sharpenMatrixEl = document.getElementById('edvidSharpenMatrix');
  }
  const k = (amount / 100) * 0.9;
  sharpenMatrixEl.setAttribute('kernelMatrix', `0 ${-k} 0 ${-k} ${1 + 4 * k} ${-k} 0 ${-k} 0`);
}

/* ---------- LUT filters: real WebGL preview, not an approximation ------------
 * Unlike the 5 sliders above, a 3D LUT preview can be EXACT: the same .cube
 * table drives both this and the real ffmpeg `lut3d` filter at Salvar time,
 * so there's nothing to fake. CSS has no LUT primitive, so this needs actual
 * WebGL2 (sampler3D + texImage3D) — a <canvas> laid exactly over the <video>
 * box (synced in JS since the video's rendered size depends on aspect-ratio-
 * constrained max-height/max-width CSS, not something a stylesheet alone can
 * hand the canvas), drawing the current video frame through the LUT every
 * animation frame while a LUT is active.
 */
// Thumbnails are written by helpers/lut_thumbs.py once cut.mp4 exists, but the
// preview opens at the START of the session — so the grid is normally built
// against a .preview_cache/luts/ that is still empty and every <img> 404s.
// Together with the build-once rule below, the old handling (removeAttribute
// with no retry) made that permanent: the picker stayed blank for the whole
// session, in EVERY project — the chronic blank-swatch bug the user reported
// 2026-08-16. Diagnosed live: 33 cards, 33 images, naturalWidth 0 on all of
// them, while curl on the same URLs returned 200 — proof the files were fine
// and only the never-retried <img> tags were stale.
// The fix keeps build-once (rebuilding cancels in-flight loads, which was its
// own real bug) and makes the failure RECOVERABLE instead: failed cards park
// in `pending` and get re-armed once a cheap probe says the directory finally
// has content.
const LUT_THUMBS = {
  pending: new Map(),   // id -> <img> awaiting a retry
  attempts: new Map(),  // id -> failures so far
  tick: 0,
  probing: false,
  MAX_ATTEMPTS: 6,
  src(id) { return `media/.preview_cache/luts/${id}.jpg`; },
  fail(id, img) {
    img.style.background = '#1a1c22'; // flat swatch, not the broken-image icon
    img.removeAttribute('src');
    const n = (this.attempts.get(id) || 0) + 1;
    this.attempts.set(id, n);
    if (n <= this.MAX_ATTEMPTS) this.pending.set(id, img); else this.pending.delete(id);
  },
  // Driven by the poll cycle. One small GET every ~6s while anything is
  // pending, and nothing at all once everything has loaded — same "safe to
  // call repeatedly with no side effect" contract as the rest of poll().
  // GET, not HEAD: preview_server.py implements do_GET only and answers HEAD
  // with 501, so a HEAD probe never recovers (measured 2026-08-16 — it looks
  // identical to "thumbnails still missing" and would have shipped silently).
  retry() {
    if (!this.pending.size || this.probing) return;
    if (++this.tick % 3) return;
    this.probing = true;
    fetch(`${this.src('none')}?probe=${Date.now()}`, { cache: 'no-store' })
      .then((r) => {
        if (!r.ok) return;
        const v = `?v=${Date.now()}`;
        for (const [id, img] of this.pending) { img.style.background = ''; img.src = this.src(id) + v; }
        this.pending.clear();
      })
      .catch(() => {})
      .finally(() => { this.probing = false; });
  },
};

function renderLutGrid() {
  const host = $('optLut');
  const current = (S.style.image && S.style.image.lut) || 'none';
  // Rebuilding the <img> tags on every call cancels whatever they were
  // mid-loading and restarts it — with 32 thumbnails that never lets a single
  // one finish (confirmed live: naturalWidth stayed 0 forever). Build the
  // cards ONCE; later calls just move the `.on` class.
  // NOTE: an earlier version of this comment claimed this function "reruns on
  // every poll tick (~2s)". It does not — poll() only reaches renderImagePanel()
  // via applyState(), which is gated on the state signature changing (see
  // poll()). That stale claim is why the thumbnail retry was first hung here
  // and silently never ran; the retry now lives in poll() itself.
  if (host.children.length === LUT_CATALOG.length) {
    for (const card of host.children) card.classList.toggle('on', card.dataset.id === current);
    LUT_THUMBS.retry();
    return;
  }
  host.innerHTML = '';
  for (const l of LUT_CATALOG) {
    const card = el('div', `lut-thumb${l.id === current ? ' on' : ''}`, host);
    card.dataset.id = l.id;
    const img = document.createElement('img');
    img.src = `media/.preview_cache/luts/${l.id}.jpg`;
    // alt vazio de propósito: enquanto lut_thumbs.py ainda não escreveu a
    // miniatura, o navegador mostrava o ícone de imagem quebrada + o nome —
    // parecia picker quebrado (relato de 2026-09-01). Com alt vazio fica só a
    // placa escura do card até a miniatura chegar (o retry a traz sozinho).
    img.alt = '';
    img.title = l.name;
    // Miniatura ainda não gerada (ou 404): esconder o <img> em vez de deixar o
    // navegador desenhar o ícone de imagem quebrada — é o que fazia o picker
    // parecer estragado antes do lut_thumbs.py rodar (relato 2026-09-01).
    img.addEventListener('error', () => { img.style.visibility = 'hidden'; });
    img.addEventListener('load', () => { img.style.visibility = 'visible'; });
    img.loading = 'lazy';
    // No {once:true}: a card re-armed by LUT_THUMBS.retry() must still be able
    // to fail again (and be re-parked) instead of falling back to the
    // browser's broken-image icon. The attempt cap in fail() is what stops it.
    img.addEventListener('error', () => LUT_THUMBS.fail(l.id, img));
    card.appendChild(img);
    el('span', '', card).textContent = l.name;
  }
}

$('optLut').addEventListener('click', (e) => {
  const card = e.target.closest('.lut-thumb');
  if (!card) return;
  S.style.image.lut = card.dataset.id;
  renderLutGrid();
  LUT_ENGINE.setActive(card.dataset.id);
  refreshHeader();
});

const LUT_ENGINE = (() => {
  let gl = null, program = null, videoTex = null, lutTex = null;
  let uLutSizeLoc = null;
  let activeId = 'none';
  let rafId = null;
  let webglFailed = false;
  const cache = {}; // id -> {size, arr}

  const canvasEl = () => $('lutCanvas');

  function compile(type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      console.error('LUT shader compile error:', gl.getShaderInfoLog(sh));
      return null;
    }
    return sh;
  }

  function initGL() {
    if (gl) return true;
    if (webglFailed) return false;
    const c = canvasEl();
    gl = c.getContext('webgl2', {premultipliedAlpha: false});
    if (!gl) { webglFailed = true; return false; }
    const vsSrc = '#version 300 es\n'
      + 'in vec2 aPos; out vec2 vUv;\n'
      + 'void main(){ vUv = aPos*0.5+0.5; vUv.y = 1.0-vUv.y; gl_Position = vec4(aPos,0.0,1.0); }';
    // uvw offset/scale is the standard half-texel correction so the LUT's
    // outer cube FACES (not just centers) map to 0..1 input range exactly.
    const fsSrc = '#version 300 es\n'
      + 'precision highp float;\n'
      + 'uniform sampler2D uVideo; uniform highp sampler3D uLut; uniform float uLutSize;\n'
      + 'in vec2 vUv; out vec4 outColor;\n'
      + 'void main(){\n'
      + '  vec4 c = texture(uVideo, vUv);\n'
      + '  float scale = (uLutSize - 1.0) / uLutSize;\n'
      + '  float offset = 1.0 / (2.0 * uLutSize);\n'
      + '  vec3 uvw = clamp(c.rgb, 0.0, 1.0) * scale + offset;\n'
      + '  outColor = vec4(texture(uLut, uvw).rgb, c.a);\n'
      + '}';
    const vs = compile(gl.VERTEX_SHADER, vsSrc);
    const fs = compile(gl.FRAGMENT_SHADER, fsSrc);
    if (!vs || !fs) { webglFailed = true; return false; }
    program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('LUT program link error:', gl.getProgramInfoLog(program));
      webglFailed = true;
      return false;
    }
    gl.useProgram(program);
    const posBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(program, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    videoTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, videoTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    lutTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_3D, lutTex);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    gl.uniform1i(gl.getUniformLocation(program, 'uVideo'), 0);
    gl.uniform1i(gl.getUniformLocation(program, 'uLut'), 1);
    uLutSizeLoc = gl.getUniformLocation(program, 'uLutSize');
    return true;
  }

  // Standard .cube (Adobe/DaVinci/CapCut-compatible) parser: TITLE/DOMAIN_*
  // lines are metadata, LUT_3D_SIZE gives the cube edge N, then N^3 "R G B"
  // rows with red varying fastest — same order WebGL2's texImage3D expects
  // for a (N,N,N) TEXTURE_3D, so the parsed array copies straight across
  // with no reshuffling.
  function parseCube(text) {
    let size = 0;
    const data = [];
    const lines = text.split('\n');
    for (const raw of lines) {
      const line = raw.trim();
      if (!line || line[0] === '#') continue;
      if (line.startsWith('TITLE')) continue;
      if (line.startsWith('LUT_3D_SIZE')) { size = parseInt(line.split(/\s+/)[1], 10); continue; }
      if (line.startsWith('DOMAIN_') || line.startsWith('LUT_1D_SIZE')) continue;
      const parts = line.split(/\s+/).map(Number);
      if (parts.length === 3 && parts.every((n) => !Number.isNaN(n))) data.push(parts);
    }
    if (!size || data.length !== size * size * size) return null;
    const arr = new Uint8Array(size * size * size * 3);
    for (let i = 0; i < data.length; i++) {
      arr[i * 3] = Math.round(Math.min(1, Math.max(0, data[i][0])) * 255);
      arr[i * 3 + 1] = Math.round(Math.min(1, Math.max(0, data[i][1])) * 255);
      arr[i * 3 + 2] = Math.round(Math.min(1, Math.max(0, data[i][2])) * 255);
    }
    return {size, arr};
  }

  async function loadLut(id) {
    if (cache[id]) return cache[id];
    const entry = LUT_CATALOG.find((l) => l.id === id);
    if (!entry || !entry.file) return null;
    let res;
    try { res = await fetch(`/assets/luts/${entry.file}`); }
    catch (e) { console.error('LUT fetch failed', entry.file, e); return null; }
    if (!res.ok) { console.error('LUT fetch failed', entry.file, res.status); return null; }
    const parsed = parseCube(await res.text());
    if (!parsed) { console.error('LUT parse failed (bad .cube?)', entry.file); return null; }
    cache[id] = parsed;
    return parsed;
  }

  // The canvas has no useful CSS size of its own — `object-fit`-style sizing
  // for a 9:16 clip inside a max-height/max-width box is exactly what the
  // <video> element's own layout already solved, so just copy its rendered
  // box every time it might have changed instead of re-deriving the same
  // constraint in CSS.
  function syncRect() {
    const c = canvasEl();
    const vRect = video.getBoundingClientRect();
    const parent = video.offsetParent;
    const pRect = parent ? parent.getBoundingClientRect() : {left: 0, top: 0};
    c.style.left = `${vRect.left - pRect.left}px`;
    c.style.top = `${vRect.top - pRect.top}px`;
    c.style.width = `${vRect.width}px`;
    c.style.height = `${vRect.height}px`;
    // O transporte acompanha a LARGURA do vídeo: uma barra de 711px sob um
    // vídeo de 512px lia como dois blocos soltos. Aqui já temos a caixa
    // renderizada do vídeo, que é a única fonte confiável dela (a proporção
    // decide qual dos dois tetos morde).
    document.documentElement.style.setProperty('--player-w', `${Math.round(vRect.width)}px`);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(vRect.width * dpr));
    const h = Math.max(1, Math.round(vRect.height * dpr));
    if (c.width !== w || c.height !== h) {
      c.width = w; c.height = h;
      if (gl) gl.viewport(0, 0, w, h);
    }
  }

  function drawFrame() {
    if (!gl || activeId === 'none' || video.readyState < 2) return;
    gl.useProgram(program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, videoTex);
    try {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
    } catch (e) { return; } // e.g. a cross-origin/tainted frame mid-load — skip this tick
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_3D, lutTex);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  function loop() { drawFrame(); rafId = requestAnimationFrame(loop); }
  function start() { if (!rafId) rafId = requestAnimationFrame(loop); }
  function stop() { if (rafId) { cancelAnimationFrame(rafId); rafId = null; } }

  async function setActive(id) {
    activeId = id;
    const c = canvasEl();
    if (id === 'none') {
      c.classList.add('hidden');
      stop();
      return;
    }
    if (!initGL()) {
      toast('Prévia de LUT precisa de WebGL2, indisponível neste navegador', 3000);
      c.classList.add('hidden');
      return;
    }
    const lut = await loadLut(id);
    if (!lut || activeId !== id) return; // user picked a different one mid-fetch
    syncRect();
    gl.bindTexture(gl.TEXTURE_3D, lutTex);
    // A LUT cube is RGB (3 bytes/texel); WebGL's default UNPACK_ALIGNMENT (4)
    // assumes each row is padded to a multiple of 4 bytes. A 33-size LUT
    // (the common DaVinci/CapCut/Adobe default) has 33*3=99 bytes/row, not a
    // multiple of 4 — with the default alignment the driver expects a padded
    // (and therefore larger) buffer than what's actually provided and
    // texImage3D throws INVALID_OPERATION (confirmed live: canvas stayed
    // fully black, `gl.getError()` was 1282 right after this call, and
    // isolating the video-only draw path with no LUT worked fine). Every
    // size in this pack (17/33/65) has the same issue since none are
    // multiples of 4 at 3 bytes/texel.
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGB8, lut.size, lut.size, lut.size, 0, gl.RGB, gl.UNSIGNED_BYTE, lut.arr);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4); // restore default for the RGBA (4 bytes/texel) video uploads
    gl.useProgram(program);
    gl.uniform1f(uLutSizeLoc, lut.size);
    c.classList.remove('hidden');
    start();
  }

  return {setActive, syncRect};
})();

window.addEventListener('resize', () => LUT_ENGINE.syncRect());
// O player agora é elástico (abrir/fechar gaveta muda a altura do vídeo sem
// mexer na janela), então observar só o `resize` deixava o canvas do LUT
// desalinhado do vídeo. O observer cobre qualquer causa.
if (typeof ResizeObserver !== 'undefined') {
  new ResizeObserver(() => LUT_ENGINE.syncRect()).observe(video);
}
video.addEventListener('loadedmetadata', () => LUT_ENGINE.syncRect());

function updateImgDrawerHint() {
  const hint = $('imgDrawerHint');
  if (!hint) return;
  const moved = Object.entries(S.style.image || {}).filter(([k, v]) => k !== 'lut' && v).length;
  const lut = S.style.image && S.style.image.lut && S.style.image.lut !== 'none'
    ? styleLutName(S.style.image.lut) : null;
  const bits = [];
  if (moved) bits.push(`${moved} ajuste${moved > 1 ? 's' : ''}`);
  if (lut) bits.push(`filtro ${lut}`);
  hint.textContent = bits.length ? bits.join(' · ') : 'sem ajuste · sem filtro';
}
const styleLutName = (id) => {
  const found = (typeof LUT_CATALOG !== 'undefined' ? LUT_CATALOG : []).find((l) => l.id === id);
  return found ? found.name : id;
};

function renderImagePanel() {
  if (typeof syncDrawerState === 'function') requestAnimationFrame(syncDrawerState);
  const show = S.tab === 1 && S.videoDuration > 0 && !!(S.style && S.style.image);
  $('imgAdjustPanel').classList.toggle('hidden', !show);
  if (show) {
    renderImageAdjustments();
    applyImagePreview();
    renderLutGrid();
    LUT_ENGINE.setActive((S.style.image && S.style.image.lut) || 'none');
  } else {
    video.style.filter = ''; // never leave a Fase-1 preview bleeding into Fase 2/Estilo
    LUT_ENGINE.setActive('none');
  }
}

$('imgReset').addEventListener('click', () => {
  const d = defaultStyle().image;
  S.style.image = {...d};
  renderImageAdjustments();
  applyImagePreview();
  renderLutGrid();
  LUT_ENGINE.setActive(S.style.image.lut);
  refreshHeader();
});

const accentUsed = () =>
  ACCENT_USERS.headlines.includes(S.style.headline)
  || ACCENT_USERS.captions.includes(S.style.captions);

function updateAccentNote() {
  const where = [
    ACCENT_USERS.headlines.includes(S.style.headline) && 'na headline',
    ACCENT_USERS.captions.includes(S.style.captions) && 'na legenda',
  ].filter(Boolean);
  $('accentNote').textContent = where.length
    ? `aplicada ${where.join(' e ')}`
    : 'os estilos escolhidos não usam destaque';
}

/* Separate from renderSetup so the live colour drag can refresh it without
 * rebuilding every demo. Skipping it there left the footer naming the previous
 * colour while the previews already showed the new one. */
function updateSummary() {
  // the fixed elements are not a choice, so they don't belong in a summary of
  // what the user picked — they get their own trailing clause instead
  const on = STYLE_CATALOG.elements.filter((e) => !e.always && S.style.elements[e.id]);
  const fixed = STYLE_CATALOG.elements.filter((e) => e.always).map((e) => e.name);
  const accentBit = accentUsed() ? ` · destaque ${accentName(S.style.accent)}` : '';
  $('setupSummary').textContent =
    `${styleName('edits', S.style.edit)} · headline ${styleName('headlines', S.style.headline)} (${styleName('headlineFonts', S.style.headlineFont)})` +
    ` · legenda ${styleName('captions', S.style.captions)}${accentBit} · ` +
    (on.length ? on.map((e) => e.name).join(', ') : 'sem elementos extras') +
    (fixed.length ? ` · sempre: ${fixed.join(', ').toLowerCase()}` : '');
}

// The Estilo tab. It sits BETWEEN the phases and is always reachable once the
// catalog applies to this job: changing the caption style after Fase 2 exists,
// or ticking one more element and re-rendering, is normal editing — not a
// decision the user gets exactly one shot at.
let wasShowing = false; // gate was up on the previous render (for the re-fit)

function renderSetup() {
  const show = S.tab === 'style';
  $('styleSetup').classList.toggle('hidden', !show);
  const hasVideo = S.videoDuration > 0;
  $('stage').classList.toggle('hidden', !hasVideo);
  $('emptyState').classList.toggle('hidden', hasVideo);

  if (!show) {
    capAnims = []; // stop stepping demos that are not on screen
    // the timeline was display:none while the tab was up, so its panel had no
    // width to fit against — re-fit once it is back on screen
    if (wasShowing && hasVideo) requestAnimationFrame(() => { fitZoom(); renderAll(); });
    wasShowing = false;
    return;
  }
  if (!wasShowing) $('styleSetup').scrollTop = 0; // open at the top, always
  wasShowing = true;

  $('setupGo').textContent = S.state.awaitingStyle
    ? 'Confirmar e iniciar a Fase 2'
    : 'Salvar e refazer a Fase 2';

  capAnims = [];
  const radios = (host, group, chosen) => {
    const opts = STYLE_CATALOG[group];
    host.innerHTML = '';
    for (const o of opts) {
      const card = el('div', `opt${o.id === chosen ? ' on' : ''}`, host);
      card.dataset.group = group;
      card.dataset.id = o.id;
      // headline previews are two short lines — they do not need the caption
      // box's height, and with four groups on one screen that height is scarce
      const kind = o.mock ? 'frame' : (o.hl || o.hlbox || o.font) ? 'cap hlbox' : 'cap';
      const prev = el('div', `opt-preview ${kind}`, card);
      if (o.demo) capAnims.push(CAP_BUILDERS[o.demo](prev));
      else if (o.hl) buildHeadlineDemo(prev, o.hl, S.style.headlineFont, S.style.headlineText || HEADLINE_TEXT,
        o.hl === 'personalizada' ? S.style.headlineCustom : null);
      // font cards render the CURRENTLY chosen headline style in THIS font —
      // real type, not a generic "Aa" swatch, and it stays in sync when the
      // style above changes without needing a second render path.
      else if (o.font) buildHeadlineDemo(prev, S.style.headline, o.font, S.style.headlineText || HEADLINE_TEXT,
        S.style.headline === 'personalizada' ? S.style.headlineCustom : null);
      else if (o.stat) {
        const step = buildStaticDemo(prev, o.stat);
        if (step) capAnims.push(step);
      }
      else if (o.none) prev.innerHTML = NONE_MARK;
      else prev.innerHTML = o.mock || '';
      // Only the abstract mockups get a title. A card that renders the real
      // caption or the real headline is already labelled — by itself. Font
      // cards are the exception: every card shows the identical headline
      // shape, so only the name tells the faces apart.
      if (o.mock || o.none || o.font) el('div', 'opt-name', card).textContent = o.name;
      el('div', 'opt-mark', card);
    }
    // the ghost only earns its space where there is a single option to explain
    if (opts.length < 2) el('div', 'opt ghost', host).textContent = 'mais estilos em breve';
  };
  // set BEFORE the demos are built: buildHeadlineDemo reads the accent through
  // var(), so the variable has to be in place when the previews first paint
  applyAccent();

  radios($('optEdit'), 'edits', S.style.edit);
  radios($('optHeadline'), 'headlines', S.style.headline);
  renderHeadlineCustom();
  radios($('optHeadlineFont'), 'headlineFonts', S.style.headlineFont);
  radios($('optCaptions'), 'captions', S.style.captions);
  renderAccents();

  const host = $('optElements');
  host.innerHTML = '';
  for (const e of STYLE_CATALOG.elements) {
    const on = e.always || !!S.style.elements[e.id];
    const row = el('div', `chk${on ? ' on' : ''}${e.always ? ' fixed' : ''}`, host);
    row.dataset.id = e.id;
    if (e.always) row.title = 'Sempre aplicado — não é opção';
    el('div', 'chk-box', row);
    el('div', 'chk-ico', row).innerHTML = e.icon || '';
    el('div', 'chk-name', row).textContent = e.name;
    if (e.always) el('div', 'chk-fixed', row).textContent = 'sempre';
  }

  updateSummary();
}

$('styleSetup').addEventListener('click', (e) => {
  // the accent controls manage themselves (live, no rebuild) — keep the card
  // handler off them, or a click in the hex field would count as a style pick
  if (e.target.closest('#optAccent')) return;
  const opt = e.target.closest('.opt:not(.ghost)');
  if (opt) {
    const key = {edits: 'edit', headlines: 'headline', headlineFonts: 'headlineFont', captions: 'captions'}[opt.dataset.group];
    S.style[key] = opt.dataset.id;
    renderSetup();
    return;
  }
  const chk = e.target.closest('.chk:not(.fixed)');
  if (chk) {
    S.style.elements[chk.dataset.id] = !S.style.elements[chk.dataset.id];
    renderSetup();
  }
});

$('headlineText').addEventListener('input', () => {
  S.style.headlineText = $('headlineText').value;
  renderSetup();
});
for (const key of ['voice', 'music', 'sfx']) $(key + 'Gain').addEventListener('input', () => {
  S.style.audioMix = S.style.audioMix || {voiceDb: 0, musicDb: 0, sfxDb: 0};
  S.style.audioMix[key + 'Db'] = Number($(key + 'Gain').value);
  $(key + 'GainValue').textContent = `${$(key + 'Gain').value} dB`;
});
// Painel da headline "Personalizada" — aparece só quando ela está escolhida.
const HL_CUSTOM_FIELDS = ['color', 'accentColor', 'weight1', 'weight2', 'maxFontPx', 'paddingTop'];
function renderHeadlineCustom() {
  const on = S.style.headline === 'personalizada';
  $('hlCustom').hidden = !on;
  if (!on) return;
  for (const k of HL_CUSTOM_FIELDS) {
    const el = $('hlc_' + k);
    if (el && document.activeElement !== el) el.value = S.style.headlineCustom[k];
  }
  $('hlCustomPreview').style.setProperty('--c1', S.style.headlineCustom.color);
  $('hlCustomPreview').style.setProperty('--c2', S.style.headlineCustom.accentColor);
  $('hlCustomPreview').style.setProperty('--w1', S.style.headlineCustom.weight1);
  $('hlCustomPreview').style.setProperty('--w2', S.style.headlineCustom.weight2);
}
for (const k of HL_CUSTOM_FIELDS) {
  const el = $('hlc_' + k);
  if (!el) continue;
  el.addEventListener('input', () => {
    const raw = el.type === 'color' ? el.value : +el.value;
    S.style.headlineCustom[k] = el.type === 'color' ? raw : (Number.isFinite(raw) ? raw : S.style.headlineCustom[k]);
    // Os cartões desenham a headline REAL, então eles mudam ao vivo junto.
    // renderSetup() é quem reconstrói o grid — `radios` é local dela, não dá
    // para chamar daqui. renderHeadlineCustom() não repõe o valor do campo em
    // foco, então digitar continua funcionando durante o redesenho.
    renderSetup();
  });
}
$('setupGo').addEventListener('click', async () => {
  S.style.note = $('setupNote').value.trim();
  const rerender = !S.state.awaitingStyle;
  const payload = {
    // a save with Fase 2 already on disk is a RE-RENDER request, not a first
    // pick — the skill has to know which of the two it is looking at
    type: 'style-setup',
    rerender,
    edit: S.style.edit,
    editName: styleName('edits', S.style.edit),
    headline: S.style.headline,
    headlineText: $('headlineText').value.trim(),
    audioMix: S.style.audioMix || {voiceDb: 0, musicDb: 0, sfxDb: 0},
    headlineName: styleName('headlines', S.style.headline),
    headlineFont: S.style.headlineFont,
    // Só quando a headline É personalizada: caso contrário a aparência é o
    // preset e mandar números aqui convidaria o agente a inventar um lugar
    // para eles — mesma lógica do `accentUsed`.
    ...(S.style.headline === 'personalizada' ? {headlineCustom: {...S.style.headlineCustom}} : {}),
    headlineFontName: styleName('headlineFonts', S.style.headlineFont),
    captions: S.style.captions,
    captionsName: styleName('captions', S.style.captions),
    accent: S.style.accent,
    accentName: accentName(S.style.accent),
    // whether the picked styles actually paint it — so the skill does not go
    // hunting for an accent in a look that has none
    accentUsed: accentUsed(),
    elements: forceAlwaysOn({ ...S.style.elements }),
    elementNames: STYLE_CATALOG.elements
      .filter((e) => S.style.elements[e.id])
      .map((e) => e.name),
    note: S.style.note,
  };
  const res = await fetch('api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const savedResult = await res.json();
  if (!res.ok || !savedResult.ok) { toast(savedResult.error || 'Não foi possível salvar os ajustes', 4000); return; }
  if (savedResult.ok) {
    S.savedPending = true;
    renderSetup();
    refreshHeader();
  } else {
    toast('Erro ao enviar — o servidor está de pé?', 4000);
  }
});

function renderClips() {
  laneVideo.innerHTML = '';
  const dl = draftLayout();
  const rl = renderedLayout();
  const editable = S.tab === 1;
  dl.forEach((r, i) => {
    if (r.removed && r.dur === 0) {
      // removed: show a slim ghost at its slot
      const g = el('div', 'clip removed', laneVideo);
      g.style.left = `${r.out * S.pps}px`;
      g.style.width = `${Math.max((r.orig.end - r.orig.start) * S.pps * 0.4, 34)}px`;
      g.dataset.i = i;
      g.title = 'clique e pressione delete para restaurar';
      return;
    }
    const c = el('div', 'clip', laneVideo);
    c.style.left = `${r.out * S.pps}px`;
    c.style.width = `${Math.max(r.dur * S.pps, 8)}px`;
    c.dataset.i = i;
    if (i === S.selected) c.classList.add('selected');
    if (r.start !== r.orig.start || r.end !== r.orig.end) c.classList.add('dirty');

    // filmstrip from the rendered cut
    if (S.thumbCount > 0 && rl[i]) {
      const strip = el('div', 'thumbs', c);
      const first = Math.floor(rl[i].out / THUMB_EVERY);
      const n = Math.ceil(rl[i].dur / THUMB_EVERY) + 1;
      for (let k = 0; k < n; k++) {
        const idx = first + k + 1; // ffmpeg %04d is 1-based
        if (idx > S.thumbCount) break;
        const img = el('img', '', strip);
        img.src = `gen/thumbs/${String(idx).padStart(4, '0')}.jpg`;
        img.style.width = `${THUMB_EVERY * S.pps}px`;
        img.style.objectFit = 'cover';
      }
    }
    const lab = el('div', 'clip-label', c);
    lab.textContent = `${r.beat || r.source} `;
    const dur = el('div', 'clip-dur', c);
    dur.textContent = `${r.dur.toFixed(2)}s`;

    if (editable) {
      el('div', 'handle l', c).dataset.i = i;
      el('div', 'handle r', c).dataset.i = i;
    }
  });
}

/* J-cut audio lanes.
 * The point is legibility, not decoration: on one lane an overlap is invisible,
 * because two blocks that overlap in time just look like one continuous block.
 * Alternating takes across A1/A2 is what makes the "J" readable — exactly how it
 * reads in Premiere. The overlap itself gets a marker on the incoming block, so
 * the user can see how many frames of voice arrive before the picture.
 */
function renderJcutAudio() {
  const t1 = $('trkAudioA1'), t2 = $('trkAudioA2');
  const l1 = $('laneAudioA1'), l2 = $('laneAudioA2');
  const btn = $('jcutToggle');
  l1.innerHTML = ''; l2.innerHTML = '';

  const has = !!(S.jcut && S.jcut.length && S.tab !== 'style');
  // the caret only appears when there is a J-cut to expand; otherwise the chip
  // stays an ordinary track icon
  btn.classList.toggle('disclose', has);
  btn.disabled = !has;
  btn.setAttribute('aria-expanded', String(has && S.jcutOpen));
  btn.title = !has ? 'Áudio (mix)'
    : S.jcutOpen ? 'Áudio (mix) — recolher as faixas do J-cut (A1/A2)'
                 : 'Áudio (mix) — expandir as faixas do J-cut (A1/A2)';

  const on = has && S.jcutOpen;
  t1.classList.toggle('hidden', !on);
  t2.classList.toggle('hidden', !on);
  if (!on) return;

  // drawn off the DRAFT layout so the blocks move with the user's trims
  draftLayout().forEach((r, i) => {
    if (r.removed && r.adur === 0) return;
    const lane = i % 2 === 0 ? l1 : l2;
    const b = el('div', 'ablock', lane);
    b.style.left = `${r.aout * S.pps}px`;
    b.style.width = `${Math.max(r.adur * S.pps, 6)}px`;
    el('div', 'ablock-label', b).textContent = r.beat || r.source || '';

    // the lead: sound already playing while the previous take is still on screen
    if (r.lead > 1e-6) {
      const ov = el('div', 'ablock-lead', b);
      ov.style.width = `${r.lead * S.pps}px`;
    }
    const tf = (S.jcut[i] || {}).tail_trim_frames || 0;
    let tip = `${r.beat || r.source}\náudio ${r.adur.toFixed(2)}s`;
    if (r.lead > 1e-6) {
      tip += `\nJ-cut: ${Math.round(r.lead * S.fps)}f (${Math.round(r.lead * 1000)}ms) `
           + 'de voz antes da imagem';
    }
    if (tf) tip += `\ncauda aparada ${tf}f`;
    b.title = tip;
  });
}

function renderChips() {
  const phase2 = S.tab === 2;
  $('trkCaptions').classList.toggle('hidden', !phase2);
  insertTracksEl.classList.toggle('hidden', !phase2);
  insertTracksEl.innerHTML = '';
  if (!phase2) return;

  laneCaptions.innerHTML = '';
  for (const c of S.captions) {
    const start = renderedToDraft(c.start);
    const end = renderedToDraft(c.end);
    const chip = el('div', 'chip caption', laneCaptions);
    chip.style.left = `${start * S.pps}px`;
    chip.style.width = `${Math.max((end - start) * S.pps, 6)}px`;
    chip.textContent = c.text;
    chip.title = c.text;
  }

  // TEXT and IMAGE get their own tracks — a headline and a photo are different
  // kinds of edit, and mixing them on one lane hid the images entirely.
  const isText = (c) => c.kind === 'hook' || c.kind === 'word';
  const groups = [
    { icon: 'text', cls: 'teal', items: S.insertsDraft.map((c, i) => ({ c, i })).filter(({ c }) => isText(c)) },
    { icon: 'inserts', cls: 'orange', items: S.insertsDraft.map((c, i) => ({ c, i })).filter(({ c }) => !isText(c)) },
  ];

  for (const g of groups) {
    if (!g.items.length) continue;
    // overlapping elements stack onto extra lanes within the same group
    const order = [...g.items].sort((a, b) => a.c.start - b.c.start || a.c.end - b.c.end);
    const trackEnd = [];
    const assign = new Map();
    for (const { c, i } of order) {
      let t = trackEnd.findIndex((end) => c.start >= end - 1e-6);
      if (t < 0) { t = trackEnd.length; trackEnd.push(0); }
      trackEnd[t] = c.end;
      assign.set(i, t);
    }
    const lanes = [];
    for (let t = 0; t < Math.max(trackEnd.length, 1); t++) {
      const trk = el('div', 'track', insertTracksEl);
      const lab = el('div', 'track-label', trk);
      // only the first lane of a group carries the icon; the rest are continuations
      if (t === 0) el('span', `tl-chip ${g.cls}`, lab).innerHTML = ICON[g.icon];
      lanes.push(el('div', 'lane', trk));
    }
    for (const { c, i } of g.items) {
      const chip = el('div', `chip insert ${isText(c) ? 'hook' : ''}`, lanes[assign.get(i) ?? 0]);
      chip.style.left = `${c.start * S.pps}px`;
      chip.style.width = `${Math.max((c.end - c.start) * S.pps, 10)}px`;
      chip.textContent = c.label;
      chip.title = c.label;
      chip.dataset.i = i;
      if (c.start !== c.orig.start || c.end !== c.orig.end) chip.classList.add('dirty');
      el('div', 'handle l', chip).dataset.i = i;
      el('div', 'handle r', chip).dataset.i = i;
    }
  }

  // soundtrack → its own read-only track, one chip spanning the whole video
  const st = S.editData && S.editData.soundtrack;
  if (st && st.enabled) {
    const trk = el('div', 'track', insertTracksEl);
    el('span', 'tl-chip olive', el('div', 'track-label', trk)).innerHTML = ICON.music;
    const lane = el('div', 'lane', trk);
    const chip = el('div', 'chip music', lane);
    const dur = S.editData.durationSec || S.videoDuration || draftTotal();
    chip.style.left = '0px';
    chip.style.width = `${Math.max(dur * S.pps, 10)}px`;
    const name = (st.file || 'trilha.mp3').split('/').pop();
    const vol = st.volume != null ? `  ·  vol ${st.volume}` : '';
    chip.textContent = `${name}${vol}`;
    chip.title = chip.textContent;
  }
}

// ---------- canvases (viewport-sized, redrawn on scroll) ----------
function canvasSetup(cv, lane) {
  const dpr = window.devicePixelRatio || 1;
  const w = panel.clientWidth;
  const h = lane.clientHeight;
  cv.width = w * dpr;
  cv.height = h * dpr;
  cv.style.width = `${w}px`;
  cv.style.height = `${h}px`;
  cv.style.position = 'absolute';
  // lanes start LABEL_W into the scrolled content — offset the viewport-sized
  // canvas so it covers exactly the visible strip of the lane
  const left = Math.max(0, panel.scrollLeft - LABEL_W);
  cv.style.left = `${left}px`;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h, x0: left };
}

function drawRuler() {
  const { ctx, w, h, x0 } = canvasSetup(rulerCv, rulerCv.parentElement);
  const laneX0 = x0; // canvas positioned at scrollLeft within lane coords
  const t0 = laneX0 / S.pps;
  const t1 = (laneX0 + w) / S.pps;
  // tick step: nice value ≥ 60px apart
  const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120];
  const step = steps.find((s) => s * S.pps >= 56) || 300;
  ctx.font = '600 9.5px Poppins, sans-serif';
  ctx.fillStyle = 'rgba(139,148,163,0.9)';
  ctx.strokeStyle = 'rgba(255,255,255,0.14)';
  for (let t = Math.floor(t0 / step) * step; t <= t1; t += step) {
    if (t < 0) continue;
    const x = t * S.pps - laneX0;
    ctx.beginPath();
    ctx.moveTo(x, h - 7);
    ctx.lineTo(x, h);
    ctx.stroke();
    ctx.fillText(fmt(t), x + 3, h - 9);
    // minor ticks
    const minor = step / 5;
    for (let m = 1; m < 5; m++) {
      const xm = (t + m * minor) * S.pps - laneX0;
      ctx.beginPath();
      ctx.moveTo(xm, h - 3.5);
      ctx.lineTo(xm, h);
      ctx.stroke();
    }
  }
}

function drawWave() {
  if (!S.wave) return;
  const { ctx, w, h, x0 } = canvasSetup(waveCv, laneAudio);
  const mid = h / 2;
  ctx.strokeStyle = 'rgba(168,194,43,0.06)';
  ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(w, mid); ctx.stroke();
  ctx.fillStyle = 'rgba(168,194,43,0.75)';
  const pps = S.wave.peaksPerSec;
  for (let px = 0; px < w; px++) {
    const tDraft = (x0 + px) / S.pps;
    if (tDraft > draftTotal()) break;
    const tRend = draftToRendered(tDraft);
    const idx = Math.floor(tRend * pps);
    if (idx < 0 || idx >= S.wave.max.length) continue;
    const hi = (S.wave.max[idx] / 100) * (mid - 2);
    const lo = (S.wave.min[idx] / 100) * (mid - 2);
    ctx.fillRect(px, mid - hi, 1, Math.max(1, hi - lo));
  }
}

// Vertical sources get the split layout (player right, editor left) — stacked,
// a 9:16 clip is tiny above a full-width timeline. Driven off the decoded frame
// size, so it works for cut.mp4 and the Phase-2 render alike.
function applyOrientation() {
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (!w || !h) return;
  const portrait = h > w;
  if (portrait === document.body.classList.contains('portrait')) return;
  document.body.classList.toggle('portrait', portrait);
  // the timeline's width just changed — re-fit after layout settles
  requestAnimationFrame(() => { fitZoom(); renderAll(); });
}
video.addEventListener('loadedmetadata', applyOrientation);

// ---------- needle / playback sync ----------
function positionNeedle() {
  const tDraft = renderedToDraft(video.currentTime || 0);
  const x = LABEL_W + tDraft * S.pps;
  needle.style.left = `${x}px`;
  needle.style.visibility = x < panel.scrollLeft + LABEL_W ? 'hidden' : '';
  $('timeNow').textContent = fmt(tDraft);
  $('timeTotal').textContent = fmt(draftTotal() || S.videoDuration);
}
function rafLoop() {
  if (capAnims.length) {
    const now = performance.now() / 1000;
    for (const step of capAnims) step(now);
  }
  positionNeedle();
  if (!video.paused && !video.ended) {
    // keep needle visible
    const x = LABEL_W + renderedToDraft(video.currentTime) * S.pps;
    const right = panel.scrollLeft + panel.clientWidth;
    if (x > right - 80) panel.scrollLeft = x - panel.clientWidth * 0.25;
  }
  requestAnimationFrame(rafLoop);
}

function seekDraft(tDraft) {
  tDraft = Math.max(0, Math.min(tDraft, draftTotal() || S.videoDuration));
  video.currentTime = draftToRendered(tDraft);
  positionNeedle();
}

// ---------- interactions ----------
let drag = null; // {type:'scrub'|'trim'|'chip-trim'|'chip-move', ...}

panel.addEventListener('pointerdown', (e) => {
  // The gutter is chrome, not timeline. Without this guard a pointerdown on a
  // track icon fell through to the scrub branch below, which both yanked the
  // needle to 0 (the gutter is left of t=0, so it computes a negative time) and
  // called setPointerCapture on the panel — retargeting the following click and
  // swallowing it, so a real click on the A1/A2 disclosure never fired while a
  // programmatic .click() did.
  if (e.target.closest('.track-label') || e.target.closest('button')) return;

  const handle = e.target.closest('.handle');
  const clip = e.target.closest('.clip');
  const chip = e.target.closest('.chip.insert');

  if (handle && clip && S.tab === 1) {
    const i = +handle.dataset.i;
    drag = { type: 'trim', i, side: handle.classList.contains('l') ? 'l' : 'r', x0: e.clientX, r: { ...S.draft[i] } };
    try { panel.setPointerCapture(e.pointerId); } catch (err) { /* synthetic/touch */ }
    e.preventDefault();
    return;
  }
  if (handle && chip && S.tab === 2) {
    const i = +handle.dataset.i;
    drag = { type: 'chip-trim', i, side: handle.classList.contains('l') ? 'l' : 'r', x0: e.clientX, c: { ...S.insertsDraft[i] } };
    try { panel.setPointerCapture(e.pointerId); } catch (err) { /* synthetic/touch */ }
    e.preventDefault();
    return;
  }
  if (chip && S.tab === 2) {
    const i = +chip.dataset.i;
    drag = { type: 'chip-move', i, x0: e.clientX, c: { ...S.insertsDraft[i] } };
    try { panel.setPointerCapture(e.pointerId); } catch (err) { /* synthetic/touch */ }
    e.preventDefault();
    return;
  }
  if (clip) {
    S.selected = +clip.dataset.i;
    renderClips();
    return;
  }
  // background / ruler → scrub
  const rect = timelineEl.getBoundingClientRect();
  const t = (e.clientX - rect.left - LABEL_W) / S.pps;
  drag = { type: 'scrub' };
  seekDraft(t);
  try { panel.setPointerCapture(e.pointerId); } catch (err) { /* synthetic/touch */ }
});

panel.addEventListener('pointermove', (e) => {
  if (!drag) return;
  if (drag.type === 'scrub') {
    const rect = timelineEl.getBoundingClientRect();
    seekDraft((e.clientX - rect.left - LABEL_W) / S.pps);
    return;
  }
  const dt = (e.clientX - drag.x0) / S.pps;

  if (drag.type === 'trim') {
    const r = S.draft[drag.i];
    if (drag.side === 'l') {
      r.start = Math.min(Math.max(0, drag.r.start + dt), r.end - MIN_SEG);
    } else {
      r.end = Math.max(drag.r.end + dt, r.start + MIN_SEG);
      const srcDur = (S.state.sourceDurations || {})[r.source];
      if (srcDur) r.end = Math.min(r.end, srcDur);
    }
    renderClips();
    drawWave();
    refreshHeader();
    const d = drag.side === 'l' ? r.start - r.orig.start : r.end - r.orig.end;
    showTooltip(e, `${fmt(r.start)} → ${fmt(r.end)} <span class="delta">(${d >= 0 ? '+' : ''}${d.toFixed(2)}s)</span>`);
  } else if (drag.type === 'chip-trim') {
    const c = S.insertsDraft[drag.i];
    if (drag.side === 'l') c.start = Math.min(Math.max(0, drag.c.start + dt), c.end - 0.15);
    else c.end = Math.max(drag.c.end + dt, c.start + 0.15);
    renderChips();
    refreshHeader();
    showTooltip(e, `${fmt(c.start)} → ${fmt(c.end)}`);
  } else if (drag.type === 'chip-move') {
    const c = S.insertsDraft[drag.i];
    const dur = drag.c.end - drag.c.start;
    c.start = Math.max(0, drag.c.start + dt);
    c.end = c.start + dur;
    renderChips();
    refreshHeader();
    showTooltip(e, `${fmt(c.start)} → ${fmt(c.end)}`);
  }
});

['pointerup', 'pointercancel'].forEach((ev) =>
  panel.addEventListener(ev, () => { drag = null; hideTooltip(); })
);

// double-click a clip = reset it
laneVideo.addEventListener('dblclick', (e) => {
  const clip = e.target.closest('.clip');
  if (!clip) return;
  const r = S.draft[+clip.dataset.i];
  r.start = r.orig.start; r.end = r.orig.end; r.removed = false;
  renderAll(); refreshHeader();
});

// keyboard
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'm' || e.key === 'M') {
    e.preventDefault();
    toggleMark();
    return;
  }
  if (e.key === 'Escape' && !$('helpModal').classList.contains('hidden')) {
    toggleHelp(false);
    return;
  }
  if (e.key === '?' || (e.key === '/' && e.shiftKey)) {
    e.preventDefault();
    toggleHelp($('helpModal').classList.contains('hidden'));
    return;
  }
  if (e.key === 'Escape' && S.pendingIn != null) {
    S.pendingIn = null;
    renderNotes();
    toast('IN cancelado', 1600);
    return;
  }
  if (e.code === 'Space') {
    e.preventDefault();
    video.paused ? video.play() : video.pause();
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    const step = e.shiftKey ? 1 : 1 / S.fps;
    seekDraft(renderedToDraft(video.currentTime) + (e.key === 'ArrowRight' ? step : -step));
  } else if ((e.key === 'Delete' || e.key === 'Backspace') && S.selected >= 0 && S.tab === 1) {
    const r = S.draft[S.selected];
    r.removed = !r.removed;
    renderAll(); refreshHeader();
  }
});

// transport
$('btnPlay').innerHTML = ICON.play;
$('btnMute').innerHTML = ICON.vol;
$('btnPlay').addEventListener('click', () => {
  video.paused ? video.play() : video.pause();
});
video.addEventListener('play', () => { $('btnPlay').innerHTML = ICON.pause; });
video.addEventListener('pause', () => { $('btnPlay').innerHTML = ICON.play; });
video.addEventListener('ended', () => { $('btnPlay').innerHTML = ICON.play; });
$('btnMute').addEventListener('click', () => {
  video.muted = !video.muted;
  $('btnMute').innerHTML = video.muted ? ICON.mute : ICON.vol;
});
$('zoom').addEventListener('input', (e) => setZoom(+e.target.value));

// ---------- correction markers: button, chips, editor ----------
$('markIcon').innerHTML = ICON.flag;
$('btnMark').addEventListener('click', toggleMark);
$('laneNotes').addEventListener('click', (e) => {
  const chip = e.target.closest('.note-chip');
  if (chip) openNoteEditor(chip.dataset.id, false);
});
$('noteOk').addEventListener('click', () => {
  const n = S.notes.find((x) => x.id === S.editingNote);
  if (n) {
    let media;
    try { media = window.noteMediaControls.read(); }
    catch (error) { toast(error.message, 3000); return; }
    n.text = $('noteText').value.trim();
    if (!n.text) { toast('Escreva o ajuste desejado', 2000); return; }
    n.media = media;
  }
  S.editingNote = null;
  $('noteEditor').classList.add('hidden');
  renderNotes();
  refreshHeader();
});
$('noteDelete').addEventListener('click', () => {
  S.notes = S.notes.filter((x) => x.id !== S.editingNote);
  S.editingNote = null;
  $('noteEditor').classList.add('hidden');
  renderNotes();
  refreshHeader();
});
$('noteClose').addEventListener('click', closeNoteEditor);

// ---------- help modal (the old footer hint strip) ----------
function toggleHelp(open) {
  $('helpModal').classList.toggle('hidden', !open);
  $('helpBackdrop').classList.toggle('hidden', !open);
}
$('btnHelp').addEventListener('click', () => toggleHelp($('helpModal').classList.contains('hidden')));
$('helpClose').addEventListener('click', () => toggleHelp(false));
$('helpBackdrop').addEventListener('click', () => toggleHelp(false));
$('noteText').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { e.stopPropagation(); closeNoteEditor(); }
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); $('noteOk').click(); }
});
$('btnFit').addEventListener('click', () => { fitZoom(); renderAll(); });
panel.addEventListener('scroll', () => requestAnimationFrame(() => { drawRuler(); drawWave(); positionNeedle(); }));
// renderSetup too: the caption demos bake their scale from the box width, so a
// resize (or the short-pane media query kicking in) has to rebuild them
window.addEventListener('resize', () => { fitZoom(); renderAll(); renderSetup(); });

// tabs
document.querySelectorAll('.tab').forEach((tab) =>
  tab.addEventListener('click', () => {
    if (tab.disabled) return;
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    S.tab = tab.dataset.tab === 'style' ? 'style' : +tab.dataset.tab;
    S.selected = -1;
    updateVideoSrc(); // Fase 2 plays the Phase-2 render when available
    renderAll();
    renderSetup();
    renderImagePanel();
  })
);

// ---------- save / discard ----------
$('btnSave').addEventListener('click', async () => {
  const payload = { type: 'timeline-edits' };
  if (edlDirty()) {
    payload.edl = {
      ranges: S.draft.filter((r) => !r.removed).map((r) => ({
        source: r.source, start: +r.start.toFixed(3), end: +r.end.toFixed(3), beat: r.beat,
      })),
      removed: S.draft.filter((r) => r.removed).map((r) => ({ source: r.source, beat: r.beat, start: r.orig.start, end: r.orig.end })),
      changes: S.draft.filter((r) => !r.removed && (r.start !== r.orig.start || r.end !== r.orig.end)).map((r) => ({
        source: r.source, beat: r.beat,
        from: { start: r.orig.start, end: r.orig.end },
        to: { start: +r.start.toFixed(3), end: +r.end.toFixed(3) },
      })),
    };
  }
  if (insertsDirty()) {
    payload.editData = {
      inserts: S.insertsDraft.filter((c) => c.kind === 'insert').map((c) => ({ ref: c.ref, start: +c.start.toFixed(3), end: +c.end.toFixed(3) })),
      splitInserts: S.insertsDraft.filter((c) => c.kind === 'split').map((c) => ({ ref: c.ref, label: c.label, start: +c.start.toFixed(3), end: +c.end.toFixed(3) })),
      splitVideos: S.insertsDraft.filter((c) => c.kind === 'splitvideo').map((c) => ({ ref: c.ref, label: c.label, start: +c.start.toFixed(3), end: +c.end.toFixed(3) })),
      hook: S.insertsDraft.filter((c) => c.kind === 'hook').map((c) => ({ endSec: +c.end.toFixed(3) }))[0] || null,
      behind: S.insertsDraft.filter((c) => c.kind === 'behind').map((c) => ({ ref: c.ref, start: +c.start.toFixed(3), dur: +(c.end - c.start).toFixed(3) })),
      wordAccents: S.insertsDraft.filter((c) => c.kind === 'word').map((c) => ({ ref: c.ref, text: c.label, start: +c.start.toFixed(3), end: +c.end.toFixed(3) })),
    };
  }
  if (S.notes.length) {
    // written in the draft timeline the user was actually looking at, plus the
    // rendered-timeline equivalent so the skill can find the spot in cut.mp4
    payload.notes = S.notes.map((n) => ({
      start: +n.start.toFixed(3),
      end: +n.end.toFixed(3),
      renderedStart: +draftToRendered(n.start).toFixed(3),
      renderedEnd: +draftToRendered(n.end).toFixed(3),
      phase: n.phase || (S.tab === 2 ? 2 : 1),
      text: n.text,
      ...(n.media ? {media: {...n.media}} : {}),
    }));
  }
  if (S.textCuts.length) {
    // trechos riscados na transcrição: tempo RENDERIZADO do cut.mp4 (é onde as
    // palavras vivem) + o equivalente no rascunho, para o skill localizar
    payload.textCuts = S.textCuts.map((c) => ({
      renderedStart: +c.start.toFixed(3), renderedEnd: +c.end.toFixed(3),
      start: +renderedToDraft(c.start).toFixed(3), end: +renderedToDraft(c.end).toFixed(3),
      text: c.text,
    }));
  }
  if (S.textFixes.length) {
    // correção de TEXTO: mesma convenção de tempo dos textCuts, mas nada aqui
    // move a linha do tempo — quem aplica é o helpers/caption_fix.py
    payload.textFixes = S.textFixes.map((f) => ({
      renderedStart: +f.start.toFixed(3), renderedEnd: +f.end.toFixed(3),
      start: +renderedToDraft(f.start).toFixed(3), end: +renderedToDraft(f.end).toFixed(3),
      from: f.from, to: f.to,
    }));
  }
  if (Object.keys(S.takeChoices).length) {
    // escolha de tomada é decisão EDITORIAL: vai como pedido, com a linha do
    // roteiro e o trecho escolhido, para o agente montar o EDL e validar as
    // bordas. O preview nunca escreve edl.json.
    payload.takeChoices = Object.entries(S.takeChoices).map(([line, idx]) => {
      const item = (S.align?.lines || []).find((l) => String(l.line) === String(line));
      const c = item && item.candidates && item.candidates[idx];
      return c ? {line: Number(line), text: item.text, take: idx,
                  source: c.source, start: c.start, end: c.end, score: c.score} : null;
    }).filter(Boolean);
  }
  if (imageDirty()) {
    // Fase-1 grade controls (per-segment ffmpeg grade at extraction, Hard
    // Rule 7) — a non-default value here means the skill re-renders the CUT,
    // not Fase 2. imageChanged flags that at a glance from the payload alone.
    payload.image = { ...S.style.image };
    payload.imageChanged = true;
  }
  const res = await fetch('api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const savedResult = await res.json();
  if (!res.ok || !savedResult.ok) { toast(savedResult.error || 'Não foi possível salvar os ajustes', 4000); return; }
  if (savedResult.ok) {
    S.savedPending = true;
    S.notes = [];
    S.pendingIn = null;
    S.textCuts = [];
    S.textFixes = [];
    S.takeChoices = {};
    S.wordSel = null;
    renderWordBar();
    S.draft.forEach((r) => { r.orig = { start: r.start, end: r.end }; if (r.removed) r.hardRemoved = true; });
    // keep visual state but clear dirty counters
    S.draft = S.draft.filter((r) => !r.removed);
    S.insertsDraft.forEach((c) => { c.orig = { start: c.start, end: c.end }; });
    S.imageOrig = { ...S.style.image };
    renderAll(); refreshHeader();
  } else {
    toast('Erro ao salvar — o servidor está de pé?', 4000);
  }
});

$('btnDiscard').addEventListener('click', () => {
  S.draft = S.rendered.map((r) => ({ ...r, removed: false, orig: { start: r.start, end: r.end } }));
  buildInsertsDraft();
  S.notes = [];
  S.pendingIn = null;
  S.textCuts = [];
  S.textFixes = [];
  S.takeChoices = {};
  S.wordSel = null;
  S.fixing = false;
  renderWordBar();
  S.editingNote = null;
  $('noteEditor').classList.add('hidden');
  S.selected = -1;
  S.style.image = { ...S.imageOrig };
  renderImageAdjustments();
  applyImagePreview();
  renderLutGrid();
  LUT_ENGINE.setActive(S.style.image.lut);
  renderAll(); refreshHeader();
  toast('Ajustes descartados', 2000);
});

// ---------- ui helpers ----------
function showTooltip(e, html) {
  tooltip.innerHTML = html;
  tooltip.style.left = `${e.clientX + 14}px`;
  tooltip.style.top = `${e.clientY - 34}px`;
  tooltip.classList.remove('hidden');
}
function hideTooltip() { tooltip.classList.add('hidden'); }
let toastTimer = null;
function toast(msg, ms) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), ms || 3000);
}

// ---------- boot ----------
document.querySelectorAll('.tl-chip[data-icon]').forEach((c) => {
  c.innerHTML = ICON[c.dataset.icon] || '';
});

// A1/A2 accordion, folded into the audio track
$('jcutToggle').addEventListener('click', () => {
  if (!(S.jcut && S.jcut.length)) return;
  S.jcutOpen = !S.jcutOpen;
  localStorage.setItem('edvid.jcutOpen', S.jcutOpen ? '1' : '0');
  renderJcutAudio();
  updateScrollRange();
  positionNeedle();
});

poll();
rafLoop();
// the headline fit is MEASURED, so it is wrong until Poppins is actually
// loaded — rebuild once the fonts land
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => { if (S.style) renderSetup(); });
}

$('recoverButton').addEventListener('click', async () => {
  const button = $('recoverButton');
  button.disabled = true;
  $('recoverResult').textContent = 'Validando e copiando o vídeo…';
  try {
    const response = await fetch('api/relink', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({field: $('recoverField').value, path: $('recoverPath').value})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível recuperar o vídeo.');
    $('recoverResult').textContent = 'Vídeo recuperado. O arquivo original foi preservado.';
    S.lastSig = null;
  } catch (error) { $('recoverResult').textContent = error.message; }
  finally { button.disabled = false; }
});
$('projectsLink').addEventListener('click', event => {
  if (dirtyCount() && !window.confirm('Há ajustes não salvos. Sair deste projeto?')) event.preventDefault();
});

$('findMedia').addEventListener('click', async () => {
  $('findMedia').disabled = true;
  $('recoverResult').textContent = 'Procurando vídeos na biblioteca…';
  try {
    const response = await fetch('api/media-candidates');
    if (!response.ok) throw new Error('Não foi possível procurar os vídeos.');
    const data = await response.json();
    $('mediaCandidates').replaceChildren(new Option('Selecione um vídeo existente', ''));
    for (const file of data.files) $('mediaCandidates').add(new Option(file.name, file.path));
    $('recoverResult').textContent = data.files.length ? `${data.files.length} vídeo(s) encontrado(s). Escolha a versão correspondente.` : 'Nenhum vídeo encontrado nesta biblioteca.';
  } catch (e) { $('recoverResult').textContent = e.message; }
  finally { $('findMedia').disabled = false; }
});
$('mediaCandidates').addEventListener('change', () => { $('recoverPath').value = $('mediaCandidates').value; });
