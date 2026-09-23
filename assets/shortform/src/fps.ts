import {useVideoConfig} from 'remotion';

/**
 * Every animation duration in this template was authored as a frame count at
 * 30fps (a "9" means 300ms). `F(n)` turns one of those counts into frames at
 * the composition's real fps, so a 60fps render keeps the same timing in
 * seconds instead of playing every fade twice as fast.
 *
 * At 30fps it returns `n` untouched — the 30fps output is bit-identical to the
 * pre-2026-09-22 template. Elsewhere it rounds to whole frames, which is what
 * <Sequence from/durationInFrames> needs and what interpolate() ranges are
 * happy with.
 *
 * NOT for VIDEO_LAG or the camera's `frame - 1`: those are one DECODE frame
 * (OffthreadVideo lands one composition frame late on a cut boundary), a fixed
 * count at any fps, not a duration.
 */
export const BASE_FPS = 30;

export const scaleFrames = (n: number, fps: number): number =>
  fps === BASE_FPS ? n : Math.round((n * fps) / BASE_FPS);

export const useF = () => {
  const {fps} = useVideoConfig();
  return (n: number) => scaleFrames(n, fps);
};

/**
 * The current frame expressed in 30fps units (unrounded). For motion written
 * as a function of the frame itself — `Math.sin(f * 0.2)` wobbles, typewriter
 * "chars per frame" — where rescaling each literal would be noisier than
 * rescaling the clock. Exact at 30fps: f * 30 / 30 === f.
 */
export const toBase = (frame: number, fps: number): number =>
  fps === BASE_FPS ? frame : (frame * BASE_FPS) / fps;
