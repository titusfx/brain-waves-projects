---
title: Web workbench
type: note
tags: [software, app, angular, fastapi, datasets]
updated: 2026-09-13
---

# Web workbench — the app on top of the driver

The `scripts/` tools answer *"is this signal real?"*. The workbench answers the next
questions: *which electrode is bad, what does T7 actually measure, and can I turn this
into a labelled dataset without writing a script.*

Built **2026-09-13**. Two processes, one repository:

| | |
| --- | --- |
| `api/` | FastAPI + `uv`, hexagonally layered. Owns the dongle, decodes the stream, computes the numbers, writes datasets, runs protocols. |
| `web/` | Angular 22 (zoneless, signals), Tailwind 4, Vitest. Renders and drives it. |
| `tools/verify-web.mjs` | Drives the **built** app in headless Chrome over CDP and asserts on the DOM, the canvas pixels and the console. 13 checks. |

```powershell
npm run api        # http://127.0.0.1:8020
npm run web        # http://localhost:4301  (proxies /api and /ws)
npm run build:web; npm run api:prod   # one process, one origin, no proxy
```

**Port 8020, not 8000.** 8000 is what `strategy-business`'s API already binds on this
machine; using it would have made `GET /health` answer from the *other* project and look
like a working deployment. The port is a guess at a free one, and it is the proxy target
in `web/proxy.conf.json`.

## Screens

| route | what it does |
| --- | --- |
| `/` | **Monitor** — traces, contact map, per-channel amplitude/mains, O1·O2 alpha meter, and the one-button "record this label" |
| `/channels` | **Channel reference** — what each of the 14 sites is over, what engages it, what ruins it. `?channel=O1` is linkable |
| `/flows` | **Protocol builder** — linear or looping, countdown, states, repeat count, live preview of the expanded run order |
| `/run` | **Runner** — spoken countdown, current state + progress ring + up-next, writes the dataset |
| `/datasets` | **Library** — label timeline, decimated preview, spectrum, and "replay this through the whole app". Clicking a state narrows the charts to that state's window; deleting asks first |
| `/datasets/:id/discovery` | **Discovery** — compare instances of a state, and find what separates two states. → below |

## Discovery: is there anything here that tells two states apart?

The question you ask after labelling a dataset. It is answered in the order it is actually
asked, and the last part is the one that keeps it honest.

**Do the instances even look like each other?** The overlay draws every selected instance of
a state from its own start, so where the traces sit on top of each other is the part of the
recording that state controls. `scripts`-style eyeballing, made honest by drawing all of them
rather than the mean.

**Do the two states differ by more than that scatter?** Each state gets a spectrum averaged
over its window (Welch, so a 20-second state is not judged on one 2-second slice), and the
difference is measured per frequency bin *in units of the pooled within-state spread*. Below
1.0 the states differ by less than their own noise — that bin is reported as **shared**, and
it cannot explain the difference however much the two curves appear to wiggle in it. Those
bins, and wholly shared bands, are listed explicitly. Also measured: which electrode
separates the two states best, out of all fourteen.

**And is the biggest difference more than luck?** Scanning ~110 bins for the largest gap
will find one by chance, so the largest observed effect is compared against a null built by
shuffling the state labels. Then the hard limit is stated rather than hidden: with three
instances per state there are only C(6,3) = 20 ways to split them, so **no result can come
out below p ≈ 0.048**, whatever the picture looks like. The screen says that, because the
alternative is an operator concluding their effect is not real when the real problem is that
they recorded three states.

A final readout — leave-one-out nearest-centroid over the few most different bins, against
the same rule over all 110 — separates "these bins carry the difference" from "this is a
validated classifier". It is the former.

Measured on a synthetic dataset whose two states genuinely differ by a 10 Hz tone in O1:

| | |
| --- | --- |
| largest difference | 11.0 at **10 Hz** — where the difference was put |
| bins shared by both states | 61 of 89 (69%), wholly shared bands: theta, gamma |
| nearest-centroid | 100% of 6 states with the 5 best bins, 83% with all 89 |
| best electrode | **O1**, then AF4, O2 |
| p-value | 0.16, and the attainable floor is 0.048 — with three states a side, "not yet significant" is the truthful answer |

## Deleting

`DELETE /api/recordings/{id}` removes a recording or a whole dataset folder. It is the only
irreversible thing the app does, so:

* the UI gates it behind a modal that **names what will go** — kind, duration, samples,
  states, labels, size, path — rather than asking "are you sure?" about a string;
* **Cancel is focused** when the modal opens, and Escape and a click outside both cancel, so
  the only way to delete is to press the button that says so;
* the server refuses anything the current source or recording is using (409), so a live
  replay cannot be deleted out from under itself, and it refuses any id that resolves outside
  `recordings/` — including `.`, `..`, and the folder itself.

Verified end to end, including that **cancelling keeps the recording** and confirming
removes it from disk and the listing.


## The protocol model

Two shapes, as asked for, plus the open-ended case:

```
linear   start with 5, laydown 10, stand up 20          → each state once, in order
loop     start with 3, close your eyes 20, open 15      → repeats until you stop
open     start with 3, "eyes closed" (no duration)      → one state, until you stop
```

`api/src/eeg_api/domain/flows.py` is a **pure state machine**: it owns no clock and does
no I/O; the runner calls `advance(now)` twenty times a second and turns the events into
stream time. Every rule below is therefore a unit test rather than a live experiment.

### Two decisions that are easy to get wrong

**The countdown is not data.** "Start with 3" is narrated and the dataset file is created
at the moment the countdown *ends* (`go`). Stopping during the countdown therefore leaves
**no dataset at all** — there was no data. An earlier version emitted `go` whenever the
countdown *phase* closed, including when the operator cancelled it, which wrote a dataset
for a run that never started. The browser harness catches this now
(`the countdown was not written into the dataset` asserts the first kept state starts at
sample 0).

**A stopped loop drops its tail.** When you stop a looping protocol you are reaching for a
button, and those seconds are not the state you meant to capture. So a stopped loop
discards the interrupted state **and** the completed one before it
(`FlowSpec.effective_discard_tail`, default 2 for a loop, 0 for a linear flow). The rows
are physically truncated out of `eeg.csv`, `meta.json` records what went, and the builder
shows the count *before* the run rather than surprising you afterwards.

## Dataset format

`recordings/<name>_<stamp>/`:

| file | contents |
| --- | --- |
| `eeg.csv` | `t,F3_uV,…,F4_uV` — a **superset** of what `record.py` writes, so `live_view.py --replay` and `alpha_test.py --file` read a dataset unchanged |
| `labels.csv` | a **segment table** (which sample range carries which label), not a per-sample column: states change a few times a minute, not 128 times a second |
| `meta.json` | the flow, the source, the counts, the kept and discarded states |
| `events.jsonl` | every boundary as it happened, for provenance |

Labels are sample-exact because boundaries are **queued with a stream time and applied by
the writer as it passes them**, rather than stamped at whatever moment the runner noticed.
An earlier version compared an absolute boundary time against an epoch-relative row time —
a bug that shifted every state by the length of the stream so far and produced a
plausible-looking dataset with the wrong labels on it.

## The synthetic source (`mode: "demo"`)

There is no way to develop or test this without a headset on someone's head, and the real
hardware needs a person to sit still for it. So `SyntheticSource` generates a 1/f scalp
signal with a genuine eyes-closed alpha burst over O1/O2, one weak-contact channel (T7)
and one dry one (T8, ~70 % mains), so the contact logic is exercised by the demo rather
than only by a real head.

It is reported as `demo` **everywhere** — header, status strip, dataset metadata — and it
implements `EyesClosedControl`, so a running protocol that says "close your eyes"
actually closes them and the alpha meter visibly rises. In the verification run, O1/O2
alpha reads 51.6 % / 62.2 % during an "eyes closed" state against 27 % / 44 % on the
demo's own free-running schedule. **A demo that could be mistaken for a head would be a
hazard, not a feature.**

## Channel documentation

The prose is authored data: `api/src/eeg_api/domain/catalog/channels.yaml`. The loader
refuses to **start the process** if a documented channel is not a real channel of this
montage, if the byte offset disagrees with the packet layout, or if a head-map position
falls outside the unit circle — a doc for a channel that does not exist is worse than no
doc, because it teaches something false about your own recording. `ChannelCatalog.check()`
is the rule, and `api/tests/test_channels.py` asserts it bites.

## How this was verified

| check | result |
| --- | --- |
| `api`: pytest | ✅ 131 passed |
| `api`: ruff, ruff format, mypy `strict`, `lint-imports` | ✅ clean (2 architecture contracts kept) |
| `web`: `ng build`, `eslint`, `prettier --check`, Vitest | ✅ 20 tests |
| End to end in headless Chrome (`tools/verify-web.mjs`) | ✅ 17/17, console clean |

Not verified: **any of it against a streaming headset.** Every check above runs on the
synthetic source.

## Hardware observation, 2026-09-13

The dongle **is** attached to this machine:

```
serial          UD20180927003B78
interfaces      interface 0  "Brain Computer Interface USB Receiver/Dongle"  (silent)
                interface 1  "EEG Signals"                                  (streams)
```

`POST /api/system/source {"mode":"live"}` selects interface 1 by product string, opens it,
and reports **`live`** with no error — then shows `reports=0 samples=0` for eight seconds
straight. Per `scripts/read_live.py` that is the documented RF/pairing signature: the
dongle enumerates and opens perfectly and carries nothing, which almost always means **the
headset is switched off, flat, or was never paired with this dongle**. It is not a software
fault, and the app now says so (see below) instead of suggesting the cable.

So the live path is verified as far as *"it opens the right interface and reports silence
honestly"*, and **not** as far as *"it has carried a real sample through the API"*. That
still needs a charged, paired headset and a person.

The `0-silent-dongle` screenshot and text dump in `tools/out-verify/` capture exactly this
state, and `tools/verify-web.mjs` asserts on it: when the dongle is present and silent the
monitor must show the power/charge/LED/pairing checklist, and when no dongle is present it
must not.

→ [[2026-02-14-first-live-session]] · [[identify-your-revision]]

→ [[ud2016-crypto-crack]] · [[emokit]] · [[roadmap]] · [[decisions-log]]
