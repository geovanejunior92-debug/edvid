# SHORT-FORM track (Reels / TikTok / Shorts) — Phase 2 + 3 reference

Read this file when the video is vertical short-form and the Phase-1 cut is
approved. Everything here rides on the **data-driven template** at
`assets/shortform/` — the code is immutable; a video is described by ONE JSON.

## The style (the proven default)

- **Frame rate:** render at **30fps when the source is 30fps or higher** (natural
  motion, matches Instagram/TikTok/Shorts capture); only slower sources use 24.
  `render.py` picks this automatically for `cut.mp4` — then set `edit-data.json`
  `fps` to the SAME value as `cut.mp4` (ffprobe it) so the Remotion render matches.
- **Base:** 1080×1920 (fps per the rule above), `<OffthreadVideo src=cut.mp4>` with the **dynamic
  camera**: hard zoom per cut segment (`zoomCuts`, ~1.10–1.22, cycles), slow
  push-in (`zoomAuto`, +0.04/segment), clamped eye-tracking (`tracking`, target
  upper third, never reveals an edge). **`zoomCuts` and `zoomAuto` are FIXED —
  every video gets them, there is no pick and no asking** (user decision
  2026-08-16, together with `flashCut` below). Only `tracking` is still a choice.
- **Visual hook (first ~4s):** static copywriting headline, **always two lines**
  with the size fitted to them (see "Headline styles"). On by default, but the
  Estilo tab offers "Nenhum" — respect it and set `hook.enabled: false`.
- **Captions:** eight styles — three animated (**karaoke**, **stacked**, **scatter**)
  and five static (**simples**, **serifada**, **classica**, **impacto**,
  **editorial** — the last two added 2026-08-15) — plus "Nenhum",
  which is `captions.enabled: false` and no caption generation at all. The user already
  picked one on the Estilo tab; see the "Caption style" section.
  Karaoke: one line ≤3 words, words rise from below, Poppins Black, lower third,
  `measureText` fit into **SAFE_WIDTH 720** (~180px each side — clears
  Instagram/TikTok's right action rail; verified on a real screenshot). Never
  rely on `nowrap` alone.
- **Inserts (upper zone):** rounded-card + shadow motif synced to spoken nouns,
  slow Ken-Burns. Pexels for concrete objects; **bespoke motion graphics** when
  a word names something animatable (timeline for "cortes", typewriter sheet
  for "roteiro" — worked examples in `src/CustomGraphics.tsx`).
- **Zones:** inserts/graphics upper third, captions lower third, face clear.
  Minimalist; accent `#33e0a3`.
- **Audio:** whoosh ~0.09 on card entrances, pop ~0.12 on shapes, music ~0.12,
  and ALWAYS a final loudnorm pass (voice+music+SFX summed will clip). The
  shared sfx pack (`public/sfx/`) also ships `click1`/`click2` (element pops) and
  `tictac` (clocks/countdowns) — trigger any at a local frame by wrapping
  `<Sfx src="click2.mp3" volume={0.7}/>` in a `<Sequence from={frame} layout="none">`.

## Workflow

**Read `<edit>/preview_style.json` first — it IS the brief.** The user chose it on
the Estilo tab at the end of Fase 1; every key maps to something here:

| Pick | What it means |
|---|---|
| `edit: "limpa"` | **the default** — NO split inserts, full frame throughout. See the "Limpa" section |
| `edit: "split" \| "split2"` | the split-screen variant below — every image insert uses it |
| `headline: "outline" \| "card" \| "realce" \| "misto"` | `hook.style` in edit-data.json |
| `headline: "none"` | **no headline at all** — `hook.enabled: false`. The template already gates on that flag, so nothing else changes |
| `headlineFont: "poppins" \| "bebas" \| "anton" \| "playfair"` (2026-08-15) | `hook.font` in edit-data.json — the TYPEFACE, independent of `hook.style` above. Default `"poppins"` if the field is absent (older `preview_style.json`) |
| `captions: "karaoke" \| "stacked" \| "scatter" \| "simples" \| "serifada" \| "classica" \| "impacto" \| "editorial"` | `captions.style` in edit-data.json (+ the director step for stacked) |
| `captions: "none"` | **no captions at all** — `captions.enabled: false`. Skip `captions_for_remotion.py` too; nothing reads the file |
| `accent` (hex) | `hook.accent` + `captions.accent`. Only `realce`/`misto`/`stacked` paint it; `accentUsed:false` means the picked styles have none |
| `elements.tracking` | `face_track.py` + `track.json`; OFF → skip it, fixed frame |
| `elements.zoomAuto` | **always true** — the slow push-in inside each segment (`+0.04/segment`) |
| `elements.zoomCuts` | **always true** — the hard zoom change ON each cut (~1.10–1.22, cycles) |
| `elements.flashCut` | **always true** — `transitions[]` in edit-data.json, see "Flash na transição" |
| `elements.musicAI` | Phase 3 via `treblo_music.py`; OFF → deliver with voice only |
| `elements.aiVideo` (2026-08-16) | AI-generated VIDEO B-roll matched to the spoken topic — see "AI-generated B-roll" below; OFF → only the existing stock-first flow ("Illustrative images" section), no unsolicited generation |
| `elements.aiImage` (2026-08-16) | AI-generated STILL B-roll, same trigger/placement mechanism as `aiVideo` but images only; when both are on, video is still the default per moment — see "AI-generated B-roll" below |
| `note` | free text — read it, it overrides the defaults above |

An unchecked box is an explicit NO, not a silence. Copy the picks into
`state.json` as `style`, clear `awaitingStyle`, delete `preview_style.json`.

**Zoom e flash são fixos, não escolha (2026-08-16).** `zoomAuto`, `zoomCuts` and
`flashCut` are locked chips on the Estilo tab — always saved `true`, never
toggleable, never asked about. The user's words: *"quero que os flash e zoom
deixem de ser opção e fiquem fixo em todos os vídeos após o corte e quando for
para fase 2 eles já estejam."* So the FIRST `edit-data.json` you write already
carries `camera.enabled: true` with `zooms` + `pushIn`, and a `transitions[]`
entry per split window — not added in a second pass after someone notices they
are missing. If a `preview_style.json` or an old `state.json` arrives with any of
them false, treat it as stale data and build them anyway. On a "Limpa" edit
(`splitInserts` empty) there are no layout changes to flash on, so place the
flashes on the cut boundaries in `segments.json` instead — spaced, never one per
cut. This is also why nothing here asks the user about camera or flash: the
question is settled.

1. **Scaffold (one command, never read the TSX):**
   ```bash
   cp -R <skill>/assets/shortform/. <edit>/remotion/ && cd <edit>/remotion && npm install
   ```
2. **Generate machine data into `remotion/public/`:**
   - `cp cut.mp4 remotion/public/`
   - `transcribe.py cut.mp4 --edit-dir <edit>` → `transcripts/cut.json`
     (cut times are already on the output timeline — never map the source EDL)
   - `captions_for_remotion.py --transcript transcripts/cut.json -o public/captions.json`
   - **Caption style** — from the Estilo tab pick. `stacked` ALSO needs
     `caption_style.py --transcript transcripts/cut.json -o public/caption-cues.json`
     plus `captions.style:"stacked"` (see the "Caption style" section).
   - `face_track.py cut.mp4 -o public/track.json` — **only when
     `elements.tracking` is on.** Off, the frame stays put — but the file must
     still EXIST: the template imports it statically and the bundle fails to
     build without it ("track.json doesn't exist" out of webpack, not a runtime
     warning). Write a neutral one instead: every point pinned to the camera
     target, so the follow has nothing to correct.
     ```bash
     python - <<'EOF'
     import json, pathlib
     ed = json.loads(pathlib.Path('public/edit-data.json').read_text())
     n = round(ed['durationSec'] * ed['fps'])
     tx, ty = ed['camera']['targetX'], ed['camera']['targetY']
     pathlib.Path('public/track.json').write_text(json.dumps(
         {"fps": ed['fps'], "width": ed['width'], "height": ed['height'],
          "count": n, "points": [[tx, ty]] * n, "neutral": True}))
     EOF
     ```
   - `public/segments.json` — cumulative cut boundaries **measured from the
     encoded segments' frame counts, never summed from the EDL's seconds**.
     **Regenerate it after EVERY Phase-1 re-render.** A stale segments.json is
     invisible: the render succeeds, the overlays look plausible, and every cut
     is off by a frame or three. Measured on this project after a re-grade — the
     file still carried EDL-summed times and drifted +1 frame by the 3rd cut and
     +3 by the 20th, while `VIDEO_LAG` quietly absorbed the first frame of it and
     made the error look fixed. The mechanism: ffmpeg quantises each segment to
     whole frames, so EDL arithmetic drifts a fraction of a frame per cut and the
     error ACCUMULATES. Anything that must land on a cut then sits visibly early.
     ```bash
     python - <<'EOF'
     import subprocess, glob, json, pathlib, sys
     # TWO assertions, because globbing a directory is only as good as the
     # directory. `_v.mp4` first: the J-cut writes video-only segments and a bare
     # glob also matches butt-join leftovers. Then check the COUNT against the EDL
     # and the SUM against cut.mp4 — a re-render with fewer ranges leaves the old
     # higher-numbered segments behind, and that gave segments.json 9.23s for a
     # 7.57s video. It renders clean and every overlay lands wrong.
     segs = sorted(glob.glob("clips_graded/seg_*_v.mp4")) or sorted(glob.glob("clips_graded/seg_*.mp4"))
     nranges = len(json.loads(pathlib.Path("edl.json").read_text())["ranges"])
     if len(segs) != nranges:
         sys.exit(f"{len(segs)} segments for {nranges} ranges — clips_graded is dirty")
     cum, t = [0], 0
     for f in segs:
         n = int(subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
             "-count_frames","-show_entries","stream=nb_read_frames",
             "-of","default=nw=1:nk=1",f], capture_output=True, text=True).stdout)
         t += n; cum.append(t)
     real = int(subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
         "-count_frames","-show_entries","stream=nb_read_frames",
         "-of","default=nw=1:nk=1","cut.mp4"], capture_output=True, text=True).stdout)
     if t != real:
         sys.exit(f"segments sum {t}f != cut.mp4 {real}f — do not ship this file")
     fps = 30  # match cut.mp4
     json.dump({"segments": [{"start": round(cum[i]/fps,4),
                              "dur": round((cum[i+1]-cum[i])/fps,4)}
                             for i in range(len(cum)-1)]},
               open("remotion/public/segments.json","w"), indent=2)
     EOF
     ```
   - **VERIFY segments.json against the picture — do not trust it.** `scdet`
     scores every frame by how much it differs from the one before, so a hard
     cut is a spike. The spike frame in `cut.mp4` must equal
     `round(segments[i].start * fps)`:
     ```bash
     ffmpeg -v info -i cut.mp4 -vf "select='between(n,344,358)',setpts=N/30/TB,scdet=threshold=0" \
       -an -f null - 2>&1 | grep scd.score
     ```
     In the RENDER the same cut lands one frame later — that is the
     `OffthreadVideo` lag `VIDEO_LAG` exists for. Both numbers together are the
     proof: cut spike at frame F in cut.mp4, at F+1 in the render, overlay
     window opening at F+1.
   - `pexels_search.py "<query>" --out-dir public/pexels --count 3 --orientation portrait`
3. **Write `public/edit-data.json`** — the whole edit in one file (schema in
   `assets/shortform/README.md`): durationSec (exact ffprobe of cut.mp4),
   camera zooms, hook lines/logo/sign, captions config, inserts[], behind[],
   soundtrack (leave `enabled:false` until Phase 3).
4. **Verify with stills, batched:** `npx remotion still Reels --frame=<n> f.png`
   for the hook still (user approval), then ONE contact sheet for spot checks:
   `contact_sheet.py <render> --times t1 t2 t3 -o sheet.png` — one image, not N.
5. **Render:** `npx remotion render Reels out/render.mp4`, then loudnorm →
   `edit/final.mp4` (see Phase 3).

Never edit `src/Main.tsx`. Bespoke graphics go in `src/CustomGraphics.tsx`
(the ONE editable file — read it only when the video needs a custom graphic).

## Headline styles — always two lines

Four looks via `hook.style`, picked by the user on the Estilo tab: **`outline`**
(default, white + thick black stroke), **`card`** (dark rounded card, UPPERCASE,
optional logo row), **`realce`** (each line on a solid accent marker block),
**`misto`** (line 1 light white, line 2 heavy accent).

### The accent colour (`accent` in preview_style.json)

`realce`, `misto` and the `stacked` caption are the only things that paint an
accent; the default is `#ff5200`. The user picks it on the Estilo tab and it
arrives as a hex — set it on **`hook.accent`** and **`captions.accent`** in
edit-data.json so headline and caption stay the same colour. `preview_style.json`
also carries `accentUsed`: when it is `false`, the picked styles have no accent
and the colour is not a request to find somewhere to put one.

Hardcoding `#ff5200` anywhere in the template re-breaks this — the preview will
show the user's colour and the render will show orange, which is worse than not
offering the choice.

**Author `hook.text` as one plain sentence.** Whatever you write — `text`, or a
hand-broken `lines[]` — is joined and re-broken into exactly TWO lines balanced by
MEASURED width, then the size is fitted to the widest one. A third line shrinks
the type and costs the glance the headline exists to win.

- The break is measured, not counted: "É assim que vai" (4 words) and "ficar a sua
  headline" (3 words) are nearly the same width. Counting words breaks it wrong.
- **`fontSizePx` is a CEILING, not a fixed size.** As a hard override it defeats
  the whole feature: at a size the text cannot fit in, the line wraps and you are
  back to three lines. Measured, not guessed — the uppercase `card` style did
  exactly that at an inherited `fontSizePx: 66`.
- Per-style geometry (weights, cap, safeWidth, lineHeight, paddingTop) lives in
  `HL_STYLES` in `src/Main.tsx` **and is mirrored in the preview's `app.js`** so
  the Estilo tab shows the real break at the real size. Change one, change both.
- In a split layout, `paddingTop` still has to follow the seam — see the split
  section.

### Headline font (`hook.font`, 2026-08-15) — independent of `hook.style`

A second, orthogonal pick: `"poppins"` (default), `"bebas"` (Bebas Neue),
`"anton"` (Anton), `"playfair"` (Playfair Display italic 900). Any of the four
`hook.style` looks can render in any of these four faces. Geometry (`HL_STYLES`)
is unchanged by the font — only the `fontFamily` fed into `hlWidth`/`twoLines`/
`fitHeadline` changes, so the two-line balance and the size-to-fit are measured
in the actual chosen face (critical for Bebas/Anton: they run noticeably wider
per character than Poppins at the same size, so measuring in the wrong face
would fit a size that then overflows).

Bebas Neue and Anton ship **weight 400 only** — `loadFont` errors on any other
weight, so `HL_FONTS` in `src/Main.tsx` loads just that one weight per font;
`HL_STYLES`' per-style `fontWeight` (800/900) has no matching cut to switch to
on those two, which is a silent no-op, not a bug — both faces already read as
bold/condensed by design. `HL_FONTS` and the preview's `HL_FONT_FAMILIES` in
`app.js` are mirrors, same as `HL_STYLES` already was — change one, change both.

## Caption style — eight of them

Three are animated (karaoke, stacked, scatter) and five are STATIC
(`simples`, `serifada`, `classica`, `impacto`, `editorial`) — no animation at
all, a cue just replaces the previous one. All five static ones live in
`SimpleCaptions.tsx`, read `captions.json` alone, and share one rule that is
the whole point:

**Lines group by MEASURED WIDTH, capped at `maxWords` — never by word count.**
"inteligência" and "de" cannot obey the same rule: the long word takes the line
alone and the short ones ride together. A fixed 3-words-per-line gets this
backwards on every long word.

- `simples` — Poppins 600 at 82, squeezed to 0.9 on BOTH axes, one line, ≤3 words.
  Poppins ships no condensed cut, so this is a distorted regular: it thins the
  stems in both directions. If it ever reads too light, raise the weight to 700
  rather than compressing further.
- `serifada` — Libre Baskerville 700 at 84, same rules, no distortion.
- `classica` — Inter 500 at 52, TWO lines, classic subtitle. The split is width
  balance PLUS a penalty for ending a line on a short function word ("o", "de"),
  which a pure balance does constantly and no real subtitle ever does.
- `impacto` (2026-08-15) — Anton 400 (its only weight) at 84, **uppercase**,
  one line, ≤2 words (Anton is an expanded poster face — two words already
  fills `maxW`). `uppercase: true` on the variant uppercases the text BEFORE
  measuring, not just at render — a CSS-only `text-transform` would size the
  line-break budget against the shorter mixed-case string and then paint
  something wider than what was measured, silently overflowing `maxW`.
- `editorial` (2026-08-15) — Playfair Display italic 900 at 66, one line,
  ≤5 words. Reuses the same italic-900 Playfair load already used by the
  `stacked` caption style and by `hook.font:"playfair"` — no new font weight
  introduced.
- **The horizontal squeeze changes the line grouping** (narrower glyphs → more
  words fit); the vertical one does not (grouping is measured on width). Worth
  knowing before "just squashing it a bit".
- All five sit at `bottom: 430`, the same band as the others. Lower than that
  and a 9:16 caption lands under the platform's own UI.
- **Adding a sixth static style needs no `Main.tsx` change.** `SIMPLE_VARIANTS`
  in `SimpleCaptions.tsx` is a config table Main.tsx already dispatches to
  generically (`SIMPLE_VARIANTS[D.captions.style] ? <SimpleCaptions
  variant=.../> : ...`) — a new entry there, mirrored into `STATIC_VARIANTS` +
  `STYLE_CATALOG.captions` in `app.js` for the picker/preview, is the whole
  change. `impacto`/`editorial` were built exactly this way.

### karaoke (default), STACKED or SCATTER

Short-form ships two caption styles. **The user already picked one on the Estilo
tab**, where both previews run the real animation — do not ask again, just set
`captions.style` from `preview_style.json`. (`caption-styles/stacked.png` is
still there as a montage over real footage if a still is useful.)

- **`"karaoke"`** (default): one line ≤3 words, Poppins Black, lower third.
- **`"scatter"`** ("Disperso"): Lora serif, lowercase, off-white with a slight
  darkening toward the baseline, one word at a time in short ragged lines. Reads
  `captions.json` alone — no extra generation step. Ordinary words FADE only; one
  word per cue (the longest, ≥7 chars) resolves out of a heavy blur at 1.62× and
  dissolves back into blur on the way out. Tunables in `captions`:
  `scatterOffsetY` (block centre, default 0.72), `scatterFontSize` (72),
  `scatterSafeWidth` (820); `SPREAD` in the component caps how far a line wanders.
  Three things it took real footage to learn:
  - **Never `Math.random()`.** Remotion renders frames independently, so a true
    random re-rolls the layout every frame and the text shakes. Positions are
    hashed off the cue index.
  - **The middle of the frame is the FACE.** The reference look lives over B-roll;
    on a talking head the block belongs on the chest (`scatterOffsetY` 0.72).
    Raise it only when the shot behind is not a face.
  - **Motion on every word is motion on nothing.** Ordinary words used to drop in
    from above too, and at one word per ~200ms the screen read as frantic. The
    blur on the highlighted word only reads because everything else is still.
- **`"stacked"`**: words stacked tight, mixing per line — Poppins bold-italic
  (white→gray gradient) / Poppins regular (smaller) / Playfair serif bold-italic
  in `captions.accent` (orange `#ff5200` only as the DEFAULT) / Poppins bold.
  Emphasis words appear solo; key ones get a hand-drawn pencil ellipse, whose
  colour is `captions.pencilColor` (green as the default). **Baked SFX** (no
  extra step, no Premiere): a **click** on every solo word, a **scratch** when a
  word is circled.
  Both colours became data on 2026-08-16 — they were constants in
  `StackedCaptions.tsx`, which forced a per-project fork of an immutable
  template file just to change one colour. If a look needs a colour the style
  paints, check whether it is already a field before touching template code.

For stacked, the ONE extra data step is the director (reads the same cut
transcript as `captions_for_remotion.py`):
```bash
uv run python helpers/caption_style.py --transcript <edit>/transcripts/cut.json \
    -o remotion/public/caption-cues.json
```
Then set `captions.style:"stacked"` in edit-data.json (keep the other caption
fields — they stay valid). Defaults match the user-approved look: the stack sits
~15.6% of the height below center and SFX play from `public/sfx/caption-click.mp3`
+ `caption-scratch.mp3` (both already in the template). Optional overrides inside
`captions`: `stackedOffsetY` (0–1 of height), `fontScale`, and
`sfx:{enabled,clickVolume(0.45),scratchVolume(0.16)}`. The director groups words
into short cues, gives the orange serif accent to the content word (never a
connective), keeps 1-letter/short connectors from standing alone, and flags
solo/circled words. It is language-tuned for pt-BR (`--lang`); for other
languages it falls back to length heuristics.

A solo word also needs DURATION, not just weight — a word spoken in under
`MIN_SOLO_MS` (340ms) renders as a one-frame flash and reads as a glitch, so the
director folds it into a neighbouring stack instead. Fast connective speech hits
this often. After generating cues, sanity-check the plan (it prints a summary):
every non-`STACK_MIXED` cue should span ≥0.34s, and the word list across all
cues must match the transcript exactly, in order.

## Visual hook — static headline, first ~4s (always on)

The first 1–2 seconds decide the swipe. Write `hook.lines` like a
social-media/copywriting/virality specialist, not a summarizer: read the cut
transcript, find the core promise/tension, and craft a scroll-stopper. Levers:
**curiosity gap · high stakes/bold claim · specificity/number · urgency ·
pattern interrupt**. Match the video's language; never clickbait it can't pay off.

**Two locked styles via `hook.style`** (both user-approved, encoded in the
template):
- **`"card"`** (default): Poppins Black white UPPERCASE on a dark-gray `#232326`
  rounded card, **every line the same font size (~54)** — never a big hero line +
  smaller kicker. Optional row above the card: real brand logo (rounded card,
  w300) + transparent symbol (drop-shadow, w128) — prefer real assets in
  `public/brand/` over drawn SVG; pick a symbol that frames the angle (danger,
  money, trophy…).
- **`"outline"`**: white text + thick black stroke (`WebkitTextStroke` +
  `paintOrder:'stroke fill'`), **no card**, **sentence-case** (write `lines[]`
  normally, not caps), sits lower (`paddingTop` ~330 — may overlap the top of the
  head, which is fine). The TikTok/MrBeast headline look. Tune `fontSizePx` (68),
  `strokePx` (12), `paddingTop` (330), `lineHeight` (1.06). Drop logo/sign.

Both are static hold, fade+rise at the edges, soft whoosh.

Example (Claude Fable video): "A IA MAIS / PERIGOSA DO MUNDO / ACABOU DE SER
LIBERADA". Draft 2–3 copy candidates in chat (text — no renders), let the user
pick, then render ONE still for design approval before the full render.

**De-conflict:** the hook owns the upper zone for its window — push any insert
that wants the same zone to after `hook.endSec` (e.g. move a 2.5s cutaway to
~4.1s).

## Flash na transição (`elements.flashCut` — sempre ligado)

A light beam whips across the frame with a bloom and a dry click. Data-driven:
one entry per cut in `transitions[]`, `at` being the cut time **exactly as
segments.json states it** — `VIDEO_LAG` lines it up with the frame the picture
changes on, same as the split windows. Never index it off its own clock.

```json
"transitions": [{"at": 11.7}]
```

Default placement (the element is always on): **one per split-insert entry, not
per cut.** The video has ~27 cuts; a flash on each one stops reading as an accent and
starts reading as a strobe. Put it where the layout changes, which is where the
transition means something. Optional per entry: `intensity` (default 1), `sfx`,
`volume`.

- **The beam LEADS the cut by 2 frames.** Starting it on the cut frame reads as a
  flash after the fact — the eye sees the picture change, then the light. Leading
  it makes the light look like the cause.
- **Blur is what separates a beam from a wash.** At 26px it read as a general
  brightening; 16px reads as a beam. Raise opacity and lower blur together.
- **CHECK THE SFX FILE BEFORE TRUSTING IT.** The pack's `click2.mp3` peaks at
  −25 dB — it is inaudible under speech at any sane volume, and the mix looks
  fine while nothing is heard. `ffmpeg -i <sfx> -af volumedetect -f null -` is
  the check. `cut-click.mp3` (−2 dB, 57ms) is the one that reads.
- **And check WHERE the transient sits inside the file.** The source this click
  came from had 180ms of silence before the hit; delayed to the cut it would have
  landed 180ms late — after a 230ms effect had already finished. Trim the lead-in
  so the transient is at t=0, then delay by the cut time.
- **The delivered click is mixed by ffmpeg, not by Remotion.** The delivery
  re-mux discards Remotion's audio (it drifts), so add the SFX as another input
  with `adelay=<frame/fps*1000>`. The `<Sfx>` in the component only sounds in a
  plain `remotion render`.

## Style: "Limpa" (`edit: "limpa"`) — no split inserts

The whole frame stays on the speaker. **Leave `splitInserts` out of
`edit-data.json` entirely** (an empty array is fine; a populated one is not) and
skip the split director step. Everything else is unchanged — captions, hook,
zoom, tracking, soundtrack and behind-the-subject all still apply, and they are
where the edit gets its life when there is no art on screen.

Two consequences of the frame never being split, both easy to miss:

- **The hook keeps its full-frame padding.** `hook.paddingTop` is tuned per split
  layout (738 / ~920 for a seam that does not exist here). Under `limpa` the
  headline places against the frame, not a seam — start from the template default
  and render one still, rather than carrying a split value over.
- **`captions.windows` has nothing to dodge.** Those entries only exist to move
  the caption off a split seam. Leave the array empty; a stale window from a
  previous render shoves the caption up for no reason.

**This is the default** (`STYLE_CATALOG.edits[0]`), so it is also what a user who
never opens the Estilo tab gets. Split inserts are opted INTO, not out of. It is a
legitimate final look — a talking-head cut, images to be placed by hand later, or
simply no B-roll worth showing — not a placeholder.

## Style: "tela dividida" (split screen) — two variants

Both pin the FACE to a fixed region and give the rest of the frame to the image.
Data lives in `edit-data.json` `splitInserts[]` (`layout: "top" | "bottom"`); the
component is already in the template's `CustomGraphics.tsx`. Every window is
snapped to a take cut, consecutive images contiguous, and `captions.windows`
moves the caption to the seam while a window is up. Full rules in
`assets/shortform/README.md`.

**Seam blend, not a hard cut (2026-08-15, tuned same day after a real-project
test).** The video renders full-bleed as the base layer now (it used to be
cropped to its own complementary region and simply wasn't there behind the
band); the image band is `bandH + SEAM_BLEND` (**60px**, v2 — see below) tall
with a `mask-image` linear-gradient that's solid over its nominal `bandH` and
fades to transparent over the trailing 60px, so the art visibly dissolves into
the video underneath instead of cutting on a line. Reference: a CapCut/Edits
gradient-split-mask tutorial the user sent (`equilíbrio de transparência` —
"balance of transparency" — is literally what the mask percentage controls).
This is now the DEFAULT for every split window, `top` and `bottom` alike — not a
toggle, and not per-project; it lives in the shared `CustomGraphics.tsx` template.

**v1→v2, and why:** the first pass used `SEAM_BLEND=140` and left the
pre-existing legibility darkening (fixed 110px, caps at 0.75 black, ends
exactly at `bandH`) untouched. Tested on a real project — user's verdict:
"ficou péssimo". A zoomed still showed why: the darkening hit its max right
where the mask was still ~opaque, so that exact row painted as a flat
muddy-grey stripe, then the reveal below it showed at low alpha with no
darkening at all — two unrelated fades butted end-to-end instead of moving
together, across a window wider than what the reference actually showed (its
blend read as tight/subtle, not a big foggy port-hole). **Fix:** shrink
`SEAM_BLEND` to 60, and make the darkening a DIP — it now spans `bandH-90` to
`bandH+SEAM_BLEND` and eases back to 0 by the end (peaking at a lower 0.5),
so the seam shadows and then resolves instead of slamming dark and holding.
**Lesson for next time:** verify a full-quality still (zoomed on the seam,
not just the whole frame) before calling a blend/gradient effect done — the
whole-frame stills used the first time looked "fine enough" at a glance and
still shipped something that read as a visible defect up close.

| | **Tela dividida** (`top`) | **Tela dividida 2** (`bottom`) |
|---|---|---|
| Art | top band (750, +60 blend) | bottom band (750, +60 blend) |
| Head | raised underneath, `zoom 1.25 / focusY 400` | held high above, `zoom 1.0 / focusY 225` |
| Caption | ON the seam (`paddingBottom` 1074) | just ABOVE the seam (`paddingBottom` 790) |
| Seam blend (transparency fade into the video) | yes | yes |
| Seam darkening (legibility gradient, dips across the same span as the blend) | yes — the caption sits over the art | **no** — it only greys the top of the photo |

**`focusY` is a SOURCE y that lands at the top of the video window** — a point
`y_src` renders at `(y_src - focusY) * zoom`. **Measure before trusting the
numbers:** pull a frame out of `cut.mp4`, read the hair-top and chin y, and set
`focusY` so the head lands where the user asked. The defaults fit a head ~660px
tall starting at y 455.

The two are opposites in one specific way, and it is the whole trick: the source
has a lot of headroom above the head. `top` has to zoom in to throw that headroom
away; `bottom` **keeps** it, and that is what puts the face under the frame edge
instead of in the middle. Swapping the zoom/focus pair between them breaks both.

**The hook does not transfer for free.** `hook.paddingTop` is tuned to the seam of
whichever layout is up: 738 for `top` (text on the seam under the art), ~920 for
`bottom` (text in the gap between chin and seam). Left at the `top` value, the
headline lands across the speaker's mouth. Render one hook still after switching.

## Behind-the-subject (element between person and background)

Puts an image or giant word(s) BEHIND the person. Great on medium/wide shots;
on tight close-ups anchor elements to the TOP (template already does). Needs
the matting extra: `uv sync --extra matting` (torch).

```bash
uv run python helpers/person_matte.py cut.mp4 -o remotion/public/fg_<name>.mov --start <s> --duration <d>
```

Then describe each window in `edit-data.json` `behind[]` (kind image/words,
matte file, start, dur, words with per-word `at` times). Gotchas the template
already encodes — do not re-learn them:
- ProRes 4444 `.mov` (libvpx silently drops alpha on some builds)
- source RGB composited with alpha, not RVM's `fgr` (halo otherwise)
- `<OffthreadVideo transparent>` or the matte renders opaque
- matte gets the same camera via `frameOffset` or the person drifts

Matte ONLY the windows you need — each file's frame 0 = its window start.

### ASSISTIR cada clipe antes de usar — não basta o nome da pasta

Pedido explícito depois de um insert entrar completamente fora de contexto
(um homem comendo sanduíche sob a fala "tanta gente toma remédio todo dia e
continua cansada"): *"A partir de agora em toda edição você vai assistir todo
vídeo e analisar antes de colocar na edição e comparar com o que eu falo para
ver se está correto ou procurar outro e se não houver pedir pra fazer o
download de algum."*

Procedimento, antes de escrever `splitInserts`:

1. Amostrar 3 frames de cada CANDIDATO (15%, 50%, 85% da duração) numa folha
   ordenada, e ler a folha contra a frase daquela janela.
2. Depois de recortar, amostrar de novo os clipes JÁ recortados — o recorte
   pode cair num trecho que não mostra o assunto.
3. Se nada no acervo servir, **pedir o download** em vez de aproveitar o que
   está perto. Uma pasta chamada "pessoa cansada" não garante que o clipe
   escolhido mostre cansaço.

Duas armadilhas técnicas na amostragem, ambas silenciosas:
- **`-ss` antes do `-i` não funciona nos recortes**: eles saem com um único
  keyframe, o seek de entrada não acha nada e o ffmpeg escreve arquivo vazio
  ("Nothing was written into output file"). Nos recortes, `-ss` vai DEPOIS do
  `-i`.
- **`scale=…:force_original_aspect_ratio=decrease` + `pad` para o mesmo
  tamanho** falha por 1px de arredondamento ("Padded dimensions cannot be
  smaller"). Para folha de revisão, `scale=300:170` direto: distorce um pouco e
  não interessa, o que importa é ver o conteúdo.

### A costura é a BORDA INFERIOR DO VÍDEO, nunca um preenchimento escuro

*"Não quero sombra, quero o vídeo fazendo essa transição na sua borda
inferior."* Um `fit: contain` com fundo desfocado/escurecido deixa uma faixa
escura embaixo do clipe, e é ELA que passa a dissolver — lê como sombra, não
como máscara. A solução é dimensionar a faixa para o clipe:

- **`bandH` + `SEAM_BLEND` = a altura natural do clipe em 1080 de largura.**
  Para 16:9 isso dá 608, ou seja `bandH: 508` com o blend de 100. O clipe
  preenche a faixa inteira com `fit: "cover"`, sobra só ~16% de corte lateral
  (contra 44% numa faixa de 750) e a borda inferior dele é a que dissolve.
- Ao mudar `bandH`, **`focusY` muda junto** — a pessoa é posicionada a partir
  da faixa (`(y_src - focusY) * zoom + bandH`). Com `bandH` 508, `focusY` 560
  mantém a cabeça cruzando a costura.

### Gate obrigatório dos inserts — rodar ANTES de todo render da Fase 2

```bash
uv run python helpers/check_inserts.py <edit>/remotion/public/edit-data.json --min-motion 0.3
```

Pedido explícito do usuário depois de receber um vídeo com as duas falhas ao
mesmo tempo: *"Sempre vai verificar essa proporção de tamanho e se o vídeo está
rodando — tarefa fixa para o erro não repetir."* O helper reprova (exit ≠ 0):

- **Insert congelado.** O clipe da faixa **precisa estar dentro de uma
  `<Sequence>`** no `SplitFrame`; sem ela o `OffthreadVideo` é indexado pelo
  tempo da COMPOSIÇÃO, então uma janela que começa aos 55s pede o segundo 55 de
  um clipe de 5s, passa do fim e congela no último frame. Só a primeira janela
  parece certa — foi assim que passou por um render inteiro. (Corrigido no
  template; o gate existe para o defeito não voltar por outro caminho, como um
  clipe mais curto que a janela.)
- **Insert ampliado.** `fit: "cover"` numa faixa de 1080×850 corta e amplia um
  16:9 até sobrar ~44% do quadro — "proporções maiores do que o normal, fugindo
  da visualização". **O padrão para clipe de banco agora é `fit: "contain"`**,
  que o `SplitFrame` completa com um fundo desfocado do próprio clipe: faixa
  cheia, proporção intacta.

Um verificador que reprova tudo é tão inútil quanto um que aprova tudo: a
primeira versão media movimento lendo o stderr do ffmpeg e devolvia 0.00 para
todo clipe (`metadata=print` só escreve com `file=-`). Validar a métrica contra
um caso conhecido — um clipe congelado de propósito deve dar 0.0 — antes de
confiar no resultado.

### Abertura: capa até ~4s, primeira tela dividida só depois (padrão permanente)

Ordem pedida em 2026-08-16, válida para todo vídeo:

1. A frase de capa entra na altura de leitura e **desliza para cima** para
   liberar o rosto (`hookStacked`: `offsetY` → `offsetYEnd`, `slideStartSec`,
   `slideDurSec`).
2. Ela fica no ar **até ~4s** (`endSec`).
3. **A primeira tela dividida só começa depois que a capa some** — nunca antes
   de 4s. Não precisa ser 4,0 exato: pode ser alguns segundos depois, conforme o
   conteúdo, mas nunca antes.

### Saída da tela dividida: flash próprio, diferente do de entrada

A volta da faixa para a tela cheia era um corte seco e lia como imperfeição.
Cada janela leva DUAS transições: `{"at": start, "variant": "corte"}` (o facho
lateral de sempre) e `{"at": end, "variant": "saida"}` — clarão curto e
simétrico, sem facho, com whoosh baixo. Usar o mesmo desenho nos dois tira o
sentido do facho, que é marcar a troca de layout.

### Zoom in/out durante a tela dividida

A câmera do template **não chega no `SplitFrame`** — ele redesenha o vídeo por
conta própria. Sem `zoomPulse` por janela, o vídeo passa dezenas de segundos com
enquadramento fixo e o usuário lê como "não teve zoom em nenhum corte". Alternar
aproximação e afastamento entre janelas (ex.: 1.07, 0.95, 1.05, 0.97…) resolve;
o zoom é ancorado no rosto, senão mudar a escala empurra a cabeça para fora da
costura.

### Tela dividida COM a pessoa na frente da faixa — o padrão deste usuário (2026-08-16)

**Isto, e não o `behindVideos[]` abaixo, é o que ele quer quando diz "atrás da
cabeça".** As palavras dele, depois de eu ter trocado uma coisa pela outra:
*"quero que fique atrás da cabeça porém mantenha a divisão das telas"* e
*"mantenha a transição entre as telas (cima e baixo) como já estava, suave em
transparência. NÃO mude isso"*. As duas referências visuais que ele mandou
mostram a mesma coisa: conteúdo ocupando a parte de cima, **a cabeça da pessoa
subindo na frente desse conteúdo**, e a costura dissolvendo atrás dela.

São os dois efeitos somados, não a escolha entre eles:

```json
"splitInserts": [
  {"src": "stock/w3.mp4", "kind": "video", "start": 14.97, "end": 19.97,
   "bandH": 750, "layout": "top", "matte": "fg/b3.mov", "focusY": 720}
]
```

- **`matte`** (um `person_matte.py` por janela, frame 0 = início da janela)
  redesenha a pessoa POR CIMA da faixa, com o mesmo par zoom/focusY do vídeo de
  baixo — mesmo enquadramento, ou ela desgruda de si mesma.
- **`focusY` precisa SUBIR a pessoa até ela cruzar a costura.** Com o valor
  padrão do layout (400) o cabelo para ~70px ABAIXO da faixa: o matte é
  desenhado, não dá erro, e o resultado é idêntico à faixa reta de sempre —
  falha silenciosa fácil de dar por boa. Medido neste projeto: 560 encosta,
  640 entra, **720 é o que lê como a referência**. Um ponto `y_src` da fonte
  cai em `(y_src - focusY) * zoom + bandH`.
- A costura continua sendo a do template (`SEAM_BLEND`), sem retângulo de
  escurecimento — não mexer nela.
- Com a legenda `stacked`, descer o bloco (`stackedOffsetY` ~0.30,
  `fontScale` ~0.92): a pessoa sobe, e no lugar de sempre a legenda cai no
  rosto. E **zerar `captions_split.json`** (`[]`), senão as legendas
  re-hospedadas do estilo antigo aparecem junto, duplicadas.

### `behindVideos[]` — B-roll de VÍDEO ocupando o quadro inteiro atrás da pessoa (2026-08-16)

Variante SEM divisão: o B-roll vira o fundo inteiro. Existe e funciona, mas
**não é o padrão dele** — ver a seção acima antes de usar.

The template's own `behind[]` only takes `image`/`words`. For **video** B-roll
behind the subject — which is this user's standing meaning of "tela dividida",
not the top band — use `behindVideos[]` in edit-data.json, rendered by
`BehindVideos` in `CustomGraphics.tsx` (already in the shared template):

```json
"behindVideos": [
  {"src": "ai/p1.mp4", "kind": "video", "matte": "fg/b3.mov",
   "start": 14.9667, "end": 19.9667, "fit": "cover"}
]
```

Layer order inside the window: B-roll full-frame → person on top via
`<DynamicVideo src={matte} frameOffset={-a} transparent/>`, where
`a = round(start*fps) + VIDEO_LAG`. Three things this got right the first time,
worth not re-deriving:

- **The base video is fully covered, so what has to line up is the PERSON.**
  `frameOffset={-a}` is what makes the matte (whose frame 0 is the window start)
  play in step with the camera. Verified on a still, not assumed.
- **Verify alignment with `bgOpacity: 0`** on one window and render one still:
  the B-roll disappears and you see the matte over the base video. Aligned =
  one sharp person; misaligned = a ghost edge. Cheaper and far more conclusive
  than staring at the composited frame.
- **Matting is fast** — measured 7.5s for 60 frames at 1080×1920 on MPS
  (mobilenetv3), i.e. ~real time. A 48s worth of windows took ~2 min. Don't
  plan around it being expensive; it is not. The files ARE big (~70MB per 5s
  window in ProRes 4444), so matte only the windows you use.

### `hookStacked` — capa com a tipografia da legenda (2026-08-16)

The template's `hook` styles `realce`/`misto` paint a **hardcoded** `#ff5200`
and never mix two faces, so a cover that has to share the stacked caption's
identity (heavy white sans + ONE serif-italic accent word) cannot be expressed
through `hook`. Use `hookStacked` instead, with `hook.enabled: false` so the two
covers don't stack:

```json
"hook": {"enabled": false},
"hookStacked": {"enabled": true, "endSec": 6.5, "offsetY": 0.30, "color": "#ffffff",
  "lines": [{"text": "4 hábitos", "style": 0, "size": 112},
            {"text": "que estão destruindo", "style": 1, "size": 66},
            {"text": "a sua tireoide", "style": 2, "size": 112, "color": "#3b82f6"},
            {"text": "todos os dias", "style": 3, "size": 92}]}
```

`style` 0–3 is the SAME scale as the stacked caption's lines (Poppins Black
italic / Poppins regular smaller / Playfair italic accent / Poppins ExtraBold),
which is the whole point — cover and caption read as one family.

## Illustrative images (and video inserts)

**O acervo do usuário vem antes de qualquer banco.** This user keeps a licensed
Shutterstock library at `~/Videos/stock-medico/`, one folder per requested
theme, plus the `PEDIDOS.md` ledger. Two things happen at the START of every
session, before any B-roll decision:

1. **Reconcile the ledger against the library.** For every open `- [ ]` item,
   check whether the clips actually arrived; tick the ones that did (marking is
   the agent's job, never the user's). This is the step that was missing on
   2026-08-16: an entire Phase 2 got built on generic Pexels placeholders while
   99 bought clips covering the exact same beats sat on disk.
2. **Never re-request what the library or the ledger already covers.**

Filenames are opaque IDs, so build a contact sheet to pick: one frame per clip,
**normalized to a single size on disk** before `tile=` (mixed sizes make
ffmpeg's image demuxer stop at the first size change and the sheet silently
comes back short — count the tiles against the file count). Then trim each pick
to its window:

```bash
ffmpeg -y -ss <in> -i <clip> -t <dur> \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30" \
  -an -c:v libx264 -crf 20 -pix_fmt yuv420p public/stock/<nome>.mp4
```

Pexels for generic concepts (key: `PEXELS_API_KEY`). For brands/people/specific
things, **Wikimedia Commons first** (`wikimedia_images.py` — no key, clean
licensing, prints license+author), then `google_images.py` (needs
`GOOGLE_API_KEY`+`GOOGLE_CSE_ID`, mind rights — pass `--rights cc`, flag
licensing to the user for logos/celebrities). Keep photographer credits.

**When nothing real fits — generate it (Kairogen MCP).** For a concept no
stock photo covers cleanly, or when the video calls for a short animated
B-roll clip illustrating exactly what's being said (not a static photo), use
the Kairogen MCP tools directly from chat (`generate_image` /
`generate_video`, `list_models` for the live catalog) — this user has it
connected as a standing MCP server, no per-project setup or API key needed.
**Model routing by tier** (2026-08-15, user-specified — verified each
`model_key` against `list_models` before adopting it):

| Use | Model | Notes |
|---|---|---|
| Draft/teste (fast iteration, cheap) | `nano-banana` | "Nano Banana 2 Lite" doesn't exist as a key — this is the closest real one (the base tier below `nano-banana-2`). Say so if the user expects the exact name. |
| Imagem padrão (approved for use) | `nano-banana-2` | The default once a draft is picked. |
| Imagem final, alta qualidade | `gpt-image-2` | Base mode (text-to-image). Reserve for hero/final assets, not iteration — it costs more. |
| Imagem final com referência | `gpt-image-2` | Same key — pass `reference_image_urls`, the tool auto-switches to `edit` mode (up to 10 images). Not a separate model. |
| text-to-video | `kling-v3-0-pro` | ("Kling 3.0" is shorthand for this.) |
| image-to-video | `seedance-20-fast-t2v` | Despite the `-t2v` in the key, it also supports image-to-video — pass `first_frame_url` and `generate_video` auto-switches mode. |
| Múltiplas referências (video) | `seedance-2-0` | The one built for it: `reference_image_urls` (≤4) + `reference_video_urls` (≤3) at once, multimodal. `seedance-20-fast-t2v` only takes references in `base` (t2v) mode, not alongside `first_frame_url`. |

Draft → approve → regenerate-at-final-quality is the same shape as the
color-grade candidates montage (Hard Rule: show cheap options, get a pick,
commit once) — don't skip straight to `gpt-image-2` for something the user
hasn't seen yet.

`generate_video` covers image-to-video and text-to-video for short animated
inserts. Both image and video calls are async by default
(`wait_for_completion:false` — the widget polls itself; don't manually poll
`get_generation` unless the user asks for a status check). Save the output
into `public/pexels/` (or a same-purpose folder) like any other insert asset.
**Real, identifiable things (an actual news photo, a real person, a specific
product) still come from Pexels/Wikimedia/Google first** — generation is for
concepts and illustrative motion, not a substitute for a real photo of a real
thing (that would misrepresent it as documentary footage). Decided
2026-08-15, session with Dr. Geovane Júnior.

### AI-generated B-roll (`elements.aiVideo` / `elements.aiImage`, 2026-08-16)

Everything above ("when nothing real fits — generate it") is the fallback
that always applies. These elements are a different thing: when ON, go
LOOKING for moments to illustrate with AI-generated content, driven by what's
actually being said, instead of waiting for a gap stock can't fill.

**Two separate elements, not one with a format option** (user request,
2026-08-16): `aiVideo` generates video, `aiImage` generates stills. What to
do per combination:
- **Only `aiVideo` on** → every generated moment is video.
- **Only `aiImage` on** → every generated moment is a still.
- **Both on** → video is the DEFAULT choice for each moment; use a still only
  for a SPECIFIC moment where you judge it reads better that way — not a
  mechanical alternation (user's own words: "revezando... mas dando
  preferência ao vídeo. Imagem somente quando você analisar que naquele
  momento fica mais interessante"). Judge per moment: a concept with real
  motion (a mechanism, a process, a demonstration) wants video; a concept
  that's inherently static (a single number, a static comparison/diagram)
  can legitimately read better as a clean still. Decide moment by moment,
  don't default to one format count-for-count.
- **Neither on** → this whole section doesn't apply; only the stock-first
  fallback above does.

1. **Read the transcript for topic beats.** Walk `takes_packed.md` phrase by
   phrase; a "moment" is a self-contained idea worth a visual (a named
   condition, a mechanism, a comparison, a number) — not every sentence needs
   one. Reuse the density already established for B-roll in general (2-4
   inserts for a ~60-90s short, per the premium-editorial reference) unless
   the user asks for more/less.
2. **Keep the aesthetic uniform across ONE video.** Pick a single model tier
   and a consistent visual language up front (see the model-routing table
   above) and hold it for every generated piece in that video — a video that
   switches style piece to piece reads as a stock-footage grab-bag, which is
   exactly what this element exists to avoid. Draft → approve → regenerate at
   final quality still applies (don't jump straight to the expensive model).
3. **Write the prompt yourself, from what's actually being said — then
   self-review before it ever reaches the edit** (user instruction,
   2026-08-16). Kairogen only generates; it has no idea what this video is
   about or what moment it's for (checked its tools directly —
   `video_analysis_create` reads a video's own visual scenes, not spoken
   content, and nothing in the catalog reads a transcript or times a result
   against one). So the loop is:
   1. From the transcript phrase for this moment, write a SPECIFIC prompt —
      the actual condition/mechanism/comparison being described, with real
      detail (setting, framing, mood), not a generic restatement of the
      sentence.
   2. Call `generate_image`/`generate_video` with it.
   3. **Look at the result yourself before inserting anything.** Does it
      actually match what's being said, hold the video's visual language,
      and read as usable? If not, do not insert it — write a correction
      prompt (what was wrong, what to change) and regenerate. Repeat until
      it's right, same as the color-grade candidates montage: judge the
      actual output, don't approve on the first try by default.
   4. Only an approved result gets placed per step 4 below.
4. **Placement depends on `preview_style.json`'s `edit` pick — reuse the
   existing mechanism, don't build a new one:**
   - **`edit: "limpa"` (single screen)** → an `inserts[]` entry, same as any
     other cutaway (see "Illustrative images" above): a brief window (a few
     seconds) with a fast, smooth transition in and out. After it, either
     return to the original camera OR flow straight into the NEXT generated
     insert if the topic keeps going — read the transcript to decide which;
     don't mechanically alternate. `InsertCard`'s default fade (9 frames in /
     7 out, ~0.3s) already reads as fast/smooth — reuse it for the general
     shortform look. **For a premium-editorial video, use that style's OWN
     B-roll treatment instead** (full-bleed, same grade applied, no whoosh
     SFX, no floating card) — see "B-roll" in
     `references/style-premium-editorial.md`; do not use the generic
     `InsertCard`/whoosh combo there, it directly contradicts that style's
     own rules.
   - **`edit: "split" | "split2"` (split screen)** → a `splitInserts[]` entry.
     For a still, `kind: "image"`, exactly like a real photo would use that
     slot. **For real motion, `kind: "video"` (2026-08-16, built for this) —
     the band now plays actual video**, not just a still frame lifted from
     one: `CustomGraphics.tsx`'s `SplitFrame` renders an `OffthreadVideo`
     inside the same masked band instead of an `Img` when `kind` is
     `"video"`, muted (the only audio track is `cut.mp4`'s). Either way the
     band mechanism already keeps this OFF the original video (full-bleed
     underneath, the art is an overlay confined to its own top/bottom band)
     — generating the content only changes WHERE it comes from, not the
     layout contract. **Generate/trim the clip to the window's own length
     (`end - start`) rather than relying on looping** — cleaner than a visible
     loop seam. If a clip really is shorter than its window, set
     `loopFrames` to the clip's own duration in frames and it plays on a
     `<Loop>`; leave it unset when the length already matches.
5. **Save generated assets** into `public/pexels/` (or a same-purpose
   folder) like any other insert, and credit nothing (it's not a real
   photograph) — no photographer/license line for these.

## Biblioteca de gráficos (`graphics`, 2026-09-01)

Gráficos de DADO no `edit-data.json`, renderizados pelo template compartilhado
(`CustomGraphics.tsx` → `<Graphics/>`). Um objeto por gráfico; `start`/`end`
em segundos do `cut.mp4`; entram com fade + deslize e um whoosh (`"sfx": false`
desliga); `accent` aceita nome da paleta dos title cards (`dourado`, `azul`…)
ou hex. Cartões ficam na zona de cima (mesma dos inserts); o lower third, no
rodapé acima da legenda.

```json
"graphics": [
  {"kind": "lowerThird", "start": 1.0, "end": 5.0, "name": "Dr. Geovane Júnior", "role": "Nutrologia · CRM-PE 28037", "y": 0.60},
  {"kind": "stat", "start": 8.2, "end": 11.5, "value": "70%", "label": "das mulheres depois dos 40 perdem massa muscular", "accent": "dourado"},
  {"kind": "list", "start": 14.0, "end": 20.0, "title": "3 coisas que seguram isso", "items": ["Musculação", "Proteína suficiente", "Comer menos à noite"]},
  {"kind": "compare", "start": 22.0, "end": 26.0, "left": {"title": "Antes", "value": "38 kg"}, "right": {"title": "Depois", "value": "31 kg"}},
  {"kind": "quote", "start": 30.0, "end": 34.0, "text": "Não existe pílula mágica.", "source": "Lancet, 2026"},
  {"kind": "progress", "start": 36.0, "end": 40.0, "label": "Adesão ao tratamento", "from": 0, "to": 82, "suffix": "%"},
  {"kind": "callout", "start": 42.0, "end": 45.0, "text": "olha aqui", "x": 0.62, "y": 0.48}
]
```

### `anotacao` — legenda manuscrita escrita à mão (2026-09-03)

Estilo pedido a partir de uma referência: em vez de legendar palavra a palavra,
o vídeo **anota a ideia** — o texto é DIGITADO letra a letra e as linhas
ACUMULAM, como alguém escrevendo num caderno enquanto fala. Substitui a legenda
karaokê (`captions.enabled: false`), não convive com ela.

```json
{"kind": "anotacao", "start": 9.6, "end": 18.5, "y": 0.70, "cps": 34,
 "lines": [
   {"text": "os análogos de GLP-1", "at": 9.8, "size": 50},
   {"text": "TIRAM A FOME", "at": 11.6, "style": "caps", "size": 56, "underline": true},
   {"text": "mas não tratam a compulsão", "at": 13.9, "size": 48, "mark": "compulsão"}
 ]}
```

- `at` por linha: o segundo do corte em que ELA começa a ser escrita. `cps` é a
  velocidade (padrão 34 caracteres/s — é o que bate com a referência).
- `style`: `normal` (Architects Daughter), `caps` (a mesma em maiúsculas),
  `marker` (Permanent Marker, para o grito). `font` força a família
  (`hand`/`patrick`/`caveat`/`marker`) — Caveat é cursiva e NÃO é o estilo.
- `underline` desenha o sublinhado **crescendo junto com o texto**; `mark`
  grifa um trecho de marca-texto amarelo, também só sob a parte já escrita.
  Os dois nunca aparecem antes da palavra que marcam — é isso que faz parecer
  escrita à mão em vez de texto revelado.
- **Som:** `typing.mp3` toca durante a escrita de cada linha (`typeSfx: false`
  desliga). Medido no mix: +16,7 dB na banda 3,5–9 kHz durante a digitação
  contra a mesma frase parada.

**Escrever ANOTAÇÃO, não transcrição.** A referência sintetiza a ideia em 2–4
linhas curtas por bloco; transcrever a fala inteira em manuscrito fica pesado e
perde o efeito. Linha ≤ 36 caracteres em size 50 (largura útil 912 px).

**`y` depende do enquadramento, e a zona de cima pode estar ocupada.** Na
referência o bloco fica no TOPO, mas num vídeo com tela dividida o topo é da
faixa: aí o bloco vai para baixo. Em fonte close com `bandH 860`, **`y: 0.70`**
deixa o texto abaixo do queixo com 4 linhas ainda fora da zona do rodapé;
`y: 0.60` cai em cima da boca. Calibre num still de um bloco de 4 linhas.

**Cuidado com vãos.** Como o bloco some no `end`, um intervalo grande entre
blocos deixa a tela sem texto nenhum — o que com a legenda karaokê nunca
acontecia. Liste os vãos antes de renderizar; acima de ~2 s, escreva um bloco.

Regras: um gráfico por vez na zona de cima (não sobreponha `stat` e `list`);
o `stat` conta até o número em ~1,2 s, então dê pelo menos 3 s de janela; o
`callout` aponta para um ponto do quadro em fração (0–1) — meça num still. A
timing de cada um cai na palavra que ele ilustra (transcript do corte), como
os inserts. Confira com `contact_sheet.py` e, na entrega, o `qc_final.py`
diz se algum caiu em zona coberta pela interface.

## Phase 3 — soundtrack (short-form)

Ask: **AI-generated** (Treblo) or **local file** (copy to `public/trilha.mp3`).

**Writing the Treblo prompt — derive it from the video's context, and ask for
MUSIC, not a texture.** Read the cut transcript: what's the topic, energy and
emotional arc? Then describe a real **composed instrumental piece** — name a
**genre + key instruments + tempo/BPM + mood**, and (optionally) a reference
artist/style. Match the content: a hype tech/AI reel wants upbeat modern
electronic with a catchy synth melody; a calm tutorial wants warm lo-fi keys; a
luxury/story piece wants cinematic strings. **Avoid SFX-y phrasing** ("bed",
bare "beat", "sound design", "drones", "risers") — that's what makes Treblo
return sound effects instead of a song. `treblo_music.py` auto-frames the vibe
as a composed instrumental and bans SFX/vocals, but the vibe you pass still has
to read musical.
```bash
uv run python helpers/treblo_music.py "upbeat modern electronic, catchy synth melody, warm analog bass, crisp light drums, ~110 BPM, bright and motivational" -o public/trilha.mp3 --length-min 30 --length-max 60
```
Then flip `soundtrack.enabled: true` in edit-data.json. **Volume:** start ~0.25
and check it's clearly audible under wall-to-wall narration (a bed at 0.12 is
usually inaudible once the mix is loudnorm'd to the voice — confirm by listening,
not just by the meter). Re-render. Finish with the mandatory loudnorm:

**Take the PICTURE from Remotion and the AUDIO from `cut.mp4`.** Remotion's own
audio track drifts against the source — measured on a 95s edit: the voice is
+90ms late by 8s and +660ms by 78s, i.e. it slides progressively out of lip sync,
unnoticeable at the start and obvious by the end. Its audio track also comes out
~0.7s longer than its video. So never re-encode Remotion's audio; re-mux the
approved master instead and mix the soundtrack here:

**Remotion's picture is FULL-RANGE and mis-tagged — never `-c:v copy` it.** Its
output is `yuvj420p`, `color_range=pc`, `color_primaries=bt470bg` (PAL!), transfer
unknown. Measured: luma 0–255 where `cut.mp4` sits at 16–235. Copying the stream
carries all of that into the delivery, so a compliant player shifts the hue off the
PAL primaries and a player that ignores the range tag crushes the blacks — the
Phase-1 grade the user approved drifts at the very last step. Convert the range and
stamp the tags. `setparams` is what makes them stick: the bare `-color_primaries` /
`-color_trc` output flags silently leave both `unknown` here.

```bash
VD=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=nw=1:nk=1 out/render.mp4)
FADE=$(python3 -c "print(f'{$VD-1.5:.3f}')")
ffmpeg -y -i out/render.mp4 -i ../cut.mp4 -i public/trilha.mp3 \
  -filter_complex "[0:v]scale=in_range=full:out_range=limited,format=yuv420p,\
setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[vid];\
                   [1:a]adelay=33:all=1[v];\
                   [2:a]volume=0.10,afade=t=in:st=0:d=0.4,afade=t=out:st=$FADE:d=1.5[m];\
                   [v][m]amix=inputs=2:duration=first:normalize=0[mix];\
                   [mix]loudnorm=I=-14:TP=-1:LRA=11[out]" \
  -map "[vid]" -map "[out]" -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  -c:a aac -b:a 192k -ar 48000 -t "$VD" -movflags +faststart ../final.mp4
```

**Verify the delivery carries the same tags as the cut** — `bt709 / bt709 / bt709 /
tv`, exactly what left Phase 1:
```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=color_space,color_primaries,color_transfer,color_range \
  -of default=nw=1 ../final.mp4
```

**Keeping Remotion's audio is sometimes the right call — measure, don't assume.**
The re-mux above exists because Remotion's audio drifts, and on a 95s edit it does
(+660ms by 78s). But the `stacked` caption bakes a click on nearly every word plus
the flash clicks, and the re-mux throws all of that away — reconstructing ~20 SFX
by hand from the cue file is guesswork. Correlate first (15s+ windows, or the whole
clip when it is short): if the offset is CONSTANT across start/middle/end there is
no drift, and Remotion's own audio keeps the SFX with the sync intact. Measured on
a 7.6s edit: +42.7ms at the head, the tail and the whole — constant, and only ~10ms
from the picture's own +33ms lag. There, `-map 0:a` through the same loudnorm beats
the re-mux. Say which one you used and why.

`adelay=33` is one frame at 30fps: OffthreadVideo draws the source frame one
composition frame late (the same VIDEO_LAG the overlays compensate for), so the
picture sits a frame behind cut.mp4's timeline and the voice must follow it.
`-t "$VD"` keeps the audio from outliving the video. **Verify** by correlating the
delivered voice against `cut.mp4` at three points — the offset must be CONSTANT
(≈+33ms). Use 15s windows: short windows lock onto the wrong syllable and report
a drift that is not there. Drop this re-mux ONLY if Phase 2 baked SFX into the
audio (stacked captions' click/scratch), and then verify sync by hand.

If the video has no soundtrack, the same shape without input 2:

```bash
ffmpeg -y -i out/render.mp4 -i ../cut.mp4 -filter_complex "[1:a]adelay=33:all=1,loudnorm=I=-14:TP=-1:LRA=11[out]" \
  -map 0:v -map "[out]" -c:v copy -c:a aac -b:a 192k -ar 48000 -t "$VD" -movflags +faststart ../final.mp4
```

Verify `max_volume ≤ -1 dB` (`-af volumedetect`). Copy to `edit/final.mp4`.

---

## The Estilo tab (between Fase 1 and Fase 2)

The cut is approved and nothing about the LOOK of Fase 2 is decided yet. **Do not
ask the style questions in chat** — set `"awaitingStyle": true` in `state.json`
and the UI opens its own tab, sitting between FASE 1 and FASE 2:

- **Tipo de edição** — `limpa` ("Limpa": no split inserts, full frame throughout —
  **the default**, and the right pick for a talking-head cut or when the user will
  place images by hand later), `split` ("Tela dividida"), `split2` ("Tela
  dividida 2").
- **Cor de destaque** — `accent`, a hex. Sits BEFORE the text styles, because it
  is what they paint with. One spectral swatch (the OS picker) plus a hex field,
  synced both ways — no preset row. Only `realce`/`misto` headlines and the
  `stacked` caption paint an accent, so the save also carries **`accentUsed`**;
  when it is `false` the picked styles have none and the colour is not an
  instruction to invent a place for one.
- **Estilo de headline** — `outline`, `card`, `realce`, `misto`,
  **`personalizada`** (2026-09-11). Always two lines, size fitted to the text
  (see the track reference). Quando o pick é `personalizada`, o save traz
  **`headlineCustom`** e ele mapeia direto para o `hook` do `edit-data.json`:
  `color` → `hook.color` (linha 1), `accentColor` → `hook.accentColor`
  (linha 2), `weight1`/`weight2` → `hook.weights: [w1, w2]`, `maxFontPx` →
  `hook.maxFontPx`, `paddingTop` → `hook.paddingTop`, mais
  `hook.style: "personalizada"`. O teto de tamanho continua sendo TETO: a
  frase sempre cabe em duas linhas e encolhe sozinha. `headlineCustom` só
  viaja quando a headline É personalizada — nos presets a aparência é o
  preset, mesma lógica do `accentUsed`.
- **Fonte da headline** (2026-08-15) — `poppins`/"Impacto" (default), `bebas`/
  "Condensada" (Bebas Neue), `anton`/"Cartaz" (Anton), `playfair`/"Editorial"
  (Playfair Display italic). Independent of the style above — every card in
  BOTH rows renders the real headline, cross-reactive (the style cards use the
  currently picked font, the font cards use the currently picked style), not a
  generic type sample.
- **Estilo de legenda** — three animated (`karaoke`, `stacked`/"Empilhado",
  `scatter`/"Disperso") and six static (`simples`, `serifada`, `classica`,
  `impacto`/Anton uppercase poster, `editorial`/Playfair Display italic,
  `premium`/Poppins ExtraBold low-band white — added 2026-08-16, the base
  dialogue caption for the premium-editorial style, opt-in here rather than
  auto-applied — see "Default vs opt-in" in `style-premium-editorial.md`).
- **Elementos da edição** — checkboxes: `tracking` (movimento de tracking),
  `musicAI` (trilha sonora com IA), `aiVideo`
  (gerar vídeos por IA, 2026-08-16), `aiImage` (gerar imagens por IA,
  2026-08-16) — see "AI-generated B-roll" above for how the last two interact
  — plus a free-text observation field. `zoomAuto`, `zoomCuts` and `flashCut`
  are in the same row but **travados** (chip with a "sempre" badge, `always:
  true` in `STYLE_CATALOG.elements`): shown so the user sees what the edit
  applies, not clickable, always saved `true`.

Saving writes `<edit>/preview_style.json` (its OWN file — a style pick and a
timeline correction are different screens at different moments, and one shared
file would clobber the other) and `watch_edits.py` notifies you with the picks,
**what was left out**, and the observation. Then: build Fase 2 from exactly those
choices, **copy them into `state.json` as `style`**, clear `awaitingStyle`, and
delete `preview_style.json`.

Writing `style` back is not bookkeeping — it is what keeps the tab open. The tab
is enabled while `awaitingStyle` OR `style` is set, so the user can return, change
a caption style or tick one more element, and save again. That save arrives with
`"rerender": true` and the watcher says **REFAÇA a Fase 2** — re-render with the
new choices, don't treat it as a first pick.

**The catalog lives in `STYLE_CATALOG` (app.js), not in a session.** A new editing
or caption style is one entry there plus its implementation in the track
reference; adding it in chat only, for one project, makes it invisible to every
other project. What is in it today is the **short-form** vocabulary (tela
dividida, karaokê/empilhado) — on a longform job the gate has nothing to offer
yet, so skip `awaitingStyle` and ask the layer questions in chat until longform
entries exist here.

---

## Anti-patterns (Fase 2/3)

These moved out of SKILL.md: they only bite after the phase gate, and the
skill prompt is resent every turn.

- Asking the style questions in chat, or starting Phase 2 before the pick lands.
  The gate screen exists so the user SEES what each style does — a chat list of
  names asks them to choose blind. Set `awaitingStyle` and wait for
  `preview_style.json`.
- Treating an unchecked element as "não pediu". It is an explicit NO: the user
  looked at "Movimento de tracking" and left it off. `watch_edits.py` prints the
  `fora:` line for exactly this reason.
- Hardcoding `#ff5200` (or any accent) in the template. The Estilo tab lets the
  user pick it, so a literal makes the preview show their colour and the render
  show orange — worse than not offering the choice. Feed `accent` into
  `hook.accent` + `captions.accent`.
- Changing a caption's look in the template without changing its preview in
  `app.js` (`buildKaraokeDemo` / `buildStackedDemo`). The gate's previews render
  the real faces, sizes and motion, scaled from 1080-wide — that is the whole
  reason the user can choose by looking. A preview that lies about the style is
  worse than no preview.
- Hardcoding a bespoke graphic's timings inside `CustomGraphics.tsx`. Put the
  windows in an `edit-data.json` array (a key the template ignores, e.g.
  `splitInserts`) and map over it — otherwise the graphic is invisible to the
  preview timeline and the user cannot see or retime it.
- Re-rendering Phase 1 without regenerating `segments.json`. Every Phase-2
  overlay that must land on a cut is indexed off that file; stale, it is off by
  frames and nothing errors. Worse, a `VIDEO_LAG`-style constant can absorb the
  first frame of the drift and make a broken file look correct at the one
  boundary you happen to check.
- Delivering Phase 2 with Remotion's own audio track — it drifts progressively against the source (+0.66s by 78s on a 95s edit). Re-mux `cut.mp4`'s audio and mix the soundtrack in ffmpeg (recipe in the track reference).
- Judging A/V sync with short correlation windows — speech is quasi-periodic and a 2–3s window happily locks onto the wrong syllable, inventing a drift. Use 15s+ windows, and remember a PARTIAL render cannot show drift that accumulates over the full timeline.
- Indexing Phase 2 off `Σ(end−start)` when a `jcut_timeline` exists — the J-cut output is shorter, so everything after the first take lands late.

---

## Helpers de Fase 2/3

- **`captions_for_remotion.py`** (karaoke JSON) · **`face_track.py`** (eye-track JSON) · **`person_matte.py`** (RVM alpha matte; `uv sync --extra matting`) · **`pexels_search.py`** · **`wikimedia_images.py`** (no key, brands/people first choice) · **`google_images.py`** (fallback, mind rights) · **`captions_srt.py`** (longform .srt) · **`chapters.py`** (YouTube chapters) · **`treblo_music.py`** (AI soundtrack — pass a context-driven MUSICAL vibe: genre + instruments + tempo + mood, not SFX-y phrasing; auto-framed as a composed instrumental).

---

## Chaves opcionais (nunca pedidas na instalação)

Nada aqui é necessário para instalar ou para a Fase 1. Peça UMA chave só no
momento em que o recurso for de fato usado, explique para quê, e escreva em
`.env` na raiz da skill — nunca em `<videos_dir>`. Se o usuário não quiser, siga
pelo caminho sem chave e diga o que muda.

| Chave | Recurso | Sem ela |
|---|---|---|
| `PEXELS_API_KEY` | imagens/vídeos ilustrativos | Wikimedia Commons cobre a maioria |
| `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | marcas, pessoas e logos específicos | Wikimedia é o fallback |
| `TREBLO_API_KEY` | trilha sonora composta por IA (Fase 3) | trilha só a partir de arquivo local |

### Como o usuário cria a chave do Treblo (trilha com IA)

Quando ele escolher `musicAI` e não houver `TREBLO_API_KEY`, dite estes passos —
são a interface real do site, não um resumo:

1. Acessar **https://treblo.com/** e fazer login.
2. Clicar no **perfil**, no canto superior direito.
3. Abrir a seção **Developers**.
4. Clicar em **Get Started for Free**.
5. Clicar em **API Keys**.
6. Clicar em **Create Key**, escrever o nome **Edvid** e confirmar em **Create**.
7. Copiar a chave e colar na conversa.

Ao receber a chave: escreva `TREBLO_API_KEY=<chave>` no `.env` da raiz da skill,
confirme em uma linha que gravou, e **nunca repita a chave de volta** na conversa
nem em saída de ferramenta. Se ele preferir não criar conta, siga com trilha de
arquivo local — a Fase 3 funciona assim, só não compõe.

A instalação não menciona nenhuma delas de propósito: a edvid não precisa de
chave para funcionar, e listar chaves no primeiro contato faz parecer que precisa.
