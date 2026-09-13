import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  input,
  output,
  viewChild,
} from '@angular/core';

/**
 * A modal that asks before something irreversible.
 *
 * Three deliberate choices, because this exists to prevent an accident rather than to
 * decorate one:
 *
 * * **Cancel is focused when it opens.** A stray Enter, or a keypress already in flight
 *   when the dialog appeared, must not delete anything.
 * * **Escape and a click outside both cancel.** Every way out of this dialog is the safe
 *   one; the only way to delete is to press the button that says so.
 * * **It repeats what will go.** The caller passes the specifics — how many samples, how
 *   much disk, which states — so the answer is to a question about *this* recording, not
 *   to "are you sure?" about a string.
 */
@Component({
  selector: 'eeg-confirm-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'cancelled.emit()' },
  template: `
    <div
      class="fixed inset-0 z-50 grid place-items-center bg-slate-950/75 p-4 backdrop-blur-sm"
      role="presentation"
      tabindex="-1"
      (click)="onBackdrop($event)"
      (keydown.escape)="cancelled.emit()"
    >
      <div
        class="panel w-full max-w-lg p-5 shadow-2xl"
        role="dialog"
        aria-modal="true"
        [attr.aria-label]="title()"
      >
        <h2 class="text-base font-semibold text-slate-100">{{ title() }}</h2>
        <p class="mt-1 text-sm text-slate-300">{{ message() }}</p>

        @if (detail().length) {
          <ul class="panel-tight mt-3 space-y-1 px-3 py-2 text-xs">
            @for (line of detail(); track line) {
              <li class="mono text-slate-400">{{ line }}</li>
            }
          </ul>
        }

        @if (warning(); as text) {
          <p
            class="mt-3 rounded-lg border border-rose-800/60 bg-rose-950/40 px-3 py-2 text-xs text-rose-200"
          >
            {{ text }}
          </p>
        }

        <div class="mt-5 flex justify-end gap-2">
          <button #cancel type="button" class="btn" (click)="cancelled.emit()">
            {{ cancelLabel() }}
          </button>
          <button
            type="button"
            class="btn btn-danger"
            [disabled]="busy()"
            (click)="confirmed.emit()"
          >
            {{ busy() ? 'working…' : confirmLabel() }}
          </button>
        </div>
      </div>
    </div>
  `,
})
export class ConfirmDialog {
  readonly title = input('Are you sure?');
  readonly message = input('');
  readonly detail = input<string[]>([]);
  readonly warning = input<string | null>(null);
  readonly confirmLabel = input('Delete');
  readonly cancelLabel = input('Cancel');
  readonly busy = input(false);
  readonly confirmed = output<void>();
  readonly cancelled = output<void>();

  private readonly cancelButton = viewChild<ElementRef<HTMLButtonElement>>('cancel');

  constructor() {
    afterNextRender(() => this.cancelButton()?.nativeElement.focus());
  }

  /** A click on the backdrop cancels; a click inside the panel must not. */
  protected onBackdrop(event: MouseEvent): void {
    if (event.target === event.currentTarget) this.cancelled.emit();
  }
}
