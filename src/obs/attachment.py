"""Extract display dates from attachment metadata."""
from datetime import date, datetime
import re
from xml.etree import ElementTree


_EXPORTED_NAMES = {"exported", "exporteddate"}
_LAST_CHANGED_NAMES = {"lastchanged", "lastchangeddate"}


def extract_attachment_date(source: bytes) -> date | None:
    """Return the exported or last-changed date encoded in XML metadata."""
    if not isinstance(source, bytes):
        return None
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError:
        return None
    values = {"exported": [], "last-changed": []}
    for element in root.iter():
        name = _metadata_name(element.tag)
        if name is not None:
            values[name].append(element.text or "")
        for attribute, value in element.attrib.items():
            name = _metadata_name(attribute)
            if name is not None:
                values[name].append(value)
    for name in ("exported", "last-changed"):
        if values[name]:
            return _parse_date(values[name][0])
    return None


def _metadata_name(value: str) -> str | None:
    local_name = value.rsplit("}", 1)[-1]
    normalized = re.sub(r"[^a-z0-9]", "", local_name.lower())
    if normalized in _EXPORTED_NAMES:
        return "exported"
    if normalized in _LAST_CHANGED_NAMES:
        return "last-changed"
    return None


def _parse_date(value: str) -> date | None:
    value = value.strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
