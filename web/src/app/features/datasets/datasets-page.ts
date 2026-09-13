import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { Router } from '@angular/router';

import { Api } from '../../core/api/api';
import type { LabelSummary, LibraryEntry, Preview, Segment, Spectrum } from '../../core/api/models';
import { EegStream } from '../../core/eeg/stream';
import { bytes, errorMessage, humanDuration } from '../../core/format';
import { SampleChart, SpectrumChart } from '../shared/charts';

const KIND_LABEL: Record<string, string> = {
  dataset: 'labelled dataset',
  session: 'live_view session',
  recording: 'recording',
};

/** A stable colour per label, so the same class is the same colour everywhere. */
function labelColour(label: string): string {
  const palette = ['#34d399', '#38bdf8', '#a78bfa', '#fbbf24', '#f472b6', '#22d3ee', '#fb923c'];
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) hash = (hash * 31 + label.charCodeAt(i)) % 9973;
  return palette[hash % palette.length];
}

/**
 * Everything recorded so far, and what is inside it.
 *
 * Three kinds are listed together because to the operator they are one library: datasets
 * written by a protocol (with labels), `live_view.py`'s session folders, and the flat
 * CSVs `record.py` writes. All of them can be replayed through the monitor — which is
 * the point of keeping the reader tolerant of three header layouts.
 *
 * The detail view answers "is this dataset what I think it is?" without opening a
 * notebook: the label timeline shows the states in proportion, the spectrum shows
 * whether the alpha is where the label says it should be, and the counts are the counts.
 */
@Component({
  selector: 'eeg-datasets-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SampleChart, SpectrumChart],
  template: `
    <div class="grid gap-4 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
      <!-- --------------------------------------------------------- the list -->
      <aside class="panel h-fit p-3">
        <div class="mb-2 flex items-center gap-2">
          <h1 class="label mb-0">Library</h1>
          <span class="badge badge-idle">{{ entries().length }}</span>
          <button
            type="button"
            class="btn btn-ghost ml-auto !px-2 !py-0.5 !text-[11px]"
            (click)="reload()"
          >
            Refresh
          </button>
        </div>

        @if (error(); as text) {
          <p class="mb-2 text-xs text-rose-300">{{ text }}</p>
        }

        @if (loading()) {
          <p class="text-xs text-slate-500">Reading recordings/…</p>
        } @else if (entries().length === 0) {
          <p class="text-xs text-slate-500">
            Nothing recorded yet. Run a protocol, or record one label from the monitor.
          </p>
        }

        <ul class="flex max-h-[70vh] flex-col gap-1 overflow-y-auto pr-1">
          @for (entry of entries(); track entry.id) {
            <li>
              <button
                type="button"
                class="panel-tight w-full cursor-pointer px-2.5 py-2 text-left transition hover:bg-slate-800/50"
                [class.!border-emerald-500]="entry.id === selectedId()"
                (click)="open(entry.id)"
              >
                <div class="flex items-center gap-2">
                  <span class="truncate text-sm font-medium text-slate-100">{{ entry.name }}</span>
                  <span
                    class="badge ml-auto shrink-0"
                    [class]="entry.kind === 'dataset' ? 'badge-ok' : 'badge-idle'"
                    >{{ kindLabel(entry.kind) }}</span
                  >
                </div>
                <p class="mono mt-0.5 text-[11px] text-slate-500">
                  {{ duration(entry.duration_s) }} · {{ entry.samples }} samples ·
                  {{ size(entry.size_bytes) }}
                </p>
                @if (entry.labels.length) {
                  <div class="mt-1 flex flex-wrap gap-1">
                    @for (label of entry.labels; track label.label) {
                      <span class="badge" [style.border-color]="colour(label.label)">
                        <span
                          class="h-1.5 w-1.5 rounded-full"
                          [style.background]="colour(label.label)"
                        ></span>
                        {{ label.label }} {{ duration(label.seconds) }}
                      </span>
                    }
                  </div>
                }
                <p class="mt-1 text-[10px] text-slate-600">{{ entry.created }}</p>
              </button>
            </li>
          }
        </ul>
      </aside>

      <!-- ------------------------------------------------------- the detail -->
      <section class="flex flex-col gap-4">
        @if (selected(); as entry) {
          <div class="panel p-4">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="text-lg font-semibold text-slate-100">{{ entry.name }}</h2>
              <span class="badge badge-idle">{{ kindLabel(entry.kind) }}</span>
              @if (entry.source) {
                <span class="badge badge-idle">from {{ entry.source }}</span>
              }
              @if (entry.dropped_chunks) {
                <span class="badge badge-warn">{{ entry.dropped_chunks }} dropped chunk(s)</span>
              }
              <div class="ml-auto flex gap-2">
                <button
                  type="button"
                  class="btn"
                  [disabled]="busy()"
                  (click)="replay(entry)"
                  title="Feed this recording through the whole app"
                >
                  ▶ Replay
                </button>
              </div>
            </div>

            <dl class="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <div class="panel-tight px-2 py-1.5">
                <dt class="label mb-0">duration</dt>
                <dd class="mono text-slate-100">{{ duration(entry.duration_s) }}</dd>
              </div>
              <div class="panel-tight px-2 py-1.5">
                <dt class="label mb-0">samples</dt>
                <dd class="mono text-slate-100">{{ entry.samples }}</dd>
              </div>
              <div class="panel-tight px-2 py-1.5">
                <dt class="label mb-0">states</dt>
                <dd class="mono text-slate-100">{{ entry.segments }}</dd>
              </div>
              <div class="panel-tight px-2 py-1.5">
                <dt class="label mb-0">size</dt>
                <dd class="mono text-slate-100">{{ size(entry.size_bytes) }}</dd>
              </div>
            </dl>

            @if (entry.notes) {
              <p class="mt-2 text-xs text-slate-400">Notes: {{ entry.notes }}</p>
            }
            <p class="mono mt-2 text-[10px] break-all text-slate-600">{{ entry.path }}</p>
          </div>

          <!-- ------------------------------------------------------ timeline -->
          @if (segments().length) {
            <div class="panel p-4">
              <h3 class="label">States, in proportion</h3>
              <div class="flex h-6 w-full overflow-hidden rounded-md border border-slate-700">
                @for (segment of segments(); track segment.index) {
                  <div
                    class="h-full border-r border-slate-900/70 last:border-r-0"
                    [style.flex-grow]="segment.samples || 1"
                    [style.background]="colour(segment.label)"
                    [title]="
                      segment.label +
                      ' · cycle ' +
                      (segment.cycle + 1) +
                      ' · ' +
                      segment.duration +
                      ' s' +
                      (segment.truncated ? ' (interrupted)' : '')
                    "
                  ></div>
                }
              </div>
              <div class="mt-2 flex flex-wrap gap-2">
                @for (label of entry.labels; track label.label) {
                  <span class="badge">
                    <span class="h-1.5 w-1.5 rounded-full" [style.background]="colour(label.label)"></span>
                    {{ label.label }} · {{ label.segments }}× ·
                    {{ duration(label.seconds) }}
                  </span>
                }
              </div>
            </div>
          }

          <!-- ------------------------------------------------------- samples -->
          <div class="panel p-4">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="label mb-0">Samples (decimated)</h3>
              <div class="ml-auto flex flex-wrap gap-1">
                @for (preset of presets; track preset.label) {
                  <button type="button" class="btn btn-ghost !px-2 !py-0.5 !text-[11px]" (click)="channels.set(preset.channels)">
                    {{ preset.label }}
                  </button>
                }
              </div>
            </div>
            <div class="mt-2 h-64 overflow-hidden rounded-lg">
              <eeg-sample-chart
                [rows]="previewRows()"
                [allChannels]="allChannels()"
                [channels]="channels()"
                [fullScaleUv]="100"
              />
            </div>
            @if (preview(); as data) {
              <p class="mt-1 text-[11px] text-slate-500">
                {{ data.total_samples }} samples, every {{ data.decimation }} kept. Decimated rather
                than averaged, so a blink stays a blink.
              </p>
            }
          </div>

          <!-- ------------------------------------------------------ spectrum -->
          <div class="panel p-4">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="label mb-0">Spectrum</h3>
              <select class="field !w-auto !py-0.5 !text-xs" [value]="spectrumChannel()" (change)="loadSpectrum(value($event))">
                @for (name of allChannels(); track name) {
                  <option [value]="name">{{ name }}</option>
                }
              </select>
              <span class="text-[11px] text-slate-500">
                Check O1/O2 with the eyes closed: alpha sits at 8–12 Hz.
              </span>
            </div>
            <div class="mt-2 h-56 overflow-hidden rounded-lg">
              <eeg-spectrum-chart
                [freqs]="spectrum()?.freqs ?? []"
                [power]="spectrum()?.power ?? []"
                [label]="spectrumChannel()"
              />
            </div>
          </div>

          <!-- ------------------------------------------------------ segments -->
          @if (segments().length) {
            <div class="panel overflow-hidden">
              <table class="w-full text-xs">
                <thead class="bg-slate-900/70 text-slate-400">
                  <tr>
                    <th class="px-3 py-1.5 text-left font-medium">#</th>
                    <th class="px-3 py-1.5 text-left font-medium">state</th>
                    <th class="px-3 py-1.5 text-right font-medium">cycle</th>
                    <th class="px-3 py-1.5 text-right font-medium">samples</th>
                    <th class="px-3 py-1.5 text-right font-medium">from</th>
                    <th class="px-3 py-1.5 text-right font-medium">to</th>
                    <th class="px-3 py-1.5 text-right font-medium">duration</th>
                  </tr>
                </thead>
                <tbody class="mono">
                  @for (segment of segments(); track segment.index) {
                    <tr class="border-t border-slate-800/60">
                      <td class="px-3 py-1 text-slate-500">{{ segment.index }}</td>
                      <td class="px-3 py-1">
                        <span class="inline-flex items-center gap-1.5 text-slate-100">
                          <span
                            class="h-2 w-2 rounded-full"
                            [style.background]="colour(segment.label)"
                          ></span>
                          {{ segment.label }}
                        </span>
                      </td>
                      <td class="px-3 py-1 text-right text-slate-400">{{ segment.cycle + 1 }}</td>
                      <td class="px-3 py-1 text-right text-slate-400">{{ segment.samples }}</td>
                      <td class="px-3 py-1 text-right text-slate-400">
                        {{ segment.start_time.toFixed(2) }}
                      </td>
                      <td class="px-3 py-1 text-right text-slate-400">
                        {{ segment.end_time.toFixed(2) }}
                      </td>
                      <td class="px-3 py-1 text-right text-slate-200">
                        {{ segment.duration.toFixed(2) }} s
                        @if (segment.truncated) {
                          <span class="badge badge-warn ml-1">cut</span>
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        } @else {
          <div class="panel px-4 py-6 text-sm text-slate-400">
            Select a recording to see its labels, samples and spectrum.
          </div>
        }
      </section>
    </div>
  `,
})
export class DatasetsPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly stream = inject(EegStream);

  /** Bound from the `/datasets/:id` route parameter. */
  readonly id = input<string>('');

  protected readonly entries = signal<LibraryEntry[]>([]);
  protected readonly segments = signal<Segment[]>([]);
  protected readonly preview = signal<Preview | null>(null);
  protected readonly spectrum = signal<Spectrum | null>(null);
  protected readonly spectrumChannel = signal('O1');
  protected readonly channels = signal<string[]>(['O1', 'O2']);
  protected readonly loading = signal(true);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly presets = [
    { label: 'Occipital', channels: ['O1', 'O2'] },
    { label: 'Frontal', channels: ['AF3', 'AF4', 'F3', 'F4'] },
    { label: 'Temporal', channels: ['T7', 'T8', 'P7', 'P8'] },
  ];

  protected readonly selectedId = computed(() => this.id());
  protected readonly selected = computed(
    () => this.entries().find((entry) => entry.id === this.id()) ?? null,
  );
  protected readonly previewRows = computed(() => this.preview()?.data ?? []);
  protected readonly allChannels = computed(() => this.stream.channels());

  private loaded = '';

  constructor() {
    void this.reload();
    // The route parameter changes without the component being recreated, so the detail
    // is loaded from a computed comparison rather than from ngOnInit.
    void Promise.resolve().then(() => this.loadDetail(this.id()));
  }

  protected async reload(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const listing = await this.api.recordings();
      this.entries.set(listing.recordings);
      await this.loadDetail(this.id() || listing.recordings[0]?.id || '');
      if (!this.id() && listing.recordings.length) {
        await this.router.navigate(['/datasets', listing.recordings[0].id], { replaceUrl: true });
      }
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected async open(id: string): Promise<void> {
    await this.router.navigate(['/datasets', id]);
    await this.loadDetail(id);
  }

  private async loadDetail(id: string): Promise<void> {
    if (!id || id === this.loaded) return;
    this.loaded = id;
    this.segments.set([]);
    this.preview.set(null);
    this.spectrum.set(null);
    try {
      const [segments, preview] = await Promise.all([
        this.api.segments(id).catch(() => [] as Segment[]),
        this.api.preview(id, 1200).catch(() => null),
      ]);
      this.segments.set(segments);
      this.preview.set(preview);
      await this.loadSpectrum(this.spectrumChannel(), id);
    } catch (error) {
      this.error.set(errorMessage(error));
    }
  }

  protected async loadSpectrum(channel: string, id = this.id()): Promise<void> {
    this.spectrumChannel.set(channel);
    if (!id) return;
    try {
      this.spectrum.set(await this.api.spectrum(id, channel));
    } catch {
      this.spectrum.set(null);
    }
  }

  protected async replay(entry: LibraryEntry): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.api.setSource({ mode: 'replay', replay_id: entry.id, loop: true });
      await this.router.navigate(['/']);
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected kindLabel(kind: string): string {
    return KIND_LABEL[kind] ?? kind;
  }

  protected colour(label: string): string {
    return labelColour(label);
  }

  protected duration(seconds: number | null | undefined): string {
    return humanDuration(seconds);
  }

  protected size(value: number): string {
    return bytes(value);
  }

  protected value(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  protected summaryOf(labels: LabelSummary[]): string {
    return labels.map((label) => `${label.label} ${Math.round(label.seconds)}s`).join(', ');
  }
}
