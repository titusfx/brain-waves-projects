import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import type {
  ChannelCatalog,
  ChannelDoc,
  FlowInput,
  FlowSpec,
  FlowValidation,
  LibraryEntry,
  LibraryListing,
  PlanPreview,
  Preview,
  QuickRecordRequest,
  Segment,
  SessionState,
  SourceRequest,
  Spectrum,
  StartSessionRequest,
  Status,
} from './models';

/**
 * Every REST call, in one place.
 *
 * The base URL is a relative `/api`, which is what makes the app work unchanged in
 * both modes: `ng serve` proxies `/api` to the API on port 8000 (see
 * `proxy.conf.json`), and the built app is served *by* that API, so the same path is
 * same-origin.
 */
const BASE = '/api';

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  // ------------------------------------------------------------------ system
  async status(): Promise<Status> {
    return firstValueFrom(this.http.get<Status>(`${BASE}/system/status`));
  }

  /**
   * Switch the stream.
   *
   * The fields the server defaults (`loop`, `replay_speed`) are filled in here rather
   * than at every call site: `openapi-typescript` types a property that carries an
   * OpenAPI `default` as required, on the grounds that the server always ends up with a
   * value. Saying so once, explicitly, is clearer than doing it in five components.
   */
  async setSource(request: Partial<SourceRequest> & Pick<SourceRequest, 'mode'>): Promise<Status> {
    return firstValueFrom(
      this.http.post<Status>(`${BASE}/system/source`, {
        replay_id: null,
        replay_speed: 1,
        loop: true,
        ...request,
      }),
    );
  }

  // ---------------------------------------------------------------- channels
  async catalog(): Promise<ChannelCatalog> {
    return firstValueFrom(this.http.get<ChannelCatalog>(`${BASE}/channels`));
  }

  async channel(name: string): Promise<ChannelDoc> {
    return firstValueFrom(
      this.http.get<ChannelDoc>(`${BASE}/channels/${encodeURIComponent(name)}`),
    );
  }

  // --------------------------------------------------------------- recordings
  async recordings(): Promise<LibraryListing> {
    return firstValueFrom(this.http.get<LibraryListing>(`${BASE}/recordings`));
  }

  async recording(id: string): Promise<LibraryEntry> {
    return firstValueFrom(
      this.http.get<LibraryEntry>(`${BASE}/recordings/${encodeURIComponent(id)}`),
    );
  }

  async segments(id: string): Promise<Segment[]> {
    return firstValueFrom(
      this.http.get<Segment[]>(`${BASE}/recordings/${encodeURIComponent(id)}/segments`),
    );
  }

  async preview(id: string, points = 900): Promise<Preview> {
    const params = new HttpParams().set('points', points);
    return firstValueFrom(
      this.http.get<Preview>(`${BASE}/recordings/${encodeURIComponent(id)}/preview`, { params }),
    );
  }

  async spectrum(id: string, channel = 'O1', seconds?: number): Promise<Spectrum> {
    let params = new HttpParams().set('channel', channel);
    if (seconds !== undefined) params = params.set('seconds', seconds);
    return firstValueFrom(
      this.http.get<Spectrum>(`${BASE}/recordings/${encodeURIComponent(id)}/spectrum`, { params }),
    );
  }

  // ------------------------------------------------------------------ flows
  async flows(): Promise<FlowSpec[]> {
    return firstValueFrom(this.http.get<FlowSpec[]>(`${BASE}/flows`));
  }

  async flow(id: string): Promise<FlowSpec> {
    return firstValueFrom(this.http.get<FlowSpec>(`${BASE}/flows/${encodeURIComponent(id)}`));
  }

  async createFlow(input: FlowInput): Promise<FlowSpec> {
    return firstValueFrom(this.http.post<FlowSpec>(`${BASE}/flows`, input));
  }

  async updateFlow(id: string, input: FlowInput): Promise<FlowSpec> {
    return firstValueFrom(
      this.http.put<FlowSpec>(`${BASE}/flows/${encodeURIComponent(id)}`, input),
    );
  }

  async deleteFlow(id: string): Promise<void> {
    await firstValueFrom(this.http.delete<void>(`${BASE}/flows/${encodeURIComponent(id)}`));
  }

  async validateFlow(input: FlowInput): Promise<FlowValidation> {
    return firstValueFrom(this.http.post<FlowValidation>(`${BASE}/flows/validate`, input));
  }

  async previewFlow(input: FlowInput): Promise<PlanPreview> {
    return firstValueFrom(this.http.post<PlanPreview>(`${BASE}/flows/preview`, input));
  }

  // --------------------------------------------------------------- sessions
  async currentSession(): Promise<SessionState | null> {
    return firstValueFrom(this.http.get<SessionState | null>(`${BASE}/sessions/current`));
  }

  async startSession(request: StartSessionRequest): Promise<SessionState> {
    return firstValueFrom(this.http.post<SessionState>(`${BASE}/sessions`, request));
  }

  async quickRecord(
    request: Partial<QuickRecordRequest> & Pick<QuickRecordRequest, 'label'>,
  ): Promise<SessionState> {
    return firstValueFrom(
      this.http.post<SessionState>(`${BASE}/sessions/quick`, {
        countdown_seconds: 3,
        dataset_name: null,
        notes: '',
        voice: true,
        ...request,
      }),
    );
  }

  async stopSession(): Promise<SessionState> {
    return firstValueFrom(this.http.post<SessionState>(`${BASE}/sessions/current/stop`, {}));
  }

  async abortSession(): Promise<SessionState> {
    return firstValueFrom(this.http.post<SessionState>(`${BASE}/sessions/current/abort`, {}));
  }
}
