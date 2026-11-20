from datetime import date, datetime, timezone

import pytest

from obs.attachment import extract_attachment_date


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"<metadata><exported>2026-03-04</exported></metadata>", date(2026, 3, 4)),
        (
            b"<attachment><metadata><last-changed>2026-03-04T00:30:00+01:00"
            b"</last-changed></metadata></attachment>",
            date(2026, 3, 4),
        ),
    ],
)
def test_extract_attachment_date_reads_root_and_item_metadata(source, expected) -> None:
    assert extract_attachment_date(source) == expected


def test_extract_attachment_date_prefers_exported_metadata() -> None:
    source = (
        b"<attachment><metadata><last-changed>2026-03-03</last-changed>"
        b"<exported>2026-03-04T12:00:00Z</exported></metadata></attachment>"
    )

    assert extract_attachment_date(source) == date(2026, 3, 4)


def test_extract_attachment_date_reads_utf16_xml() -> None:
    source = (
        '<?xml version="1.0" encoding="UTF-16"?><metadata>'
        "<last-changed>2026-03-04</last-changed></metadata>"
    ).encode("utf-16")

    assert extract_attachment_date(source) == date(2026, 3, 4)


@pytest.mark.parametrize(
    "source",
    [
        b"<metadata><exported>2026-02-29</exported></metadata>",
        b"<metadata><last-changed>not-a-date</last-changed></metadata>",
        b"<metadata><exported>2026-03-04</metadata>",
    ],
)
def test_extract_attachment_date_returns_none_for_invalid_xml_or_dates(source) -> None:
    assert extract_attachment_date(source) is None


def test_extract_attachment_date_uses_supplied_modification_instant_without_metadata() -> None:
    modified = datetime(2026, 3, 5, 0, 30, tzinfo=timezone.utc)

    assert extract_attachment_date(b"<metadata/>", modified) == date(2026, 3, 5)


@pytest.mark.parametrize("modified", [None, "2026-03-05", date(2026, 3, 5)])
def test_extract_attachment_date_rejects_unsupported_modification_values(modified) -> None:
    assert extract_attachment_date(b"<metadata/>", modified) is None
