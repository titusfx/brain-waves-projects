import { describe, expect, it } from 'vitest';

import { SampleRing } from './ring';

/**
 * The ring's wrap-around is the part that is only ever wrong once a session has been
 * running for a minute — which is exactly the kind of bug that never shows up while
 * someone is watching the screen it feeds.
 */
describe('SampleRing', () => {
  it('reports nothing before anything is pushed', () => {
    const ring = new SampleRing(4, 2);
    expect(ring.rows).toBe(0);
    expect(ring.latest(4)).toEqual([]);
  });

  it('returns rows oldest first', () => {
    const ring = new SampleRing(8, 2);
    ring.push([
      [1, 2],
      [3, 4],
    ]);
    expect(ring.latest(8)).toEqual([
      [1, 2],
      [3, 4],
    ]);
  });

  it('keeps only the newest rows once it has wrapped', () => {
    const ring = new SampleRing(3, 1);
    ring.push([[1], [2], [3], [4], [5]]);
    expect(ring.rows).toBe(3);
    expect(ring.written).toBe(5);
    expect(ring.latest(3)).toEqual([[3], [4], [5]]);
  });

  it('keeps the order across the wrap point', () => {
    const ring = new SampleRing(4, 2);
    for (let i = 1; i <= 6; i += 1) ring.push([[i, i * 10]]);
    // Capacity 4, six written: the oldest two are gone, and 3..6 are in order.
    expect(ring.latest(4)).toEqual([
      [3, 30],
      [4, 40],
      [5, 50],
      [6, 60],
    ]);
  });

  it('copies into a reusable buffer without allocating', () => {
    const ring = new SampleRing(5, 2);
    const out = new Float32Array(5 * 2);
    ring.push([
      [1, 2],
      [3, 4],
    ]);
    expect(ring.copyLatest(2, out)).toBe(2);
    expect([...out.subarray(0, 4)]).toEqual([1, 2, 3, 4]);
  });

  it('never returns more rows than it holds', () => {
    const ring = new SampleRing(5, 1);
    const out = new Float32Array(5);
    ring.push([[1], [2]]);
    expect(ring.copyLatest(4, out)).toBe(2);
  });

  it('replaces the whole ring when a chunk is larger than the capacity', () => {
    const ring = new SampleRing(2, 1);
    ring.push([[1], [2], [3], [4]]);
    expect(ring.latest(2)).toEqual([[3], [4]]);
  });

  it('refuses a capacity that could never hold anything', () => {
    expect(() => new SampleRing(0, 1)).toThrow();
  });
});
