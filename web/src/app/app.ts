import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { Api } from './core/api/api';
import { EegStream } from './core/eeg/stream';
import { errorMessage, sourceLabel } from './core/format';
import { Speech } from './core/speech/speech';

interface NavItem {
  label: string;
  route: string;
  hint: string;
}

/**
 * The application shell: navigation, the live status strip, and the two switches worth
 * having on every screen — which signal is being read, and whether the voice is on.
 *
 * Both live in the header rather than on a settings page because both change what the
 * data *means*: a monitor showing the demo signal is not showing a brain, and the header
 * says so instead of leaving it to be remembered.
 */
@Component({
  selector: 'eeg-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="flex min-h-screen flex-col">
      <header
        class="flex flex-wrap items-center gap-3 border-b border-slate-800/80 bg-slate-950/80 px-4 py-2.5 backdrop-blur"
      >
        <a routerLink="/" class="flex items-center gap-2 text-slate-100 no-underline">
          <span class="grid h-7 w-7 place-items-center rounded-md bg-emerald-500/15 text-emerald-300">
            <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M2 12h3l2-6 3 12 3-9 2 5h7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span class="text-sm font-semibold tracking-tight">EPOC+ workbench</span>
        </a>

        <nav class="flex flex-wrap items-center gap-0.5">
          @for (item of nav; track item.route) {
            <a
              class="rounded-md px-2.5 py-1.5 text-[13px] font-medium text-slate-400 no-underline transition hover:bg-slate-800/60 hover:text-slate-100"
              routerLinkActive="!bg-slate-800 !text-emerald-300"
              [routerLinkActiveOptions]="{ exact: item.route === '/' }"
              [routerLink]="item.route"
              [title]="item.hint"
              >{{ item.label }}</a
            >
          }
        </nav>

        <div class="ml-auto flex flex-wrap items-center gap-2">
          <!-- Which signal are we actually reading? -->
          <div class="flex items-center gap-1 rounded-lg border border-slate-700/60 bg-slate-900/60 p-0.5">
            <button
              type="button"
              class="btn btn-ghost !px-2 !py-1"
              [class.!bg-emerald-600]="stream.sourceStats()?.mode === 'live'"
              [class.!text-white]="stream.sourceStats()?.mode === 'live'"
              [disabled]="busy()"
              (click)="useSource('live')"
              title="Read the Emotiv dongle"
            >
              Dongle
            </button>
            <button
              type="button"
              class="btn btn-ghost !px-2 !py-1"
              [class.!bg-sky-600]="stream.sourceStats()?.mode === 'demo'"
              [class.!text-white]="stream.sourceStats()?.mode === 'demo'"
              [disabled]="busy()"
              (click)="useSource('demo')"
              title="Generate a synthetic signal — no headset needed"
            >
              Demo
            </button>
            <button
              type="button"
              class="btn btn-ghost !px-2 !py-1"
              [disabled]="busy() || stream.sourceStats()?.mode === 'idle'"
              (click)="useSource('idle')"
              title="Stop reading"
            >
              Stop
            </button>
          </div>

          <span class="badge" [class]="'badge-' + linkTone()">
            <span class="h-1.5 w-1.5 rounded-full" [style.background]="linkColor()"></span>
            {{ linkLabel() }}
          </span>

          <button
            type="button"
            class="btn btn-ghost !px-2"
            [title]="speech.supported() ? 'Voice prompts' : 'This browser has no speech synthesis'"
            [disabled]="!speech.supported()"
            (click)="speech.toggle()"
          >
            {{ speech.muted() ? '🔇' : '🔊' }}
          </button>
        </div>
      </header>

      @if (banner(); as message) {
        <div class="border-b border-rose-900/60 bg-rose-950/50 px-4 py-2 text-xs text-rose-200">
          {{ message }}
        </div>
      }

      <main class="flex-1 px-4 py-4">
        <router-outlet />
      </main>

      <footer class="border-t border-slate-800/80 px-4 py-2 text-[11px] text-slate-500">
        Raw EEG read directly from the dongle — no Emotiv software or licence. Recordings are
        biometric data: they stay in <span class="mono">recordings/</span>, which is git-ignored.
      </footer>
    </div>
  `,
})
export class App {
  protected readonly stream = inject(EegStream);
  protected readonly speech = inject(Speech);
  private readonly api = inject(Api);

  protected readonly busy = signal(false);
  protected readonly banner = signal<string | null>(null);

  protected readonly nav: NavItem[] = [
    { label: 'Monitor', route: '/', hint: 'Live signal, contact quality and alpha' },
    { label: 'Channels', route: '/channels', hint: 'What each of the 14 electrodes is for' },
    { label: 'Protocols', route: '/flows', hint: 'Build a guided protocol' },
    { label: 'Run', route: '/run', hint: 'Run a protocol and record a dataset' },
    { label: 'Datasets', route: '/datasets', hint: 'Everything recorded so far' },
  ];

  protected readonly linkTone = computed(() => {
    if (this.stream.connected()) return this.stream.streaming() ? 'ok' : 'warn';
    return 'bad';
  });

  protected readonly linkColor = computed(() => {
    if (this.stream.connected()) return this.stream.streaming() ? '#10b981' : '#f59e0b';
    return '#f43f5e';
  });

  protected readonly linkLabel = computed(() => {
    const stats = this.stream.sourceStats();
    if (!this.stream.connected()) return this.stream.connecting() ? 'connecting…' : 'no link';
    if (!stats || stats.mode === 'idle') return 'idle';
    return `${sourceLabel(stats.mode)} · ${stats.samples} samples`;
  });

  protected async useSource(mode: 'live' | 'demo' | 'idle'): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.banner.set(null);
    try {
      const status = await this.api.setSource({ mode });
      if (mode !== 'idle' && status.source === 'idle') {
        // The request succeeded but nothing started: the dongle is not attached, or the
        // recording is gone. The server's reason is the useful part.
        this.banner.set(status.error ?? `No ${mode} source is available.`);
      }
    } catch (error) {
      this.banner.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }
}
