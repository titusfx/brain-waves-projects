import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  afterNextRender,
  computed,
  effect,
  input,
  viewChild,
} from '@angular/core';

import { bandColor } from '../../core/format';
import { ChartViewport, nearestIndex } from './chart-viewport';
import type { ChartTooltip, TooltipRow } from './chart-viewport';

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

/** The vertical line and the dots that make a hover readout readable against the data. */
function drawCrosshair(
  ctx: CanvasRenderingContext2D,
  x: number,
  top: number,
  height: number,
  dpr: number,
): void {
  ctx.strokeStyle = 'rgb(226 232 240 / 0.45)';
  ctx.lineWidth = dpr;
  ctx.setLineDash([3 * dpr, 3 * dpr]);
  ctx.beginPath();
  ctx.moveTo(Math.round(x) + 0.5, top);
  ctx.lineTo(Math.round(x) + 0.5, top + height);
  ctx.stroke();
  ctx.setLineDash([]);
}

function marker(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  colour: string,
  dpr: number,
): void {
  ctx.fillStyle = colour;
  ctx.beginPath();
  ctx.arc(x, y, 3 * dpr, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#020617';
  ctx.lineWidth = dpr;
  ctx.stroke();
}

function axisTicks(freqs: readonly number[]): number[] {
  return [2, 4, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45].filter(
    (tick) => tick >= freqs[0] && tick <= freqs[freqs.length - 1],
  );
}

/**
 * A recorded file, drawn as stacked strips.
 *
 * Scroll to zoom into a stretch of it, drag to pan, hover for the value of every channel
 * at that instant. Decimated, not averaged, by the server — an average would smooth away
 * exactly the transient that says a recording is bad.
 */
@Component({
  selector: 'eeg-sample-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #surface class="relative h-full w-full cursor-crosshair touch-none select-none">
      <canvas #canvas class="h-full w-full"></canvas>
      @if (tooltip(); as tip) {
        <div
          class="pointer-events-none absolute top-1 z-10 min-w-[7rem] rounded-md border border-slate-700 bg-slate-950/95 px-2 py-1.5 shadow-lg"
          [style.left.px]="tip.x + 12"
          [style.transform]="tip.x > lastWidth * 0.6 ? 'translateX(calc(-100% - 24px))' : null"
        >
          <p class="mono text-[11px] font-semibold text-slate-200">{{ tip.header }}</p>
          @for (row of tip.rows; track row.label) {
            <p class="mono flex items-center gap-1.5 text-[11px] text-slate-300">
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                [style.background]="row.colour"
              ></span>
              {{ row.label }}
              <span class="ml-auto pl-2 text-slate-100">{{ row.value }}</span>
            </p>
          }
        </div>
      }
      <div class="absolute right-1 bottom-1 flex items-center gap-1">
        @if (viewport.zoomed) {
          <button
            type="button"
            class="btn btn-ghost !px-2 !py-0 !text-[10px]"
            (click)="viewport.reset()"
            title="Show the whole recording again"
          >
            reset zoom
          </button>
        }
        <span class="pointer-events-none text-[10px] text-slate-600">scroll to zoom</span>
      </div>
    </div>
  `,
})
export class SampleChart implements OnDestroy {
  private readonly surfaceRef = viewChild<ElementRef<HTMLDivElement>>('surface');
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  /** Rows of samples, oldest first; `allChannels` names the columns. */
  readonly rows = input<number[][]>([]);
  /** Times for each row, in seconds. Falls back to the sample rate when absent. */
  readonly times = input<number[]>([]);
  readonly allChannels = input<string[]>([]);
  readonly channels = input<string[]>([]);
  readonly fullScaleUv = input(100);
  readonly sampleRate = input(128);

  protected readonly viewport = new ChartViewport(() => {
    const count = this.rows().length;
    if (count < 2) return [0, 1];
    const times = this.times();
    return times.length === count
      ? [times[0], times[count - 1]]
      : [0, (count - 1) / this.sampleRate()];
  });

  protected lastWidth = 1;

  protected readonly tooltip = computed<ChartTooltip | null>(() => {
    const cursor = this.viewport.cursor();
    if (cursor === null) return null;
    const rows = this.rows();
    const count = rows.length;
    if (count < 2) return null;
    const times = this.times();
    const axis = times.length === count ? times : rows.map((_, i) => i / this.sampleRate());
    const index = nearestIndex(axis, cursor);
    const at = axis[index] ?? cursor;

    const series = this.channels().length ? this.channels() : this.allChannels().slice(0, 4);
    const list: TooltipRow[] = [];
    series.slice(0, 8).forEach((name, position) => {
      const column = this.allChannels().indexOf(name);
      if (column < 0) return;
      const value = rows[index]?.[column] ?? 0;
      list.push({
        label: name,
        value: `${value.toFixed(1)} µV`,
        colour: TRACE_COLOURS[position % TRACE_COLOURS.length],
      });
    });
    const width = this.canvasRef()?.nativeElement.getBoundingClientRect().width ?? 1;
    this.lastWidth = width;
    return { x: this.viewport.toPixel(at, width), header: `t = ${at.toFixed(2)} s`, rows: list };
  });

  constructor() {
    effect(() => {
      this.rows();
      this.viewport.domain();
      this.viewport.cursor();
      this.draw();
    });
    afterNextRender(() => {
      const surface = this.surfaceRef()?.nativeElement;
      const canvas = this.canvasRef()?.nativeElement;
      if (!surface || !canvas) return;
      this.viewport.attach(surface);
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  ngOnDestroy(): void {
    this.viewport.detachListeners();
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    this.lastWidth = this.canvasRef()?.nativeElement.clientWidth ?? width / dpr;

    const rows = this.rows();
    const names = this.channels();
    const strips = Math.max(names.length, 1);
    const stripHeight = height / strips;
    const scale = this.fullScaleUv();
    const columns = rows.length;
    const visible = this.viewport.visible();
    const times = this.times();
    const axis = times.length === columns ? times : rows.map((_, i) => i / this.sampleRate());

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

      ctx.save();
      ctx.beginPath();
      ctx.rect(0, top, width, stripHeight);
      ctx.clip();
      ctx.strokeStyle = TRACE_COLOURS[strip % TRACE_COLOURS.length];
      ctx.lineWidth = 1.3 * dpr;
      ctx.beginPath();
      let started = false;
      for (let column = 0; column < columns; column += 1) {
        const t = axis[column];
        if (t < visible[0] || t > visible[1]) continue;
        const x = this.viewport.toPixel(t, width);
        const y = centre - ((rows[column][index] ?? 0) / scale) * half;
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
      ctx.restore();

      const cursor = this.viewport.cursor();
      if (cursor !== null && cursor >= visible[0] && cursor <= visible[1]) {
        const at = nearestIndex(axis, cursor);
        const t = axis[at] ?? cursor;
        const x = this.viewport.toPixel(t, width);
        const y = centre - ((rows[at]?.[index] ?? 0) / scale) * half;
        marker(ctx, x, y, TRACE_COLOURS[strip % TRACE_COLOURS.length], dpr);
      }

      ctx.fillStyle = 'rgb(226 232 240 / 0.85)';
      ctx.font = `600 ${11 * dpr}px ui-monospace, monospace`;
      ctx.fillText(name, 8 * dpr, top + 13 * dpr);
    });

    const cursor = this.viewport.cursor();
    if (cursor !== null && cursor >= visible[0] && cursor <= visible[1]) {
      drawCrosshair(ctx, this.viewport.toPixel(cursor, width), 0, height, dpr);
    }
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
 * everything above 15 Hz looks like nothing — including a genuine alpha peak's neighbours,
 * which is what you need to see to judge whether a peak is real.
 */
@Component({
  selector: 'eeg-spectrum-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #surface class="relative h-full w-full cursor-crosshair touch-none select-none">
      <canvas #canvas class="h-full w-full"></canvas>
      @if (tooltip(); as tip) {
        <div
          class="pointer-events-none absolute top-1 z-10 min-w-[7rem] rounded-md border border-slate-700 bg-slate-950/95 px-2 py-1.5 shadow-lg"
          [style.left.px]="tip.x + 12"
          [style.transform]="tip.x > lastWidth * 0.6 ? 'translateX(calc(-100% - 24px))' : null"
        >
          <p class="mono text-[11px] font-semibold text-slate-200">{{ tip.header }}</p>
          @for (row of tip.rows; track row.label) {
            <p class="mono flex items-center gap-1.5 text-[11px] text-slate-300">
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                [style.background]="row.colour"
              ></span>
              {{ row.label }}
              <span class="ml-auto pl-2 text-slate-100">{{ row.value }}</span>
            </p>
          }
        </div>
      }
      @if (viewport.zoomed) {
        <button
          type="button"
          class="btn btn-ghost absolute right-1 bottom-1 !px-2 !py-0 !text-[10px]"
          (click)="viewport.reset()"
        >
          reset zoom
        </button>
      }
    </div>
  `,
})
export class SpectrumChart implements OnDestroy {
  private readonly surfaceRef = viewChild<ElementRef<HTMLDivElement>>('surface');
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly freqs = input<number[]>([]);
  readonly power = input<number[]>([]);
  readonly label = input('');

  protected readonly viewport = new ChartViewport(() => {
    const freqs = this.freqs();
    return freqs.length > 1 ? [freqs[0], freqs[freqs.length - 1]] : [1, 45];
  });

  protected lastWidth = 1;

  protected readonly tooltip = computed<ChartTooltip | null>(() => {
    const cursor = this.viewport.cursor();
    const freqs = this.freqs();
    if (cursor === null || freqs.length < 2) return null;
    const index = nearestIndex(freqs, cursor);
    const at = freqs[index];
    const width = this.canvasRef()?.nativeElement.getBoundingClientRect().width ?? 1;
    this.lastWidth = width;
    return {
      x: this.viewport.toPixel(at, width),
      header: `${at} Hz`,
      rows: [
        {
          label: this.label(),
          value: `${(this.power()[index] ?? 0).toFixed(2)}`,
          colour: '#34d399',
        },
      ],
    };
  });

  constructor() {
    this.viewport.snap = (x) => {
      const freqs = this.freqs();
      return freqs.length ? freqs[nearestIndex(freqs, x)] : x;
    };
    effect(() => {
      this.freqs();
      this.power();
      this.viewport.domain();
      this.viewport.cursor();
      this.draw();
    });
    afterNextRender(() => {
      const surface = this.surfaceRef()?.nativeElement;
      const canvas = this.canvasRef()?.nativeElement;
      if (!surface || !canvas) return;
      this.viewport.attach(surface);
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  ngOnDestroy(): void {
    this.viewport.detachListeners();
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    this.lastWidth = this.canvasRef()?.nativeElement.clientWidth ?? width / dpr;

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
    const [lo, hi] = this.viewport.visible();

    // The y axis follows the visible window, so zooming in on a flat stretch actually
    // shows its shape instead of a straight line near the bottom of the frame.
    const inWindow = freqs
      .map((f, i) => ({ f, p: power[i] }))
      .filter(({ f }) => f >= lo && f <= hi);
    const values = (inWindow.length ? inWindow : freqs.map((f, i) => ({ f, p: power[i] }))).map(
      (entry) => entry.p,
    );
    const maxPower = Math.max(...values);
    const minPower = Math.min(...values);
    const span = Math.max(maxPower - minPower, 1e-6);
    const yOf = (p: number) => padTop + plotHeight * (1 - (p - minPower) / span);

    ctx.globalAlpha = 0.12;
    for (const band of BAND_SPANS) {
      const from = Math.max(band.from, lo);
      const to = Math.min(band.to, hi);
      if (to <= from) continue;
      ctx.fillStyle = bandColor(band.key);
      ctx.fillRect(
        this.viewport.toPixel(from, width),
        padTop,
        this.viewport.toPixel(to, width) - this.viewport.toPixel(from, width),
        plotHeight,
      );
    }
    ctx.globalAlpha = 1;

    ctx.strokeStyle = 'rgb(148 163 184 / 0.2)';
    ctx.lineWidth = dpr;
    for (const tick of axisTicks(freqs)) {
      if (tick < lo || tick > hi) continue;
      const x = Math.round(this.viewport.toPixel(tick, width)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, padTop + plotHeight);
      ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.font = `${10 * dpr}px ui-monospace, monospace`;
      ctx.fillText(`${tick}`, x + 3 * dpr, height - 6 * dpr);
    }

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, padTop, width, plotHeight);
    ctx.clip();
    ctx.strokeStyle = '#34d399';
    ctx.lineWidth = 1.6 * dpr;
    ctx.beginPath();
    let started = false;
    freqs.forEach((f, index) => {
      if (f < lo || f > hi) return;
      const x = this.viewport.toPixel(f, width);
      const y = yOf(power[index]);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
    ctx.restore();

    const cursor = this.viewport.cursor();
    if (cursor !== null && cursor >= lo && cursor <= hi) {
      const x = this.viewport.toPixel(cursor, width);
      drawCrosshair(ctx, x, padTop, plotHeight, dpr);
      const index = nearestIndex(freqs, cursor);
      marker(ctx, x, yOf(power[index]), '#34d399', dpr);
    }

    ctx.fillStyle = 'rgb(226 232 240 / 0.85)';
    ctx.font = `600 ${11 * dpr}px ui-monospace, monospace`;
    ctx.fillText(`${this.label()} · log power`, 10 * dpr, 13 * dpr);
    ctx.fillStyle = '#64748b';
    ctx.font = `${10 * dpr}px ui-monospace, monospace`;
    ctx.fillText('Hz', width - 20 * dpr, height - 6 * dpr);
  }
}

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
 * other, the states agree; where they diverge, that part of the recording is not something
 * the state controls. Deliberately not averaged — an average hides exactly the
 * disagreement that matters. Scroll to zoom, drag to pan, hover to read every instance's
 * value at one instant.
 */
@Component({
  selector: 'eeg-trace-overlay',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #surface class="relative h-full w-full cursor-crosshair touch-none select-none">
      <canvas #canvas class="h-full w-full"></canvas>
      @if (tooltip(); as tip) {
        <div
          class="pointer-events-none absolute top-1 z-10 min-w-[9rem] rounded-md border border-slate-700 bg-slate-950/95 px-2 py-1.5 shadow-lg"
          [style.left.px]="tip.x + 12"
          [style.transform]="tip.x > lastWidth * 0.6 ? 'translateX(calc(-100% - 24px))' : null"
        >
          <p class="mono text-[11px] font-semibold text-slate-200">{{ tip.header }}</p>
          @for (row of tip.rows; track row.label) {
            <p class="mono flex items-center gap-1.5 text-[11px] text-slate-300">
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                [style.background]="row.colour"
              ></span>
              <span class="truncate">{{ row.label }}</span>
              <span class="ml-auto pl-2 text-slate-100">{{ row.value }}</span>
            </p>
          }
        </div>
      }
      <div class="absolute right-1 bottom-1 flex items-center gap-1">
        @if (viewport.zoomed) {
          <button
            type="button"
            class="btn btn-ghost !px-2 !py-0 !text-[10px]"
            (click)="viewport.reset()"
            title="Show the whole window again"
          >
            reset zoom
          </button>
        }
        <span class="pointer-events-none text-[10px] text-slate-600">scroll to zoom</span>
      </div>
    </div>
  `,
})
export class TraceOverlay implements OnDestroy {
  private readonly surfaceRef = viewChild<ElementRef<HTMLDivElement>>('surface');
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly traces = input<OverlayTrace[]>([]);
  readonly sampleRate = input(128);
  readonly fullScaleUv = input(100);

  protected readonly viewport = new ChartViewport(() => {
    const fs = this.sampleRate();
    const longest = Math.max(
      0,
      ...this.traces().map((trace) => ((trace.values.length - 1) * trace.step) / fs),
    );
    return longest > 0 ? [0, longest] : [0, 1];
  });

  protected lastWidth = 1;

  protected readonly tooltip = computed<ChartTooltip | null>(() => {
    const cursor = this.viewport.cursor();
    const traces = this.traces().filter((trace) => trace.values.length > 1);
    if (cursor === null || !traces.length) return null;
    const width = this.canvasRef()?.nativeElement.getBoundingClientRect().width ?? 1;
    this.lastWidth = width;
    const rows: TooltipRow[] = [];
    traces.slice(0, 6).forEach((trace) => {
      rows.push({
        label: trace.label,
        value: `${this.valueAt(trace, cursor).toFixed(1)} µV`,
        colour: trace.colour,
      });
    });
    if (traces.length > 6) {
      rows.push({
        label: `+${traces.length - 6} more`,
        value: '',
        colour: 'rgb(100 116 139)',
      });
    }
    return { x: this.viewport.toPixel(cursor, width), header: `t = ${cursor.toFixed(2)} s`, rows };
  });

  constructor() {
    effect(() => {
      this.traces();
      this.viewport.domain();
      this.viewport.cursor();
      this.draw();
    });
    afterNextRender(() => {
      const surface = this.surfaceRef()?.nativeElement;
      const canvas = this.canvasRef()?.nativeElement;
      if (!surface || !canvas) return;
      this.viewport.attach(surface);
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  ngOnDestroy(): void {
    this.viewport.detachListeners();
  }

  /** The value of one instance at time ``t``, interpolated between its samples. */
  private valueAt(trace: OverlayTrace, t: number): number {
    const dt = trace.step / this.sampleRate();
    if (dt <= 0 || !trace.values.length) return 0;
    const position = t / dt;
    const low = Math.max(0, Math.min(trace.values.length - 1, Math.floor(position)));
    const high = Math.min(trace.values.length - 1, low + 1);
    const ratio = Math.max(0, Math.min(1, position - low));
    return trace.values[low] + (trace.values[high] - trace.values[low]) * ratio;
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    this.lastWidth = this.canvasRef()?.nativeElement.clientWidth ?? width / dpr;

    const traces = this.traces().filter((trace) => trace.values.length > 1);
    if (!traces.length) {
      ctx.fillStyle = '#64748b';
      ctx.font = `${12 * dpr}px ui-monospace, monospace`;
      ctx.fillText('no states selected', 12 * dpr, height / 2);
      return;
    }

    const fs = this.sampleRate();
    const [lo, hi] = this.viewport.visible();
    const scale = this.fullScaleUv();
    const padTop = 16 * dpr;
    const padBottom = 18 * dpr;
    const plot = height - padTop - padBottom;
    const centre = padTop + plot / 2;
    const half = plot / 2;

    ctx.strokeStyle = 'rgb(148 163 184 / 0.12)';
    ctx.lineWidth = dpr;
    const step = hi - lo > 3 ? 1 : hi - lo > 0.8 ? 0.2 : 0.05;
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      const x = Math.round(this.viewport.toPixel(t, width)) + 0.5;
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
    ctx.fillText('time from each state’s start', 60 * dpr, height - 5 * dpr);

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, padTop, width, padTop + plot);
    ctx.clip();
    traces.forEach((trace, index) => {
      ctx.strokeStyle = trace.colour;
      // The first few instances carry the eye; later ones fade so ten overlaid traces
      // stay readable rather than becoming a solid block.
      ctx.globalAlpha = index < 4 ? 0.95 : 0.45;
      ctx.lineWidth = 1.3 * dpr;
      ctx.beginPath();
      let started = false;
      trace.values.forEach((value, i) => {
        const t = (i * trace.step) / fs;
        if (t < lo || t > hi) return;
        const x = this.viewport.toPixel(t, width);
        const y = centre - (value / scale) * half;
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.stroke();
    });
    ctx.globalAlpha = 1;

    const cursor = this.viewport.cursor();
    if (cursor !== null && cursor >= lo && cursor <= hi) {
      const x = this.viewport.toPixel(cursor, width);
      traces.forEach((trace) => {
        marker(ctx, x, centre - (this.valueAt(trace, cursor) / scale) * half, trace.colour, dpr);
      });
    }
    ctx.restore();

    if (cursor !== null && cursor >= lo && cursor <= hi) {
      drawCrosshair(ctx, this.viewport.toPixel(cursor, width), padTop, plot, dpr);
    }
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
 * The band is the important part: a mean line on its own invites reading a difference into
 * two curves that are well inside each other's scatter. Seeing the two bands overlap is the
 * honest version of "they look different here". Zoom in on the band where they nearly do.
 */
@Component({
  selector: 'eeg-spectrum-overlay',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #surface class="relative h-full w-full cursor-crosshair touch-none select-none">
      <canvas #canvas class="h-full w-full"></canvas>
      @if (tooltip(); as tip) {
        <div
          class="pointer-events-none absolute top-1 z-10 min-w-[10rem] rounded-md border border-slate-700 bg-slate-950/95 px-2 py-1.5 shadow-lg"
          [style.left.px]="tip.x + 12"
          [style.transform]="tip.x > lastWidth * 0.6 ? 'translateX(calc(-100% - 24px))' : null"
        >
          <p class="mono text-[11px] font-semibold text-slate-200">{{ tip.header }}</p>
          @for (row of tip.rows; track row.label) {
            <p class="mono flex items-center gap-1.5 text-[11px] text-slate-300">
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                [style.background]="row.colour"
              ></span>
              <span class="truncate">{{ row.label }}</span>
              <span class="ml-auto pl-2 text-slate-100">{{ row.value }}</span>
            </p>
          }
        </div>
      }
      <div class="absolute right-1 bottom-1 flex items-center gap-1">
        @if (viewport.zoomed) {
          <button
            type="button"
            class="btn btn-ghost !px-2 !py-0 !text-[10px]"
            (click)="viewport.reset()"
          >
            reset zoom
          </button>
        }
        <span class="pointer-events-none text-[10px] text-slate-600">scroll to zoom</span>
      </div>
    </div>
  `,
})
export class SpectrumOverlay implements OnDestroy {
  private readonly surfaceRef = viewChild<ElementRef<HTMLDivElement>>('surface');
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly freqs = input<number[]>([]);
  readonly series = input<OverlaySeries[]>([]);
  /** Per bin: true where the two states are the same. Shaded, because it matters. */
  readonly shared = input<boolean[]>([]);
  /** Frequencies to mark with a line, e.g. the bins carrying the difference. */
  readonly highlight = input<number[]>([]);
  readonly showInstances = input(true);

  protected readonly viewport = new ChartViewport(() => {
    const freqs = this.freqs();
    return freqs.length > 1 ? [freqs[0], freqs[freqs.length - 1]] : [1, 45];
  });

  protected lastWidth = 1;

  protected readonly tooltip = computed<ChartTooltip | null>(() => {
    const cursor = this.viewport.cursor();
    const freqs = this.freqs();
    if (cursor === null || freqs.length < 2) return null;
    const index = nearestIndex(freqs, cursor);
    const at = freqs[index];
    const rows: TooltipRow[] = this.series().map((entry) => {
      const mean = entry.mean?.[index];
      const sd = entry.sd?.[index];
      const spread = mean !== undefined && sd !== undefined ? ` ±${sd.toFixed(2)}` : '';
      return {
        label: entry.label,
        value: mean === undefined ? '—' : `${mean.toFixed(2)}${spread}`,
        colour: entry.colour,
      };
    });
    const isShared = this.shared()[index];
    if (isShared !== undefined) {
      rows.push({
        label: isShared ? 'the same in both' : 'differs',
        value: '',
        colour: isShared ? 'rgb(100 116 139)' : '#10b981',
      });
    }
    const width = this.canvasRef()?.nativeElement.getBoundingClientRect().width ?? 1;
    this.lastWidth = width;
    return { x: this.viewport.toPixel(at, width), header: `${at} Hz`, rows };
  });

  constructor() {
    this.viewport.snap = (x) => {
      const freqs = this.freqs();
      return freqs.length ? freqs[nearestIndex(freqs, x)] : x;
    };
    effect(() => {
      this.freqs();
      this.series();
      this.shared();
      this.viewport.domain();
      this.viewport.cursor();
      this.draw();
    });
    afterNextRender(() => {
      const surface = this.surfaceRef()?.nativeElement;
      const canvas = this.canvasRef()?.nativeElement;
      if (!surface || !canvas) return;
      this.viewport.attach(surface);
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  ngOnDestroy(): void {
    this.viewport.detachListeners();
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    this.lastWidth = this.canvasRef()?.nativeElement.clientWidth ?? width / dpr;
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
    const [lo, hi] = this.viewport.visible();
    const toX = (f: number) => this.viewport.toPixel(f, width);

    // y range from the visible window only, so zooming into a narrow band shows its shape.
    const window = freqs.map((f, i) => i).filter((i) => freqs[i] >= lo && freqs[i] <= hi);
    const chosen = window.length ? window : freqs.map((_, i) => i);
    const values: number[] = [];
    for (const index of chosen) {
      for (const entry of series) {
        if (entry.mean)
          values.push(
            entry.mean[index],
            entry.mean[index] - (entry.sd?.[index] ?? 0),
            entry.mean[index] + (entry.sd?.[index] ?? 0),
          );
        if (this.showInstances() && entry.instances) {
          for (const line of entry.instances) values.push(line[index]);
        }
      }
    }
    const high = values.length ? Math.max(...values) : 1;
    const low = values.length ? Math.min(...values) : 0;
    const span = Math.max(high - low, 1e-6);
    const yOf = (value: number) => padTop + plot * (1 - (value - low) / span);

    const shared = this.shared();
    if (shared.length === freqs.length) {
      ctx.fillStyle = 'rgb(148 163 184 / 0.16)';
      shared.forEach((isShared, i) => {
        if (!isShared || freqs[i] < lo || freqs[i] > hi) return;
        ctx.fillRect(
          toX(freqs[i]),
          height - padBottom,
          Math.max(1, width / freqs.length),
          padBottom - 4 * dpr,
        );
      });
    }

    ctx.globalAlpha = 0.08;
    for (const band of BAND_SPANS) {
      const from = Math.max(band.from, lo);
      const to = Math.min(band.to, hi);
      if (to <= from) continue;
      ctx.fillStyle = bandColor(band.key);
      ctx.fillRect(toX(from), padTop, toX(to) - toX(from), plot);
    }
    ctx.globalAlpha = 1;

    ctx.strokeStyle = 'rgb(148 163 184 / 0.2)';
    ctx.lineWidth = dpr;
    for (const tick of axisTicks(freqs)) {
      if (tick < lo || tick > hi) continue;
      const x = Math.round(toX(tick)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, padTop + plot);
      ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.font = `${10 * dpr}px ui-monospace, monospace`;
      ctx.fillText(`${tick}`, x + 3 * dpr, height - 5 * dpr);
    }

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, padTop, width, plot);
    ctx.clip();

    const segment = (values: number[], draw: (x: number, y: number, first: boolean) => void) => {
      let started = false;
      freqs.forEach((f, i) => {
        if (f < lo || f > hi) return;
        draw(toX(f), yOf(values[i]), !started);
        started = true;
      });
    };

    series.forEach((entry) => {
      if (this.showInstances() && entry.instances) {
        ctx.strokeStyle = entry.colour;
        ctx.globalAlpha = 0.35;
        ctx.lineWidth = dpr;
        for (const line of entry.instances) {
          ctx.beginPath();
          segment(line, (x, y, first) => (first ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      if (entry.mean && entry.sd) {
        const upper = entry.mean.map((value, i) => value + (entry.sd?.[i] ?? 0));
        const lower = entry.mean.map((value, i) => value - (entry.sd?.[i] ?? 0));
        ctx.fillStyle = entry.colour;
        ctx.globalAlpha = 0.18;
        ctx.beginPath();
        segment(upper, (x, y, first) => (first ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        for (let i = freqs.length - 1; i >= 0; i -= 1) {
          if (freqs[i] < lo || freqs[i] > hi) continue;
          ctx.lineTo(toX(freqs[i]), yOf(lower[i]));
        }
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;

        ctx.strokeStyle = entry.colour;
        ctx.lineWidth = 1.8 * dpr;
        ctx.beginPath();
        segment(entry.mean, (x, y, first) => (first ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.stroke();
      }
    });

    const cursor = this.viewport.cursor();
    if (cursor !== null && cursor >= lo && cursor <= hi) {
      const index = nearestIndex(freqs, cursor);
      const x = this.viewport.toPixel(freqs[index], width);
      series.forEach((entry) => {
        if (entry.mean) marker(ctx, x, yOf(entry.mean[index]), entry.colour, dpr);
      });
    }
    ctx.restore();

    ctx.strokeStyle = '#fbbf24';
    ctx.lineWidth = dpr;
    ctx.setLineDash([3 * dpr, 3 * dpr]);
    for (const frequency of this.highlight()) {
      if (frequency < lo || frequency > hi) continue;
      const x = Math.round(toX(frequency)) + 0.5;
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

    if (cursor !== null && cursor >= lo && cursor <= hi) {
      drawCrosshair(ctx, this.viewport.toPixel(cursor, width), padTop, plot, dpr);
    }
  }
}

/**
 * The per-bin difference, against the two lines that decide whether it means anything:
 * the level below which the states are the same, and the level chance reaches by itself.
 */
@Component({
  selector: 'eeg-effect-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #surface class="relative h-full w-full cursor-crosshair touch-none select-none">
      <canvas #canvas class="h-full w-full"></canvas>
      @if (tooltip(); as tip) {
        <div
          class="pointer-events-none absolute top-1 z-10 min-w-[9rem] rounded-md border border-slate-700 bg-slate-950/95 px-2 py-1.5 shadow-lg"
          [style.left.px]="tip.x + 12"
          [style.transform]="tip.x > lastWidth * 0.6 ? 'translateX(calc(-100% - 24px))' : null"
        >
          <p class="mono text-[11px] font-semibold text-slate-200">{{ tip.header }}</p>
          @for (row of tip.rows; track row.label) {
            <p class="mono flex items-center gap-1.5 text-[11px] text-slate-300">
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                [style.background]="row.colour"
              ></span>
              <span class="truncate">{{ row.label }}</span>
              <span class="ml-auto pl-2 text-slate-100">{{ row.value }}</span>
            </p>
          }
        </div>
      }
      <div class="absolute right-1 bottom-1 flex items-center gap-1">
        @if (viewport.zoomed) {
          <button
            type="button"
            class="btn btn-ghost !px-2 !py-0 !text-[10px]"
            (click)="viewport.reset()"
          >
            reset zoom
          </button>
        }
        <span class="pointer-events-none text-[10px] text-slate-600">scroll to zoom</span>
      </div>
    </div>
  `,
})
export class EffectChart implements OnDestroy {
  private readonly surfaceRef = viewChild<ElementRef<HTMLDivElement>>('surface');
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly freqs = input<number[]>([]);
  readonly effect = input<number[]>([]);
  readonly shared = input<boolean[]>([]);
  readonly sharedThreshold = input(1);
  readonly nullP95 = input(0);
  readonly labelA = input('A');
  readonly labelB = input('B');

  protected readonly viewport = new ChartViewport(() => {
    const freqs = this.freqs();
    return freqs.length > 1 ? [freqs[0], freqs[freqs.length - 1]] : [1, 45];
  });

  protected lastWidth = 1;

  protected readonly tooltip = computed<ChartTooltip | null>(() => {
    const cursor = this.viewport.cursor();
    const freqs = this.freqs();
    if (cursor === null || freqs.length < 2) return null;
    const index = nearestIndex(freqs, cursor);
    const value = this.effect()[index] ?? 0;
    const isShared = this.shared()[index];
    const width = this.canvasRef()?.nativeElement.getBoundingClientRect().width ?? 1;
    this.lastWidth = width;
    return {
      x: this.viewport.toPixel(freqs[index], width),
      header: `${freqs[index]} Hz`,
      rows: [
        {
          label: 'difference',
          value: value.toFixed(2),
          colour: isShared ? 'rgb(100 116 139)' : '#10b981',
        },
        {
          label: isShared ? 'the same in both' : 'differs',
          value: value >= this.nullP95() && this.nullP95() > 0 ? 'above chance' : '',
          colour: isShared ? 'rgb(100 116 139)' : '#10b981',
        },
      ],
    };
  });

  constructor() {
    this.viewport.snap = (x) => {
      const freqs = this.freqs();
      return freqs.length ? freqs[nearestIndex(freqs, x)] : x;
    };
    effect(() => {
      this.freqs();
      this.effect();
      this.shared();
      this.nullP95();
      this.viewport.domain();
      this.viewport.cursor();
      this.draw();
    });
    afterNextRender(() => {
      const surface = this.surfaceRef()?.nativeElement;
      const canvas = this.canvasRef()?.nativeElement;
      if (!surface || !canvas) return;
      this.viewport.attach(surface);
      new ResizeObserver(() => this.draw()).observe(canvas);
      this.draw();
    });
  }

  ngOnDestroy(): void {
    this.viewport.detachListeners();
  }

  private draw(): void {
    const prepared = prepare(this.canvasRef()?.nativeElement);
    if (!prepared) return;
    const { ctx, width, height, dpr } = prepared;
    this.lastWidth = this.canvasRef()?.nativeElement.clientWidth ?? width / dpr;
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
    const [lo, hi] = this.viewport.visible();
    // The ceiling follows the visible window, so a quiet band is not flattened to nothing
    // by one large difference elsewhere in the spectrum.
    const inWindow = effect.filter((_, i) => freqs[i] >= lo && freqs[i] <= hi);
    const ceiling =
      Math.max(...(inWindow.length ? inWindow : effect), this.nullP95(), this.sharedThreshold()) *
      1.1;
    const yOf = (value: number) => padTop + plot * (1 - value / ceiling);
    const barWidth = Math.max(
      1,
      width / Math.max(1, freqs.filter((f) => f >= lo && f <= hi).length),
    );

    const shared = this.shared();
    effect.forEach((value, i) => {
      if (freqs[i] < lo || freqs[i] > hi) return;
      const x = this.viewport.toPixel(freqs[i], width);
      const top = yOf(value);
      const isShared = shared[i] ?? false;
      ctx.fillStyle = isShared ? 'rgb(100 116 139 / 0.55)' : '#10b981';
      ctx.fillRect(x, top, Math.max(barWidth - 0.6, 0.6), padTop + plot - top);
    });

    ctx.strokeStyle = 'rgb(226 232 240 / 0.45)';
    ctx.lineWidth = dpr;
    ctx.setLineDash([4 * dpr, 3 * dpr]);
    const sameY = Math.round(yOf(this.sharedThreshold())) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, sameY);
    ctx.lineTo(width, sameY);
    ctx.stroke();

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
    for (const tick of axisTicks(freqs)) {
      if (tick < lo || tick > hi) continue;
      ctx.fillText(
        `${tick}`,
        Math.round(this.viewport.toPixel(tick, width)) + 2 * dpr,
        height - 5 * dpr,
      );
    }

    const cursor = this.viewport.cursor();
    if (cursor !== null && cursor >= lo && cursor <= hi) {
      const index = nearestIndex(freqs, cursor);
      const x = this.viewport.toPixel(freqs[index], width);
      const top = yOf(effect[index]);
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(x - 1.5 * dpr, top - 3 * dpr, 3 * dpr, 3 * dpr);
      drawCrosshair(ctx, x, padTop, plot, dpr);
    }
  }
}
