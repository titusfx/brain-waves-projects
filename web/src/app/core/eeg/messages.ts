/**
 * The real-time protocol.
 *
 * These frames are hand-written because a WebSocket is not an OpenAPI concept — there
 * is nothing for `openapi-typescript` to generate them from. Keeping them beside the
 * client that parses them is the next best thing: one file to change when the server's
 * `hub.frame()` changes, and the compiler then finds every consumer.
 *
 * Server → client:
 *
 *   `hello`     once on connect: sample rate, channels, device, catalog pointer
 *   `history`   once on connect: the last few seconds, so the chart is not blank
 *   `tick`      ~10/s: new samples, per-channel metrics, alpha, session state
 *   `session`   immediately, on every state change of a running flow
 *   `source`    immediately, when the stream is switched
 *   `recording` immediately, when a dataset starts or finishes
 *   `ping`      every 10 s of silence, so a dead socket is noticed
 */
import type {
  DeviceStatus,
  RecordingState,
  RecordingSummary,
  SessionState,
  SourceStats,
  Status,
} from '../api/models';

/** One channel's display numbers, recomputed by the server over the display window. */
export interface ChannelMetrics {
  name: string;
  amplitude_uv: number;
  current_uv: number;
  mains_percent: number;
  /** ok | low | high | DEAD | DRY? | artefact */
  status: string;
  bands: Record<string, number>;
}

/** The alpha rhythm's share of total power, and its peak ratio vs theta/beta. */
export interface AlphaMetrics {
  share: number;
  peak: number;
}

export interface ContactSummary {
  ok: number;
  total: number;
  ok_fraction: number;
  dead: string[];
  dry: string[];
  problem_channels: string[];
}

/** A block of samples: `data` is one row of 14 microvolts per sample, oldest first. */
export interface SampleBlock {
  t0: number;
  data: number[][];
}

export interface HelloFrame {
  type: 'hello';
  fs: number;
  channels: string[];
  occipital: string[];
  source: SourceStats;
  device: DeviceStatus;
  recording: RecordingState | null;
  session: SessionState | null;
  window_seconds: number;
}

export interface HistoryFrame {
  type: 'history';
  t0: number;
  fs: number;
  step: number;
  total_samples: number;
  data: number[][];
}

export interface TickFrame {
  type: 'tick';
  seq: number;
  t: number;
  fs: number;
  channels: string[];
  source: SourceStats;
  samples: SampleBlock;
  metrics: ChannelMetrics[];
  alpha: Record<string, AlphaMetrics>;
  contact: ContactSummary | null;
  window_seconds: number;
  session: SessionState | null;
  recording: RecordingState | null;
  error: string | null;
}

/** One state transition of a running protocol. */
export interface SessionEvent {
  kind:
    | 'started'
    | 'countdown'
    | 'go'
    | 'cycle_start'
    | 'phase_start'
    | 'phase_end'
    | 'finished'
    | 'stopped'
    | 'ended';
  at: number;
  count: number | null;
  truncated: boolean;
  phase?: {
    kind: string;
    label: string;
    cycle: number;
    step_index: number;
    duration: number | null;
    speak: string | null;
  } | null;
}

export interface SessionFrame {
  type: 'session';
  event?: SessionEvent;
  state: SessionState;
  summary?: RecordingSummary | null;
  outcome?: string | null;
  error?: string | null;
}

export interface SourceFrame {
  type: 'source';
  reason: string;
  state: Status;
}

export interface RecordingFrame {
  type: 'recording';
  state: 'started' | 'finished';
  recording?: RecordingState;
  summary?: RecordingSummary;
}

export interface PingFrame {
  type: 'ping';
  t: number;
}

export type StreamFrame =
  HelloFrame | HistoryFrame | TickFrame | SessionFrame | SourceFrame | RecordingFrame | PingFrame;
