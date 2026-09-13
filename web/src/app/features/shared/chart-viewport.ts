import { signal } from '@angular/core';

/** One line of a chart's hover readout. */
export interface TooltipRow {
  label: string;
  value: string;
  colour: string;
}

/** What to show when the pointer is inside a chart, and where. */
export interface ChartTooltip {
  /** Pixel position of the crosshair, for placing the box beside it. */
  x: number;
  header: string;
  rows: TooltipRow[];
}

/**
 * Zoom, pan and hover for the canvas charts.
 *
 * Every chart here plots against a continuous x axis — frequency in hertz, time in
 * seconds — and the question they are asked is almost always about a narrow part of it:
 * *is the difference at 10 Hz or at 10.5?*, *where exactly do these two traces diverge?*
 * Reading that off a 44-hertz-wide picture is guesswork, so each chart gets a window onto
 * it.
 *
 * The domain is `null` while unzoomed, which means "whatever the data spans" — so a chart
 * that has never been touched is drawn exactly as before, and a dataset that reloads
 * cannot leave a stale window behind.
 *
 * Wheel zooms about the pointer, so the thing under the cursor stays under the cursor.
 * Dragging pans. Both are clamped to the data, so it is impossible to get lost off the
 * end of a chart and conclude the data is empty.
 */
export class ChartViewport {
  /** Visible x range, or `null` for "all of it". */
  readonly domain = signal<[number, number] | null>(null);
  /** Data x under the pointer, or `null` when the pointer is outside. */
  readonly cursor = signal<number | null>(null);
  readonly panning = signal(false);

  /** Set by the spectral charts so the cursor lands on a real frequency bin. */
  snap: ((x: number) => number) | null = null;

  private detach: (() => void) | null = null;
  private dragFrom: { pixel: number; domain: [number, number] } | null = null;

  constructor(private readonly fullRange: () => [number, number]) {}

  /** The range in use: the zoom window, or the whole data range. */
  visible(): [number, number] {
    const [lo, hi] = this.fullRange();
    const domain = this.domain();
    if (!domain || hi <= lo) return [lo, hi];
    // A reload can move the data out from under a window; fall back rather than draw
    // an empty chart with no way to tell why.
    if (domain[1] <= lo || domain[0] >= hi) return [lo, hi];
    return [Math.max(lo, domain[0]), Math.min(hi, domain[1])];
  }

  get zoomed(): boolean {
    const [lo, hi] = this.fullRange();
    const [vlo, vhi] = this.visible();
    return vhi - vlo < (hi - lo) * 0.999;
  }

  toPixel(x: number, width: number): number {
    const [lo, hi] = this.visible();
    return hi <= lo ? 0 : ((x - lo) / (hi - lo)) * width;
  }

  fromPixel(pixel: number, width: number): number {
    const [lo, hi] = this.visible();
    return width <= 0 ? lo : lo + (pixel / width) * (hi - lo);
  }

  reset(): void {
    this.domain.set(null);
  }

  /** Zoom about a data x, keeping that point fixed. `factor` < 1 zooms in. */
  zoomAt(x: number, factor: number): void {
    const [lo, hi] = this.visible();
    const full = this.fullRange();
    const span = hi - lo;
    const fullSpan = Math.max(full[1] - full[0], 1e-9);
    const next = Math.min(Math.max(span * factor, fullSpan / 200), fullSpan);
    if (next >= fullSpan * 0.999) {
      this.domain.set(null);
      return;
    }
    const ratio = span <= 0 ? 0.5 : (x - lo) / span;
    let start = x - ratio * next;
    let end = start + next;
    if (start < full[0]) {
      start = full[0];
      end = start + next;
    }
    if (end > full[1]) {
      end = full[1];
      start = end - next;
    }
    this.domain.set([start, end]);
  }

  panBy(deltaPixels: number, width: number): void {
    if (!this.dragFrom) return;
    const [lo, hi] = this.dragFrom.domain;
    const span = hi - lo;
    if (width <= 0) return;
    const shift = -(deltaPixels / width) * span;
    const full = this.fullRange();
    let start = lo + shift;
    let end = hi + shift;
    if (start < full[0]) {
      start = full[0];
      end = start + span;
    }
    if (end > full[1]) {
      end = full[1];
      start = end - span;
    }
    this.domain.set([start, end]);
  }

  startDrag(pixel: number): void {
    this.dragFrom = { pixel, domain: this.visible() };
    this.panning.set(true);
  }

  endDrag(): void {
    this.dragFrom = null;
    this.panning.set(false);
  }

  /**
   * Wire wheel and pointer events to an element, and return a detach function.
   *
   * Registered by hand rather than with template bindings because the wheel listener has
   * to be non-passive: zooming a chart that sits in a scrolling page must not also scroll
   * the page. Angular's `(wheel)` binding cannot ask for that.
   */
  attach(element: HTMLElement): void {
    const onWheel = (event: WheelEvent): void => {
      event.preventDefault();
      const rect = element.getBoundingClientRect();
      const x = this.fromPixel(event.clientX - rect.left, rect.width);
      // Exponential so a flick of the wheel is a consistent proportion at any zoom.
      const factor = Math.exp(
        Math.sign(event.deltaY) * Math.min(Math.abs(event.deltaY), 120) * 0.0022,
      );
      this.zoomAt(x, factor);
      this.cursor.set(this.snap ? this.snap(x) : x);
    };

    const onPointerMove = (event: PointerEvent): void => {
      const rect = element.getBoundingClientRect();
      const pixel = event.clientX - rect.left;
      if (this.dragFrom) {
        this.panBy(pixel - this.dragFrom.pixel, rect.width);
        this.dragFrom = { pixel, domain: this.visible() };
      }
      const x = this.fromPixel(pixel, rect.width);
      this.cursor.set(this.snap ? this.snap(x) : x);
    };

    const onPointerLeave = (): void => {
      this.cursor.set(null);
      this.endDrag();
    };

    const onPointerDown = (event: PointerEvent): void => {
      if (event.button !== 0) return;
      const rect = element.getBoundingClientRect();
      this.startDrag(event.clientX - rect.left);
      // A synthetic event has no pointer to capture, and that is not an error worth
      // surfacing — the pan still works without it.
      try {
        element.setPointerCapture(event.pointerId);
      } catch {
        /* no capture available */
      }
    };

    const onPointerUp = (event: PointerEvent): void => {
      try {
        element.releasePointerCapture(event.pointerId);
      } catch {
        /* never captured */
      }
      this.endDrag();
    };

    const onDoubleClick = (): void => this.reset();

    element.addEventListener('wheel', onWheel, { passive: false });
    element.addEventListener('pointermove', onPointerMove);
    element.addEventListener('pointerleave', onPointerLeave);
    element.addEventListener('pointerdown', onPointerDown);
    element.addEventListener('pointerup', onPointerUp);
    element.addEventListener('dblclick', onDoubleClick);

    this.detach = () => {
      element.removeEventListener('wheel', onWheel);
      element.removeEventListener('pointermove', onPointerMove);
      element.removeEventListener('pointerleave', onPointerLeave);
      element.removeEventListener('pointerdown', onPointerDown);
      element.removeEventListener('pointerup', onPointerUp);
      element.removeEventListener('dblclick', onDoubleClick);
    };
  }

  detachListeners(): void {
    this.detach?.();
    this.detach = null;
  }
}

/** The index of the bin nearest ``x`` on a sorted axis. */
export function nearestIndex(axis: readonly number[], x: number): number {
  if (!axis.length) return -1;
  let best = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let i = 0; i < axis.length; i += 1) {
    const distance = Math.abs(axis[i] - x);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = i;
    }
  }
  return best;
}
