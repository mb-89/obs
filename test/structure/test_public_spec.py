"""The public repository names no private work context.

This file is the one owner of the deny list. It holds only salted SHA-256 hashes, never a term,
so the check does not publish what it keeps out. It spans every authored file under `spec/`
(generated `spec/design_output` excluded).

To add a term without writing it anywhere public, the owner runs locally

    python -c "import sys; sys.path.insert(0, 'test/structure'); import test_public_spec as t; print(t.digest(input()))"

types the term at the prompt (nothing lands in shell history or a file), and adds the printed
hash to `DENIED` (or to `DENIED_EXACT` when the lowercased term is a generic word that must stay
allowed in lowercase). A term is its words as `WORD` finds them, joined by one space, at most
`MAX_WORDS` words; `digest` lowercases for `DENIED`.
"""

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]

SALT = "obs-public-check:2026-11-06:"
# A word keeps inner hyphens and dots, so a compound such as a file name is one word, and a
# term never matches part of a compound.
WORD = re.compile(r"\w+(?:[-.]\w+)*")
MAX_WORDS = 3

# Hashes of lowercased terms: matched whatever their case.
DENIED = frozenset({
    "005b25de205dbb987a62f6a3ca30c5e067ea2a70d1f5e8c09eb13e9a07e5b837",
    "04172b3de3b906f99f1f02a3061d75876051ebc4ab88107734147626f31fdf7c",
    "11ae2f91c7c893d5d69950809c256b0a314608da8704a3aed7d2379e61b4a777",
    "139ca2213b032a515894d899e13ece2a46bbb78aad42b45341a7194640b32041",
    "2fea93edf3a698f40701f4a08b37868acc3179e1663403f41328ff22edb2d53e",
    "4a4d18ae9c994a11a3bb601a4c75e5b088be11f663a40dfc7909e2519e5c8621",
    "52040bee0a6ab1b06202c94230c13d02b57f32efe1c882a3e4883c33863f28f4",
    "660cf6a4653d2ffc08e41c5990ded686ac230f8b95cc9c2cdd905697463c3fa7",
    "6e111780b14747bf6695f84a8a4a170559ff6c85eea4cccde7aaeb3742d35fb2",
    "793c2b186416a59956dbe4a36dff809366e611f147c2ad3d8222abe6cb333ca4",
    "824d5eaf7273e6c25d8ac12eb007a94536bb4386716c79ce3a070b6052cde206",
    "8574c0e9a2cdd1a90164efe7cd4facfe42da84601025e75fad006d8b14ca9544",
    "95b7691e0a0ec05df95ae1e46cb623bd0b59308a0abae3d82ca90bad90bce031",
    "a98dca56984160101ffda43c25a8e2f3d5b7376911c09883124b608fd5c55f9c",
    "c408fc91096e77f77c559755e46c31f4a9dfe71ee042b26b1be6967a44871d71",
    "c5ef433edf4715791e0e276cc41631c817e18fecd1e5e9aaff9933fb0dfebaee",
    "dcd3501bc1f16b154bc53c648ab3ba8646fffbcef3b43ed5c7462e3b8e13d0df",
    "e8314f8507c99f0eb9f461bb00d7762f353f6db1b53c3cea7f31de4cf324094e",
    "f6bfe6c901b40c92b2107c727b9d4f2eca70544b1f8895dfa7a2e65b1368a0b0",
})
# Hashes of exact-case terms whose lowercase form is a generic word that stays allowed.
DENIED_EXACT = frozenset({
    "2a61f00cdb708473cb69ff2710d68afb83eb10e6ee8c470c991ec3848b3c529d",
})


def _hash(phrase: str) -> str:
    return hashlib.sha256((SALT + phrase).encode()).hexdigest()


def digest(term: str, *, exact: bool = False) -> str:
    phrase = " ".join(WORD.findall(term))
    return _hash(phrase if exact else phrase.lower())


def denied_lines(text: str) -> list[int]:
    """The 1-based lines on which a denied term starts; terms may wrap across lines."""
    matches = list(WORD.finditer(text))
    words = [match.group(0) for match in matches]
    lines = []
    for start in range(len(words)):
        for count in range(1, min(MAX_WORDS, len(words) - start) + 1):
            phrase = " ".join(words[start:start + count])
            if (_hash(phrase.lower()) in DENIED or _hash(phrase) in DENIED_EXACT):
                lines.append(text.count("\n", 0, matches[start].start()) + 1)
                break
    return lines


def test_matching_ignores_case_and_wrapping_but_not_compounds(monkeypatch) -> None:
    monkeypatch.setattr(sys.modules[__name__], "DENIED", frozenset({digest("planted example term")}))
    monkeypatch.setattr(sys.modules[__name__], "DENIED_EXACT", frozenset({digest("Shown", exact=True)}))
    text = "one\nthe Planted example\n  TERM here\nplanted-example term\nshown\nShown\n"
    assert denied_lines(text) == [2, 6]


def scanned_files() -> list[Path]:
    return [
        path for path in sorted((ROOT / "spec").rglob("*"))
        if path.is_file() and "design_output" not in path.parts
    ]


def test_repository_names_no_denied_term() -> None:
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for path in scanned_files()
        for line in denied_lines(path.read_text(encoding="utf-8"))
    ]
    assert not found, (
        "A denied term (private work context) matched; this check never names it. Rewrite each "
        "place generically (test/structure/test_public_spec.py owns the deny list):\n"
        + "\n".join(found)
    )
