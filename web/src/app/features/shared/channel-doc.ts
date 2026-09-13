import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import type { ChannelDoc } from '../../core/api/models';
import type { ChannelMetrics } from '../../core/eeg/messages';
import { bandColor, statusTone } from '../../core/format';

/**
 * The "what does this channel do?" panel.
 *
 * The prose is served by the backend from an authored catalog
 * (`api/src/eeg_api/domain/catalog/channels.yaml`), which is validated against the
 * hardware at startup. Nothing here is generated or guessed, and the panel is careful
 * to describe what a *region* is associated with rather than claiming to decode a
 * thought — the placeholder text says so explicitly, because a UI that looks
 * authoritative is exactly how that mistake gets made.
 */
@Component({
  selector: 'eeg-channel-doc',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (doc(); as channel) {
      <div class="flex flex-col gap-4">
        <header class="flex items-start justify-between gap-3">
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-xl font-semibold text-slate-100">{{ channel.name }}</h2>
              <span class="badge">{{ channel.lobe }} · {{ channel.hemisphere }}</span>
              @if (metrics(); as live) {
                <span class="badge" [class]="'badge-' + toneOf(live.status)">{{ live.status }}</span>
              }
            </div>
            <p class="mt-1 text-sm text-slate-400">{{ channel.region }}</p>
          </div>
          @if (closable()) {
            <button type="button" class="btn btn-ghost" (click)="close.emit()" aria-label="Close">✕</button>
          }
        </header>

        <p class="text-sm text-slate-200">{{ channel.summary }}</p>

        @if (metrics(); as live) {
          <dl class="grid grid-cols-3 gap-2 text-center">
            <div class="panel-tight px-2 py-1.5">
              <dt class="label mb-0">amplitude</dt>
              <dd class="mono text-sm text-slate-100">{{ live.amplitude_uv.toFixed(1) }} µV</dd>
            </div>
            <div class="panel-tight px-2 py-1.5">
              <dt class="label mb-0">now</dt>
              <dd class="mono text-sm text-slate-100">{{ live.current_uv.toFixed(1) }} µV</dd>
            </div>
            <div class="panel-tight px-2 py-1.5">
              <dt class="label mb-0">mains</dt>
              <dd class="mono text-sm text-slate-100">{{ live.mains_percent.toFixed(0) }}%</dd>
            </div>
          </dl>

          @if (bandEntries().length) {
            <div>
              <span class="label">band power (% of 1–45 Hz)</span>
              <div class="flex h-2.5 overflow-hidden rounded-full bg-slate-800">
                @for (band of bandEntries(); track band.key) {
                  <div
                    class="h-full"
                    [style.width.%]="band.value"
                    [style.background]="band.colour"
                    [title]="band.key + ' ' + band.value.toFixed(1) + '%'"
                  ></div>
                }
              </div>
            </div>
          }
        }

        <section>
          <h3 class="label">What it is over</h3>
          <p class="text-sm text-slate-300">{{ channel.placement }}</p>
        </section>

        <section>
          <h3 class="label">Usually associated with</h3>
          <ul class="list-disc space-y-1 pl-5 text-sm text-slate-300">
            @for (item of channel.functions; track item) {
              <li>{{ item }}</li>
            }
          </ul>
        </section>

        <div class="grid gap-4 sm:grid-cols-2">
          <section>
            <h3 class="label">Tasks that engage it</h3>
            <ul class="space-y-1 text-sm text-slate-300">
              @for (item of channel.tasks; track item) {
                <li>· {{ item }}</li>
              }
            </ul>
          </section>
          <section>
            <h3 class="label">What ruins it</h3>
            <ul class="space-y-1 text-sm text-slate-300">
              @for (item of channel.artefacts; track item) {
                <li>· {{ item }}</li>
              }
            </ul>
          </section>
        </div>

        <section class="panel-tight px-3 py-2">
          <h3 class="label">What a good recording looks like</h3>
          <p class="text-sm text-slate-300">{{ channel.expected }}</p>
        </section>

        @if (channel.related.length) {
          <section>
            <h3 class="label">Compare with</h3>
            <div class="flex flex-wrap gap-1.5">
              @for (name of channel.related; track name) {
                <button type="button" class="btn btn-ghost mono" (click)="pick.emit(name)">
                  {{ name }}
                </button>
              }
            </div>
          </section>
        }

        <p class="text-xs text-slate-500">
          Scalp EEG blurs across centimetres: this describes the region an electrode sits over and
          what it is useful for, not a measurement of a thought.
        </p>
      </div>
    } @else {
      <p class="text-sm text-slate-400">Select an electrode on the map to read about it.</p>
    }
  `,
})
export class ChannelDocPanel {
  readonly doc = input<ChannelDoc | null>(null);
  readonly metrics = input<ChannelMetrics | null>(null);
  readonly closable = input(false);
  readonly close = output<void>();
  readonly pick = output<string>();

  protected toneOf(status: string): string {
    return statusTone(status);
  }

  protected bandEntries(): { key: string; value: number; colour: string }[] {
    const bands = this.metrics()?.bands;
    if (!bands) return [];
    return Object.entries(bands).map(([key, value]) => ({
      key,
      value,
      colour: bandColor(key),
    }));
  }
}
