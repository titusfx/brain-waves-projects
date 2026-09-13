import { defineConfig } from 'vitest/config';

/**
 * Vitest options for `ng test`.
 *
 * Angular's unit-test builder generates its own Vitest configuration; this file is
 * merged into it (see `runnerConfig` in `angular.json`) for the one option the builder
 * does not expose.
 *
 * `pool: 'threads'` because the default `forks` pool fails to start its worker in this
 * environment — `[vitest-pool-runner]: Timeout waiting for worker to respond` — while
 * the same tests run in worker threads in under a second. Nothing here is a test
 * behaviour change: it is the same files, the same assertions, a different process
 * model.
 */
export default defineConfig({
  test: {
    pool: 'threads',
  },
});
