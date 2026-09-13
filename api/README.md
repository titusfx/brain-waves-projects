# eeg-api — the EPOC+ workbench backend

FastAPI service that owns the dongle, decodes the stream, and records labelled
datasets from guided protocols. It is the only process that may touch the HID
device, so everything else — the browser, the CLI tools — goes through it or waits.

```powershell
# from the repository root
uv --directory api run uvicorn eeg_api.main.run:app --reload --port 8000
# docs at http://127.0.0.1:8000/docs
```

## What it does

| | |
| --- | --- |
| **Reads the dongle** | Same verified decoder as `scripts/live_view.py`: AES-128-ECB, 32-byte reports, 16-bit little-endian fields, unsigned counts, 0.51 µV/LSB, a continuous 0.5 Hz highpass. |
| **Streams it** | `GET /ws/stream` pushes new samples ~10×/s plus per-channel metrics, band power, an occipital alpha meter and every session state change. |
| **Explains the montage** | `GET /api/channels` serves authored documentation for all 14 sites, validated against the hardware at startup. |
| **Records datasets** | A guided flow writes `recordings/<name>_<stamp>/` with `eeg.csv`, a state table in `labels.csv`, `meta.json` and `events.jsonl`. |
| **Replays recordings** | `POST /api/system/source` can point the whole app at any recording this project has ever produced — including `live_view.py` folders. |
| **Runs without a headset** | `mode: "demo"` generates a plausible scalp signal, with a real eyes-closed alpha burst, so the UI and the flows can be developed and demonstrated. |

## Layers

```
src/eeg_api/
├── domain/       the signal, the montage docs, the analysis, the flow state machine
│                 — pure; no FastAPI, no I/O, no clock
├── eeg/          the only code that touches the dongle or a CSV on disk
├── services/     use cases: acquisition hub, dataset recorder, flow runner, library
└── main/         settings, the app factory, the HTTP routers and the WebSocket
```

`import-linter` enforces the direction (outer may depend on inner, never the reverse)
and ruff bans `fastapi` from the inner layers, so "the domain is framework-free" is a
build failure rather than a review comment.

## Two design decisions worth knowing

**The countdown is not data.** A flow's "start with 3-2-1" is narrated, and the
dataset file is created at the moment the countdown *ends*. Stopping during the
countdown therefore leaves no dataset at all, which is correct: there was no data.

**A stopped loop drops its tail.** When you stop a looping protocol you are reaching
for a button, and the seconds you spend doing that are not the state you meant to
capture. So a stopped loop discards the interrupted state **and** the completed one
before it (`FlowSpec.effective_discard_tail`, default 2). Those rows are physically
removed from `eeg.csv`, not merely annotated, and `meta.json` records what went.

## Commands

```powershell
uv --directory api run pytest -q          # tests
uv --directory api run ruff check .       # lint
uv --directory api run mypy src           # types
uv --directory api run lint-imports       # architecture
uv --directory api run python scripts/dump_openapi.py   # -> web/openapi.json
```

## Configuration

Every knob is an environment variable prefixed `EEG_` — see `.env.example`. The one
that matters most is `EEG_RECORDINGS_DIR`: it defaults to this repository's
`recordings/`, the same folder the CLI tools write to, so there is one library rather
than one per tool.
