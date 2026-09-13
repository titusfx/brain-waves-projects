"""The device layer: crypto, decoding, HID, and the three sample sources.

This package is the only part of the backend that touches the dongle or the
filesystem's recordings. It knows nothing about HTTP, and nothing about flows.
"""

from __future__ import annotations

from eeg_api.eeg.csvio import iter_rows, read_all
from eeg_api.eeg.decoder import UVStream, decode_reports, raw_counts
from eeg_api.eeg.device import detect, find_interfaces, hid_available, streaming_interface
from eeg_api.eeg.sources import (
    EyesClosedControl,
    LiveSource,
    ReplaySource,
    SignalSource,
    SyntheticSource,
    ThreadedSource,
    create_source,
)


__all__ = [
    "EyesClosedControl",
    "LiveSource",
    "ReplaySource",
    "SignalSource",
    "SyntheticSource",
    "ThreadedSource",
    "UVStream",
    "create_source",
    "decode_reports",
    "detect",
    "find_interfaces",
    "hid_available",
    "iter_rows",
    "raw_counts",
    "read_all",
    "streaming_interface",
]
