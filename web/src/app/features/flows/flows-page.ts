import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';

import { Api } from '../../core/api/api';
import type { FlowInput, FlowSpec, FlowStepInput, PlanPreview } from '../../core/api/models';
import { errorMessage, humanDuration } from '../../core/format';

/** A blank protocol, matching the backend's own defaults. */
function emptyDraft(): FlowInput {
  return {
    name: '',
    mode: 'linear',
    countdown_seconds: 3,
    repeat: 1,
    rest_seconds: 0,
    discard_tail: null,
    description: '',
    steps: [{ label: '', seconds: 10, speak: null }],
  };
}

/** A saved protocol, as an editable draft. */
function toDraft(spec: FlowSpec): FlowInput {
  return {
    name: spec.name,
    mode: spec.mode,
    countdown_seconds: spec.countdown_seconds,
    repeat: spec.repeat,
    rest_seconds: spec.rest_seconds,
    discard_tail: spec.discard_tail ?? null,
    description: spec.description,
    steps: spec.steps.map((step) => ({
      label: step.label,
      seconds: step.open_ended ? null : step.seconds,
      speak: step.speak,
    })),
  };
}

/**
 * Where protocols are built.
 *
 * The three shapes the operator asked for are all the same form: a countdown, a list of
 * states, and how many times to run them.
 *
 * * **Linear** — each state once, in order: `start with 5, lie down 10, stand up 20`.
 * * **Looping** — the list repeats until stopped: `start with 3, eyes closed 20, eyes
 *   open 15`, over and over.
 * * **Open-ended** — one state, "until I stop": the single-label case.
 *
 * The time is always in seconds here and the countdown is always the "start with" the
 * brief described. What the builder shows *before* saving is the expanded running order,
 * because "repeat 4" is a number and "close 20, open 15, close 20, open 15, …" is what
 * actually happens — and the difference between them is where a mistake would hide.
 */
@Component({
  selector: 'eeg-flows-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
      <!-- --------------------------------------------------------- the list -->
      <aside class="panel h-fit p-3">
        <div class="mb-2 flex items-center justify-between">
          <h1 class="label mb-0">Saved protocols</h1>
          <button
            type="button"
            class="btn btn-ghost !px-2 !py-0.5 !text-[11px]"
            (click)="newFlow()"
          >
            + New
          </button>
        </div>
        @if (flows().length === 0) {
          <p class="text-xs text-slate-500">Nothing saved yet.</p>
        }
        <ul class="flex flex-col gap-1">
          @for (flow of flows(); track flow.id) {
            <li>
              <button
                type="button"
                class="panel-tight w-full cursor-pointer px-2.5 py-2 text-left transition hover:bg-slate-800/50"
                [class.!border-emerald-500]="draft().name === flow.name && editingId() === flow.id"
                (click)="edit(flow)"
              >
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium text-slate-100">{{ flow.name }}</span>
                  <span
                    class="badge ml-auto"
                    [class]="flow.mode === 'loop' ? 'badge-warn' : 'badge-idle'"
                  >
                    {{ flow.mode === 'loop' ? 'loop' : 'linear' }}
                  </span>
                </div>
                <p class="mono mt-0.5 text-[11px] text-slate-500">
                  {{ flow.steps.length }} state(s) ·
                  {{ flow.total_seconds === null ? 'until stopped' : duration(flow.total_seconds) }}
                  @if (flow.cycles !== null && flow.repeat !== null && flow.repeat > 1) {
                    · ×{{ flow.repeat }}
                  }
                </p>
              </button>
            </li>
          }
        </ul>
      </aside>

      <!-- ------------------------------------------------------- the builder -->
      <section class="flex flex-col gap-4">
        <div class="panel p-4">
          <div class="flex flex-wrap items-center gap-3">
            <h2 class="text-sm font-semibold text-slate-100">
              {{ editingId() ? 'Edit protocol' : 'New protocol' }}
            </h2>
            @if (editingId()) {
              <span class="badge badge-idle mono">{{ editingId() }}</span>
            }
            <div class="ml-auto flex gap-2">
              @if (editingId()) {
                <button type="button" class="btn btn-danger" [disabled]="busy()" (click)="remove()">
                  Delete
                </button>
              }
              <button type="button" class="btn" [disabled]="busy()" (click)="saveAsNew()">
                Save as new
              </button>
              <button
                type="button"
                class="btn btn-primary"
                [disabled]="busy() || !valid()"
                (click)="save()"
              >
                {{ editingId() ? 'Save changes' : 'Save' }}
              </button>
              <button
                type="button"
                class="btn"
                [disabled]="busy() || !valid()"
                (click)="run()"
                title="Record a dataset with this protocol"
              >
                Run →
              </button>
            </div>
          </div>

          @if (error(); as text) {
            <p class="mt-3 text-xs text-rose-300">{{ text }}</p>
          }

          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <div class="sm:col-span-2">
              <label class="label" for="flow-name">Name</label>
              <input
                id="flow-name"
                class="field"
                placeholder="Eyes closed / eyes open"
                [value]="draft().name"
                (input)="patch({ name: value($event) })"
              />
            </div>

            <div class="sm:col-span-2">
              <span class="label">Shape</span>
              <div class="flex flex-wrap gap-2">
                <button
                  type="button"
                  class="btn"
                  [class.!bg-emerald-600]="draft().mode === 'linear'"
                  [class.!text-white]="draft().mode === 'linear'"
                  (click)="patch({ mode: 'linear' })"
                >
                  Linear — each state once, in order
                </button>
                <button
                  type="button"
                  class="btn"
                  [class.!bg-emerald-600]="draft().mode === 'loop'"
                  [class.!text-white]="draft().mode === 'loop'"
                  (click)="patch({ mode: 'loop' })"
                >
                  Loop — repeat until you stop
                </button>
              </div>
            </div>

            <div>
              <label class="label" for="flow-countdown"
                >Start with (countdown before recording)</label
              >
              <div class="flex items-center gap-2">
                <input
                  id="flow-countdown"
                  type="number"
                  min="0"
                  max="60"
                  step="1"
                  class="field"
                  [value]="draft().countdown_seconds"
                  (input)="patch({ countdown_seconds: number($event) })"
                />
                <span class="text-xs text-slate-400">seconds, spoken 3-2-1</span>
              </div>
            </div>

            <div>
              <label class="label" for="flow-repeat">
                {{
                  draft().mode === 'loop'
                    ? 'Repeat (blank = until stopped)'
                    : 'Repeat the whole list'
                }}
              </label>
              <input
                id="flow-repeat"
                type="number"
                min="1"
                step="1"
                class="field"
                placeholder="{{ draft().mode === 'loop' ? 'until stopped' : '1' }}"
                [value]="draft().repeat ?? ''"
                (input)="patchRepeat($event)"
              />
            </div>

            <div>
              <label class="label" for="flow-rest"
                >Rest between repetitions (seconds, unlabelled)</label
              >
              <input
                id="flow-rest"
                type="number"
                min="0"
                step="1"
                class="field"
                [value]="draft().rest_seconds"
                (input)="patch({ rest_seconds: number($event) })"
              />
            </div>

            <div>
              <label class="label" for="flow-discard">Discard from the end when stopped</label>
              <input
                id="flow-discard"
                type="number"
                min="0"
                max="20"
                step="1"
                class="field"
                placeholder="{{
                  draft().mode === 'loop' ? '2 (the interrupted state + the one before it)' : '0'
                }}"
                [value]="draft().discard_tail ?? ''"
                (input)="patchDiscard($event)"
              />
            </div>

            <div class="sm:col-span-2">
              <label class="label" for="flow-description">Notes</label>
              <textarea
                id="flow-description"
                rows="2"
                class="field"
                placeholder="What this protocol is for, and what the subject should do."
                [value]="draft().description"
                (input)="patch({ description: value($event) })"
              ></textarea>
            </div>
          </div>
        </div>

        <!-- --------------------------------------------------------- states -->
        <div class="panel p-4">
          <div class="flex items-center gap-3">
            <h2 class="text-sm font-semibold text-slate-100">States</h2>
            <p class="text-xs text-slate-400">
              In order. Leave the duration blank for "until I stop" — allowed only as the last
              state.
            </p>
            <button
              type="button"
              class="btn btn-ghost ml-auto !text-xs"
              (click)="addStep()"
              [disabled]="draft().steps.length >= 64"
            >
              + Add state
            </button>
          </div>

          <ol class="mt-3 flex flex-col gap-2">
            @for (step of draft().steps; track $index) {
              <li class="panel-tight flex flex-wrap items-end gap-2 px-3 py-2">
                <span class="mono mb-1.5 w-6 text-xs text-slate-500">{{ $index + 1 }}</span>
                <div class="min-w-[180px] flex-1">
                  <label class="label" [attr.for]="'step-label-' + $index"
                    >Name (also spoken)</label
                  >
                  <input
                    [id]="'step-label-' + $index"
                    class="field"
                    placeholder="close your eyes"
                    [value]="step.label"
                    (input)="patchStep($index, { label: value($event) })"
                  />
                </div>
                <div class="w-28">
                  <label class="label" [attr.for]="'step-seconds-' + $index">Seconds</label>
                  <input
                    [id]="'step-seconds-' + $index"
                    type="number"
                    min="0.1"
                    step="1"
                    class="field"
                    placeholder="until stop"
                    [disabled]="step.seconds === null"
                    [value]="step.seconds ?? ''"
                    (input)="patchStep($index, { seconds: number($event) })"
                  />
                </div>
                <div class="w-44">
                  <label class="label" [attr.for]="'step-speak-' + $index">Say instead</label>
                  <input
                    [id]="'step-speak-' + $index"
                    class="field"
                    placeholder="(the name)"
                    [value]="step.speak ?? ''"
                    (input)="patchStep($index, { speak: value($event) || null })"
                  />
                </div>
                <label class="mb-1.5 flex items-center gap-1.5 text-xs text-slate-300">
                  <input
                    type="checkbox"
                    [checked]="step.seconds === null"
                    (change)="toggleOpenEnded($index)"
                  />
                  until stopped
                </label>
                <div class="mb-1 flex gap-1">
                  <button
                    type="button"
                    class="btn btn-ghost !px-1.5 !py-0.5"
                    [disabled]="$index === 0"
                    (click)="moveStep($index, -1)"
                    aria-label="Move up"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    class="btn btn-ghost !px-1.5 !py-0.5"
                    [disabled]="$index === draft().steps.length - 1"
                    (click)="moveStep($index, 1)"
                    aria-label="Move down"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    class="btn btn-ghost !px-1.5 !py-0.5"
                    [disabled]="draft().steps.length <= 1"
                    (click)="removeStep($index)"
                    aria-label="Remove state"
                  >
                    ✕
                  </button>
                </div>
              </li>
            }
          </ol>
        </div>

        <!-- -------------------------------------------------------- preview -->
        <div class="panel p-4">
          <div class="flex flex-wrap items-center gap-3">
            <h2 class="text-sm font-semibold text-slate-100">What it will actually do</h2>
            @if (preview(); as plan) {
              <span class="badge badge-idle">
                {{ plan.total_seconds === null ? 'open-ended' : duration(plan.total_seconds) }}
              </span>
              @if (plan.discard_tail > 0) {
                <span class="badge badge-warn">
                  a manual stop drops the last {{ plan.discard_tail }} state(s)
                </span>
              }
            }
          </div>

          @if (validation(); as check) {
            @if (check.errors.length) {
              <ul class="mt-3 space-y-1 text-xs text-rose-300">
                @for (message of check.errors; track message) {
                  <li>✕ {{ message }}</li>
                }
              </ul>
            }
            @if (check.warnings.length) {
              <ul class="mt-3 space-y-1 text-xs text-amber-300">
                @for (message of check.warnings; track message) {
                  <li>! {{ message }}</li>
                }
              </ul>
            }
            @if (check.valid && !check.warnings.length) {
              <p class="mt-2 text-xs text-emerald-300">This protocol is valid.</p>
            }
          }

          @if (preview(); as plan) {
            <ol class="mt-3 flex flex-wrap gap-1.5">
              @for (phase of plan.phases; track $index) {
                <li
                  class="rounded-md border px-2 py-1 text-[11px]"
                  [class]="
                    phase.kind === 'countdown'
                      ? 'border-slate-600 bg-slate-800/60 text-slate-300'
                      : phase.kind === 'rest'
                        ? 'border-slate-700 bg-slate-900/60 text-slate-500'
                        : 'border-emerald-600/50 bg-emerald-950/40 text-emerald-200'
                  "
                >
                  <span class="font-medium">{{ phase.label }}</span>
                  <span class="mono ml-1 text-slate-400">
                    {{ phase.duration === null ? '∞' : phase.duration + 's' }}
                  </span>
                </li>
              }
              @if (plan.truncated) {
                <li class="px-2 py-1 text-[11px] text-slate-500">… and on</li>
              }
            </ol>
          }
        </div>
      </section>
    </div>
  `,
})
export class FlowsPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  /** Route data: `/flows/new` starts on a blank draft. `undefined` on `/flows`. */
  readonly fresh = input<boolean | undefined>(undefined);

  protected readonly flows = signal<FlowSpec[]>([]);
  protected readonly editingId = signal<string | null>(null);
  protected readonly draft = signal<FlowInput>(emptyDraft());
  protected readonly preview = signal<PlanPreview | null>(null);
  protected readonly validation = signal<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly valid = computed(() => this.validation()?.valid ?? false);

  constructor() {
    void this.load();
    // Re-check as the operator types, debounced: the preview is the point of this
    // screen, and a preview that lags a keystroke behind is a preview nobody reads.
    effect((onCleanup) => {
      const input = this.draft();
      const timer = setTimeout(() => void this.check(input), 250);
      onCleanup(() => clearTimeout(timer));
    });
  }

  private async load(): Promise<void> {
    try {
      const flows = await this.api.flows();
      this.flows.set(flows);
      if (!this.fresh() && flows.length > 0) this.edit(flows[0]);
    } catch (error) {
      this.error.set(errorMessage(error));
    }
  }

  private async check(input: FlowInput): Promise<void> {
    try {
      const [validation, preview] = await Promise.all([
        this.api.validateFlow(input),
        this.api.previewFlow(input).catch(() => null),
      ]);
      this.validation.set(validation);
      this.preview.set(preview);
    } catch (error) {
      this.validation.set({ valid: false, errors: [errorMessage(error)], warnings: [] });
      this.preview.set(null);
    }
  }

  // ------------------------------------------------------------------ editing
  protected edit(flow: FlowSpec): void {
    this.editingId.set(flow.id);
    this.draft.set(toDraft(flow));
    this.error.set(null);
  }

  protected newFlow(): void {
    this.editingId.set(null);
    this.draft.set(emptyDraft());
    this.error.set(null);
  }

  protected patch(changes: Partial<FlowInput>): void {
    this.draft.update((draft) => ({ ...draft, ...changes }));
  }

  protected patchRepeat(event: Event): void {
    const raw = (event.target as HTMLInputElement).value.trim();
    this.patch({ repeat: raw === '' ? null : Math.max(1, Number(raw) || 1) });
  }

  protected patchDiscard(event: Event): void {
    const raw = (event.target as HTMLInputElement).value.trim();
    this.patch({ discard_tail: raw === '' ? null : Math.max(0, Number(raw) || 0) });
  }

  protected patchStep(index: number, changes: Partial<FlowStepInput>): void {
    this.draft.update((draft) => ({
      ...draft,
      steps: draft.steps.map((step, i) => (i === index ? { ...step, ...changes } : step)),
    }));
  }

  protected toggleOpenEnded(index: number): void {
    const step = this.draft().steps[index];
    this.patchStep(index, { seconds: step.seconds === null ? 10 : null });
  }

  protected addStep(): void {
    this.draft.update((draft) => ({
      ...draft,
      steps: [...draft.steps, { label: '', seconds: 10, speak: null }],
    }));
  }

  protected removeStep(index: number): void {
    this.draft.update((draft) => ({
      ...draft,
      steps: draft.steps.filter((_, i) => i !== index),
    }));
  }

  protected moveStep(index: number, delta: number): void {
    this.draft.update((draft) => {
      const steps = [...draft.steps];
      const target = index + delta;
      if (target < 0 || target >= steps.length) return draft;
      [steps[index], steps[target]] = [steps[target], steps[index]];
      return { ...draft, steps };
    });
  }

  // ------------------------------------------------------------------- saving
  protected async save(): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      const draft = this.draft();
      const saved = this.editingId()
        ? await this.api.updateFlow(this.editingId() as string, draft)
        : await this.api.createFlow(draft);
      this.editingId.set(saved.id);
      this.flows.set(await this.api.flows());
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected async saveAsNew(): Promise<void> {
    this.editingId.set(null);
    await this.save();
  }

  protected async remove(): Promise<void> {
    const id = this.editingId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.api.deleteFlow(id);
      this.flows.set(await this.api.flows());
      this.newFlow();
    } catch (error) {
      this.error.set(errorMessage(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected async run(): Promise<void> {
    // Save first so the run page has a real protocol to start, then hand over.
    await this.save();
    if (this.error()) return;
    await this.router.navigate(['/run'], { queryParams: { flow: this.editingId() } });
  }

  // ------------------------------------------------------------------ helpers
  protected value(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement).value;
  }

  protected number(event: Event): number {
    return Number((event.target as HTMLInputElement).value) || 0;
  }

  protected duration(seconds: number): string {
    return humanDuration(seconds);
  }
}
