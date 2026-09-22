# Style: "premium editorial" (2026-08-15)

A standing, autonomous editorial preset for this user's aesthetic-medicine
content (@drgeovanejunior — emagrecimento, hipertrofia, implantes hormonais,
menopausa, lipedema, remodelação corporal, testes genéticos, estética facial
e corporal). Built from a detailed brief **plus direct frame analysis of a
reference creator's real published Reels** (@tay.ldantas, 11 videos) — not
the brief alone. Where the two disagreed, the real frames won (see the color
grade history below).

**Goal: autoridade editorial e sofisticação.** Explicitly NOT infoproduto
aesthetics, NOT karaoke captions, NOT shaky zoom, NOT emoji on screen, NOT a
whoosh on every cut.

This is a **standing preset in the shared skill**, not a one-off — see
`feedback_edvid_shared_template_scope` in the assistant's own memory. Read
this file before editing any video for this user unless they explicitly ask
for a different look.

## Default vs opt-in (2026-08-16 — user instruction, applies to every future edit)

When the user says "editar no Edvid" with no further style direction, run
**everything below EXCEPT** these three — they are opt-in only, picked by the
user in the Estilo tab, never applied automatically:

- **Base dialogue captions** (`captions.style: "premium"`) — the Estilo tab's
  "Estilo de Legenda" already lists `Premium` as a card (`STYLE_CATALOG.captions`
  in `app.js`). Leave `captions.style` as whatever the user actually picks
  there; do not default it to `"premium"` yourself.
- **Color grade / "tonalidade"** — do NOT run `grade.py --preset
  premium_editorial` at Phase-1 extraction time. It now lives as a LUT named
  **"Premium"** in the same LUT picker as the other 32 (`assets/preview/luts/
  premium.cube`, baked from the preset's pointwise ops via `helpers/
  bake_lut.py`). The video ships at its ORIGINAL tonality (`grade: ""` per
  the normal `detect_color.py` rec709 path) unless the user picks that LUT
  themselves in the Estilo/Fase-1 image panel.
- **AI-generated soundtrack** — only when the user checks "Trilha sonora com
  IA" (`elements.musicAI` in the Estilo tab, `def: false`). When checked,
  generate something subtle/soft (low mix level, unobtrusive instrumental —
  see the Audio section's music guidance below) — the user asked for a
  "padrão sutil e suave" as the default character when this is on.

After the base edit (everything else on this page — title cards, framing,
cutting rhythm, hook rules, typography system, B-roll rules, export spec,
standard non-premium captions if the user picked one, -16 LUFS loudnorm),
**land the result on the Fase 1 Corte preview** (`awaitingStyle: true`, do not
force-jump the UI to the Estilo tab — see the Preview interface section in
SKILL.md). The user reviews the cut there and opens Estilo themselves to add
any of the three opt-in pieces.

## What's already built (code, not just rules)

| Piece | Where |
|---|---|
| Color grade | `helpers/grade.py` → `PRESETS["premium_editorial"]`, baked as the `Premium` LUT (`assets/preview/luts/premium.cube`) — **opt-in, see above, not applied by default** |
| Base dialogue captions | `assets/shortform/src/SimpleCaptions.tsx` → `SIMPLE_VARIANTS.premium` (`captions.style: "premium"`) — **opt-in via the Estilo tab, see above** |
| Stacked title cards (the typography signature) | `assets/shortform/src/CustomGraphics.tsx` → `TitleCards` component, driven by `editData.titleCards[]` |
| Script accent font | Alex Brush, loaded in `CustomGraphics.tsx` and the preview app |
| Voice mastering | `helpers/render.py` → `PREMIUM_VOICE_MASTER_CHAIN`, `--voice-master premium` — **built, but not used by default for this user, see Audio section** |
| Loudness target | `helpers/render.py` → `PREMIUM_LOUDNORM_I/TP` (-16 LUFS / -3 dBTP), same flag |
| Final delivery encode | `helpers/render.py` → `export_premium()`, `--export-premium` (HEVC 2-pass na resolução/fps do arquivo: 16 Mbps em 1080p, 45 Mbps em 4K; AAC 320k) |

Everything below this line is EDITORIAL JUDGMENT — decisions to make while
cutting, not something a script enforces for you.

## Color and image

Use `grade.py`'s `premium_editorial` preset as the starting point, always
still through the candidates-montage workflow (Hard Rule 12) — never assume
it's right for a new room/lighting without checking a real frame.

**Calibration history, worth re-reading before pushing this warmer:** the
first version of this preset (colortemperature 5200K, stronger colorbalance)
tested "too saturated, amarelada" per the user directly comparing it against
the unfiltered original. Two real frames from the reference account, sent
after that, confirmed why: her warmth reads as coming from the room's own
ambient light (tungsten walls, golden-hour sun), not a heavy push on top of
neutral footage. The shipped preset is deliberately restrained — a small
color-temperature nudge (~400K), light-touch colorbalance, a barely-there
S-curve. If a video's own lighting is already warm, this preset might need
to do EVEN LESS, not more.

- Lifted black point, soft highlight roll-off, never clip to pure white/black.
- Global saturation slightly DOWN (0.96), not up — preserve orange/red poses
  no risk, but pushing saturation up risks the exact yellowing the user flagged.
- Sharpening is GLOBAL in the preset (ffmpeg has no face mask) — kept low
  (0.25) specifically so it doesn't halo the background. True face-only
  sharpening needs a per-shot mask; not solved here.
- Near-invisible film grain (`noise=alls=2`) — masks Instagram's own
  recompression banding, not meant to read as "vintage film" on its own.

## Framing and movement

- Alternate open/close framing of the SAME take on every new idea — cut, not
  a zoom animation, between the two.
- If zooming, 2-4% over several seconds, imperceptible. No fast/snap zooms.
- Stabilize shaky handheld footage UNLESS it's deliberately "raw" B-roll
  (see B-roll section) — the rawness there is the point.

## Cutting rhythm

- Hard cut on ~95% of transitions. The one exception (a short whip-pan or a
  2-frame white flash on a strong subject turn) at most ONCE per video —
  `CutFlashes` in `CustomGraphics.tsx` already builds this; don't add more
  than one window per video's `transitions[]`.
- No shot longer than 4 seconds without a change (framing, text, or coverage).
- Remove ALL breathing room, filler ("é...", "tipo", restarts), dead air —
  this is a Hard Rule 4/5/`speech_regions.py` job already, just apply it more
  aggressively than usual for this style: high information density, no slack.
- No decorative transitions — no flash-glitch, zoom-blur, spin, slide.

## The hook (first 3 seconds)

- Start mid-sentence, on the strongest claim. No greeting, no "oi gente", no
  self-introduction.
- Frame 1 already shows the graded image AND the title card assembled — not
  building up from nothing.
- The hook text states a TENSION or CONTRADICTION, not a topic label ("os
  chips que prometem substituir o Ozempic" beats "hoje vou falar sobre
  chips").
- At least TWO visual changes (a framing cut or a text entry) inside the
  first 3 seconds.

## Typography system — the signature

Two families only, per card:
- **Poppins** (already in every template) — Light (300) for connector words,
  ExtraBold (800) for the key word. Never more than two weights on screen at
  once.
- **Alex Brush** (script) — ONE accent word or short phrase per card, in a
  color from `TITLE_ACCENT_PALETTE` (`CustomGraphics.tsx`): azul, vermelho,
  dourado, verde, azulPiscina. **Pick ONE color per video** and stay
  consistent within it — do not mix accent colors across cards in the same
  video, and do not default every video to the same color either (a first
  draft hardcoded pink; the user's correction: "não quero que a cor seja
  fixa, pode mudar de um vídeo para outro").
- Not every card needs a script line — the reference doesn't put one on
  every card. Use it for the genuine emphasis moment, not reflexively.
- Left-aligned by default (`align: "left"` on the `TitleCard`), centered as
  an option. Anchored middle-lower third (`paddingBottom: 650`).
- Soft drop shadow only (already baked into `TitleCardFrame`) — never a
  background box, never an outline, never full-caps body text.

**Building a `titleCards` entry:** get the exact phrase timing from the cut
transcript, break it into 2-4 lines by hand (light/bold/script), same
judgment as writing the hook itself — this is not auto-generated from the
caption word list.

## Captions (running dialogue)

Use `captions.style: "premium"`: white, Poppins ExtraBold, low on frame (same
band as the other five `SimpleCaptions` variants — NOT centered; a centered
first pass sat on the face on this user's tight vertical selfie framing, see
the Audio section's sibling note in memory), max 3 words, instant cut (no
fade/pop/scale-in), punctuation kept. No color highlight, no karaoke, no
emoji, no underline. This is the style for plain dialogue stretches —
`TitleCards` carries the emphasis moments instead of a fancier caption style.

## B-roll — alternate two treatments, 2-4 raw inserts per video

1. **Full-bleed cinematic** — a real or AI-illustrative image/video, same
   `premium_editorial` grade applied, filling the frame.
2. **Raw/documentary** — vertical phone footage, a scientific-article
   screenshot, a screen recording, a newspaper headline — rounded corners
   (~24px radius) on a black background, contrast deliberately "unpolished"
   next to the graded main shot. This is the split-screen `SplitFrame`
   pattern already in `CustomGraphics.tsx` (bandH/layout), or a simple inset
   `Img`/`OffthreadVideo` with `borderRadius: 24`.

Cover every concept spoken (metabolismo, hormônio, exame, alimento, treino,
corpo, cidade → show it). Never generic stock (a doctor smiling in a white
coat, an animated bar chart, DNA spinning in 3D) — these read as
"infoproduto", exactly what this style avoids.

## AI-generated images/video — allowed, scoped

Only as illustrative/conceptual material: visual metaphor, historical scene,
environment, illustrative human organs, surgical instruments/hospital
supplies, disease/symptom illustration, physical activity/exercise — all
oriented to endocrinology, nutrology, sports medicine. Ethical, sensible,
medically responsible — never a specific real patient's likeness, never a
misleading medical claim illustrated as fact. Always pass through the SAME
`premium_editorial` grade as the rest of the video and must never read as
plastic/render-y — if a generation looks like a 3D render, regenerate or
drop it, don't ship it. Always tied to what's being said at that exact
moment, not a generic filler image.

## Animation

Minimal and sober. Text entry: instant, or a fade of AT MOST 4 frames
(`TITLE_ENTER` in `CustomGraphics.tsx` is already exactly 4). Highlighting a
number: a simple count-up or a single hand-drawn underline, once per video,
if at all. No particles, no animated emoji, no pulsing/spinning arrows, no
progress bars.

## Audio

**Default: skip `--voice-master premium`.** First live test (2026-08-16)
applied the full `PREMIUM_VOICE_MASTER_CHAIN` and the user's read was "o
audio ficou muito pior que o original, parece abafado". The already-approved
delivered project's `edl.json` has no `voice_master` field at all — this
user's raw recordings (good mic, treated room) are clean enough as-is, and
the chain's `afftdn` denoise + EQ cuts + compression + deesser reads as
muffled/dulled on them, not "polished". Ship dialogue with only the -16
LUFS / -3 dBTP loudnorm (`PREMIUM_LOUDNORM_I/TP`) and skip the rest of the
chain, matching what's already approved.

Only reach for `--voice-master premium` (or a lighter hand-picked subset of
`PREMIUM_VOICE_MASTER_CHAIN`) if a SPECIFIC recording actually has an audible
problem — background noise, room echo, a boxy mic — and say so before
applying it, since it changes the voice's character.

Music: only when the user checks "Trilha sonora com IA" (see Default vs
opt-in above) — instrumental only, no vocals, mixed −24 to −20 LUFS (≈18-22 dB
under the voice) with auto-ducking, piano/strings minimalist or cinematic
ambient/lo-fi. No funk, trap, a hard beat, or trending audio competing for
attention. Enters softly after the hook, fades out over the last 2 seconds.
Zero transition SFX — this style does not use whoosh/pop on cuts at all
(unlike the shared template's other worked examples, which do — don't copy
those `<Sfx>` calls into premium-style graphics). Example `treblo_music.py`
vibe prompt for this user (subtler than the generic shortform.md example,
which is upbeat/electronic — do not use that one here): `"minimalist piano
and soft strings, cinematic ambient, unobtrusive and warm, slow tempo,
sophisticated and calm, no drums"`.

## Ending

Ends on the sentence's last word. No goodbye, no "se inscreve", no static
end card, no logo card. Last frame is a living image — **this style skips
the standing outro card** (`OutroGraphic`) that's the default for this
user's OTHER videos; if both instructions are ever in tension for a specific
video, ask rather than silently picking one.

## Approval checklist (before delivering)

1. Natural skin tone in every shot — no yellow cast, no plastic AI look.
2. No caption covers the mouth or leaves the safe zone (top 250px / bottom
   420px excluded — Reels UI).
3. No shot over 4s without a change.
4. Audio at -16 LUFS integrated (verify: `ffmpeg -i final.mp4 -af
   loudnorm=print_format=summary -f null -` or re-run `measure_loudness`).
5. Color consistency between A-roll and B-roll (same grade family, not two
   different looks stitched together).

## Technical delivery spec

Resolução e fps do próprio arquivo, constantes (4K sai 4K — regra de 2026-09-22),
HEVC main profile, VBR 2-pass a 16 Mbps em 1080p ou 45 Mbps (máx. 55) em 4K, AAC
320kbps/48kHz, `hvc1` tag (QuickTime/iOS compatibility) — `export_premium()`
in `render.py` does this as a final transcode pass, run after the normal
pipeline, output alongside the H.264 file as `<name>.premium.mp4`. No
letterbox, no black bars. No graphic element in the top 250px or bottom
420px (Reels UI exclusion zones) — `TitleCards`' default `paddingBottom: 650`
already respects this; re-check by hand for any card with 4+ lines or
unusually large text. Duration 45-90s.
