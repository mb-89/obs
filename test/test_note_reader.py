"""Every part of the core reads note bodies through one reader; see input-model "Chapter content"."""

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "obs"
READER = CORE / "note.py"


def test_only_the_note_reader_sets_up_markdown_it() -> None:
    setups = []
    for module in sorted(CORE.glob("*.py")):
        if module == READER:
            continue
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (
                any(alias.name == "MarkdownIt" for alias in node.names)
                or (node.module or "").startswith("mdit_py_plugins")
            ) or isinstance(node, ast.Attribute) and node.attr == "MarkdownIt":
                setups.append(f"{module.name}:{node.lineno}")

    assert setups == [], "parse note bodies through obs.note (read_note, parser), not markdown_it"
