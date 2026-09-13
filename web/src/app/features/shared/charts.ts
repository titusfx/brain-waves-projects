import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  effect,
  input,
  viewChild,
} from '@angular/core';

import { bandColor } from '../../core/format';

const TRACE_COLOURS = ['#38bdf8', '#34d399', '#a78bfa', '#fbbf24', '#f472b6', '#22d3ee'];

/** Prepare a canvas for a device-pixel-ratio-correct redraw. Returns null if hidden. */
function prepare(canvas: HTMLCanvasElement | undefined): {
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
  dpr: number;
} | null {
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) return null;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.floor(rect.width * dpr);
  const height = Math.floor(rect.height * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#04070d';
  ctx.fillRect(0, 0, width, height);
  return { ctx, width, height, dpr };
}

/**
 * A recorded file, drawn as stacked strips.
 *
 * Decimated, not averaged, by the server — an average would smooth away exactly the
 * transient that says a recording is bad, and a bad recording that looks smooth is the
 * most expensive kind of wrong.
 */
@Component({
  selector: 'eeg-sample-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas class="h-full w-full"></canvas>`,
})
export class SampleChart {
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  /** Rows of the 14 channels, in channel order, oldest first. */
  readonly rows = input<number[][]>([]);
  /** The full channel name list, so strips can be picked by name rather than index. */
  readonly allChannels = input<string[]>([]);
  readonly channels = input<string[]>([]);
  readonly fullScaleUv = input(100);

  constructor() {
    effect(() => {
      this.rows();
      this.channels();
      this.draw();
    });
    afterNextRender(() => {
      const canvas = this.canvasRef()?.nativeElement;
      if (!canvas) return;
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;

    const rows = this.rows();
    const names = this.channels();
    const strips = Math.max(names.length, 1);
    const stripHeight = height / strips;
    const scale = this.fullScaleUv();
    const columns = rows.length;

    names.forEach((name, strip) => {
      const top = strip * stripHeight;
      const centre = top + stripHeight / 2;
      const half = stripHeight / 2 - 6 * dpr;

      ctx.strokeStyle = 'rgb(148 163 184 / 0.16)';
      ctx.lineWidth = dpr;
      ctx.beginPath();
      ctx.moveTo(0, Math.round(top) + 0.5);
      ctx.lineTo(width, Math.round(top) + 0.5);
      ctx.stroke();

      ctx.strokeStyle = 'rgb(148 163 184 / 0.3)';
      ctx.beginPath();
      ctx.moveTo(0, centre);
      ctx.lineTo(width, centre);
      ctx.stroke();

      const index = this.allChannels().indexOf(name);
      if (index < 0 || columns < 2) {
        ctx.fillStyle = '#64748b';
        ctx.font = `${11 * dpr}px ui-monospace, monospace`;
        ctx.fillText(`${name} — nothing to draw`, 8 * dpr, centre + 4 * dpr);
        return;
      }

      ctx.strokeStyle = TRACE_COLOURS[strip % TRACE_COLOURS.length];
      ctx.lineWidth = 1.3 * dpr;
      ctx.beginPath();
      for (let column = 0; column < columns; column += 1) {
        const value = rows[column][index] ?? 0;
        const x = (column / (columns - 1)) * width;
        const y = centre - (value / scale) * half;
        if (column === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      ctx.fillStyle = 'rgb(226 232 240 / 0.85)';
      ctx.font = `600 ${11 * dpr}px ui-monospace, monospace`;
      ctx.fillText(name, 8 * dpr, top + 13 * dpr);
    });
  }
}

/** The bands, in the order they appear on the axis. */
const BAND_SPANS: { key: string; from: number; to: number }[] = [
  { key: 'delta', from: 1, to: 4 },
  { key: 'theta', from: 4, to: 8 },
  { key: 'alpha', from: 8, to: 13 },
  { key: 'beta', from: 13, to: 30 },
  { key: 'gamma', from: 30, to: 45 },
];

/** One instance of a state, as the overlay draws it. */
export interface OverlayTrace {
  label: string;
  colour: string;
  /** Microvolts from the start of the state. */
  values: number[];
  /** Every `step`-th sample was kept, so time = index * step / sampleRate. */
  step: number;
}

/**
 * Several instances of a state drawn on top of each other, from the same origin.
 *
 * This is the "two graphs at the same time" view: where the traces sit on top of each
 * other, the states agree; where they diverge, that part of the recording is not
 * something the state controls. Deliberately not averaged — an average hides exactly the
 * disagreement that matters.
 */
@Component({
  selector: 'eeg-trace-overlay',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas class="h-full w-full"></canvas>`,
})
export class TraceOverlay {
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly traces = input<OverlayTrace[]>([]);
  readonly sampleRate = input(128);
  readonly fullScaleUv = input(100);

  constructor() {
    effect(() => {
      this.traces();
      this.draw();
    });
    afterNextRender(() => {
      const canvas = this.canvasRef()?.nativeElement;
      if (!canvas) return;
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    const traces = this.traces().filter((trace) => trace.values.length > 1);
    if (!traces.length) {
      ctx.fillStyle = '#64748b';
      ctx.font = `${12 * dpr}px ui-monospace, monospace`;
      ctx.fillText('no states selected', 12 * dpr, height / 2);
      return;
    }

    const fs = this.sampleRate();
    const seconds = Math.max(
      ...traces.map((trace) => ((trace.values.length - 1) * trace.step) / fs),
    );
    const scale = this.fullScaleUv();
    const padTop = 16 * dpr;
    const padBottom = 18 * dpr;
    const plot = height - padTop - padBottom;
    const centre = padTop + plot / 2;
    const half = plot / 2;

    // One-second gridlines, so "where they diverge" has a time attached to it.
    ctx.strokeStyle = 'rgb(148 163 184 / 0.12)';
    ctx.lineWidth = dpr;
    for (let s = 1; s <= Math.floor(seconds); s += 1) {
      const x = Math.round((s / seconds) * width) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, padTop + plot);
      ctx.stroke();
    }
    ctx.strokeStyle = 'rgb(148 163 184 / 0.3)';
    ctx.beginPath();
    ctx.moveTo(0, centre);
    ctx.lineTo(width, centre);
    ctx.stroke();
    ctx.fillStyle = '#64748b';
    ctx.font = `${10 * dpr}px ui-monospace, monospace`;
    ctx.fillText(`±${scale} µV`, 4 * dpr, height - 5 * dpr);
    ctx.fillText(`${seconds.toFixed(1)} s from each state's start`, 60 * dpr, height - 5 * dpr);

    traces.forEach((trace, index) => {
      ctx.strokeStyle = trace.colour;
      // The first few instances carry the eye; later ones fade so ten overlaid traces
      // stay readable rather than becoming a solid block.
      ctx.globalAlpha = index < 4 ? 0.95 : 0.45;
      ctx.lineWidth = 1.3 * dpr;
      ctx.beginPath();
      trace.values.forEach((value, i) => {
        const x = ((i * trace.step) / fs / seconds) * width;
        const y = centre - (value / scale) * half;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    });
    ctx.globalAlpha = 1;

    // A colour key, because the point is comparing *which* instance.
    let legendX = 6 * dpr;
    traces.slice(0, 6).forEach((trace) => {
      ctx.fillStyle = trace.colour;
      ctx.fillRect(legendX, 4 * dpr, 7 * dpr, 7 * dpr);
      ctx.fillStyle = '#94a3b8';
      ctx.font = `${10 * dpr}px ui-monospace, monospace`;
      ctx.fillText(trace.label, legendX + 10 * dpr, 11 * dpr);
      legendX += ctx.measureText(trace.label).width + 26 * dpr;
    });
  }
}

/** One class on the spectrum overlay: its instances, or its mean and spread. */
export interface OverlaySeries {
  label: string;
  colour: string;
  /** Individual instance spectra, when the caller wants the raw lines. */
  instances?: number[][];
  /** Class mean and spread, drawn as a shaded band plus a line. */
  mean?: number[];
  sd?: number[];
}

/**
 * Spectra overlaid, with each state's spread shaded behind its mean.
 *
 * The band is the important part: a mean line on its own invites reading a difference
 * into two curves that are well inside each other's scatter. Seeing the two bands
 * overlap is the honest version of "they look different here".
 */
@Component({
  selector: 'eeg-spectrum-overlay',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas class="h-full w-full"></canvas>`,
})
export class SpectrumOverlay {
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly freqs = input<number[]>([]);
  readonly series = input<OverlaySeries[]>([]);
  /** Per bin: true where the two states are the same. Shaded, because it matters. */
  readonly shared = input<boolean[]>([]);
  /** Frequencies to mark with a line, e.g. the bins carrying the difference. */
  readonly highlight = input<number[]>([]);
  readonly showInstances = input(true);

  constructor() {
    effect(() => {
      this.freqs();
      this.series();
      this.shared();
      this.draw();
    });
    afterNextRender(() => {
      const canvas = this.canvasRef()?.nativeElement;
      if (!canvas) return;
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    const freqs = this.freqs();
    const series = this.series();
    if (freqs.length < 2 || !series.length) {
      ctx.fillStyle = '#64748b';
      ctx.font = `${12 * dpr}px ui-monospace, monospace`;
      ctx.fillText('nothing to compare yet', 12 * dpr, height / 2);
      return;
    }

    const padTop = 16 * dpr;
    const padBottom = 18 * dpr;
    const plot = height - padTop - padBottom;
    const lo = freqs[0];
    const hi = freqs[freqs.length - 1];
    const xOf = (f: number) => ((f - lo) / (hi - lo)) * width;

    const values = series.flatMap((entry) => [
      ...(entry.mean ?? []),
      ...(entry.sd ?? []).flatMap((sd) => [sd, -sd]),
      ...(this.showInstances() ? (entry.instances ?? []).flat() : []),
    ]);
    const high = Math.max(...values);
    const low = Math.min(...values);
    const span = Math.max(high - low, 1e-6);
    const yOf = (value: number) => padTop + plot * (1 - (value - low) / span);

    // The bins that are the same in both states, marked along the bottom: those cannot
    // explain a difference, however much the curves appear to wiggle there.
    const shared = this.shared();
    if (shared.length === freqs.length) {
      ctx.fillStyle = 'rgb(148 163 184 / 0.16)';
      shared.forEach((isShared, i) => {
        if (!isShared) return;
        const x = xOf(freqs[i]);
        const w = Math.max(1, width / freqs.length);
        ctx.fillRect(x, height - padBottom, w, padBottom - 4 * dpr);
      });
    }

    ctx.globalAlpha = 0.08;
    for (const band of BAND_SPANS) {
      ctx.fillStyle = bandColor(band.key);
      ctx.fillRect(xOf(band.from), padTop, xOf(band.to) - xOf(band.from), plot);
    }
    ctx.globalAlpha = 1;

    ctx.strokeStyle = 'rgb(148 163 184 / 0.2)';
    ctx.lineWidth = dpr;
    for (const tick of [4, 8, 13, 30]) {
      if (tick <= lo || tick >= hi) continue;
      const x = Math.round(xOf(tick)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, padTop + plot);
      ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.font = `${10 * dpr}px ui-monospace, monospace`;
      ctx.fillText(`${tick}`, x + 3 * dpr, height - 5 * dpr);
    }

    series.forEach((entry) => {
      if (this.showInstances() && entry.instances) {
        ctx.strokeStyle = entry.colour;
        ctx.globalAlpha = 0.35;
        ctx.lineWidth = dpr;
        for (const line of entry.instances) {
          ctx.beginPath();
          line.forEach((value, i) => {
            const x = xOf(freqs[i]);
            const y = yOf(value);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      if (entry.mean && entry.sd) {
        ctx.fillStyle = entry.colour;
        ctx.globalAlpha = 0.18;
        ctx.beginPath();
        entry.mean.forEach((value, i) => {
          const x = xOf(freqs[i]);
          const y = yOf(value + entry.sd![i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        for (let i = entry.mean.length - 1; i >= 0; i -= 1) {
          ctx.lineTo(xOf(freqs[i]), yOf(entry.mean[i] - entry.sd[i]));
        }
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;

        ctx.strokeStyle = entry.colour;
        ctx.lineWidth = 1.8 * dpr;
        ctx.beginPath();
        entry.mean.forEach((value, i) => {
          const x = xOf(freqs[i]);
          const y = yOf(value);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
    });

    // The bins carrying the difference.
    ctx.strokeStyle = '#fbbf24';
    ctx.lineWidth = dpr;
    ctx.setLineDash([3 * dpr, 3 * dpr]);
    for (const frequency of this.highlight()) {
      if (frequency < lo || frequency > hi) continue;
      const x = Math.round(xOf(frequency)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, padTop + plot);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    let legendX = 6 * dpr;
    series.forEach((entry) => {
      ctx.fillStyle = entry.colour;
      ctx.fillRect(legendX, 4 * dpr, 7 * dpr, 7 * dpr);
      ctx.fillStyle = '#94a3b8';
      ctx.font = `${10 * dpr}px ui-monospace, monospace`;
      ctx.fillText(entry.label, legendX + 10 * dpr, 11 * dpr);
      legendX += ctx.measureText(entry.label).width + 26 * dpr;
    });
    ctx.fillStyle = '#64748b';
    ctx.font = `${10 * dpr}px ui-monospace, monospace`;
    ctx.fillText('log10 power · grey strip = same in both', width - 210 * dpr, height - 5 * dpr);
  }
}

/**
 * The per-bin difference, against the two lines that decide whether it means anything:
 * the level below which the states are the same, and the level chance reaches by itself.
 */
@Component({
  selector: 'eeg-effect-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas class="h-full w-full"></canvas>`,
})
export class EffectChart {
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly freqs = input<number[]>([]);
  readonly effect = input<number[]>([]);
  readonly shared = input<boolean[]>([]);
  readonly sharedThreshold = input(1);
  readonly nullP95 = input(0);

  constructor() {
    effect(() => {
      this.freqs();
      this.effect();
      this.shared();
      this.nullP95();
      this.draw();
    });
    afterNextRender(() => {
      const canvas = this.canvasRef()?.nativeElement;
      if (!canvas) return;
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    const freqs = this.freqs();
    const effect = this.effect();
    if (freqs.length < 2 || effect.length !== freqs.length) {
      ctx.fillStyle = '#64748b';
      ctx.font = `${12 * dpr}px ui-monospace, monospace`;
      ctx.fillText('no comparison yet', 12 * dpr, height / 2);
      return;
    }

    const padTop = 14 * dpr;
    const padBottom = 18 * dpr;
    const plot = height - padTop - padBottom;
    const ceiling = Math.max(...effect, this.nullP95(), this.sharedThreshold()) * 1.1;
    const yOf = (value: number) => padTop + plot * (1 - value / ceiling);
    const barWidth = Math.max(1, width / effect.length);

    const shared = this.shared();
    effect.forEach((value, i) => {
      const x = (i / effect.length) * width;
      const top = yOf(value);
      const isShared = shared[i] ?? false;
      ctx.fillStyle = isShared ? 'rgb(100 116 139 / 0.55)' : '#10b981';
      ctx.fillRect(x, top, Math.max(barWidth - 0.6, 0.6), padTop + plot - top);
    });

    // Above this, a difference is bigger than the two states' own scatter.
    ctx.strokeStyle = 'rgb(226 232 240 / 0.45)';
    ctx.lineWidth = dpr;
    ctx.setLineDash([4 * dpr, 3 * dpr]);
    const sameY = Math.round(yOf(this.sharedThreshold())) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, sameY);
    ctx.lineTo(width, sameY);
    ctx.stroke();

    // And above this, shuffling the labels does as well by itself.
    const nullP95 = this.nullP95();
    if (nullP95 > 0) {
      ctx.strokeStyle = '#f43f5e';
      const nullY = Math.round(yOf(nullP95)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, nullY);
      ctx.lineTo(width, nullY);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    ctx.fillStyle = '#94a3b8';
    ctx.font = `${10 * dpr}px ui-monospace, monospace`;
    ctx.fillText(
      `same in both below ${this.sharedThreshold().toFixed(1)}`,
      4 * dpr,
      sameY - 3 * dpr,
    );
    if (nullP95 > 0) {
      ctx.fillStyle = '#fda4af';
      ctx.fillText('chance reaches this', 4 * dpr, yOf(nullP95) - 3 * dpr);
    }
    ctx.fillStyle = '#64748b';
    ctx.fillText('Hz', width - 18 * dpr, height - 5 * dpr);
    for (const tick of [4, 8, 13, 30]) {
      if (tick < freqs[0] || tick > freqs[freqs.length - 1]) continue;
      const x = ((tick - freqs[0]) / (freqs[freqs.length - 1] - freqs[0])) * width;
      ctx.fillText(`${tick}`, x + 2 * dpr, height - 5 * dpr);
    }
  }
}

/**
 * One channel's log power spectrum.
 *
 * Log-scaled, because EEG power falls off steeply with frequency and on a linear axis
 * everything above 15 Hz looks like nothing — including a genuine alpha peak's
 * neighbours, which is what you need to see to judge whether a peak is real.
 */
@Component({
  selector: 'eeg-spectrum-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas class="h-full w-full"></canvas>`,
})
export class SpectrumChart {
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly freqs = input<number[]>([]);
  readonly power = input<number[]>([]);
  readonly label = input('');

  constructor() {
    effect(() => {
      this.freqs();
      this.power();
      this.draw();
    });
    afterNextRender(() => {
      const canvas = this.canvasRef()?.nativeElement;
      if (!canvas) return;
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;

    const freqs = this.freqs();
    const power = this.power();
    if (freqs.length < 2 || power.length !== freqs.length) {
      ctx.fillStyle = '#64748b';
      ctx.font = `${12 * dpr}px ui-monospace, monospace`;
      ctx.fillText('no spectrum available', 12 * dpr, height / 2);
      return;
    }

    const padTop = 18 * dpr;
    const padBottom = 20 * dpr;
    const plotHeight = height - padTop - padBottom;
    const lo = Math.min(...freqs);
    const hi = Math.max(...freqs);
    const maxPower = Math.max(...power);
    const minPower = Math.min(...power);
    const span = Math.max(maxPower - minPower, 1e-6);

    const xOf = (f: number) => ((f - lo) / (hi - lo)) * width;
    const yOf = (p: number) => padTop + plotHeight * (1 - (p - minPower) / span);

    // Band shading, so "which bump is alpha" needs no legend.
    ctx.globalAlpha = 0.12;
    for (const span_ of BAND_SPANS) {
      ctx.fillStyle = bandColor(span_.key);
      ctx.fillRect(xOf(span_.from), padTop, xOf(span_.to) - xOf(span_.from), plotHeight);
    }
    ctx.globalAlpha = 1;

    ctx.strokeStyle = 'rgb(148 163 184 / 0.2)';
    ctx.lineWidth = dpr;
    for (const tick of [4, 8, 13, 30]) {
      if (tick <= lo || tick >= hi) continue;
      const x = Math.round(xOf(tick)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, padTop + plotHeight);
      ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.font = `${10 * dpr}px ui-monospace, monospace`;
      ctx.fillText(`${tick}`, x + 3 * dpr, height - 6 * dpr);
    }

    ctx.strokeStyle = '#34d399';
    ctx.lineWidth = 1.6 * dpr;
    ctx.beginPath();
    freqs.forEach((f, index) => {
      const x = xOf(f);
      const y = yOf(power[index]);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    ctx.fillStyle = 'rgb(226 232 240 / 0.85)';
    ctx.font = `600 ${11 * dpr}px ui-monospace, monospace`;
    ctx.fillText(`${this.label()} · log power`, 10 * dpr, 13 * dpr);
    ctx.fillStyle = '#64748b';
    ctx.font = `${10 * dpr}px ui-monospace, monospace`;
    ctx.fillText('Hz', width - 20 * dpr, height - 6 * dpr);
  }
}
