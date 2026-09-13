import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { Api } from '../../core/api/api';
import type { FlowSpec, SessionState } from '../../core/api/models';
import { EegStream } from '../../core/eeg/stream';
import { clock, errorMessage, humanDuration } from '../../core/format';
import { Speech } from '../../core/speech/speech';
import { Waveform } from '../shared/waveform';

const RING_RADIUS = 54;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/**
 * Running a protocol.
 *
 * This screen is for the subject as much as for the operator: the state name is large,
 * the time remaining is a ring, and the transitions are spoken, so the person wearing
 * the headset does not have to watch the screen or ask what is next.
 *
 * It is also the only screen that writes a dataset, and it is honest about the two
 * things that decide what ends up in one:
 *
 * * the countdown is narrated and **not recorded** — the file is created when it ends;
 * * stopping a loop **drops its tail**, because reaching for the button changes what the
 *   subject is doing. The number of states that will be dropped is shown *before* the
 *   run, not discovered afterwards.
 */
@Component({
  selector: 'eeg-run-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Waveform, RouterLink],
  template: `
    <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section
        class="panel relative flex min-h-[520px] flex-col items-center justify-center overflow-hidden p-6"
      >
        <!-- ------------------------------------------------------ countdown -->
        @if (countdown() !== null) {
          <div class="flex flex-col items-center">
            <p class="text-sm uppercase tracking-[0.3em] text-slate-400">starting with</p>
            <p class="mono mt-2 text-[120px] leading-none font-semibold text-emerald-300">
              {{ countdown() }}
            </p>
            <p class="mt-4 max-w-md text-center text-sm text-slate-400">
              Nothing is being recorded yet. The countdown is narrated and left out of the dataset —
              recording begins the moment it reaches zero.
            </p>
            @if (speech.muted()) {
              <p class="mt-3 badge badge-idle">voice muted — counting silently</p>
            } @else if (!speech.supported()) {
              <p class="mt-3 badge badge-warn">this browser has no speech synthesis</p>
            }
          </div>
        } @else if (session(); as run) {
          <!-- -------------------------------------------------- current state -->
          <div class="flex flex-col items-center">
            <div class="relative grid place-items-center">
              <svg viewBox="0 0 120 120" class="h-56 w-56 -rotate-90">
                <circle
                  cx="60"
                  cy="60"
                  [attr.r]="ringRadius"
                  fill="none"
                  stroke="#1e293b"
                  stroke-width="8"
                />
                <circle
                  cx="60"
                  cy="60"
                  [attr.r]="ringRadius"
                  fill="none"
                  [attr.stroke]="run.recording ? '#10b981' : '#38bdf8'"
                  stroke-width="8"
                  stroke-linecap="round"
                  [attr.stroke-dasharray]="circumference"
                  [attr.stroke-dashoffset]="dashOffset()"
                />
              </svg>
              <div class="absolute flex flex-col items-center">
                <span class="mono text-5xl font-semibold text-slate-100">{{ remaining() }}</span>
                <span class="mt-1 text-xs uppercase tracking-widest text-slate-400">remaining</span>
              </div>
            </div>

            <p class="mt-6 text-2xl font-semibold text-slate-100">
              {{ run.engine.phase?.label ?? '…' }}
            </p>
            <p class="mt-1 text-sm text-slate-400">
              @if (run.engine.cycles === null) {
                cycle {{ run.engine.cycle + 1 }} · until you stop
              } @else {
                cycle {{ run.engine.cycle + 1 }} of {{ run.engine.cycles }}
              }
              · elapsed {{ time(run.engine.elapsed) }}
            </p>

            @if (run.engine.upcoming.length) {
              <div class="mt-5 flex flex-wrap items-center justify-center gap-1.5">
                <span class="text-[11px] uppercase tracking-widest text-slate-500">next</span>
                @for (phase of run.engine.upcoming; track $index) {
                  <span class="badge badge-idle">
                    {{ phase.label }}
                    <span class="mono text-slate-400">
                      {{ phase.duration === null ? '∞' : phase.duration + 's' }}
                    </span>
                  </span>
                }
              </div>
            }

            <div class="mt-6 flex flex-wrap items-center justify-center gap-2">
              <span class="badge" [class]="run.recording ? 'badge-ok' : 'badge-warn'">
                {{ run.recording ? 'recording' : 'armed — not yet recording' }}
              </span>
              <span class="mono text-xs text-slate-400">
                {{ run.recording_state?.samples ?? 0 }} samples ·
                {{ time(run.recording_state?.duration) }}
              </span>
            </div>

            <div class="mt-6 flex flex-wrap justify-center gap-2">
              <button
                type="button"
                class="btn btn-primary !px-5 !py-2"
                [disabled]="busy()"
                (click)="stop()"
              >
                ■ Stop and keep
              </button>
              <button
                type="button"
                class="btn btn-danger !px-5 !py-2"
                [disabled]="busy()"
                (click)="discard()"
              >
                Discard
              </button>
            </div>

            @if (run.flow.discard_tail > 0 && run.engine.cycles === null) {
              <p class="mt-4 max-w-lg text-center text-xs text-amber-300">
                Stopping this loop will drop the last {{ run.flow.discard_tail }} recorded state(s):
                the one you interrupt and the completed one before it.
              </p>
            }
          </div>
        } @else {
          <!-- -------------------------------------------------------- setup -->
          <div class="w-full max-w-xl">
            <h1 class="text-lg font-semibold text-slate-100">Run a protocol</h1>
            <p class="mt-1 text-sm text-slate-400">
              The subject hears the states and the countdown; the dataset is written here and
              nowhere else.
            </p>

            @if (!stream.streaming()) {
              <p
                class="mt-4 rounded-lg border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-xs text-amber-200"
              >
                Nothing is streaming. Start the dongle or the demo signal from the header before
                running a protocol — recording silence produces a dataset that looks fine and means
                nothing.
              </p>
            }

            <div class="mt-4 grid gap-3">
              <div>
                <label class="label" for="run-flow">Protocol</label>
                <select
                  id="run-flow"
                  class="field"
                  [value]="selectedId() ?? ''"
                  (change)="selectedId.set(value($event) || null)"
                >
                  @for (flow of flows(); track flow.id) {
                    <option [value]="flow.id">{{ flow.name }}</option>
                  }
                </select>
                @if (selectedFlow(); as flow) {
                  <p class="mt-1 text-[11px] text-slate-500">
                    {{ flow.steps.length }} state(s) ·
                    {{
                      flow.total_seconds === null ? 'until stopped' : duration(flow.total_seconds)
                    }}
                    · countdown {{ flow.countdown_seconds }} s
                    @if (flow.mode === 'loop') {
                      · loops
                    }
                  </p>
                }
              </div>

              <div>
                <label class="label" for="run-name">Dataset name</label>
                <input
                  id="run-name"
                  class="field"
                  placeholder="eyes-closed-session-1"
                  [value]="datasetName()"
                  (input)="datasetName.set(value($event))"
                />
              </div>

              <div>
                <label class="label" for="run-notes">Notes</label>
                <input
                  id="run-notes"
                  class="field"
                  placeholder="subject, electrode condition, anything unusual"
                  [value]="notes()"
                  (input)="notes.set(value($event))"
                />
              </div>

              <label class="flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" [checked]="!speech.muted()" (change)="speech.toggle()" />
                Speak the states and the countdown
              </label>

              <button
                type="button"
                class="btn btn-primary !py-2"
                [disabled]="busy() || !stream.streaming() || !selectedId()"
                (click)="start()"
              >
                ▶ Start protocol
              </button>

              @if (error(); as text) {
                <p class="text-xs text-rose-300">{{ text }}</p>
              }
            </div>
          </div>
        }
      </section>

      <aside class="flex flex-col gap-4">
        <section class="panel p-3">
          <h2 class="label">Live check</h2>
          <div class="h-40 overflow-hidden rounded-lg">
            <eeg-waveform [channels]="stream.occipital()" [seconds]="5" [fullScaleUv]="80" />
          </div>
          <div class="mt-2 grid grid-cols-2 gap-2">
            @for (name of stream.occipital(); track name) {
              <div class="panel-tight px-2 py-1.5">
                <p class="mono text-xs font-semibold text-slate-200">{{ name }}</p>
                <p class="mono text-[11px] text-slate-400">
                  alpha {{ alphaFor(name).share.toFixed(1) }}% · peak
                  {{ alphaFor(name).peak.toFixed(2) }}
                </p>
              </div>
            }
          </div>
          <p class="mt-2 text-[11px] text-slate-500">
            With the eyes closed, alpha should rise here. That is the check that the recording is
            worth keeping.
          </p>
        </section>

        @if (summary(); as result) {
          <section class="panel p-4">
            <h2 class="text-sm font-semibold text-slate-100">Dataset written</h2>
            <p class="mono mt-1 text-xs text-slate-400">{{ result.name }}</p>
            <dl class="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div class="panel-tight px-2 py-1.5">
                <dt class="label mb-0">duration</dt>
                <dd class="mono text-slate-100">{{ duration(result.duration) }}</dd>
              </div>
              <div class="panel-tight px-2 py-1.5">
                <dt class="label mb-0">samples</dt>
                <dd class="mono text-slate-100">{{ result.samples }}</dd>
              </div>
            </dl>

            @if (result.labels.length) {
              <h3 class="label mt-3">Kept</h3>
              <ul class="space-y-1 text-xs">
                @for (label of result.labels; track label.label) {
                  <li class="flex justify-between gap-2">
                    <span class="text-slate-200">{{ label.label }}</span>
                    <span class="mono text-slate-400">
                      {{ label.segments }}× · {{ duration(label.seconds) }}
                    </span>
                  </li>
                }
              </ul>
            }

            @if (result.discarded_segments.length) {
              <h3 class="label mt-3">Discarded from the end</h3>
              <ul class="space-y-1 text-xs text-amber-300">
                @for (segment of result.discarded_segments; track segment.index) {
                  <li class="flex justify-between gap-2">
                    <span>{{ segment.label }}</span>
                    <span class="mono">{{ duration(segment.duration) }}</span>
                  </li>
                }
              </ul>
            }

            @if (result.removed) {
              <p class="mt-3 text-xs text-rose-300">The dataset was discarded, not kept.</p>
            } @else {
              <a class="link mt-3 inline-block text-xs" [routerLink]="['/datasets', result.id]">
                Open in Datasets →
              </a>
            }
          </section>
        }
      </aside>
    </div>
  `,
})
export class RunPage {
  private readonly api = inject(Api);
  protected readonly stream = inject(EegStream);
  protected readonly speech = inject(Speech);

  /** Bound from `?flow=<id>`; `undefined` when the query parameter is absent. */
  readonly flow = input<string | undefined>(undefined);

  protected readonly flows = signal<FlowSpec[]>([]);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly datasetName = signal('');
  protected readonly notes = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly ringRadius = RING_RADIUS;
  protected readonly circumference = RING_CIRCUMFERENCE;

  protected readonly session = computed(() => {
    const state: SessionState | null = this.stream.session();
    return state?.active ? state : null;
  });
  protected readonly summary = computed(() => this.stream.summary());

  protected readonly selectedFlow = computed(
    () => this.flows().find((flow) => flow.id === this.selectedId()) ?? null,
  );

  /** The big countdown number: derived from the clock, not from an event. */
  protected readonly countdown = computed(() => {
    const phase = this.stream.phase();
    if (!phase || phase.kind !== 'countdown' || phase.remaining === null) return null;
    return Math.max(1, Math.ceil(phase.remaining - 1e-6));
  });

  protected readonly remaining = computed(() => {
    const phase = this.stream.phase();
    if (!phase) return '—';
    if (phase.remaining === null) return '∞';
    return clock(phase.remaining);
  });

  protected readonly dashOffset = computed(() => {
    const phase = this.stream.phase();
    const progress = phase?.progress ?? 0;
    return RING_CIRCUMFERENCE * (1 - Math.min(1, Math.max(0, progress)));
  });

  constructor() {
    void this.load();

    // Speak exactly what the server announces, and only that: the timings are the
    // server's, so the voice cannot drift out of step with the recording.
    effect(() => {
      const event = this.stream.lastEvent();
      if (!event) return;
      if (event.kind === 'countdown' && event.count !== null) {
        this.speech.count(event.count);
      } else if (event.kind === 'phase_start' && event.phase) {
        this.speech.say(event.phase.speak ?? event.phase.label);
      }
    });

    // A finished run should say so out loud — the subject may be lying down.
    effect(() => {
      const outcome = this.summary();
      if (outcome && !outcome.removed) this.speech.say('recording finished');
    });
  }

  private async load(): Promise<void> {
    try {
      const flows = await this.api.flows();
      this.flows.set(flows);
      const requested = this.flow() || flows[0]?.id || null;
      this.selectedId.set(requested);
      const chosen = flows.find((flow) => flow.id === requested) ?? flows[0];
      if (chosen) this.datasetName.set(chosen.name);
    } catch (error) {
      this.error.set(errorMessage(error));
    }
  }

  protected async start(): Promise<void> {
    const id = this.selectedId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    this.stream.summary.set(null);
    try {
      await this.api.startSession({
        flow_id: id,
        dataset_name: this.datasetName().trim() || undefined,
        notes: this.notes().trim(),
        voice: !this.speech.muted(),
      });
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected async stop(): Promise<void> {
    await this.finish(() => this.api.stopSession());
  }

  protected async discard(): Promise<void> {
    await this.finish(() => this.api.abortSession());
  }

  private async finish(action: () => Promise<unknown>): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await action();
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected alphaFor(name: string): { share: number; peak: number } {
    return this.stream.alpha()[name] ?? { share: 0, peak: 0 };
  }

  protected time(seconds: number | null | undefined): string {
    return clock(seconds);
  }

  protected duration(seconds: number | null | undefined): string {
    return humanDuration(seconds);
  }

  protected value(event: Event): string {
    return (event.target as HTMLInputElement | HTMLSelectElement).value;
  }
}
