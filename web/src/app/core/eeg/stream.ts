import { Injectable, computed, signal } from '@angular/core';

import type {
  AlphaMetrics,
  ChannelMetrics,
  ContactSummary,
  HelloFrame,
  SessionEvent,
  StreamFrame,
  TickFrame,
} from './messages';
import type { RecordingState, RecordingSummary, SessionState, SourceStats } from '../api/models';
import { SampleRing } from './ring';

/** Seconds of samples kept on the client, which bounds what a chart can show. */
export const HISTORY_SECONDS = 15;

/** The sample rate assumed until the server says otherwise. */
const DEFAULT_FS = 128;

/** Reconnect backoff, in milliseconds. */
const RETRY_MS = [500, 1000, 2000, 4000, 8000];

/** The newest few seconds of samples, as handed to a chart. */
export interface SampleWindow {
  /** Row-major, oldest first: row * width + channel. */
  data: Float32Array;
  rows: number;
  width: number;
}

/**
 * The live stream, as signals.
 *
 * Components read signals rather than subscribing: the monitor redraws whenever `ticks`
 * changes, and every panel that shows a number reads it from here. The socket
 * reconnects on its own, because a monitor that silently stops updating is worse than
 * one that says it is disconnected.
 */
@Injectable({ providedIn: 'root' })
export class EegStream {
  readonly connected = signal(false);
  readonly connecting = signal(false);
  readonly hello = signal<HelloFrame | null>(null);
  readonly sourceStats = signal<SourceStats | null>(null);
  readonly metrics = signal<ChannelMetrics[]>([]);
  readonly alpha = signal<Record<string, AlphaMetrics>>({});
  readonly contact = signal<ContactSummary | null>(null);
  readonly session = signal<SessionState | null>(null);
  readonly recording = signal<RecordingState | null>(null);
  readonly lastEvent = signal<SessionEvent | null>(null);
  readonly summary = signal<RecordingSummary | null>(null);
  readonly error = signal<string | null>(null);

  /** Bumped on every frame that carried samples, so canvases can redraw on demand. */
  readonly ticks = signal(0);

  readonly channels = computed(() => this.hello()?.channels ?? []);
  readonly occipital = computed(() => this.hello()?.occipital ?? ['O1', 'O2']);
  readonly sampleRate = computed(() => this.hello()?.fs ?? DEFAULT_FS);
  readonly phase = computed(() => this.session()?.engine.phase ?? null);
  readonly sessionActive = computed(() => this.session()?.active ?? false);

  /** Whether samples are actually arriving, as opposed to a socket being open. */
  readonly streaming = computed(() => {
    const stats = this.sourceStats();
    return stats !== null && stats.mode !== 'idle' && stats.samples > 0;
  });

  private currentCapacity = Math.round(HISTORY_SECONDS * DEFAULT_FS);
  private ring = new SampleRing(this.currentCapacity, 14);
  private scratch = new Float32Array(this.currentCapacity * 14);
  private socket: WebSocket | null = null;
  private retry = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private wanted = false;

  // ------------------------------------------------------------------ control
  /** Connect, and keep reconnecting until `disconnect()` is called. */
  connect(): void {
    this.wanted = true;
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    this.open();
  }

  disconnect(): void {
    this.wanted = false;
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    const socket = this.socket;
    this.socket = null;
    this.connected.set(false);
    this.connecting.set(false);
    socket?.close();
  }

  /** The newest `seconds` of samples. The buffer is reused — copy it to keep it. */
  window(seconds: number): SampleWindow {
    const rows = this.ring.copyLatest(Math.round(seconds * this.sampleRate()), this.scratch);
    return { data: this.scratch, rows, width: this.ring.width };
  }

  /** Forget everything buffered. Used when the source changes under us. */
  reset(): void {
    this.ring = new SampleRing(this.currentCapacity, 14);
    this.scratch = new Float32Array(this.currentCapacity * 14);
    this.metrics.set([]);
    this.alpha.set({});
    this.contact.set(null);
    this.ticks.update((n) => n + 1);
  }

  // ------------------------------------------------------------------ socket
  private open(): void {
    this.connecting.set(true);
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    let socket: WebSocket;
    try {
      socket = new WebSocket(`${scheme}://${location.host}/ws/stream`);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.connecting.set(false);
      this.connected.set(true);
      this.error.set(null);
      this.retry = 0;
    };
    socket.onmessage = (event: MessageEvent<string>) => this.handle(event.data);
    socket.onerror = () => this.error.set('The live connection failed.');
    socket.onclose = () => {
      this.connected.set(false);
      this.connecting.set(false);
      if (this.wanted) this.scheduleRetry();
    };
  }

  private scheduleRetry(): void {
    if (!this.wanted || this.retryTimer !== null) return;
    const delay = RETRY_MS[Math.min(this.retry, RETRY_MS.length - 1)];
    this.retry += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.wanted) this.open();
    }, delay);
  }

  private handle(raw: string): void {
    let frame: StreamFrame;
    try {
      frame = JSON.parse(raw) as StreamFrame;
    } catch {
      return;
    }

    switch (frame.type) {
      case 'hello':
        this.hello.set(frame);
        this.sourceStats.set(frame.source);
        this.session.set(frame.session);
        this.recording.set(frame.recording);
        this.ensureCapacity(frame.fs);
        break;

      case 'history':
        this.ensureCapacity(frame.fs);
        this.ingest(frame.data);
        break;

      case 'tick':
        this.applyTick(frame);
        break;

      case 'session':
        this.session.set(frame.state);
        if (frame.event) this.lastEvent.set(frame.event);
        if (frame.summary) this.summary.set(frame.summary);
        if (frame.error) this.error.set(frame.error);
        break;

      case 'source':
        this.sourceStats.set(frame.state.stats);
        this.reset();
        break;

      case 'recording':
        this.recording.set(frame.recording ?? null);
        if (frame.summary) this.summary.set(frame.summary);
        break;

      case 'ping':
        break;
    }
  }

  private applyTick(frame: TickFrame): void {
    this.ingest(frame.samples.data);
    this.sourceStats.set(frame.source);
    this.metrics.set(frame.metrics);
    this.alpha.set(frame.alpha);
    this.contact.set(frame.contact);
    this.session.set(frame.session);
    this.recording.set(frame.recording);
    this.error.set(frame.error);
    this.ticks.update((n) => n + 1);
  }

  private ingest(rows: number[][]): void {
    if (!rows || rows.length === 0) return;
    this.ring.push(rows);
  }

  private ensureCapacity(fs: number): void {
    const capacity = Math.max(1, Math.round(HISTORY_SECONDS * fs));
    if (capacity === this.currentCapacity) return;
    this.currentCapacity = capacity;
    this.ring = new SampleRing(capacity, 14);
    this.scratch = new Float32Array(capacity * 14);
    this.ticks.update((n) => n + 1);
  }
}
