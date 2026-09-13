---
title: LSL and Interop
type: reference
tags: [software, lsl, interop, realtime]
updated: 2026-02-14
---

# LSL and Interop

**The strategic move:** stop trying to make the EPOC+ speak every protocol. Make it speak **one** — LSL — and let the ecosystem come to us.

## Why LSL

[Lab Streaming Layer](https://labstreaminglayer.org/) is the de-facto transport for real-time biosignals in research. Emit one LSL stream and these all become available **for free**, regardless of how we got the data:

- **OpenViBE** — BCI pipelines and scenarios
- **Timeflux** — Python real-time graphs
- **Brainstorm** / **BCILAB** / **EEGLAB** (MATLAB)
- **OpenBCI GUI** — can *record* any LSL stream
- **LabRecorder** — standard session recording
- **BrainFlow** — has a streaming/playback path
- **Unity / Unreal** — via LSL→engine bridges, for games and VR

That single decision is what converts "a headset nobody supports" into "a headset that feeds the whole ecosystem."

## Where LSL fits in our architecture

```
[dongle]──HID──┐
[Cortex]──WS───┼──> [ Source ] ──> [ our processing ] ──> [ LSL outlet ] ──> ecosystem
[synthetic]────┤                                            │
[replay]───────┘                                            └──> [ our own UI ]
```

Emit **two streams**, mirroring what other vendors do:

| Stream | Type | Rate | Content |
| --- | --- | --- | --- |
| `EmotivEPOCPlus-EEG` | `EEG` | 128 / 256 Hz | 14 channels, µV, with channel labels + 10-20 positions |
| `EmotivEPOCPlus-Markers` | `Markers` | event | Stimulus/event annotations for epoching |

Metadata matters: LSL streams carry an XML header with **channel labels and units**. Set them properly (`AF3`, …, units `microvolts`) or every downstream tool will label your data wrong. Reading the header from `emokit`'s `sensors_mapping` ordering is a known trap — the CSV writer order and the channel-name order differ.

## Python implementation

Preferred: **pylsl** (the official Python binding).

```python
from pylsl import StreamInfo, StreamOutlet

info = StreamInfo(
    name="EmotivEPOCPlus-EEG",
    type="EEG",
    channel_count=14,
    nominal_srate=128,
    channel_format="float32",
    source_id="epocplus-<dongle-serial>",
)
ch = info.desc().append_child("channels")
for label in CHANNELS:                     # AF3 F7 F3 FC5 T7 P7 O1 O2 P8 T8 FC6 F4 F8 AF4
    c = ch.append_child("channel")
    c.append_child_value("label", label)
    c.append_child_value("unit", "microvolts")
    c.append_child_value("type", "EEG")

outlet = StreamOutlet(info)
outlet.push_sample(values)                 # one sample
# or outlet.push_chunk(list_of_samples)    # batched — prefer this at 256 Hz
```

Notes that will bite:
- `pylsl` needs the LSL **native library** present. On Windows the `pylsl` wheel usually bundles it; if not, install the liblsl release and put it on `PATH`.
- **Push chunks, not samples**, at 128/256 Hz. Per-sample pushes add avoidable overhead and jitter.
- Use a stable `source_id` (e.g. the dongle serial) so consumers can re-find the stream across restarts.
- Timestamps: let LSL timestamp on push (`push_chunk` without explicit timestamps) unless you have a real clock alignment story. Mixed clocks are a classic source of unepoched garbage.

## When NOT to bother with LSL

- Pure offline analysis of recorded files → just use MNE. LSL adds nothing.
- A single-process script that reads and plots → an in-process queue is simpler.
- Development against [[roadmap]] Phase 2's `SyntheticSource` → add the LSL outlet at Phase 4, not before.

## Alternative interop routes

| Route | Verdict |
| --- | --- |
| **CSV / Parquet files** | Simplest. Perfect for Phase 3. Not real-time. |
| **ZMQ / raw sockets** | Fine for our own components; no ecosystem reach. |
| **BrainFlow's streaming board** | Would give us BrainFlow's format + ecosystem, but requires re-encoding our data. Revisit if we need `DataFilter`/`MLModel`. |
| **Cortex API's WebSocket** | Upstream of us, not a distribution format. Never expose this directly to consumers. |

## Sources
- <https://labstreaminglayer.org/>
- <https://github.com/labstreaminglayer/pylsl>
- BrainFlow streaming board docs: <https://brainflow.readthedocs.io/en/stable/SupportedBoards.html>

## Related
[[roadmap]] · [[ecosystems-without-support]] · [[cortex-api]] · [[glossary]]
