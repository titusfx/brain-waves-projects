import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';

import { Api } from '../../core/api/api';
import type { LabelSummary, LibraryEntry, Preview, Segment, Spectrum } from '../../core/api/models';
import { EegStream } from '../../core/eeg/stream';
import { bytes, errorMessage, humanDuration } from '../../core/format';
import { SampleChart, SpectrumChart } from '../shared/charts';
import { ConfirmDialog } from '../shared/confirm-dialog';
import { DiscoveryPanel } from './discovery-panel';

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
  imports: [
    SampleChart,
    SpectrumChart,
    DiscoveryPanel,
    ConfirmDialog,
    RouterLink,
    RouterLinkActive,
  ],
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
            <li class="flex items-stretch gap-1">
              <button
                type="button"
                class="panel-tight min-w-0 flex-1 cursor-pointer px-2.5 py-2 text-left transition hover:bg-slate-800/50"
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
              <button
                type="button"
                class="btn btn-ghost shrink-0 !px-2"
                [attr.aria-label]="'Delete ' + entry.name"
                [title]="'Delete ' + entry.name"
                (click)="askDelete(entry)"
              >
                🗑
              </button>
            </li>
          }
        </ul>
      </aside>

      <!-- ------------------------------------------------------- the detail -->
      <section class="flex flex-col gap-4">
        @if (id()) {
          <nav class="flex items-center gap-1 border-b border-slate-800 pb-2">
            <a
              class="rounded-md px-3 py-1.5 text-[13px] font-medium text-slate-400 no-underline transition hover:bg-slate-800/60 hover:text-slate-100"
              routerLinkActive="!bg-slate-800 !text-emerald-300"
              [routerLinkActiveOptions]="{ exact: true }"
              [routerLink]="['/datasets', id()]"
              >Overview</a
            >
            <a
              class="rounded-md px-3 py-1.5 text-[13px] font-medium text-slate-400 no-underline transition hover:bg-slate-800/60 hover:text-slate-100"
              routerLinkActive="!bg-slate-800 !text-emerald-300"
              [routerLink]="['/datasets', id(), 'discovery']"
              title="Compare instances of a state, and find what separates two states"
              >Discovery</a
            >
          </nav>
        }

        @if (isDiscovery()) {
          <eeg-discovery-panel [entryId]="id() ?? ''" />
        } @else if (selected(); as entry) {
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
                <button
                  type="button"
                  class="btn"
                  [disabled]="busy()"
                  (click)="askDelete(entry)"
                  title="Delete this recording from disk"
                >
                  🗑 Delete
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
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="label mb-0">States, in proportion</h3>
                <span class="text-[11px] text-slate-500">
                  Click a state to show only its window below — and to take it to Discovery.
                </span>
              </div>
              <div class="mt-2 flex h-6 w-full overflow-hidden rounded-md border border-slate-700">
                @for (segment of segments(); track segment.index) {
                  <button
                    type="button"
                    class="h-full cursor-pointer border-r border-slate-900/70 p-0 last:border-r-0"
                    [class.ring-2]="range()?.index === segment.index"
                    [class.ring-emerald-400]="range()?.index === segment.index"
                    [style.flex-grow]="segment.samples || 1"
                    [style.background]="colour(segment.label)"
                    [style.opacity]="range() && range()?.index !== segment.index ? 0.45 : 1"
                    [title]="
                      segment.label +
                      ' · cycle ' +
                      (segment.cycle + 1) +
                      ' · ' +
                      segment.duration +
                      ' s' +
                      (segment.truncated ? ' (interrupted)' : '')
                    "
                    (click)="showSegment(segment)"
                  ></button>
                }
              </div>
              <div class="mt-2 flex flex-wrap gap-2">
                @for (label of entry.labels; track label.label) {
                  <span class="badge">
                    <span
                      class="h-1.5 w-1.5 rounded-full"
                      [style.background]="colour(label.label)"
                    ></span>
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
              @if (range(); as window) {
                <span class="badge badge-ok">
                  only {{ window.label }} #{{ window.index }} · {{ window.start.toFixed(1) }}–{{
                    window.end.toFixed(1)
                  }}
                  s
                </span>
                <button
                  type="button"
                  class="btn btn-ghost !px-2 !py-0.5 !text-[11px]"
                  (click)="clearRange()"
                >
                  whole recording
                </button>
              }
              <div class="ml-auto flex flex-wrap gap-1">
                @for (preset of presets; track preset.label) {
                  <button
                    type="button"
                    class="btn btn-ghost !px-2 !py-0.5 !text-[11px]"
                    (click)="channels.set(preset.channels)"
                  >
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
              <select
                class="field !w-auto !py-0.5 !text-xs"
                [value]="spectrumChannel()"
                (change)="loadSpectrum(value($event))"
              >
                @for (name of allChannels(); track name) {
                  <option [value]="name">{{ name }}</option>
                }
              </select>
              <span class="text-[11px] text-slate-500">
                @if (range(); as window) {
                  Only {{ window.label }} #{{ window.index }}, averaged over its window.
                } @else {
                  Check O1/O2 with the eyes closed: alpha sits at 8–12 Hz. Pick a state above to see
                  one instance on its own.
                }
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
                    <tr
                      class="cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40"
                      [class.!bg-emerald-950]="range()?.index === segment.index"
                      (click)="showSegment(segment)"
                    >
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

    <!--
      Deleting is the one thing here with no undo, so it never happens from a click:
      it happens from a second click, on a dialog that names what will go.
    -->
    @if (pendingDelete(); as target) {
      <eeg-confirm-dialog
        [title]="'Delete “' + target.name + '”?'"
        [message]="deleteMessage(target)"
        [detail]="deleteDetail(target)"
        [warning]="deleteWarning()"
        confirmLabel="Delete for good"
        [busy]="busy()"
        (cancelled)="cancelDelete()"
        (confirmed)="confirmDelete()"
      />
    }
  `,
})
export class DatasetsPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly stream = inject(EegStream);

  /**
   * Bound from the `/datasets/:id` route parameter.
   *
   * `| undefined` because the router binding writes `undefined` when the parameter is
   * absent — including on `/datasets`, where the page then selects the newest recording.
   */
  readonly id = input<string | undefined>(undefined);

  /** Route data: `overview` or `discovery`. `undefined` outside those routes. */
  readonly tab = input<string | undefined>(undefined);

  protected readonly entries = signal<LibraryEntry[]>([]);
  protected readonly segments = signal<Segment[]>([]);
  protected readonly preview = signal<Preview | null>(null);
  protected readonly spectrum = signal<Spectrum | null>(null);
  protected readonly spectrumChannel = signal('O1');
  protected readonly channels = signal<string[]>(['O1', 'O2']);
  protected readonly loading = signal(true);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  /**
   * The state being looked at, if any.
   *
   * Everything below — the traces and the spectrum — follows this, which is what turns
   * "eyes open" from a label in a table into a window you can actually inspect, and then
   * take to the Discovery tab to compare with another instance of the same state.
   */
  protected readonly range = signal<{
    index: number;
    label: string;
    start: number;
    end: number;
  } | null>(null);

  /** The recording the confirmation dialog is asking about, if any. */
  protected readonly pendingDelete = signal<LibraryEntry | null>(null);
  protected readonly deleteWarning = signal<string | null>(null);

  protected readonly presets = [
    { label: 'Occipital', channels: ['O1', 'O2'] },
    { label: 'Frontal', channels: ['AF3', 'AF4', 'F3', 'F4'] },
    { label: 'Temporal', channels: ['T7', 'T8', 'P7', 'P8'] },
  ];

  protected readonly selectedId = computed(() => this.id());
  protected readonly isDiscovery = computed(() => this.tab() === 'discovery');
  protected readonly selected = computed(
    () => this.entries().find((entry) => entry.id === this.id()) ?? null,
  );
  protected readonly previewRows = computed(() => this.preview()?.data ?? []);
  protected readonly allChannels = computed(() => this.stream.channels());

  private loaded = '';

  constructor() {
    void this.reload();
    // The route parameter changes without this component being recreated — browser
    // back/forward, or a link from the run screen — so the detail follows the parameter
    // rather than being loaded once. `loadDetail` ignores a repeat of the same id.
    effect(() => {
      const id = this.id();
      if (id) void this.loadDetail(id);
    });
    // Following the selected state reloads only the charts, so clicking through the
    // states of a dataset does not re-read the whole library listing each time.
    effect(() => {
      const range = this.range();
      if (!this.loaded) return;
      void this.applyRange(range);
    });
  }

  private async applyRange(
    range: { index: number; label: string; start: number; end: number } | null,
  ): Promise<void> {
    const id = this.id();
    if (!id) return;
    const window_ = range ? { start: range.start, end: range.end } : {};
    const [preview, spectrum] = await Promise.all([
      this.api.preview(id, 1200, window_).catch(() => null),
      this.api.spectrum(id, this.spectrumChannel(), window_).catch(() => null),
    ]);
    this.preview.set(preview);
    this.spectrum.set(spectrum);
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
    // Navigation is all this has to do: the effect above loads whatever the parameter
    // becomes, so there is one code path for "the id changed" rather than two.
    await this.router.navigate(['/datasets', id]);
  }

  private async loadDetail(id: string): Promise<void> {
    if (!id || id === this.loaded) return;
    this.loaded = id;
    this.range.set(null);
    this.segments.set([]);
    this.preview.set(null);
    this.spectrum.set(null);
    try {
      const segments = await this.api.segments(id).catch(() => [] as Segment[]);
      this.segments.set(segments);
      await this.refreshWindow();
    } catch (error) {
      this.error.set(errorMessage(error));
    }
  }

  /**
   * Load the samples and the spectrum for whatever window is selected.
   *
   * With no window that is the whole recording; with one it is a single state, which is
   * what makes "show me only what the eyes-open states look like" a click rather than a
   * download.
   */
  private async refreshWindow(): Promise<void> {
    const id = this.id();
    if (!id) return;
    const range = this.range();
    const window_ = range ? { start: range.start, end: range.end } : {};
    const [preview, spectrum] = await Promise.all([
      this.api.preview(id, 1200, window_).catch(() => null),
      this.api.spectrum(id, this.spectrumChannel(), window_).catch(() => null),
    ]);
    this.preview.set(preview);
    this.spectrum.set(spectrum);
  }

  /** Show one state's window only, or the whole recording again. */
  protected showSegment(segment: Segment): void {
    const current = this.range();
    if (current && current.index === segment.index) {
      this.range.set(null);
    } else {
      this.range.set({
        index: segment.index,
        label: segment.label,
        start: segment.start_time,
        end: segment.end_time,
      });
    }
  }

  protected clearRange(): void {
    this.range.set(null);
  }

  protected async loadSpectrum(channel: string, id = this.id()): Promise<void> {
    this.spectrumChannel.set(channel);
    if (!id) return;
    const range = this.range();
    const window_ = range ? { start: range.start, end: range.end } : {};
    try {
      this.spectrum.set(await this.api.spectrum(id, channel, window_));
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

  // ---------------------------------------------------------------- deleting
  protected askDelete(entry: LibraryEntry): void {
    this.deleteWarning.set(null);
    this.pendingDelete.set(entry);
  }

  protected cancelDelete(): void {
    this.pendingDelete.set(null);
    this.deleteWarning.set(null);
  }

  /**
   * Delete, but only what the dialog named.
   *
   * The entry is re-read from the signal rather than trusted from the click, and the id
   * is the one the server was shown — so a dialog left open while the library refreshed
   * cannot delete something other than what it described.
   */
  protected async confirmDelete(): Promise<void> {
    const target = this.pendingDelete();
    if (!target || this.busy()) return;
    this.busy.set(true);
    this.deleteWarning.set(null);
    this.error.set(null);
    try {
      const removed = await this.api.deleteRecording(target.id);
      this.pendingDelete.set(null);
      const listing = await this.api.recordings();
      this.entries.set(listing.recordings);
      if (this.id() === removed.id) {
        // The page was showing the thing that no longer exists.
        this.loaded = '';
        this.segments.set([]);
        this.preview.set(null);
        this.spectrum.set(null);
        const next = listing.recordings[0];
        await this.router.navigate(next ? ['/datasets', next.id] : ['/datasets'], {
          replaceUrl: true,
        });
        if (next) await this.loadDetail(next.id);
      }
    } catch (error) {
      // Kept open on purpose: if the server refused — a replay is streaming it, say —
      // the operator should see why against the dialog that asked.
      this.deleteWarning.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }

  /** What the dialog promises is about to be removed. */
  protected deleteDetail(entry: LibraryEntry): string[] {
    const lines = [
      `${this.kindLabel(entry.kind)} · ${this.duration(entry.duration_s)} · ${entry.samples} samples · ${this.size(entry.size_bytes)}`,
    ];
    if (entry.segments) {
      lines.push(`${entry.segments} recorded state(s), with their labels`);
    }
    if (entry.labels.length) {
      lines.push(`labels: ${entry.labels.map((label) => label.label).join(', ')}`);
    }
    lines.push(entry.path);
    return lines;
  }

  protected deleteMessage(entry: LibraryEntry): string {
    return entry.kind === 'dataset'
      ? 'This removes the whole dataset folder — samples, labels, metadata and events — from disk.'
      : 'This removes the recording file from disk.';
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
