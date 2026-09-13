# eeg-web — the EPOC+ workbench front end

Angular 22 (zoneless, standalone, signal-based), Tailwind 4, Vitest. It talks to the
FastAPI service in `../api` over REST for anything static and a WebSocket for the
stream.

```powershell
# from the repository root
npm run api          # FastAPI on http://127.0.0.1:8020
npm run web          # dev server on http://localhost:4301, proxying /api and /ws
```

Or build it and let the API serve it — one process, one origin:

```powershell
npm run build:web
npm run api:prod     # http://127.0.0.1:8020 serves the app and the API together
```

## Screens

| route       | what it is                                                                                                                                             |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `/`         | **Monitor** — live traces, the contact map, per-channel amplitude and mains, the O1/O2 alpha meter, and the one-button "record this label"             |
| `/channels` | **Channels** — what each of the 14 electrodes is over, what engages it, what ruins it, and what a good recording looks like. `?channel=O1` is linkable |
| `/flows`    | **Protocols** — the builder: linear or looping, a countdown, states with durations, a repeat count, and a live preview of the expanded running order   |
| `/run`      | **Run** — the spoken countdown, the current state with a progress ring and what is next, and the dataset it writes                                     |
| `/datasets` | **Datasets** — everything in `recordings/`, with its label timeline, a decimated preview, a spectrum, and a "replay this" button                       |

## How it is put together

```
src/app/
├── core/
│   ├── api/       Api (every REST call), models (types derived from the API's OpenAPI
│   │              document), schema.d.ts (generated — do not edit)
│   ├── eeg/       EegStream (the socket, as signals), SampleRing, messages (frame types)
│   ├── speech/    Speech (the spoken countdown, mutable, persisted)
│   └── format.ts  the small shared presentations
├── features/      one folder per screen, plus `shared/` for the head map, the trace
│                  canvases and the channel-documentation panel
└── app.ts         the shell: navigation, the source switch and the voice switch
```

Three decisions worth knowing:

**The server computes the numbers; the browser draws them.** Amplitude, mains
contamination, band power and the alpha peak are calculated in Python by the same code
path `scripts/live_view.py` uses, so the browser and the terminal cannot disagree about
whether an electrode is dry. The client only renders.

**Types come from the API.** `npm run api:types` (from the repository root) regenerates
`schema.d.ts` from the backend's OpenAPI document. A field renamed on the server breaks
the Angular build rather than producing an `undefined` three layers away — which is why
the backend's _response_ models declare no defaults: a default makes a field optional in
the generated TypeScript, and every consumer would then have to be defensive about
fields that are always sent.

**The demo source is a first-class citizen, and always labelled.** `Demo` in the header
generates a synthetic scalp signal with a real eyes-closed alpha burst; the header, the
status strip and the source label all say `Demo signal` wherever the mode is reported. A
demo that could be mistaken for a head would be a hazard, not a feature.

## Tests

```powershell
npm run test:ci      # Vitest, via the Angular builder
npm run lint
npm run format:check
```

`SampleRing` (the wrap-around arithmetic) and `format.ts` are covered by unit tests. The
screens are covered end to end by `tools/verify-web.mjs` at the repository root, which
drives the _built_ app in headless Chrome and asserts on the rendered DOM, the canvas
pixels and the console.

## `vitest-base.config.ts`

`ng test` merges this file into the configuration it generates. It exists for one line —
`pool: 'threads'` — because Vitest's default `forks` pool fails to start its worker in
this environment while the same tests run in worker threads in under a second.
