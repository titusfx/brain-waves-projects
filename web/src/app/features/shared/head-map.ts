import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import type { ChannelDoc } from '../../core/api/models';
import type { ChannelMetrics } from '../../core/eeg/messages';
import { statusColor } from '../../core/format';

interface Dot {
  name: string;
  px: number;
  py: number;
  fill: string;
  status: string;
  amplitude: number | null;
  active: boolean;
}

/**
 * A top-down 10-20 map of the montage.
 *
 * Positions come from the backend's channel catalog, not from a hard-coded table here:
 * the catalog is validated against the packet layout at startup, so if a documented
 * position ever disagrees with the hardware the API refuses to boot rather than this
 * picture quietly lying about where an electrode is.
 *
 * Coloured by contact verdict, so the fastest way to find the dry pad is to look at it.
 */
@Component({
  selector: 'eeg-head-map',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg viewBox="-118 -118 236 236" class="h-auto w-full select-none" role="img"
         aria-label="Top-down map of the 14 electrode positions">
      <!-- skull -->
      <circle cx="0" cy="0" r="100" fill="rgb(15 23 42 / 0.5)" stroke="#475569" stroke-width="2" />
      <!-- nose (anterior is up) -->
      <path d="M -13 -99 L 0 -117 L 13 -99" fill="none" stroke="#475569" stroke-width="2" />
      <!-- ears -->
      <path d="M -100 -20 q -15 20 0 40" fill="none" stroke="#475569" stroke-width="2" />
      <path d="M 100 -20 q 15 20 0 40" fill="none" stroke="#475569" stroke-width="2" />
      <!-- midline -->
      <line x1="0" y1="-99" x2="0" y2="99" stroke="#334155" stroke-width="1" stroke-dasharray="3 5" />
      <line x1="-99" y1="0" x2="99" y2="0" stroke="#334155" stroke-width="1" stroke-dasharray="3 5" />

      @for (dot of dots(); track dot.name) {
        <g
          class="cursor-pointer"
          (click)="pick.emit(dot.name)"
          (keydown.enter)="pick.emit(dot.name)"
          (keydown.space)="pick.emit(dot.name)"
          tabindex="0"
          role="button"
          [attr.aria-label]="dot.name + ' — ' + dot.status"
        >
          @if (dot.active) {
            <circle [attr.cx]="dot.px" [attr.cy]="dot.py" r="17" fill="none" stroke="#6ee7b7" stroke-width="2" />
          }
          <circle
            [attr.cx]="dot.px"
            [attr.cy]="dot.py"
            r="12"
            [attr.fill]="dot.fill"
            [attr.fill-opacity]="dot.status === 'ok' ? 0.85 : 0.75"
            stroke="#020617"
            stroke-width="1.5"
          />
          <text
            [attr.x]="dot.px"
            [attr.y]="dot.py + 3.5"
            text-anchor="middle"
            font-size="9"
            font-weight="600"
            fill="#020617"
          >{{ dot.name }}</text>
          <title>{{ dot.name }} — {{ dot.status }}{{ dot.amplitude === null ? '' : ' · ' + dot.amplitude + ' µV' }}</title>
        </g>
      }
    </svg>
  `,
})
export class HeadMap {
  readonly docs = input<ChannelDoc[]>([]);
  readonly metrics = input<Map<string, ChannelMetrics>>(new Map());
  readonly selected = input<string | null>(null);
  readonly radius = input(78);
  readonly pick = output<string>();

  protected readonly dots = computed<Dot[]>(() => {
    const metrics = this.metrics();
    const selected = this.selected();
    return this.docs().map((doc) => {
      const metric = metrics.get(doc.name);
      return {
        name: doc.name,
        px: doc.head.x * this.radius(),
        py: -doc.head.y * this.radius(),
        fill: statusColor(metric?.status),
        status: metric?.status ?? 'no data',
        amplitude: metric ? Math.round(metric.amplitude_uv) : null,
        active: selected === doc.name,
      };
    });
  });
}
