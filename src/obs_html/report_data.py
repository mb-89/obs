"""The standalone canonical-data transport and ordered runtime boundary."""
from __future__ import annotations

import base64
import gzip
import json
import re
from html.parser import HTMLParser
from importlib.resources import files
from zlib import error as ZlibError

from obs_html.content import ContentError


REPORT_PATTERN = re.compile(r'(<script id="report-data"[^>]*>)(.*?)(</script>)', re.DOTALL)
_SCRIPT_PATTERN = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.DOTALL | re.IGNORECASE)
_INERT_TYPE = "application/x-obs-html-script"


class _Attributes(HTMLParser):
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.attrs = dict(attrs)


def _attributes(opening: str) -> dict[str, str | None]:
    parser = _Attributes()
    parser.feed(opening)
    return parser.attrs


def serialize_report_data(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def encode_report_data(data: dict, compression: str | None = None) -> str:
    if compression is None:
        compression = json.loads(files("obs_html").joinpath("cfg.json").read_text(encoding="utf-8"))["report"]["dataCompression"]
    if compression not in {"gzip", "none"}:
        raise ContentError(f"Unsupported document data compression: {compression}")
    text = serialize_report_data(data)
    raw = text.encode("utf-8")
    plain = (f'<script id="report-data" type="application/json" data-report-data '
             f'data-compression="{compression}">{text}</script>')
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii") if compression == "gzip" else ""
    if encoded:
        compressed = (f'<script id="report-data" type="application/octet-stream" data-report-data '
                      f'data-compression="{compression}" data-encoding="gzip">{encoded}</script>')
        if len(compressed) < len(plain.encode("utf-8")):
            return compressed
    return plain


def decode_report_data(report: str) -> dict:
    match = REPORT_PATTERN.search(report)
    if not match:
        raise ContentError("Cannot read document data: canonical island is missing.")
    try:
        data = json.loads(_island_text(match))
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data
    except (ValueError, TypeError, OSError, EOFError, ZlibError) as error:
        raise ContentError(f"Invalid document data: {error}") from error


def _island_text(match: re.Match[str]) -> str:
    attrs = _attributes(match[1])
    encoding = attrs.get("data-encoding")
    if encoding == "gzip":
        if attrs.get("type") != "application/octet-stream":
            raise ValueError("invalid gzip island type")
        raw = base64.b64decode(re.sub(r"\s", "", match[2]), validate=True)
        return gzip.decompress(raw).decode("utf-8")
    if encoding is None and attrs.get("type") == "application/json":
        return match[2]
    raise ValueError(f"unsupported encoding {encoding or attrs.get('type')}")


def same_document_content(report: str, existing: str) -> bool:
    """Whether two documents differ at most in their generation timestamp.

    The timestamp records the last content change, so an unchanged rebuild keeps the
    existing document instead of rewriting it with a new build time.
    """
    new, old = REPORT_PATTERN.search(report), REPORT_PATTERN.search(existing)
    if (not new or not old or new[1] != old[1] or report[:new.start()] != existing[:old.start()]
            or report[new.end():] != existing[old.end():]):
        return False
    try:
        previous_text = _island_text(old)
        data, previous = json.loads(_island_text(new)), json.loads(previous_text)
        data["document"]["generation"]["timestamp"] = previous["document"]["generation"]["timestamp"]
        return serialize_report_data(data) == previous_text
    except (ValueError, TypeError, KeyError, OSError, EOFError, ZlibError):
        return False


def prepare_report_scripts(report: str) -> str:
    """Make every model consumer inert, including scripts added by later stages."""
    def prepare(match: re.Match[str]) -> str:
        opening, body, closing = match.groups()
        attrs = _attributes(opening)
        if attrs.get("id") in {"reader-startup-script", "running-header-script", "report-bootstrap-script"}:
            return match[0]
        kind = attrs.get("type", "")
        if kind not in {"", "text/javascript", "application/javascript"}:
            return match[0]
        opening = re.sub(r"""\s+type\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", "", opening, flags=re.IGNORECASE)
        return opening[:-1] + f' type="{_INERT_TYPE}" data-obs-runtime>' + body + closing

    report = _SCRIPT_PATTERN.sub(prepare, report)
    if 'id="report-bootstrap-script"' not in report:
        runtime = files("obs_html").joinpath("report-data.js").read_text(encoding="utf-8")
        report = report.replace('<script id="report-data"',
                                f'<script id="report-bootstrap-script">{runtime}</script>\n'
                                '<script id="report-data"', 1)
    return report
