import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import ValidationError

from obs_html import timings
from obs_html.cli import DEFAULT_CONFIG, main
from obs_html.config import load_config


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 4, tzinfo=timezone.utc)


def _vault(root: Path, name: str, body: str, figure: bool = False) -> Path:
    vault = root / name
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    text = f"# {name}\n\n{body}\n"
    if figure:
        (vault / "scene.json").write_text(
            '{"version":1,"panels":[{"id":"a","title":"A","box":[0,0,100,50]}]}', encoding="utf-8",
        )
        (vault / "default.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"/>', encoding="utf-8",
        )
        text += ("\n```figure\nversion: 1\nkind: svg\nsource: scene.json\n"
                 "fallback: default.svg\ncaption: Composition\n```\n")
    (vault / "chapter.md").write_text(text, encoding="utf-8")
    return vault


def test_one_call_builds_several_documents_equal_to_separate_calls(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("obs_html.renderer.datetime", _FixedClock)
    first = _vault(tmp_path, "alpha", "First body.", figure=True)
    second = _vault(tmp_path, "beta", "Second body with a [[chapter]] link.")
    combined = tmp_path / "combined"
    separate = tmp_path / "separate"

    assert main(["--source", str(first), "--output", str(combined / "a.html"),
                 "--source", str(second), "--output", str(combined / "b.html")]) == 0
    out = capsys.readouterr().out
    assert out.count("Generated ") == 2
    assert main(["--source", str(second), "--output", str(separate / "b.html")]) == 0
    assert main(["--source", str(first), "--output", str(separate / "a.html")]) == 0

    for name in ("a.html", "b.html"):
        assert (combined / name).read_bytes() == (separate / name).read_bytes()
    assert (combined / "a.html").read_bytes() != (combined / "b.html").read_bytes()


def test_trusted_runtime_bundles_pair_with_sources_in_order(tmp_path, capsys) -> None:
    first = _vault(tmp_path, "alpha", "First.")
    second = _vault(tmp_path, "beta", "Second.")
    for vault, marker in ((first, "alpha-runtime"), (second, "beta-runtime")):
        (vault / "runtime.js").write_text(f"globalThis.marker = '{marker}';", encoding="utf-8")

    assert main([
        "--source", str(first), "--output", str(tmp_path / "a.html"),
        "--trusted-runtime-bundle", f"app-v1={first / 'runtime.js'}",
        "--source", str(second), "--output", str(tmp_path / "b.html"),
        "--trusted-runtime-bundle", f"app-v1={second / 'runtime.js'}",
    ]) == 0
    assert "alpha-runtime" in (tmp_path / "a.html").read_text(encoding="utf-8")
    assert "beta-runtime" in (tmp_path / "b.html").read_text(encoding="utf-8")
    assert "beta-runtime" not in (tmp_path / "a.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(("arguments", "message"), [
    (["--source", "a", "--source", "b", "--output", "a.html"], "one --output per --source"),
    (["--source", "a", "--output", "x.html", "--source", "b", "--output", "x.html"], "own --output"),
    (["--source", "a", "--output", "a.html", "--source", "b", "--output", "b.html",
      "--trusted-runtime-bundle", "app-v1=a/runtime.js"], "one --trusted-runtime-bundle per --source"),
])
def test_several_documents_need_unambiguous_pairs(arguments, message, capsys) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(arguments)
    assert message in capsys.readouterr().err


def test_generation_refuses_a_pdf_output_and_names_the_export_remedy(tmp_path, capsys) -> None:
    vault = _vault(tmp_path, "alpha", "First.")
    output = tmp_path / "document.PDF"

    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--output", str(output)])
    err = capsys.readouterr().err
    assert "obs-html: error: --output " in err
    assert "generation writes HTML, not PDF" in err
    assert f"--export-pdf {output.with_suffix('.html')} --output {output}" in err
    assert not output.exists()


def test_check_accepts_several_sources_without_outputs(tmp_path, capsys) -> None:
    first = _vault(tmp_path, "alpha", "First.")
    second = _vault(tmp_path, "beta", "Second.")

    assert main(["--check", "--source", str(first), "--source", str(second)]) == 0
    assert capsys.readouterr().out.count("Checked 1 chapters") == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == ["alpha", "beta"]


def test_failure_names_the_failing_source_when_several(tmp_path, capsys) -> None:
    good = _vault(tmp_path, "alpha", "First.")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.md").write_text("1. [[chapter]]\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(good), "--output", str(tmp_path / "a.html"),
              "--source", str(broken), "--output", str(tmp_path / "b.html")])
    assert f"{broken}: " in capsys.readouterr().err


def test_timings_print_one_line_per_stage(tmp_path, capsys) -> None:
    first = _vault(tmp_path, "alpha", "First.", figure=True)
    second = _vault(tmp_path, "beta", "Second.")
    outputs = [tmp_path / "a.html", tmp_path / "b.html"]

    assert main(["--timings", "--source", str(first), "--output", str(outputs[0]),
                 "--source", str(second), "--output", str(outputs[1])]) == 0
    lines = capsys.readouterr().out.splitlines()
    timed = [re.fullmatch(r"Timing: (\S+) (\d+\.\d{3}) s(?: \((.+)\))?", line) for line in lines]
    stages = [(match[1], match[3]) for match in timed if match]
    assert stages[0] == ("imports", None) and stages[-1] == ("total", None)
    labels = [str(output.resolve()) for output in outputs]
    for label in labels:
        document = [stage for stage, owner in stages if owner == label]
        assert {"parse", "provenance", "render", "write"} <= set(document)
        assert len(document) == len(set(document))
    assert ("figures", labels[0]) in stages
    assert ("figures", labels[1]) not in stages
    assert not any(line.startswith("Timing") for line, match in zip(lines, timed) if not match)


def test_without_timings_no_timing_lines(tmp_path, capsys) -> None:
    vault = _vault(tmp_path, "alpha", "First.")
    assert main(["--source", str(vault), "--output", str(tmp_path / "a.html")]) == 0
    assert "Timing" not in capsys.readouterr().out


def test_nested_stages_record_exclusive_durations(monkeypatch) -> None:
    clock = iter([0.0, 1.0, 3.0, 6.0, 10.0, 15.0])
    monkeypatch.setattr(timings, "perf_counter", lambda: next(clock))
    with timings.recording() as recorded:
        with timings.stage("render"):
            with timings.stage("figures"):
                pass
            with timings.stage("figures"):
                pass
    assert recorded.durations == {"render": 1.0 + 3.0 + 5.0, "figures": 2.0 + 4.0}


def test_stages_outside_a_recording_are_free(monkeypatch) -> None:
    monkeypatch.setattr(timings, "perf_counter", lambda: pytest.fail("clock read without recording"))
    with timings.stage("render"):
        pass


def test_unregistered_stage_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unregistered build stage: bogus"):
        with timings.stage("bogus"):
            pass


def test_help_names_every_registered_stage(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    for name, description in timings.STAGES.items():
        assert f"{name} ({description})" in help_text


def test_producers_are_their_own_stage_before_conversion(tmp_path, monkeypatch, capsys) -> None:
    vault = _vault(tmp_path, "alpha", "```cmd silent\nproduce\n```")
    monkeypatch.setattr(
        "obs.producers.subprocess.run",
        lambda command, **_: subprocess.CompletedProcess(command, 0, ""),
    )
    output = tmp_path / "a.html"
    assert main(["--timings", "--execute-commands", "--source", str(vault), "--output", str(output)]) == 0
    stages = re.findall(r"^Timing: (\S+) \d+\.\d{3} s \(", capsys.readouterr().out, re.MULTILINE)
    assert stages.index("producers") < stages.index("render")


def test_stage_durations_do_not_overlap_and_sum_to_at_most_the_total(tmp_path, capsys) -> None:
    vault = _vault(tmp_path, "alpha", "Body.", figure=True)
    assert main(["--timings", "--source", str(vault), "--output", str(tmp_path / "a.html")]) == 0
    timed = re.findall(r"^Timing: (\S+) (\d+\.\d{3}) s(?: \((.+)\))?$", capsys.readouterr().out, re.MULTILINE)
    document = {name: float(seconds) for name, seconds, label in timed if label}
    call = {name: float(seconds) for name, seconds, label in timed if not label}
    assert set(document) <= set(timings.STAGES)
    assert {"parse", "render", "figures", "write"} <= set(document)
    parts = [*document.values(), call["imports"], call["provenance"]]
    assert sum(parts) <= call["total"] + 0.0005 * (len(parts) + 1)  # three-decimal rounding


def test_packaged_baselines_cover_only_registered_stages() -> None:
    baselines = timings.load_baselines()
    assert baselines and set(baselines) <= set(timings.STAGES)
    assert all(seconds > 0 for seconds in baselines.values())


@pytest.mark.parametrize(
    ("stages", "error"),
    [({"render": -1.0}, ValidationError), ({"render": "fast"}, ValidationError),
     ({"bogus": 1.0}, ValueError)],
)
def test_invalid_baselines_are_rejected(tmp_path, stages, error) -> None:
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps({"schemaVersion": 1, "stages": stages}), encoding="utf-8")
    with pytest.raises(error):
        timings.load_baselines(path)


@pytest.mark.parametrize(
    ("seconds", "warned"),
    [(0.04, False),   # +300 % but only +0.03 s: relative threshold alone
     (10.5, False),   # +0.5 s but only +5 %: absolute threshold alone
     (16.0, True)],   # +60 % and +6 s: both thresholds
)
def test_a_stage_warns_only_above_both_thresholds(seconds, warned) -> None:
    baselines = {"parse": 0.01, "render": 10.0}
    stage = "parse" if seconds < 1 else "render"
    warnings = timings.slower_stages({stage: seconds}, baselines, relative=0.5, absolute_seconds=0.25)
    assert bool(warnings) == warned
    if warned:
        assert warnings == ["stage render took 16.000 s, 60% and 6.000 s over its baseline of 10.000 s."]


def test_stages_without_a_baseline_are_not_compared() -> None:
    assert timings.slower_stages({"figures": 99.0}, {}, relative=0.5, absolute_seconds=0.25) == []


@pytest.mark.parametrize("timing", [{"relativeThreshold": 0}, {"absoluteThresholdSeconds": -1},
                                    {"relativeThreshold": "half"}, {"unknown": 1}])
def test_invalid_timing_thresholds_are_rejected(tmp_path, timing) -> None:
    override = tmp_path / "cfg.json"
    override.write_text(json.dumps({"schemaVersion": 1, "timings": timing}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(DEFAULT_CONFIG, override)


def test_a_slow_stage_warns_without_failing_the_build(tmp_path, monkeypatch, capsys) -> None:
    vault = _vault(tmp_path, "alpha", "Body.")
    (vault / "cfg.json").write_text(json.dumps(
        {"schemaVersion": 1, "timings": {"relativeThreshold": 0.01, "absoluteThresholdSeconds": 0.000001}},
    ), encoding="utf-8")
    monkeypatch.setattr("obs_html.cli.load_baselines", lambda: {"render": 0.0000001})
    output = tmp_path / "a.html"
    assert main(["--timings", "--source", str(vault), "--output", str(output)]) == 0
    captured = capsys.readouterr()
    assert output.is_file()
    assert re.search(rf"^Warning: {re.escape(str(output.resolve()))}: stage render took ", captured.err, re.MULTILINE)
    assert "Warning:" not in captured.out


def test_without_timings_no_baseline_warnings(tmp_path, monkeypatch, capsys) -> None:
    vault = _vault(tmp_path, "alpha", "Body.")
    monkeypatch.setattr("obs_html.cli.load_baselines", lambda: pytest.fail("baselines read without --timings"))
    assert main(["--source", str(vault), "--output", str(tmp_path / "a.html")]) == 0
    assert "baseline" not in capsys.readouterr().err
