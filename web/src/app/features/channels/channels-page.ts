import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { Router } from '@angular/router';

import { Api } from '../../core/api/api';
import type { ChannelCatalog } from '../../core/api/models';
import { EegStream } from '../../core/eeg/stream';
import type { ChannelMetrics } from '../../core/eeg/messages';
import { bandColor, errorMessage, statusTone } from '../../core/format';
import { ChannelDocPanel } from '../shared/channel-doc';
import { HeadMap } from '../shared/head-map';

/**
 * The channel reference.
 *
 * The point of this screen is that a number on the monitor becomes answerable: *why*
 * is T7 always noisy, *why* is O1 the channel the alpha test reads, *which* pad is the
 * one behind the ear. Each entry says what the site is over, what it is used for, what
 * destroys it, and what a good recording looks like.
 *
 * The selected channel lives in the URL (`/channels?channel=O1`), so it can be linked
 * to — which is the difference between documentation and a thing someone has to be
 * walked through.
 */
@Component({
  selector: 'eeg-channels-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [HeadMap, ChannelDocPanel],
  template: `
    @if (catalog(); as data) {
      <div class="mb-4 grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <section class="panel p-4">
          <h1 class="text-lg font-semibold text-slate-100">{{ data.montage.name }}</h1>
          <p class="mt-0.5 text-xs text-slate-400">
            {{ data.montage.system }} · {{ data.montage.sampling_hz }} Hz ·
            {{ data.montage.scale }}
          </p>
          <p class="mt-2 text-sm text-slate-300">{{ data.montage.summary }}</p>
          <div class="mt-2">
            <eeg-head-map
              [docs]="data.channels"
              [metrics]="metricsMap()"
              [selected]="selected()"
              (pick)="select($event)"
            />
          </div>
        </section>

        <section class="panel p-4">
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <h2 class="label">The two pads that are not channels</h2>
              <p class="text-sm font-medium text-slate-200">{{ data.montage.reference.name }}</p>
              <p class="mt-1 text-sm text-slate-300">{{ data.montage.reference.explanation }}</p>
            </div>
            <div>
              <h2 class="label">What the montage cannot do</h2>
              <p class="text-sm text-slate-300">{{ data.montage.midline_note }}</p>
            </div>
          </div>

          <h2 class="label mt-4">Frequency bands</h2>
          <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            @for (band of data.bands; track band.key) {
              <article class="panel-tight px-3 py-2">
                <div class="flex items-center gap-2">
                  <span class="h-2 w-2 rounded-full" [style.background]="colour(band.key)"></span>
                  <h3 class="text-sm font-semibold text-slate-100">{{ band.name }}</h3>
                  <span class="mono text-xs text-slate-400">{{ band.range }}</span>
                </div>
                <p class="mt-0.5 text-xs text-slate-300">{{ band.summary }}</p>
                <p class="mt-1 text-[11px] text-slate-500">{{ band.note }}</p>
              </article>
            }
          </div>

          <p class="mt-4 text-[11px] text-slate-500">{{ data.disclaimer }}</p>
        </section>
      </div>

      <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
        <section class="panel p-4">
          <h2 class="label">All {{ data.channels.length }} electrodes</h2>
          <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            @for (doc of data.channels; track doc.name) {
              <button
                type="button"
                class="panel-tight cursor-pointer px-3 py-2 text-left transition hover:border-emerald-500/40 hover:bg-slate-800/50"
                [class.!border-emerald-500]="selected() === doc.name"
                (click)="select(doc.name)"
              >
                <div class="flex items-center gap-2">
                  <span class="mono text-sm font-semibold text-slate-100">{{ doc.name }}</span>
                  <span class="text-[11px] text-slate-500">{{ doc.lobe }} · {{ doc.hemisphere }}</span>
                  @if (metricsMap().get(doc.name); as live) {
                    <span class="badge ml-auto" [class]="'badge-' + tone(live.status)">{{
                      live.status
                    }}</span>
                  }
                </div>
                <p class="mt-1 text-xs text-slate-300">{{ doc.summary }}</p>
              </button>
            }
          </div>
        </section>

        <aside class="panel h-fit p-4 xl:sticky xl:top-4">
          <eeg-channel-doc [doc]="selectedDoc()" [metrics]="selectedMetrics()" (pick)="select($event)" />
        </aside>
      </div>
    } @else if (error(); as text) {
      <p class="panel px-4 py-3 text-sm text-rose-300">{{ text }}</p>
    } @else {
      <p class="text-sm text-slate-400">Loading the channel reference…</p>
    }
  `,
})
export class ChannelsPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly stream = inject(EegStream);

  /** Bound from `?channel=O1` by the router's component input binding. */
  readonly channel = input<string>('O1');

  protected readonly catalog = signal<ChannelCatalog | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly selected = computed(() => this.channel().toUpperCase());

  protected readonly metricsMap = computed(() => {
    const map = new Map<string, ChannelMetrics>();
    for (const metric of this.stream.metrics()) map.set(metric.name, metric);
    return map;
  });

  protected readonly selectedDoc = computed(
    () => this.catalog()?.channels.find((doc) => doc.name === this.selected()) ?? null,
  );

  protected readonly selectedMetrics = computed(
    () => this.metricsMap().get(this.selected()) ?? null,
  );

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      this.catalog.set(await this.api.catalog());
    } catch (error) {
      this.error.set(errorMessage(error));
    }
  }

  /** Keep the selection in the URL so the page can be linked to and reloaded. */
  protected select(name: string): void {
    void this.router.navigate([], {
      queryParams: { channel: name },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  protected tone(status: string): string {
    return statusTone(status);
  }

  protected colour(key: string): string {
    return bandColor(key);
  }
}
