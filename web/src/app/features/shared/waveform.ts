import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';

import { EegStream } from '../../core/eeg/stream';

const TRACE_COLOURS = [
  '#38bdf8',
  '#a78bfa',
  '#34d399',
  '#fbbf24',
  '#f472b6',
  '#22d3ee',
  '#fb923c',
  '#4ade80',
  '#e879f9',
  '#60a5fa',
  '#facc15',
  '#2dd4bf',
  '#f87171',
  '#c084fc',
];

/**
 * Live traces, one horizontal strip per channel.
 *
 * One strip per channel rather than 14 lines on shared axes, because at these
 * amplitudes 14 overlapping traces are unreadable. Each strip is drawn at the same
 * scale, so comparing channels is a matter of looking, and a strip that is visibly
 * flat or visibly saturated is immediately obvious — which is the whole point of a
 * contact-debugging screen.
 *
 * Redrawn from an `effect` on the stream's tick counter rather than on a timer: the
 * picture then updates exactly as often as data arrives, and nothing spins when the
 * stream is stopped.
 */
@Component({
  selector: 'eeg-waveform',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<canvas #canvas class="h-full w-full"></canvas>`,
})
export class Waveform {
  private readonly stream = inject(EegStream);
  private readonly canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('canvas');

  readonly channels = input<string[]>(['O1', 'O2']);
  readonly seconds = input(4);
  /** Full-scale amplitude of each strip, in microvolts (±). */
  readonly fullScaleUv = input(100);

  constructor() {
    effect(() => {
      this.stream.ticks();
      this.draw();
    });
    afterNextRender(() => {
      const canvas = this.canvasRef()?.nativeElement;
      if (!canvas) return;
      const observer = new ResizeObserver(() => this.draw());
      observer.observe(canvas);
      this.draw();
    });
  }

  private draw(): void {
    const canvas = this.canvasRef()?.nativeElement;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.floor(rect.width * dpr);
    const height = Math.floor(rect.height * dpr);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#04070d';
    ctx.fillRect(0, 0, width, height);

    const names = this.channels();
    const feed = this.stream.window(this.seconds());
    const strips = Math.max(names.length, 1);
    const stripHeight = height / strips;
    const scale = this.fullScaleUv();

    // A vertical grid every second, so duration is readable at a glance.
    const seconds = this.seconds();
    ctx.strokeStyle = 'rgb(148 163 184 / 0.12)';
    ctx.lineWidth = dpr;
    for (let s = 1; s < seconds; s += 1) {
      const x = Math.round((width * s) / seconds) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }

    const channelIndex = new Map<string, number>();
    this.stream.channels().forEach((name, index) => channelIndex.set(name, index));

    names.forEach((name, strip) => {
      const top = strip * stripHeight;
      const centre = top + stripHeight / 2;
      const half = stripHeight / 2 - 6 * dpr;

      // Strip frame, baseline, and the ±full-scale guides.
      ctx.strokeStyle = 'rgb(148 163 184 / 0.16)';
      ctx.lineWidth = dpr;
      ctx.beginPath();
      ctx.moveTo(0, Math.round(top) + 0.5);
      ctx.lineTo(width, Math.round(top) + 0.5);
      ctx.stroke();

      ctx.strokeStyle = 'rgb(148 163 184 / 0.35)';
      ctx.beginPath();
      ctx.moveTo(0, centre);
      ctx.lineTo(width, centre);
      ctx.stroke();

      ctx.strokeStyle = 'rgb(148 163 184 / 0.12)';
      ctx.setLineDash([4 * dpr, 4 * dpr]);
      for (const sign of [-1, 1]) {
        const y = centre + (sign * half) / 2;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      const index = channelIndex.get(name);
      if (index === undefined || feed.rows < 2) {
        ctx.fillStyle = '#64748b';
        ctx.font = `${11 * dpr}px ui-monospace, monospace`;
        ctx.fillText(`${name} — no data`, 8 * dpr, centre + 4 * dpr);
        return;
      }

      ctx.strokeStyle = TRACE_COLOURS[strip % TRACE_COLOURS.length];
      ctx.lineWidth = 1.4 * dpr;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      for (let row = 0; row < feed.rows; row += 1) {
        const value = feed.data[row * feed.width + index];
        const x = (row / (feed.rows - 1)) * width;
        const y = centre - (value / scale) * half;
        if (row === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      ctx.fillStyle = 'rgb(226 232 240 / 0.85)';
      ctx.font = `600 ${11 * dpr}px ui-monospace, monospace`;
      ctx.fillText(name, 8 * dpr, top + 14 * dpr);
    });
  }
}
