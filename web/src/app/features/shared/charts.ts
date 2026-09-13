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
