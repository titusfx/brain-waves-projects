/** Small presentation helpers shared by the pages. */

/** `95` -> `1:35`; `null` -> an em dash, because "unknown" is not "0:00". */
export function clock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, '0')}`;
}

/** A longer, human duration: `3725` -> `1 h 2 m`. */
export function humanDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} m ${String(total % 60).padStart(2, '0')} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} m`;
}

export function bytes(size: number): string {
  if (size < 1024) return `${size} B`;
  const units = ['kB', 'MB', 'GB'];
  let value = size / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/** `ok` | `warn` | `bad` | `idle`, matching the `.badge-*` classes. */
export type Tone = 'ok' | 'warn' | 'bad' | 'idle';

/**
 * The contact verdict, in the same words the backend uses.
 *
 * `ok` is deliberately the only green one: "low" and "high" both mean the electrode is
 * not sitting where it should, and hiding that behind a neutral grey is how a bad
 * recording gets recorded anyway.
 */
export function statusTone(status: string | undefined | null): Tone {
  switch (status) {
    case 'ok':
      return 'ok';
    case 'low':
    case 'high':
      return 'warn';
    case 'DRY?':
    case 'DEAD':
    case 'artefact':
      return 'bad';
    default:
      return 'idle';
  }
}

/** The colour of a channel dot on the head map, by contact verdict. */
export function statusColor(status: string | undefined | null): string {
  switch (status) {
    case 'ok':
      return '#10b981';
    case 'low':
      return '#f59e0b';
    case 'high':
      return '#fb923c';
    case 'DRY?':
      return '#f43f5e';
    case 'DEAD':
      return '#64748b';
    case 'artefact':
      return '#d946ef';
    default:
      return '#1e293b';
  }
}

export function bandColor(key: string): string {
  switch (key) {
    case 'delta':
      return '#38bdf8';
    case 'theta':
      return '#818cf8';
    case 'alpha':
      return '#34d399';
    case 'beta':
      return '#fbbf24';
    case 'gamma':
      return '#f472b6';
    default:
      return '#94a3b8';
  }
}

/** The message to show for a failed request, preferring the server's own words. */
export function errorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const response = error as { error?: unknown; message?: string; status?: number };
    const body = response.error;
    if (typeof body === 'string' && body.trim()) return body;
    if (body && typeof body === 'object') {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item) =>
            item && typeof item === 'object' && 'msg' in item
              ? String((item as { msg: unknown }).msg)
              : String(item),
          )
          .filter(Boolean);
        if (messages.length) return messages.join('; ');
      }
    }
    if (response.message) return response.message;
  }
  return 'Something went wrong.';
}

/** `mode` as the operator should read it — never let the demo look like a headset. */
export function sourceLabel(mode: string | undefined | null): string {
  switch (mode) {
    case 'live':
      return 'Dongle';
    case 'demo':
      return 'Demo signal';
    case 'replay':
      return 'Replay';
    default:
      return 'Idle';
  }
}
