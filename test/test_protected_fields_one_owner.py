"""The protected-field list has one owner: the core's input.schema.json (``$defs/protectedField``).

Reader: whoever adds a check on the fields a property editor may write. Read the list with
``obs.input.protected_fields()``; an adapter takes what it needs from the Document
(capabilities/property-editors#Document node).
"""
import re
import subprocess
from pathlib import Path

from obs.input import protected_fields

ROOT = Path(__file__).resolve().parents[1]

OWNER = "src/obs/input.schema.json"
# Files that may restate the list, with why; today none does.
EXCEPTIONS: set[str] = set()
PROTOTYPE = {"__proto__", "constructor", "prototype"}
QUOTED = re.compile(r"""["']([^"'\s]+)["']""")


def _lists(text: str):
    """Each bracketed list of quoted names that holds at least three protected fields, of them
    both a note field (title, kind, ...) and a prototype name: a statement of the protected list,
    not a mention of a few fields."""
    for match in re.finditer(r"\[[^\[\]]*\]", text):
        names = {name.lower() for name in QUOTED.findall(match.group())} & protected_fields()
        if len(names) >= 3 and names & PROTOTYPE and names - PROTOTYPE:
            yield text.count("\n", 0, match.start()) + 1, sorted(names)


def test_the_protected_field_list_appears_only_in_the_core_schema() -> None:
    paths = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    found = []
    for path in paths.splitlines():
        if path in EXCEPTIONS or path == "uv.lock" or path.endswith("/uv.lock"):
            continue
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        found += [f"{path}:{line}: {names}" for line, names in _lists(text)]
    owner = [f"{OWNER}:{line}: {names}" for line, names in _lists((ROOT / OWNER).read_text(encoding="utf-8"))]
    assert len(owner) == 1, f"{OWNER} states the list once ($defs/protectedField)"
    assert found == owner, (
        f"a protected-field list outside {OWNER} ($defs/protectedField); read it with "
        "obs.input.protected_fields() or, in an adapter, from the Document's attrs.writes")
