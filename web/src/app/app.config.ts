import {
  ApplicationConfig,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  inject,
} from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, withComponentInputBinding } from '@angular/router';

import { EegStream } from './core/eeg/stream';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // Angular 22's HttpClient is Fetch-based by default, so `withFetch()` is gone.
    provideHttpClient(),
    // Open the live socket before the first component renders, so the monitor has data
    // in flight rather than showing an empty chart for a frame and then filling in.
    provideAppInitializer(() => inject(EegStream).connect()),
    // `withComponentInputBinding` lets query params arrive as signal inputs, so
    // `/channels?channel=O1` binds straight to the page's `channel` input.
    provideRouter(routes, withComponentInputBinding()),
  ],
};
