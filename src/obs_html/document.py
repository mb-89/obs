"""Write a schema-valid Document and deliver it to an executable adapter."""
import argparse
import json
import subprocess
from pathlib import Path
from typing import Sequence

from jsonschema import validate

from obs_html.adapter import AdapterError, load_adapter


DOCUMENT_SCHEMA_PATH = Path(__file__).with_name("document.schema.json")
CONTRACT_VERSION = 1


class DocumentError(ValueError):
    """Raised when a Document violates the neutral contract."""


def read_document(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(DOCUMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
        validate(document, schema)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise DocumentError(f"Invalid Document {path}: {error}") from error
    return document


def write_document(document: dict[str, object], path: Path) -> None:
    schema = json.loads(DOCUMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        validate(document, schema)
    except ValueError as error:
        raise DocumentError(f"Invalid Document: {error}") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def call_adapter(adapter_name: str, configuration_path: Path, document_path: Path,
                 destination: Path) -> None:
    adapter = load_adapter(adapter_name, configuration_path)
    document = read_document(document_path)
    if adapter["contractVersion"] != document["schemaVersion"]:
        raise AdapterError(
            f"Adapter {adapter_name!r} contract version {adapter['contractVersion']} does not "
            f"match Document schema version {document['schemaVersion']}."
        )
    supported = set(adapter["capabilities"])
    unsupported = sorted(set(document["capabilities"]) - supported)
    if unsupported:
        raise AdapterError(
            f"Adapter {adapter_name!r} does not support Document capabilities: "
            f"{', '.join(unsupported)}."
        )
    try:
        completed = subprocess.run(
            [*adapter["command"], str(document_path.resolve()), str(destination.resolve())],
            cwd=configuration_path.parent,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise AdapterError(f"Cannot start adapter {adapter_name!r}: {error}") from error
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        suffix = f": {detail}" if detail else ""
        raise AdapterError(f"Adapter {adapter_name!r} exited with code {completed.returncode}{suffix}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obs-document",
        description="Validate a JSON Document and deliver it to a configured adapter.",
    )
    parser.add_argument("--document", type=Path, required=True, help="Schema-valid JSON Document.")
    parser.add_argument("--adapter", required=True, help="Configured adapter name.")
    parser.add_argument("--adapter-config", type=Path, required=True, help="Adapter configuration JSON.")
    parser.add_argument("--destination", type=Path, required=True, help="Adapter output destination.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    try:
        call_adapter(options.adapter, options.adapter_config, options.document, options.destination)
    except (AdapterError, DocumentError) as error:
        raise SystemExit(f"obs-document: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
