import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';

import { Api } from '../../core/api/api';
import type { Comparison, Discovery, DiscoveryInstance, Segment } from '../../core/api/models';
import { errorMessage, humanDuration } from '../../core/format';
import { EffectChart, SpectrumOverlay, TraceOverlay } from '../shared/charts';
import type { OverlaySeries, OverlayTrace } from '../shared/charts';

/** Class A and B are distinguished by hue; instances within a class by shade. */
const PALETTE_A = ['#34d399', '#10b981', '#6ee7b7', '#059669', '#a7f3d0', '#047857'];
const PALETTE_B = ['#38bdf8', '#0ea5e9', '#7dd3fc', '#0284c7', '#bae6fd', '#0369a1'];

const COLOUR_A = '#34d399';
const COLOUR_B = '#38bdf8';

/**
 * Discovery: is there anything here that tells two states apart?
 *
 * The screen is built around one question, in the order it gets asked:
 *
 * 1. **Do the instances of this state even look like each other?** The overlay draws
 *    every selected instance from the same origin; where they sit on top of each other
 *    is the part of the recording this state controls.
 * 2. **Do the two states differ by more than that?** The effect chart puts the per-bin
 *    difference against the two lines that decide it: the level below which the states
 *    are the same, and the level that shuffling the labels reaches by itself.
 * 3. **What is the same in both?** Those bins are listed and shaded, because they are
 *    the ones that look like findings and cannot explain anything.
 *
 * The last readout is the one that keeps it honest: with three instances per state there
 * are twenty ways to split them, so no result can come out below p ≈ 0.048 however clean
 * the separation looks. The screen says that rather than letting a promising picture be
 * mistaken for an established one.
 */
@Component({
  selector: 'eeg-discovery-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TraceOverlay, SpectrumOverlay, EffectChart],
  template: `
    @if (error(); as text) {
      <p class="panel mb-3 px-4 py-3 text-sm text-rose-300">{{ text }}</p>
    }

    @if (!labels().length) {
      <p class="panel px-4 py-3 text-sm text-slate-400">
        This recording has no labelled states, so there is nothing to compare. Discovery works on
        datasets written from a protocol — record one with the
        <span class="text-emerald-300">Run</span>
        screen.
      </p>
    } @else {
      <!-- ------------------------------------------------------------ controls -->
      <section class="panel mb-3 flex flex-wrap items-end gap-3 px-4 py-3">
        <div>
          <label class="label" for="discovery-channel">Electrode</label>
          <select
            id="discovery-channel"
            class="field !w-28"
            [value]="channel()"
            (change)="channel.set(value($event))"
          >
            @for (name of result()?.channels ?? []; track name) {
              <option [value]="name">{{ name }}</option>
            }
          </select>
        </div>
        <div>
          <label class="label" for="discovery-a">State A</label>
          <select
            id="discovery-a"
            class="field !w-44"
            [value]="labelA() ?? ''"
            (change)="labelA.set(value($event))"
          >
            @for (label of labels(); track label) {
              <option [value]="label">{{ label }}</option>
            }
          </select>
        </div>
        <div>
          <label class="label" for="discovery-b">State B</label>
          <select
            id="discovery-b"
            class="field !w-44"
            [value]="labelB() ?? ''"
            (change)="labelB.set(value($event))"
          >
            <option value="">compare with nothing</option>
            @for (label of labels(); track label) {
              <option [value]="label">{{ label }}</option>
            }
          </select>
        </div>
        <div>
          <label class="label" for="discovery-window">Overlay window</label>
          <input
            id="discovery-window"
            type="number"
            min="1"
            max="60"
            class="field !w-20"
            [value]="windowSeconds()"
            (input)="windowSeconds.set(number($event))"
          />
        </div>
        <div>
          <label class="label" for="discovery-min">Ignore states under</label>
          <input
            id="discovery-min"
            type="number"
            min="1"
            max="120"
            class="field !w-20"
            [value]="minSeconds()"
            (input)="minSeconds.set(number($event))"
          />
        </div>
        <div>
          <span class="label">Draw</span>
          <div class="flex gap-1">
            <button
              type="button"
              class="btn"
              [class.!bg-emerald-600]="view() === 'time'"
              [class.!text-white]="view() === 'time'"
              (click)="view.set('time')"
            >
              Traces
            </button>
            <button
              type="button"
              class="btn"
              [class.!bg-emerald-600]="view() === 'spectrum'"
              [class.!text-white]="view() === 'spectrum'"
              (click)="view.set('spectrum')"
            >
              Spectra
            </button>
          </div>
        </div>
        @if (loading()) {
          <span class="badge badge-idle ml-auto">analysing…</span>
        } @else if (result(); as data) {
          <span class="badge badge-idle ml-auto">
            {{ data.classes.length }} state(s) · {{ data.freqs.length }} bins
          </span>
        }
      </section>

      <!-- ------------------------------------------------------- which instances -->
      <section class="mb-3 grid gap-3 lg:grid-cols-2">
        @for (group of groups(); track group.label) {
          <div class="panel px-3 py-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="h-2.5 w-2.5 rounded-full" [style.background]="group.colour"></span>
              <h3 class="text-sm font-semibold text-slate-100">{{ group.label }}</h3>
              <span class="badge badge-idle">{{ group.instances.length }} instance(s)</span>
              <div class="ml-auto flex gap-1">
                <button
                  type="button"
                  class="btn btn-ghost !px-2 !py-0.5 !text-[11px]"
                  (click)="selectAll(group.label, true)"
                >
                  all
                </button>
                <button
                  type="button"
                  class="btn btn-ghost !px-2 !py-0.5 !text-[11px]"
                  (click)="selectAll(group.label, false)"
                >
                  none
                </button>
              </div>
            </div>
            <div class="mt-2 flex flex-wrap gap-1">
              @for (instance of group.instances; track instance.index) {
                <button
                  type="button"
                  class="badge cursor-pointer"
                  [class.badge-ok]="isChosen(group.label, instance.index)"
                  [title]="
                    'cycle ' + (instance.cycle + 1) + ' · ' + instance.duration.toFixed(1) + ' s'
                  "
                  (click)="toggleInstance(group.label, instance.index)"
                >
                  #{{ instance.index }} · {{ instance.duration.toFixed(1) }}s
                </button>
              }
            </div>
          </div>
        }
      </section>

      <!-- ------------------------------------------------------------- overlay -->
      <section class="panel mb-3 p-3">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <h3 class="label mb-0">
            {{
              view() === 'time'
                ? 'Each state drawn from its own start'
                : 'Spectra, with each state’s spread'
            }}
          </h3>
          <span class="text-[11px] text-slate-500">
            @if (view() === 'time') {
              Where the traces sit on top of each other, the state is doing the same thing.
            } @else {
              A mean alone invites reading a difference into curves that are inside each other's
              band. The band is the honest part.
            }
          </span>
        </div>
        <div class="h-72 overflow-hidden rounded-lg">
          @if (view() === 'time') {
            <eeg-trace-overlay
              [traces]="traces()"
              [sampleRate]="result()?.fs ?? 128"
              [fullScaleUv]="100"
            />
          } @else {
            <eeg-spectrum-overlay
              [freqs]="result()?.freqs ?? []"
              [series]="spectrumSeries()"
              [shared]="comparison()?.shared ?? []"
              [highlight]="highlightBins()"
              [showInstances]="true"
            />
          }
        </div>
      </section>

      <!-- ------------------------------------------------------- the difference -->
      @if (comparison(); as cmp) {
        <section class="panel mb-3 p-3">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <h3 class="label mb-0">Difference per frequency bin</h3>
            <span class="badge" [class]="cmp.reliable ? 'badge-idle' : 'badge-warn'">
              {{ cmp.label_a }} vs {{ cmp.label_b }}
            </span>
            <span class="text-[11px] text-slate-500">
              measured in units of each state's own spread, so 1.0 means "as big as the scatter"
            </span>
          </div>
          <div class="h-56 overflow-hidden rounded-lg">
            <eeg-effect-chart
              [freqs]="cmp.freqs"
              [effect]="cmp.effect"
              [shared]="cmp.shared"
              [sharedThreshold]="1"
              [nullP95]="cmp.null_p95_effect"
              [labelA]="cmp.label_a"
              [labelB]="cmp.label_b"
            />
          </div>

          <!-- ------------------------------------------------------- findings -->
          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <div class="panel-tight px-3 py-2">
              <h4 class="label">Is the biggest difference more than luck?</h4>
              @if (!cmp.reliable) {
                <p class="text-sm text-amber-300">
                  One of the two states has a single instance, so there is no spread to compare
                  against. Record at least two of each and try again.
                </p>
              } @else {
                <p class="text-sm text-slate-200">
                  Largest difference
                  <span class="mono text-emerald-300">{{
                    cmp.observed_max_effect.toFixed(2)
                  }}</span>
                  at
                  <span class="mono">{{ bestFrequency(cmp) }} Hz</span>.
                </p>
                @if (cmp.p_value !== null) {
                  <p class="mt-1 text-sm text-slate-300">
                    Shuffling the state labels reaches that or more in
                    <span class="mono">{{ (cmp.p_value * 100).toFixed(1) }}%</span> of
                    {{ cmp.permutations }} trials (chance alone reaches
                    <span class="mono">{{ cmp.null_p95_effect.toFixed(2) }}</span
                    >).
                  </p>
                  @if (cmp.p_value > 0.05 && (cmp.min_attainable_p ?? 0) > 0.05) {
                    <p class="mt-2 text-xs text-amber-300">
                      With {{ cmp.n_a }} and {{ cmp.n_b }} instances there are only
                      {{ waysToSplit(cmp) }} ways to split them, so nothing this test could produce
                      would come out below
                      <span class="mono">{{ ((cmp.min_attainable_p ?? 0) * 100).toFixed(1) }}%</span
                      >. The sample is too small to conclude anything either way — record more
                      states.
                    </p>
                  }
                }
              }
            </div>

            <div class="panel-tight px-3 py-2">
              <h4 class="label">Could a simple rule tell them apart?</h4>
              @if (cmp.separability.available) {
                <p class="text-sm text-slate-200">
                  Nearest-centroid, leaving each state out in turn, using the
                  {{ cmp.separability.bins_used.length }} most different frequency bins:
                  <span class="mono text-emerald-300">
                    {{ percent(cmp.separability.accuracy_top_bins) }}
                  </span>
                  of {{ cmp.separability.n_test }} states correct.
                </p>
                <p class="mt-1 text-xs text-slate-400">
                  Using all {{ cmp.freqs.length }} bins instead:
                  <span class="mono">{{ percent(cmp.separability.accuracy_all_bins) }}</span
                  >. Chance is 50%. {{ cmp.separability.n_test }} states is a handful — this is a
                  hint about which frequencies carry the difference, not a validated classifier.
                </p>
                <p class="mt-1 text-[11px] text-slate-500">
                  Bins used: {{ cmp.separability.bins_used.join(', ') }} Hz
                </p>
              } @else {
                <p class="text-sm text-slate-400">
                  Not enough states, or too few instances per state, to hold any out.
                </p>
              }
            </div>
          </div>

          <!-- --------------------------------------------------------- shared -->
          <div class="panel-tight mt-3 px-3 py-2">
            <h4 class="label">What both states have in common</h4>
            <p class="text-sm text-slate-200">
              <span class="mono text-slate-100">{{ cmp.shared_count }}</span> of
              {{ cmp.shared.length }} frequency bins (<span class="mono"
                >{{ (cmp.shared_fraction * 100).toFixed(0) }}%</span
              >) are the same in both: the difference there is smaller than the states' own spread.
            </p>
            <p class="mt-1 text-xs text-slate-400">
              Those bins cannot explain the difference, however much the two curves appear to wiggle
              in them. If a promising-looking band is listed here, it is not the signal.
              @if (cmp.shared_band_names.length) {
                Wholly shared bands:
                <span class="text-slate-300">{{ cmp.shared_band_names.join(', ') }}</span
                >.
              } @else {
                No band is wholly shared.
              }
            </p>
            <div class="mt-2 flex flex-wrap gap-1">
              @for (bin of cmp.shared_bins; track bin.frequency) {
                <span class="badge badge-idle mono">{{ bin.frequency }} Hz</span>
              }
            </div>
          </div>

          <!-- ----------------------------------------------------- which bins -->
          <div class="mt-3 grid gap-3 lg:grid-cols-2">
            <div class="overflow-hidden rounded-lg border border-slate-800">
              <table class="w-full text-xs">
                <thead class="bg-slate-900/70 text-slate-400">
                  <tr>
                    <th class="px-3 py-1.5 text-left font-medium">where they differ</th>
                    <th class="px-3 py-1.5 text-right font-medium">Hz</th>
                    <th class="px-3 py-1.5 text-right font-medium">effect</th>
                    <th class="px-3 py-1.5 text-right font-medium">{{ cmp.label_a }}</th>
                    <th class="px-3 py-1.5 text-right font-medium">{{ cmp.label_b }}</th>
                  </tr>
                </thead>
                <tbody class="mono">
                  @for (bin of cmp.top_bins; track bin.frequency) {
                    <tr class="border-t border-slate-800/60">
                      <td class="px-3 py-1">
                        <span
                          class="badge"
                          [class.badge-ok]="!bin.shared"
                          [class.badge-idle]="bin.shared"
                          >{{ bin.shared ? 'shared' : 'differs' }}</span
                        >
                      </td>
                      <td class="px-3 py-1 text-right text-slate-200">{{ bin.frequency }}</td>
                      <td class="px-3 py-1 text-right">{{ bin.effect.toFixed(2) }}</td>
                      <td class="px-3 py-1 text-right text-slate-400">
                        {{ bin.mean_a.toFixed(2) }}
                      </td>
                      <td class="px-3 py-1 text-right text-slate-400">
                        {{ bin.mean_b.toFixed(2) }}
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>

            <div class="overflow-hidden rounded-lg border border-slate-800">
              <table class="w-full text-xs">
                <thead class="bg-slate-900/70 text-slate-400">
                  <tr>
                    <th class="px-3 py-1.5 text-left font-medium">electrode</th>
                    <th class="px-3 py-1.5 text-right font-medium">largest effect</th>
                    <th class="px-3 py-1.5 text-right font-medium">at</th>
                    <th class="px-3 py-1.5 text-right font-medium"></th>
                  </tr>
                </thead>
                <tbody class="mono">
                  @for (rank of result()?.channel_ranking ?? []; track rank.channel) {
                    <tr
                      class="cursor-pointer border-t border-slate-800/60 hover:bg-slate-800/40"
                      [class.!bg-emerald-950]="rank.channel === channel()"
                      (click)="channel.set(rank.channel)"
                    >
                      <td class="px-3 py-1 font-semibold text-slate-200">{{ rank.channel }}</td>
                      <td class="px-3 py-1 text-right">{{ rank.max_effect.toFixed(2) }}</td>
                      <td class="px-3 py-1 text-right text-slate-400">
                        {{ rank.best_frequency }} Hz
                      </td>
                      <td class="px-3 py-1 text-right">
                        @if (rank.channel === channel()) {
                          <span class="badge badge-ok">shown</span>
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </div>
        </section>
      }

      <!-- ------------------------------------------------------------ repeat](#) -->
      <section class="mb-3 grid gap-3 lg:grid-cols-2">
        @for (group of groups(); track group.label) {
          <div class="panel px-3 py-2">
            <div class="flex items-center gap-2">
              <span class="h-2.5 w-2.5 rounded-full" [style.background]="group.colour"></span>
              <h3 class="text-sm font-semibold text-slate-100">{{ group.label }}</h3>
              @if (summaryFor(group.label); as summary) {
                <span
                  class="badge"
                  [class]="
                    summary.reliability === 'ok'
                      ? 'badge-ok'
                      : summary.reliability === 'thin'
                        ? 'badge-warn'
                        : 'badge-bad'
                  "
                  >{{ summary.n }} instance(s) · {{ summary.reliability }}</span
                >
              }
            </div>
            @if (summaryFor(group.label); as summary) {
              <p class="mt-1 text-xs text-slate-300">
                @if (summary.n > 1) {
                  Across the whole spectrum the instances repeat at
                  <span class="mono">{{ percent(summary.mean_stability) }}</span
                  >, with a typical spread of
                  <span class="mono">{{ summary.median_sd }}</span> decades of power between them.
                } @else {
                  One instance: nothing to compare it with, so nothing here can be called
                  repeatable.
                }
              </p>
              <p class="mt-1 text-[11px] text-slate-500">
                Per-frequency repeatability is the green shading behind the curves — a bin where the
                band is wide is one this state does not pin down.
              </p>
            }
          </div>
        }
      </section>

      <!-- ------------------------------------------------------------ excluded -->
      @if (result()?.excluded?.length) {
        <section class="panel px-3 py-2 text-xs">
          <h4 class="label">Left out of the analysis</h4>
          <ul class="space-y-0.5 text-slate-400">
            @for (item of result()!.excluded; track item.index) {
              <li>
                <span class="mono">#{{ item.index }}</span> {{ item.label }} ·
                {{ item.duration.toFixed(1) }} s — {{ item.reason }}
              </li>
            }
          </ul>
        </section>
      }
    }
  `,
})
export class DiscoveryPanel {
  private readonly api = inject(Api);

  readonly entryId = input.required<string>();

  protected readonly segments = signal<Segment[]>([]);
  protected readonly result = signal<Discovery | null>(null);
  protected readonly channel = signal('O1');
  protected readonly labelA = signal<string | null>(null);
  protected readonly labelB = signal<string | null>(null);
  protected readonly selected = signal<Record<string, number[]>>({});
  protected readonly windowSeconds = signal(6);
  protected readonly minSeconds = signal(2);
  protected readonly permutations = signal(200);
  protected readonly view = signal<'time' | 'spectrum'>('spectrum');
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);

  /** Every label in the dataset, in the order the states appear. */
  protected readonly labels = computed(() => {
    const seen: string[] = [];
    for (const segment of this.segments()) {
      if (!seen.includes(segment.label)) seen.push(segment.label);
    }
    return seen;
  });

  protected readonly groups = computed(() =>
    this.labels().map((label, index) => ({
      label,
      colour: index === 0 ? COLOUR_A : COLOUR_B,
      instances: this.segments().filter((segment) => segment.label === label),
    })),
  );

  protected readonly comparison = computed<Comparison | null>(
    () => this.result()?.comparison ?? null,
  );

  /** Colours for the overlay, in palette order so each instance is tellable apart. */
  private readonly instanceColour = computed(() => {
    const map = new Map<number, string>();
    this.groups().forEach((group, groupIndex) => {
      const palette = groupIndex === 0 ? PALETTE_A : PALETTE_B;
      group.instances.forEach((segment, index) => {
        map.set(segment.index, palette[index % palette.length]);
      });
    });
    return map;
  });

  protected readonly traces = computed<OverlayTrace[]>(() => {
    const data = this.result();
    if (!data) return [];
    const colours = this.instanceColour();
    return data.classes.flatMap((entry) =>
      entry.instances.map((instance) => ({
        label: `${instance.label} #${instance.index}`,
        colour: colours.get(instance.index) ?? COLOUR_A,
        values: instance.trace,
        step: instance.trace_step,
      })),
    );
  });

  protected readonly spectrumSeries = computed<OverlaySeries[]>(() => {
    const data = this.result();
    if (!data) return [];
    return data.classes.map((entry, index) => ({
      label: entry.label,
      colour: index === 0 ? COLOUR_A : COLOUR_B,
      instances: entry.instances.map((instance) => instance.log_power),
      mean: entry.summary.mean,
      sd: entry.summary.sd,
    }));
  });

  protected readonly highlightBins = computed(() => {
    const comparison = this.comparison();
    if (!comparison) return [];
    return comparison.separability.bins_used;
  });

  private loadedFor = '';

  constructor() {
    // Load the state list whenever the dataset changes, then pick the two most obvious
    // states to compare and select every instance of both.
    effect(() => {
      const id = this.entryId();
      if (!id || id === this.loadedFor) return;
      this.loadedFor = id;
      void this.loadSegments(id);
    });

    // Re-analyse on any change of what or how to compare, debounced so that ticking five
    // instance chips is one request rather than five.
    effect((onCleanup) => {
      const request = {
        id: this.entryId(),
        channel: this.channel(),
        labels: [this.labelA(), this.labelB()],
        selected: this.selected(),
        window: this.windowSeconds(),
        min: this.minSeconds(),
      };
      const timer = setTimeout(() => void this.analyse(request), 300);
      onCleanup(() => clearTimeout(timer));
    });
  }

  private async loadSegments(id: string): Promise<void> {
    try {
      const segments = await this.api.segments(id);
      this.segments.set(segments);
      const labels = this.labels();
      this.labelA.set(labels[0] ?? null);
      this.labelB.set(labels[1] ?? null);
      const chosen: Record<string, number[]> = {};
      for (const label of labels) {
        chosen[label] = segments
          .filter((segment) => segment.label === label)
          .map((segment) => segment.index);
      }
      this.selected.set(chosen);
    } catch (error) {
      this.error.set(errorMessage(error));
    }
  }

  private async analyse(request: {
    id: string;
    channel: string;
    labels: (string | null)[];
    selected: Record<string, number[]>;
    window: number;
    min: number;
  }): Promise<void> {
    const labels = request.labels.filter((label): label is string => Boolean(label));
    if (!request.id || labels.length === 0) {
      this.result.set(null);
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    try {
      const instances: Record<string, number[]> = {};
      for (const label of labels) instances[label] = request.selected[label] ?? [];
      this.result.set(
        await this.api.discover(request.id, {
          channel: request.channel,
          labels,
          instances,
          window_seconds: request.window,
          min_seconds: request.min,
          permutations: this.permutations(),
        }),
      );
    } catch (error) {
      this.error.set(errorMessage(error));
      this.result.set(null);
    } finally {
      this.loading.set(false);
    }
  }

  // ------------------------------------------------------------------ editing
  protected isChosen(label: string, index: number): boolean {
    return (this.selected()[label] ?? []).includes(index);
  }

  protected toggleInstance(label: string, index: number): void {
    this.selected.update((current) => {
      const chosen = current[label] ?? [];
      return {
        ...current,
        [label]: chosen.includes(index)
          ? chosen.filter((value) => value !== index)
          : [...chosen, index].sort((a, b) => a - b),
      };
    });
  }

  protected selectAll(label: string, on: boolean): void {
    this.selected.update((current) => ({
      ...current,
      [label]: on
        ? this.segments()
            .filter((segment) => segment.label === label)
            .map((segment) => segment.index)
        : [],
    }));
  }

  // ------------------------------------------------------------------ helpers
  protected summaryFor(label: string) {
    return this.result()?.classes.find((entry) => entry.label === label)?.summary ?? null;
  }

  protected bestFrequency(comparison: Comparison): number {
    const index = comparison.effect.indexOf(Math.max(...comparison.effect));
    return comparison.freqs[index] ?? 0;
  }

  /** The p-value is a rank among the ways the instances can be split. */
  protected waysToSplit(comparison: Comparison): number {
    const floor = comparison.min_attainable_p;
    if (!floor) return 0;
    return Math.round(1 / floor - 1);
  }

  protected percent(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    return `${Math.round(value * 100)}%`;
  }

  protected value(event: Event): string {
    return (event.target as HTMLSelectElement).value;
  }

  protected number(event: Event): number {
    return Number((event.target as HTMLInputElement).value) || 0;
  }

  protected duration(seconds: number): string {
    return humanDuration(seconds);
  }

  protected instanceOf(entry: DiscoveryInstance): number {
    return entry.index;
  }
}
