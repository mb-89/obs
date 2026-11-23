"""The generator of the core's case-folding table, src/obs/case-folding.json.

Reader: whoever changes the case-folding table or the Unicode version it is built from.

It writes the table from Unicode's `CaseFolding.txt`, committed at `data/data_input/CaseFolding.txt`:
every code point with a full folding (statuses C and F, without the Turkic T and the simple S
mappings) and the text it folds to, at the Unicode version the file's first line names.
capabilities/bases#Comparisons owns the rule the table holds. The table is JSON, which has no
comments, so `.gitattributes` marks it as this generator's output and `generated.yaml` declares it
(se's guidance note generated-files-are-marked).

`python -m obs.case_folding` writes the table; `--check` writes nothing and fails where the committed
table is not what a fresh run writes, byte for byte. Exit code 0 written or current, 1 stale.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

GENERATOR = "obs.case_folding"
SOURCE = Path("data") / "data_input" / "CaseFolding.txt"
OUTPUT = Path("src") / "obs" / "case-folding.json"
ROOT = Path(__file__).resolve().parents[2]

DESCRIPTION = (
    "Unicode full case folding (CaseFolding.txt, statuses C and F, no Turkic T mappings): each code "
    "point, in hexadecimal, that folds, and the text it folds to. Every case-insensitive selection "
    "folds both sides by this table; owner: spec/capabilities/bases.md, Comparisons."
)
FULL = {"C", "F"}
VERSION = re.compile(r"^# CaseFolding-(?P<version>\d+\.\d+\.\d+)\.txt$")


def folds(source: str) -> dict[int, str]:
    """Each code point `source` gives a full folding, and the text it folds to."""
    found = {}
    for line in source.splitlines():
        data = line.split("#", 1)[0].strip()
        if not data:
            continue
        code, status, mapping = (field.strip() for field in data.split(";")[:3])
        if status in FULL:
            found[int(code, 16)] = "".join(chr(int(point, 16)) for point in mapping.split())
    return found


def table(source: str) -> str:
    """The table's text, written from `CaseFolding.txt`'s text `source`."""
    lines = source.splitlines()
    match = VERSION.match(lines[0]) if lines else None
    if match is None:
        raise ValueError(f"{SOURCE.as_posix()}: its first line names no version "
                         "(# CaseFolding-<version>.txt)")
    entries = ",\n".join(f"{json.dumps(f'{code:04X}')}:{json.dumps(folded)}"
                         for code, folded in sorted(folds(source).items()))
    return (f'{{"description":{json.dumps(DESCRIPTION)},\n"unicode":{json.dumps(match["version"])},\n'
            f'"folds":{{{entries}}}}}\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m obs.case_folding", description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=ROOT / SOURCE, help="CaseFolding.txt")
    parser.add_argument("--output", type=Path, default=ROOT / OUTPUT, help="the table")
    parser.add_argument("--check", action="store_true", help="write nothing; fail where the table is stale")
    args = parser.parse_args(argv)
    text = table(args.source.read_text(encoding="utf-8"))
    current = args.output.read_bytes() if args.output.is_file() else b""
    if args.check:
        if current != text.encode("utf-8"):
            print(f"{args.output}: not what {GENERATOR} writes from {args.source}; "
                  f"run python -m {GENERATOR} and commit what it writes")
            return 1
        return 0
    if current != text.encode("utf-8"):
        args.output.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
