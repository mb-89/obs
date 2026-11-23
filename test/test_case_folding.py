"""The core's case-folding table, src/obs/case-folding.json, is what its generator writes.

Reader: whoever changes the case-folding table, its generator obs.case_folding, or the Unicode
version it is built from.

capabilities/bases#Comparisons owns the rule the table holds; generated.yaml declares the generator
and names this file as the test that reruns it.
"""
from pathlib import Path

from obs import case_folding

ROOT = Path(__file__).parents[1]


def test_the_generator_reproduces_the_committed_table_byte_for_byte() -> None:
    source = (ROOT / case_folding.SOURCE).read_text(encoding="utf-8")

    assert case_folding.table(source).encode("utf-8") == (ROOT / case_folding.OUTPUT).read_bytes()


def test_the_table_holds_the_full_foldings_and_no_turkic_or_simple_one() -> None:
    source = "\n".join([
        "# CaseFolding-99.0.0.txt",
        "0041; C; 0061; # LATIN CAPITAL LETTER A",
        "00DF; F; 0073 0073; # LATIN SMALL LETTER SHARP S",
        "0049; T; 0131; # LATIN CAPITAL LETTER I",
        "1E9E; S; 00DF; # LATIN CAPITAL LETTER SHARP S",
        "1E921; C; 1E943; # ADLAM CAPITAL LETTER SHA",
        "",
    ])

    table = case_folding.table(source)

    assert table.splitlines()[1:] == [
        '"unicode":"99.0.0",',
        '"folds":{"0041":"a",',
        '"00DF":"ss",',
        '"1E921":"\\ud83a\\udd43"}}',
    ]


def test_check_names_a_stale_table_and_the_command_that_writes_it(tmp_path: Path) -> None:
    source = tmp_path / "CaseFolding.txt"
    source.write_text("# CaseFolding-99.0.0.txt\n0041; C; 0061; # A\n", encoding="utf-8")
    output = tmp_path / "case-folding.json"
    output.write_text("{}\n", encoding="utf-8")
    paths = ["--source", str(source), "--output", str(output)]

    assert case_folding.main([*paths, "--check"]) == 1
    assert case_folding.main(paths) == 0
    assert case_folding.main([*paths, "--check"]) == 0
    assert output.read_text(encoding="utf-8") == case_folding.table(source.read_text(encoding="utf-8"))
