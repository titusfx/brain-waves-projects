import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { Api } from '../../core/api/api';
import type { ChannelCatalog, ChannelDoc } from '../../core/api/models';
import { EegStream } from '../../core/eeg/stream';
import type { ChannelMetrics } from '../../core/eeg/messages';
import { clock, errorMessage, sourceLabel, statusTone } from '../../core/format';
import { Speech } from '../../core/speech/speech';
import { ChannelDocPanel } from '../shared/channel-doc';
import { HeadMap } from '../shared/head-map';
import { Waveform } from '../shared/waveform';

/**
 * The live monitor: what the electrodes are doing, right now.
 *
 * Three questions, in the order they get asked:
 *
 * 1. *Is anything arriving?* — the source strip, which also names which signal it is.
 * 2. *Is each electrode on properly?* — the head map and the channel table, coloured by
 *    the same contact verdict the CLI tools print.
 * 3. *Is it a brain?* — the occipital alpha meter, which is the only evidence this
 *    project accepts for that claim, next to the raw traces.
 *
 * Plus the single-label recorder, because "make me a dataset of this" is the job that
 * gets done most often and it should not require leaving the screen that shows whether
 * the contact is good enough to bother.
 */
@Component({
  selector: 'eeg-monitor-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [HeadMap, Waveform, ChannelDocPanel, RouterLink],
  template: `
    <!-- ------------------------------------------------------------- source -->
    <section class="panel mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3">
      <div>
        <span class="label mb-0">Signal</span>
        <p class="text-sm font-semibold text-slate-100">
          {{ modeLabel(stats()?.mode) }}
          @if (stats()?.label) {
            <span class="ml-1 text-xs font-normal text-slate-400">{{ stats()?.label }}</span>
          }
        </p>
      </div>

      <dl class="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
        <div>
          <dt class="label mb-0">reports/s</dt>
          <dd class="mono text-slate-200">{{ rate() }}</dd>
        </div>
        <div>
          <dt class="label mb-0">samples</dt>
          <dd class="mono text-slate-200">{{ stats()?.samples ?? 0 }}</dd>
        </div>
        <div>
          <dt class="label mb-0">elapsed</dt>
          <dd class="mono text-slate-200">{{ time(stats()?.elapsed_s) }}</dd>
        </div>
        <div>
          <dt class="label mb-0">key</dt>
          <dd>
            @if (stats()?.key_ok === null) {
              <span class="badge badge-idle">n/a</span>
            } @else if (stats()?.key_ok) {
              <span class="badge badge-ok">confirmed</span>
            } @else {
              <span class="badge badge-bad">WRONG KEY</span>
            }
          </dd>
        </div>
        @if (contact(); as summary) {
          <div>
            <dt class="label mb-0">contact</dt>
            <dd>
              <span class="badge" [class]="'badge-' + (summary.ok_fraction >= 0.7 ? 'ok' : 'warn')">
                {{ summary.ok }}/{{ summary.total }} good
              </span>
            </dd>
          </div>
        }
      </dl>

      @if (stream.error() || stats()?.error) {
        <p class="ml-auto text-xs text-rose-300">{{ stream.error() || stats()?.error }}</p>
      }
    </section>

    @if (!stream.streaming()) {
      <section class="panel mb-4 px-4 py-3 text-sm text-slate-300">
        <p class="font-medium text-slate-100">Nothing is streaming.</p>
        <p class="mt-1 text-slate-400">
          Plug the dongle in and press <span class="text-emerald-300">Dongle</span> in the header, or
          press <span class="text-sky-300">Demo</span> to exercise the whole app with a synthetic
          signal — no headset required. A recording can be replayed from
          <a class="link" routerLink="/datasets">Datasets</a>.
        </p>
      </section>
    }

    <!-- ------------------------------------------------------- map + traces -->
    <div class="mb-4 grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_320px]">
      <section class="panel p-3">
        <h2 class="label">Montage</h2>
        <eeg-head-map
          [docs]="catalog()?.channels ?? []"
          [metrics]="metricsMap()"
          [selected]="selected()"
          (pick)="select($event)"
        />
        <p class="mt-1 text-center text-[11px] text-slate-500">
          Colour = contact verdict. Click an electrode for its documentation.
        </p>
      </section>

      <section class="panel flex min-h-[420px] flex-col p-3">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <h2 class="label mb-0">Traces</h2>
          <span class="badge badge-idle">±{{ fullScale() }} µV · {{ windowSeconds() }} s</span>
          <div class="ml-auto flex flex-wrap gap-1">
            @for (preset of presets(); track preset.label) {
              <button
                type="button"
                class="btn btn-ghost !px-2 !py-0.5 !text-[11px]"
                (click)="show.set(preset.channels)"
              >
                {{ preset.label }}
              </button>
            }
          </div>
        </div>
        <div class="min-h-[360px] flex-1 overflow-hidden rounded-lg">
          <eeg-waveform [channels]="show()" [seconds]="windowSeconds()" [fullScaleUv]="fullScale()" />
        </div>
      </section>

      <section class="panel flex flex-col gap-3 p-3">
        <div>
          <h2 class="label">Alpha 8–12 Hz — close your eyes and watch it rise</h2>
          @for (name of stream.occipital(); track name) {
            <div class="mb-2">
              <div class="flex items-baseline justify-between text-xs">
                <span class="mono font-semibold text-slate-200">{{ name }}</span>
                <span class="mono text-slate-400">
                  {{ alphaFor(name).share.toFixed(1) }}% share · peak
                  {{ alphaFor(name).peak.toFixed(2) }}
                </span>
              </div>
              <div class="mt-1 h-2 overflow-hidden rounded-full bg-slate-800">
                <div
                  class="h-full rounded-full transition-[width] duration-200"
                  [style.width.%]="alphaWidth(alphaFor(name).share)"
                  [style.background]="alphaFor(name).peak > 1.5 ? '#34d399' : '#38bdf8'"
                ></div>
              </div>
            </div>
          }
          <p class="text-[11px] text-slate-500">
            A peak ratio above <span class="text-emerald-300">1.5</span> on O1/O2 with the eyes
            closed is this project's evidence that the signal is a real brain. If you have not seen
            it, you do not have EEG yet — check the two reference pads behind the ears first.
          </p>
        </div>

        @if (metrics().length) {
          <div class="overflow-hidden rounded-lg border border-slate-800">
            <table class="w-full text-xs">
              <thead class="bg-slate-900/70 text-slate-400">
                <tr>
                  <th class="px-2 py-1 text-left font-medium">ch</th>
                  <th class="px-2 py-1 text-right font-medium">amp µV</th>
                  <th class="px-2 py-1 text-right font-medium">now</th>
                  <th class="px-2 py-1 text-right font-medium">mains</th>
                  <th class="px-2 py-1 text-left font-medium">state</th>
                </tr>
              </thead>
              <tbody class="mono">
                @for (metric of metrics(); track metric.name) {
                  <tr
                    class="cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40"
                    (click)="select(metric.name)"
                  >
                    <td class="px-2 py-0.5 font-semibold text-slate-200">{{ metric.name }}</td>
                    <td class="px-2 py-0.5 text-right">{{ metric.amplitude_uv.toFixed(1) }}</td>
                    <td class="px-2 py-0.5 text-right text-slate-400">
                      {{ metric.current_uv.toFixed(0) }}
                    </td>
                    <td class="px-2 py-0.5 text-right text-slate-400">
                      {{ metric.mains_percent.toFixed(0) }}%
                    </td>
                    <td class="px-2 py-0.5">
                      <span class="badge" [class]="'badge-' + tone(metric.status)">{{
                        metric.status
                      }}</span>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else {
          <p class="text-xs text-slate-500">Waiting for the first analysis window…</p>
        }
      </section>
    </div>

    <!-- ---------------------------------------------------- record + docs -->
    <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section class="panel p-4">
        <h2 class="text-sm font-semibold text-slate-100">Record one label</h2>
        <p class="mt-1 text-xs text-slate-400">
          Name what the subject is doing, press record, and it counts down aloud — 3, 2, 1 — then
          records until you stop. The countdown itself is never written to the dataset.
        </p>

        @if (stream.sessionActive()) {
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <span class="badge badge-ok">recording</span>
            <span class="text-sm text-slate-200">
              {{ stream.session()?.dataset_name }}
              @if (stream.phase(); as phase) {
                <span class="text-slate-400">· {{ phase.label }}</span>
              }
            </span>
            <span class="mono text-xs text-slate-400">
              {{ stream.recording()?.samples ?? 0 }} samples ·
              {{ time(stream.recording()?.duration) }}
            </span>
            <div class="ml-auto flex gap-2">
              <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="stop()">
                Stop and keep
              </button>
              <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="discard()">
                Discard
              </button>
            </div>
          </div>
        } @else {
          <div class="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_140px_120px_auto] sm:items-end">
            <div>
              <label class="label" for="quick-label">Label</label>
              <input
                id="quick-label"
                class="field"
                placeholder="eyes closed"
                [value]="quickLabel()"
                (input)="quickLabel.set($any($event.target).value)"
                (keydown.enter)="startQuick()"
              />
            </div>
            <div>
              <label class="label" for="quick-count">Countdown</label>
              <select
                id="quick-count"
                class="field"
                [value]="quickCountdown()"
                (change)="setCountdown($event)"
              >
                <option [value]="0">none</option>
                <option [value]="3">3 s</option>
                <option [value]="5">5 s</option>
                <option [value]="10">10 s</option>
              </select>
            </div>
            <div>
              <span class="label">Voice</span>
              <button type="button" class="btn w-full" (click)="speech.toggle()">
                {{ speech.muted() ? '🔇 muted' : '🔊 on' }}
              </button>
            </div>
            <button
              type="button"
              class="btn btn-primary h-[34px]"
              [disabled]="busy() || !quickLabel().trim() || !stream.streaming()"
              (click)="startQuick()"
            >
              ● Record
            </button>
          </div>
          @if (!stream.streaming()) {
            <p class="mt-2 text-xs text-amber-300">
              Start a source first — recording silence produces a dataset that looks fine and means
              nothing.
            </p>
          }
        }

        @if (message(); as text) {
          <p class="mt-3 text-xs text-rose-300">{{ text }}</p>
        }
      </section>

      <section class="panel p-4">
        <eeg-channel-doc
          [doc]="selectedDoc()"
          [metrics]="selectedMetrics()"
          [closable]="false"
          (pick)="select($event)"
        />
        <a class="link mt-3 inline-block text-xs" routerLink="/channels">Open the full channel reference →</a>
      </section>
    </div>
  `,
})
export class MonitorPage {
  protected readonly stream = inject(EegStream);
  protected readonly speech = inject(Speech);
  private readonly api = inject(Api);

  protected readonly catalog = signal<ChannelCatalog | null>(null);
  protected readonly selected = signal<string | null>('O1');
  protected readonly show = signal<string[]>(['O1', 'O2', 'F3', 'F4']);
  protected readonly quickLabel = signal('eyes closed');
  protected readonly quickCountdown = signal(3);
  protected readonly busy = signal(false);
  protected readonly message = signal<string | null>(null);

  protected readonly windowSeconds = signal(4);
  protected readonly fullScale = signal(100);

  /** Trace presets. "All 14" resolves against the live channel list, not a guess. */
  protected readonly presets = computed(() => [
    { label: 'Occipital', channels: ['O1', 'O2'] },
    { label: 'Frontal', channels: ['AF3', 'AF4', 'F3', 'F4'] },
    { label: 'Temporal', channels: ['T7', 'T8', 'P7', 'P8'] },
    { label: 'All 14', channels: this.stream.channels() },
  ]);

  protected readonly stats = computed(() => this.stream.sourceStats());
  protected readonly metrics = computed(() => this.stream.metrics());
  protected readonly contact = computed(() => this.stream.contact());

  protected readonly metricsMap = computed(() => {
    const map = new Map<string, ChannelMetrics>();
    for (const metric of this.metrics()) map.set(metric.name, metric);
    return map;
  });

  protected readonly selectedDoc = computed<ChannelDoc | null>(
    () => this.catalog()?.channels.find((doc) => doc.name === this.selected()) ?? null,
  );

  protected readonly selectedMetrics = computed(
    () => this.metricsMap().get(this.selected() ?? '') ?? null,
  );

  constructor() {
    // "All 14" has to be resolved once the catalog knows the channel order.
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      const catalog = await this.api.catalog();
      this.catalog.set(catalog);
      this.show.set(['O1', 'O2', 'F3', 'F4']);
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }

  protected modeLabel(mode: string | undefined | null): string {
    return sourceLabel(mode);
  }

  protected time(seconds: number | null | undefined): string {
    return clock(seconds);
  }

  protected setCountdown(event: Event): void {
    this.quickCountdown.set(Number((event.target as HTMLSelectElement).value) || 0);
  }

  protected rate(): string {
    return (this.stats()?.reports_per_second ?? 0).toFixed(0);
  }

  protected tone(status: string): string {
    return statusTone(status);
  }

  protected alphaFor(name: string): { share: number; peak: number } {
    return this.stream.alpha()[name] ?? { share: 0, peak: 0 };
  }

  protected alphaWidth(share: number): number {
    return Math.min(100, (share / 40) * 100);
  }

  protected select(name: string): void {
    this.selected.set(name);
  }

  protected async startQuick(): Promise<void> {
    const label = this.quickLabel().trim();
    if (!label || this.busy()) return;
    this.busy.set(true);
    this.message.set(null);
    try {
      await this.api.quickRecord({
        label,
        countdown_seconds: this.quickCountdown(),
        voice: !this.speech.muted(),
      });
    } catch (error) {
      this.message.set(errorMessage(error));
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
    this.message.set(null);
    try {
      await action();
    } catch (error) {
      this.message.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }
}
