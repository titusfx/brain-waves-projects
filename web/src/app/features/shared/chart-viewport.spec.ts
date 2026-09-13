import { describe, expect, it } from 'vitest';

import { ChartViewport, nearestIndex } from './chart-viewport';

/** A viewport over 0..40 Hz, the shape the spectral charts use. */
function viewport(full: [number, number] = [0, 40]): ChartViewport {
  return new ChartViewport(() => full);
}

describe('ChartViewport', () => {
  it('shows the whole range until something zooms it', () => {
    const chart = viewport();
    expect(chart.visible()).toEqual([0, 40]);
    expect(chart.zoomed).toBe(false);
  });

  it('keeps the point under the cursor fixed while zooming', () => {
    const chart = viewport();
    chart.zoomAt(10, 0.5);
    const [lo, hi] = chart.visible();
    // 10 Hz was at 25% of the range; after halving the span it should still be at 25%.
    expect(hi - lo).toBeCloseTo(20, 6);
    expect((10 - lo) / (hi - lo)).toBeCloseTo(0.25, 6);
  });

  it('never scrolls off the end of the data', () => {
    const chart = viewport();
    // Zoom hard against the left edge, then the right.
    chart.zoomAt(0, 0.25);
    expect(chart.visible()[0]).toBeGreaterThanOrEqual(0);
    chart.reset();
    chart.zoomAt(40, 0.25);
    expect(chart.visible()[1]).toBeLessThanOrEqual(40);
  });

  it('stops zooming in at a limit rather than collapsing to a point', () => {
    const chart = viewport();
    for (let i = 0; i < 200; i += 1) chart.zoomAt(20, 0.5);
    const [lo, hi] = chart.visible();
    expect(hi - lo).toBeGreaterThan(0);
    expect(hi - lo).toBeCloseTo(40 / 200, 6);
  });

  it('returning to the full span clears the window entirely', () => {
    const chart = viewport();
    chart.zoomAt(20, 0.5);
    chart.zoomAt(20, 4);
    expect(chart.visible()).toEqual([0, 40]);
    expect(chart.zoomed).toBe(false);
  });

  it('pans without changing the span, and clamps at the edges', () => {
    const chart = viewport();
    chart.zoomAt(20, 0.5); // 10..30
    chart.startDrag(100);
    chart.panBy(-50, 100); // half a width to the right
    const [lo, hi] = chart.visible();
    expect(hi - lo).toBeCloseTo(20, 6);
    expect(lo).toBeGreaterThan(10);

    for (let i = 0; i < 20; i += 1) chart.panBy(-100, 100);
    expect(chart.visible()[1]).toBeCloseTo(40, 6);
    for (let i = 0; i < 40; i += 1) chart.panBy(100, 100);
    expect(chart.visible()[0]).toBeCloseTo(0, 6);
  });

  it('maps between data and pixels consistently', () => {
    const chart = viewport();
    expect(chart.toPixel(0, 1000)).toBeCloseTo(0, 6);
    expect(chart.toPixel(40, 1000)).toBeCloseTo(1000, 6);
    expect(chart.toPixel(10, 1000)).toBeCloseTo(250, 6);
    expect(chart.fromPixel(250, 1000)).toBeCloseTo(10, 6);
    chart.zoomAt(10, 0.5);
    expect(chart.fromPixel(chart.toPixel(10, 800), 800)).toBeCloseTo(10, 6);
  });

  it('falls back to the whole range when the data reloads under a stale window', () => {
    const chart = viewport();
    chart.zoomAt(30, 0.1); // a window near the old end
    // New data spans a different range (a different recording).
    const reloaded = new ChartViewport(() => [0, 5]);
    reloaded.domain.set(chart.domain());
    expect(reloaded.visible()).toEqual([0, 5]);
  });
});

describe('nearestIndex', () => {
  it('finds the closest bin, not the closest value', () => {
    const axis = [1, 4, 8, 13, 30];
    expect(nearestIndex(axis, 3.9)).toBe(1);
    expect(nearestIndex(axis, 6.5)).toBe(2);
    expect(nearestIndex(axis, 100)).toBe(4);
    expect(nearestIndex(axis, -100)).toBe(0);
    expect(nearestIndex([], 1)).toBe(-1);
  });

  it('breaks an exact tie towards the lower bin', () => {
    // Bin centres are 4 Hz apart, so this happens often; either answer is right, but it
    // has to be the same one every time or the readout flickers as the pointer moves.
    expect(nearestIndex([1, 4, 8], 6)).toBe(1);
  });
});
