/**
 * A ring of samples held as one flat `Float32Array`.
 *
 * Flat and pre-allocated rather than an array of rows because the draw loop asks for the
 * newest few seconds several times a second, and allocating ~9,000 numbers each time
 * would produce a steady stream of garbage for the collector to chase.
 *
 * The wrap-around is the part worth testing: the arithmetic is the kind that is off by
 * one only once the buffer has actually wrapped, which is a minute into a session.
 */
export class SampleRing {
  private readonly data: Float32Array;
  private total = 0;

  constructor(
    private readonly capacity: number,
    readonly width: number,
  ) {
    if (capacity < 1) throw new Error('a sample ring needs a positive capacity');
    this.data = new Float32Array(capacity * width);
  }

  /** Rows currently available, which is `total` until the ring has wrapped. */
  get rows(): number {
    return Math.min(this.total, this.capacity);
  }

  /** Rows ever written, including those already overwritten. */
  get written(): number {
    return this.total;
  }

  push(rows: number[][]): void {
    for (const row of rows) {
      const base = (this.total % this.capacity) * this.width;
      for (let i = 0; i < this.width; i += 1) {
        this.data[base + i] = row[i] ?? 0;
      }
      this.total += 1;
    }
  }

  /**
   * Copy the newest `count` samples into `out`, oldest first, and return how many rows
   * were written. `out` must hold at least `capacity * width` values.
   */
  copyLatest(count: number, out: Float32Array): number {
    const n = Math.min(count, this.rows);
    if (n <= 0) return 0;
    const stride = this.width;
    const end = this.total % this.capacity || this.capacity;
    const start = end - n;
    if (start >= 0) {
      out.set(this.data.subarray(start * stride, end * stride), 0);
    } else {
      const head = -start;
      out.set(this.data.subarray((this.capacity - head) * stride), 0);
      out.set(this.data.subarray(0, end * stride), head * stride);
    }
    return n;
  }

  /** The newest few seconds, as rows of `width` values. Used by tests and previews. */
  latest(count: number): number[][] {
    const out = new Float32Array(this.capacity * this.width);
    const rows = this.copyLatest(count, out);
    const result: number[][] = [];
    for (let row = 0; row < rows; row += 1) {
      const slice: number[] = [];
      for (let column = 0; column < this.width; column += 1) {
        slice.push(out[row * this.width + column]);
      }
      result.push(slice);
    }
    return result;
  }
}
