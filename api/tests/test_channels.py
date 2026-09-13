"""The channel documentation must match the hardware.

A doc for a channel that does not exist, or the wrong byte offset, is worse than no
doc — it would teach the operator something false about their own recording. The
loader enforces this at startup, so these tests assert the enforcement is real.
"""

from __future__ import annotations

import pytest

from eeg_api.config import get_settings
from eeg_api.domain.channels import ChannelCatalog
from eeg_api.domain.models import CHANNEL_OFFSETS, CHANNELS
from eeg_api.services.catalog import CatalogError, load_catalog


@pytest.fixture(scope="module")
def catalog() -> ChannelCatalog:
    return load_catalog(get_settings().catalog_file)


def test_catalog_matches_the_montage(catalog: ChannelCatalog) -> None:
    assert catalog.check() == []


def test_every_channel_of_the_headset_is_documented(catalog: ChannelCatalog) -> None:
    assert catalog.names() == CHANNELS


def test_offsets_are_the_packet_offsets(catalog: ChannelCatalog) -> None:
    assert {doc.name: doc.offset for doc in catalog.channels} == dict(CHANNEL_OFFSETS)


def test_each_channel_answers_the_question_that_was_asked(catalog: ChannelCatalog) -> None:
    """'What does it do?' — every channel must actually answer it."""
    for doc in catalog.channels:
        assert doc.summary, doc.name
        assert len(doc.summary) > 20, doc.name
        assert doc.functions, doc.name
        assert doc.placement, doc.name
        assert doc.region, doc.name
        assert doc.expected, doc.name
        assert doc.artefacts, doc.name


def test_head_map_positions_are_inside_the_unit_circle(catalog: ChannelCatalog) -> None:
    for doc in catalog.channels:
        assert (doc.head.x**2 + doc.head.y**2) ** 0.5 <= 1.0, doc.name


def test_left_and_right_are_on_the_right_sides(catalog: ChannelCatalog) -> None:
    for doc in catalog.channels:
        if doc.hemisphere == "left":
            assert doc.head.x < 0, doc.name
        elif doc.hemisphere == "right":
            assert doc.head.x > 0, doc.name


def test_occipital_channels_sit_at_the_back_of_the_head(catalog: ChannelCatalog) -> None:
    for name in ("O1", "O2"):
        doc = catalog.get(name)
        assert doc is not None
        assert doc.head.y < -0.5, name


def test_the_documentation_says_what_it_is_not(catalog: ChannelCatalog) -> None:
    """The disclaimer is the difference between a reference and a false claim."""
    assert "not a clinical tool" in catalog.disclaimer
    assert "cannot read a thought" in catalog.disclaimer


def test_the_catalog_explains_the_reference_pads(catalog: ChannelCatalog) -> None:
    assert "CMS" in catalog.montage.reference_name
    assert "common-mode rejection fails" in catalog.montage.reference_explanation


def test_bands_are_documented_with_the_alpha_note(catalog: ChannelCatalog) -> None:
    by_key = {band.key: band for band in catalog.bands}
    assert set(by_key) == {"delta", "theta", "alpha", "beta", "gamma"}
    assert "eyes closed" in by_key["alpha"].note


def test_a_catalog_that_disagrees_with_the_hardware_is_refused(tmp_path) -> None:
    broken = tmp_path / "channels.yaml"
    broken.write_text(
        "version: 1\n"
        "disclaimer: test\n"
        "montage: {name: x}\n"
        "channels:\n"
        "  - {name: F3, offset: 4, head: {x: -0.3, y: 0.3}}\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="undocumented channels"):
        load_catalog(broken)


def test_a_missing_catalog_is_an_error_not_an_empty_page(tmp_path) -> None:
    with pytest.raises(CatalogError, match="not found"):
        load_catalog(tmp_path / "nope.yaml")
