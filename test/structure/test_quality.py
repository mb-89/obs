import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
GLOSSARY_TERMS = ("Document", "artifact", "note", "file", "vault")
GLOSSARY_ENTRY = re.compile(r"^- \*\*(\w+)\*\*:", re.MULTILINE)
# A definition starts like a glossary entry; a list of names (the Document profile) does not.
DEFINITION = re.compile(r"^- \*\*(\w+)\*\*: (?:the|a|an|any|one|what) ", re.MULTILINE | re.IGNORECASE)


def test_quality_glossary_alone_defines_the_vocabulary() -> None:
    quality = (ROOT / "spec" / "design_input" / "quality.md").read_text(encoding="utf-8")
    glossary = quality.split("\n## Glossary\n", 1)[1].split("\n## ", 1)[0]
    assert tuple(GLOSSARY_ENTRY.findall(glossary)) == GLOSSARY_TERMS
    assert tuple(DEFINITION.findall(glossary)) == GLOSSARY_TERMS

    terms = {term.lower() for term in GLOSSARY_TERMS}
    for path in [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "spec").rglob("*.md"))]:
        if path.name == "quality.md" or "design_output" in path.parts:
            continue
        redefined = [term for term in DEFINITION.findall(path.read_text(encoding="utf-8"))
                     if term.lower() in terms]
        assert redefined == [], f"{path}: link [[quality#Glossary]] instead of defining {redefined}"
