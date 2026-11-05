import json
import os
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from obs_html.report_data import decode_report_data

from obs_html.cli import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    build_parser,
    main,
    resolve_manifest,
    _documents,
    _write_if_changed,
)


def test_help_is_available(capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])
    assert "Generate HTML documents" in capsys.readouterr().out


def test_help_is_the_complete_cli_reference() -> None:
    help_text = build_parser().format_help()
    for section in ("Generation:", "Reproduction sources:", "PDF operations:", "Comment extraction:",
                    "Examples:", "Exit status:"):
        assert section in help_text
    for term in ("transitive", "non-hidden", "signed", "outside", "stderr", "playwright install chromium"):
        assert term in help_text
    assert "--trusted-runtime-bundle ID=PATH" in help_text
    assert "--embed-source additionally retains it for source reproduction" in help_text
    assert str(DEFAULT_SOURCE) in help_text
    assert str(DEFAULT_OUTPUT) in help_text


@pytest.mark.parametrize("argument", ["--source=vault", "--config=cfg.json"])
def test_pdf_rejects_generation_options_in_equals_form(argument, capsys) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--export-pdf", "report.html", "--output=report.pdf", argument])
    assert "cannot be combined" in capsys.readouterr().err


def test_pdf_accepts_equals_output(tmp_path, monkeypatch) -> None:
    output = tmp_path / "report.pdf"
    monkeypatch.setattr("obs_html.pdf.export_pdf", lambda _path: b"pdf fixture")
    assert main(["--export-pdf=report.html", f"--output={output}"]) == 0
    assert output.read_bytes() == b"pdf fixture"


def test_parser_defaults_to_the_tools_spec_folder() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert _documents(parser, args) == [(DEFAULT_SOURCE, DEFAULT_OUTPUT, None)]
    assert args.config == DEFAULT_CONFIG


def test_parser_accepts_path_overrides() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["--source", "vault", "--output", "report", "--config", "custom.json"]
    )

    assert _documents(parser, args) == [(Path("vault"), Path("report"), None)]
    assert args.config == Path("custom.json")


def test_source_folder_resolves_its_manifest(tmp_path) -> None:
    assert resolve_manifest(tmp_path, "manifest.md") == tmp_path / "manifest.md"


def test_explicit_manifest_is_unchanged(tmp_path) -> None:
    manifest = tmp_path / "contents.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")

    assert resolve_manifest(manifest, "manifest.md") == manifest


def test_cli_generates_one_html_file(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Generated\n\nBody.", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    output = tmp_path / "output" / "report.html"

    assert main(["--source", str(vault), "--output", str(output)]) == 0

    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "Generated" in decode_report_data(output.read_text(encoding="utf-8"))["notes"][1]["html"]
    assert "from 1 chapters" in capsys.readouterr().out


def test_cli_records_generator_and_target_repository_provenance(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "target-repository" / "vault"
    vault.mkdir(parents=True)
    (vault / "chapter.md").write_text("# Generated\n", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    output = tmp_path / "report.html"
    calls = []

    def provenance(path):
        calls.append(Path(path))
        if len(calls) == 1:
            return {"name": "obs-html", "version": "generator-git-description", "commit": "a" * 40}
        return {"name": "reference", "version": "release-7-dirty", "commit": "b" * 40}

    monkeypatch.setattr("obs_html.cli._repository_provenance", provenance)
    monkeypatch.setattr("obs_html.cli.version", lambda _name: "1.2.3")
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    generation = decode_report_data(output.read_text(encoding="utf-8"))["document"]["generation"]
    assert list(generation) == ["timestamp", "generator", "target"]
    assert generation["generator"] == {
        "name": "obs-html", "version": "generator-git-description", "commit": "a" * 40,
    }
    assert generation["target"] == {"name": "reference", "version": "release-7-dirty", "commit": "b" * 40}
    assert generation["timestamp"]
    assert len(calls) == 2


def test_generator_version_falls_back_to_package_version_outside_git(monkeypatch) -> None:
    from obs_html.cli import _generator_provenance

    monkeypatch.setattr("obs_html.cli._repository_provenance",
                        lambda _path: {"name": "obs_html", "version": "unknown", "commit": "unknown"})
    monkeypatch.setattr("obs_html.cli.version", lambda _name: "1.2.3")
    assert _generator_provenance() == {"name": "obs_html", "version": "1.2.3", "commit": "unknown"}


def test_repository_provenance_records_short_commit_hash(tmp_path) -> None:
    import subprocess
    from obs_html.cli import _repository_provenance

    repository = tmp_path / "target"
    repository.mkdir()
    git = ["git", "-C", str(repository), "-c", "user.name=t", "-c", "user.email=t@t",
           "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], check=True)
    (repository / "file.txt").write_text("x", encoding="utf-8")
    subprocess.run([*git, "add", "file.txt"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    short = subprocess.run([*git, "rev-parse", "--short", "HEAD"], check=True,
                           capture_output=True, text=True).stdout.strip()
    provenance = _repository_provenance(repository)
    assert provenance["commit"] == short
    assert len(short) < 40
    assert provenance == {"name": "target", "version": short, "commit": short}


def test_trusted_runtime_can_be_embedded_without_source_archive(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Generated", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "runtime.js").write_text("globalThis.trustedFixture = true;", encoding="utf-8")
    output = tmp_path / "report.html"
    assert main([
        "--source", str(vault), "--output", str(output),
        "--trusted-runtime-bundle", "fixture-v1=" + str(vault / "runtime.js"),
    ]) == 0
    html = output.read_text(encoding="utf-8")
    assert '<meta name="obs-trusted-runtime" content="fixture-v1">' in html
    assert 'id="trusted-application-runtime"' in html
    assert 'id="zip-rewrite-script"' in html
    assert 'id="payload-script"' in html
    from obs_html.reproduction import embedded_archive
    assert embedded_archive(html) is None


def test_cli_embeds_only_the_explicit_trusted_runtime(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Generated", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    runtime = vault / "runtime.js"
    runtime.write_text("globalThis.trustedFixture = true;", encoding="utf-8")
    archive = BytesIO()
    with ZipFile(archive, "w"):
        pass
    monkeypatch.setattr("obs_html.cli.source_archive", lambda *_args: archive.getvalue())
    output = tmp_path / "report.html"
    assert main([
        "--source", str(vault), "--output", str(output), "--embed-source",
        "--trusted-runtime-bundle", f"fixture-v1={runtime}",
    ]) == 0
    html = output.read_text(encoding="utf-8")
    assert '<meta name="obs-trusted-runtime" content="fixture-v1">' in html
    assert 'id="trusted-application-runtime"' in html
    assert "globalThis.trustedFixture = true;" in html


def test_cli_rejects_runtime_outside_the_selected_vault(tmp_path, monkeypatch, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Generated", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    runtime = tmp_path / "runtime.js"
    runtime.write_text("globalThis.trustedFixture = true;", encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main([
            "--source", str(vault), "--output", str(tmp_path / "report.html"),
            "--embed-source", "--trusted-runtime-bundle", f"fixture-v1={runtime}",
        ])
    assert "must be a regular file inside the selected vault" in capsys.readouterr().err


def test_cli_checks_and_generates_explicitly_empty_cover_title(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Chapter\n\nEvidence.", encoding="utf-8")
    manifest = vault / "My document.md"
    manifest.write_text(
        "---\ntitle: ''\nsubtitle: Source → Target\n---\n- [[chapter]]\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.html"
    assert main(["--source", str(manifest), "--output", str(output), "--check"]) == 0
    assert not output.exists()
    assert main(["--source", str(manifest), "--output", str(output)]) == 0
    report = output.read_text(encoding="utf-8")
    data = decode_report_data(report)
    assert "<title>My document</title>" in report
    assert "document-title" not in data["notes"][0]["html"]
    assert "Source → Target" in data["notes"][0]["html"]
    assert "from 1 chapters" in capsys.readouterr().out


def test_cli_check_rejects_protected_editor_projection(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text(
        "---\ntitle: Original\nexplanation: Original\n---\n# Chapter\n\n"
        "```property-editor\nversion: 1\nfield: explanation\nlabel: Review\n"
        "projection:\n  blank: {title: Changed}\n  nonblank: {title: Original}\n```\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.html"
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--output", str(output), "--check"])
    assert "Property editor" in capsys.readouterr().err
    assert not output.exists()


def test_check_validates_commands_without_execution_or_output(tmp_path, monkeypatch, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Chapter\n\n```cmd\nmust-not-run\n```\n", encoding="utf-8")
    def unexpected_execution(*args, **kwargs):
        pytest.fail("Check mode executed an authored command.")
    monkeypatch.setattr("obs_html.cli.run_command", unexpected_execution)
    output = tmp_path / "not-created" / "report.html"
    assert main(["--source", str(vault), "--output", str(output), "--check"]) == 0
    assert not output.parent.exists()
    assert "no commands executed" in capsys.readouterr().out
    (vault / "chapter.md").write_text("# Chapter\n\n[[missing]]", encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--check"])
    assert "Unresolved note reference" in capsys.readouterr().err


def test_authorized_silent_producers_create_inputs_before_conversion(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[producer]]\n- [[generated]]\n", encoding="utf-8")
    (vault / "producer.md").write_text(
        "# Producer\n\n```cmd silent\n"
        "copy /Y template.svg generated.svg > NUL & copy /Y template.md generated.md > NUL\n"
        "```\n",
        encoding="utf-8",
    )
    (vault / "template.svg").write_text("<svg/>", encoding="utf-8")
    (vault / "template.md").write_text(
        "# Generated\n\nGenerated note.\n\n![Producer figure](generated.svg)\n", encoding="utf-8",
    )
    output = tmp_path / "report.html"

    assert main(["--source", str(vault), "--output", str(output), "--execute-commands"]) == 0

    report = output.read_text(encoding="utf-8")
    data = decode_report_data(report)
    generated = next(note for note in data["notes"] if note["slug"] == "generated")
    assert "Generated note." in generated["html"]
    assert 'src="data:image/svg+xml;base64,PHN2Zy8+" alt="Producer figure" />' in generated["html"]
    assert "copy /Y template.svg" not in report


@pytest.mark.parametrize("check", [False, True])
def test_unauthorized_silent_producers_use_existing_artifacts_without_execution(
    tmp_path, check,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[producer]]\n- [[generated]]\n", encoding="utf-8")
    (vault / "producer.md").write_text(
        "# Producer\n\n```cmd silent\nmust-not-run\n```\n", encoding="utf-8",
    )
    (vault / "generated.md").write_text("# Generated\n\nExisting artifact.\n", encoding="utf-8")
    output = tmp_path / "report.html"
    arguments = ["--source", str(vault), "--output", str(output)]
    if check:
        arguments.append("--check")

    assert main(arguments) == 0

    if check:
        assert not output.exists()
    else:
        data = decode_report_data(output.read_text(encoding="utf-8"))
        generated = next(note for note in data["notes"] if note["slug"] == "generated")
        assert "Existing artifact." in generated["html"]


def test_unauthorized_silent_producer_missing_artifact_fails_clearly(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[producer]]\n- [[generated]]\n", encoding="utf-8")
    (vault / "producer.md").write_text(
        "# Producer\n\n```cmd silent\nmust-not-run\n```\n", encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--output", str(tmp_path / "report.html")])

    assert "Manifest target does not exist: generated" in capsys.readouterr().err


def test_conversion_failure_after_authorized_producer_preserves_previous_output(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[producer]]\n- [[generated]]\n", encoding="utf-8")
    (vault / "producer.md").write_text(
        "# Producer\n\n```cmd silent\ncopy /Y template.md generated.md > NUL\n```\n",
        encoding="utf-8",
    )
    (vault / "template.md").write_text("# Generated\n\n[[missing]]\n", encoding="utf-8")
    output = tmp_path / "report.html"
    output.write_text("previous report", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--output", str(output), "--execute-commands"])

    assert output.read_text(encoding="utf-8") == "previous report"


def test_cli_checks_and_renders_card_metric_links_and_base_queries(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    card = {
        "version": 1,
        "cards": [{
            "title": "Evidence",
            "body": (
                "```base\n"
                "filters:\n"
                "  and: ['kind == \"evidence\"']\n"
                "obsHtml: {records: note}\n"
                "views:\n"
                "  - type: table\n"
                "    name: Evidence\n"
                "    order: [label]\n"
                "```"
            ),
            "metrics": [{
                "label": "Evidence",
                "where": [{"field": "kind", "equals": "evidence"}],
                "link": "#home/@table-group--home-base-1--kind--evidence?tableFilter=kind%3Aevidence",
            }],
        }],
    }
    (vault / "manifest.md").write_text(
        "- [[chapter]]\n\n```cards\n" + json.dumps(card) + "\n```\n",
        encoding="utf-8",
    )
    (vault / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    (vault / "evidence.md").write_text(
        "---\nkind: evidence\nlabel: Canonical evidence\n---\nEvidence details.\n",
        encoding="utf-8",
    )
    output = tmp_path / "output" / "report.html"

    assert main(["--source", str(vault), "--check"]) == 0
    assert not output.exists()
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    report = output.read_text(encoding="utf-8")
    data = decode_report_data(report)
    home = next(note for note in data["notes"] if note["slug"] == "home")
    assert 'data-base-table="home-base-1"' in home["html"]
    assert any(note["slug"] == "evidence" for note in data["notes"])
    assert "no commands executed" in capsys.readouterr().out


def test_check_rejects_broken_view_members(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[register]]\n", encoding="utf-8")
    (vault / "register.md").write_text(
        "# Register\n\n```base\nfilters: 'kind == \"reference\"'\n"
        "views:\n  - type: table\n    order: [document]\n"
        "obsHtml:\n  members:\n    - path: ../outside.md\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--check"])
    assert "Invalid base definition" in capsys.readouterr().err

    (vault / "register.md").write_text(
        "# Register\n\n```base\nfilters: 'kind == \"reference\"'\n"
        "views:\n  - type: table\n    order: [document]\n"
        "obsHtml:\n  members:\n    - path: missing.md\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--check"])
    assert "does not resolve to a Markdown note" in capsys.readouterr().err

    (vault / "register.md").write_text(
        "# Register\n\n```base\nviews:\n  - type: table\n    order: [document]\n"
        "obsHtml:\n  members:\n    - path: chapter.md\n    - path: chapter.md\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--check"])
    assert "Duplicate obsHtml.members path" in capsys.readouterr().err


def test_cli_checks_and_renders_quantity_notes(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "chapter.md").write_text("# Chapter\n\nRequirement [[flatness_A]].\n", encoding="utf-8")
    quantity = vault / "flatness.md"
    quantity.write_text(
        "---\nkind: quantity\nvalue: 20\nunit: µm\naliases: [flatness_A]\n"
        "source: '[[drawing]]'\n---\n# Datum A flatness\n\n"
        "Drawing limit, total zone width.\n",
        encoding="utf-8",
    )
    (vault / "drawing.md").write_text("# Drawing\n", encoding="utf-8")
    output = tmp_path / "report.html"

    assert main(["--source", str(vault), "--check"]) == 0
    assert not output.exists()
    assert main(["--source", str(vault), "--output", str(output)]) == 0
    report = output.read_text(encoding="utf-8")
    store = re.search(r'<script id="report-data"[^>]*>(.*?)</script>', report, re.DOTALL)
    assert store
    data = decode_report_data(store[0])
    chapter = next(note for note in data["notes"] if note["slug"] == "chapter")
    assert '<a href="#flatness">20 µm</a>' in chapter["html"]
    capsys.readouterr()

    quantity.write_text(
        "---\nkind: quantity\nvalue: .nan\nunit: µm\naliases: [flatness_A]\n"
        "source: '[[drawing]]'\n---\n# Datum A flatness\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(vault), "--check"])
    assert "finite" in capsys.readouterr().err


def test_check_rejects_command_execution(capsys) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--check", "--execute-commands"])
    assert "cannot be combined" in capsys.readouterr().err


def test_atomic_write_failure_preserves_previous_report_and_removes_temporary_file(
    tmp_path, monkeypatch,
) -> None:
    output = tmp_path / "report.html"
    output.write_text("previous report", encoding="utf-8")
    def fail_replace(_source, _destination):
        raise OSError("Replacement denied")
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="Replacement denied"):
        _write_if_changed(output, "new report")
    assert output.read_text(encoding="utf-8") == "previous report"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report.html"]


def test_second_identical_build_writes_no_files(tmp_path, monkeypatch) -> None:
    from datetime import datetime, timezone

    import obs_html.cli as cli
    import obs_html.renderer as renderer

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Generated\n\nBody.", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    output = tmp_path / "output" / "document.html"
    arguments = ["--source", str(vault), "--output", str(output)]
    builds = iter(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00",
                   "2026-01-03T00:00:00+00:00"])

    class BuildClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(next(builds)).astimezone(tz)

    monkeypatch.setattr(renderer, "datetime", BuildClock)
    assert main(arguments) == 0
    first = output.read_bytes()
    os.utime(output, ns=(1_000_000_000, 1_000_000_000))
    temporary_files = []
    named_temporary_file = cli.tempfile.NamedTemporaryFile

    def counted_temporary_file(*args, **kwargs):
        temporary_files.append(kwargs.get("dir"))
        return named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(cli.tempfile, "NamedTemporaryFile", counted_temporary_file)

    assert main(arguments) == 0

    assert temporary_files == []
    assert output.stat().st_mtime_ns == 1_000_000_000
    assert output.read_bytes() == first
    assert decode_report_data(first.decode("utf-8"))["document"]["generation"]["timestamp"] == (
        "2026-01-01T00:00:00+00:00")
    assert sorted(path.name for path in output.parent.iterdir()) == ["document.html"]

    (vault / "chapter.md").write_text("# Generated\n\nChanged body.", encoding="utf-8")
    assert main(arguments) == 0

    assert len(temporary_files) == 1
    changed = decode_report_data(output.read_text(encoding="utf-8"))
    assert changed["document"]["generation"]["timestamp"] == "2026-01-03T00:00:00+00:00"
    assert "Changed body." in changed["notes"][1]["html"]


def test_pdf_writer_skips_identical_bytes(tmp_path, monkeypatch) -> None:
    output = tmp_path / "document.pdf"
    assert _write_if_changed(output, b"%PDF-1.7 same") is True
    os.utime(output, ns=(1_000_000_000, 1_000_000_000))
    assert _write_if_changed(output, b"%PDF-1.7 same") is False
    assert output.stat().st_mtime_ns == 1_000_000_000
    assert _write_if_changed(output, b"%PDF-1.7 other") is True
    assert output.read_bytes() == b"%PDF-1.7 other"


def test_project_config_replaces_default_filter_presets(tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text("# Generated", encoding="utf-8")
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "cfg.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "report": {
                "filterPresets": [
                    {"label": "Generated only", "expression": "title: Generated"}
                ]
            },
        }),
        encoding="utf-8",
    )
    output = tmp_path / "report.html"

    assert main(["--source", str(vault), "--output", str(output)]) == 0

    report = output.read_text(encoding="utf-8")
    store = re.search(r'<script id="report-data"[^>]*>(.*?)</script>', report, re.DOTALL)
    assert store
    data = decode_report_data(store[0])
    assert data["filterPresets"] == [
        {"label": "Generated only", "expression": "title: Generated"}
    ]
    assert "from 1 chapters" in capsys.readouterr().out


def test_cli_extracts_comments_without_generating(tmp_path, capsys) -> None:
    report = tmp_path / "reviewed.html"
    report.write_text(
        '<script id="obs-comments" type="application/json">'
        '{"version":2,"annotations":[],"reviewers":[],"reviews":[]}'
        "</script>",
        encoding="utf-8",
    )

    assert main(["--extract-comments", str(report)]) == 0

    assert capsys.readouterr().out == "comment candidates: 0\n"


def test_cli_rejects_output_inside_source_vault(tmp_path, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path / "report.html")])

    assert "Output must be outside the source vault" in capsys.readouterr().err


def test_project_can_enable_a_tag_border(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text(
        "Watch this. #mark/risk/delay\n", encoding="utf-8"
    )
    (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (vault / "cfg.json").write_text(
        json.dumps({"report": {"borderedTags": ["risk"]}}), encoding="utf-8"
    )
    output = tmp_path / "report.html"

    assert main(["--source", str(vault), "--output", str(output)]) == 0

    store = re.search(
        r'<script id="report-data"[^>]*>(.*?)</script>',
        output.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert store
    chapter = decode_report_data(store[0])["notes"][1]
    assert '<section class="content-card">' in chapter["html"]
    assert '<header class="content-card-title">Risk</header>' in chapter["html"]


@pytest.mark.parametrize("tags", [["unknown"], ["risk", "risk"]])
def test_project_rejects_invalid_bordered_tags(tmp_path, capsys, tags) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"borderedTags": tags}}), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path.parent / "report.html")])

    assert "borderedTags" in capsys.readouterr().err


def test_project_overrides_initial_table_page_size(tmp_path) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"tablePageSize": 7}}), encoding="utf-8"
    )
    output = tmp_path.parent / f"{tmp_path.name}.html"

    assert main(["--source", str(tmp_path), "--output", str(output)]) == 0
    store = re.search(
        r'<script id="report-data"[^>]*>(.*?)</script>',
        output.read_text(encoding="utf-8"), re.DOTALL,
    )
    assert store and decode_report_data(store[0])["tablePageSize"] == 7


@pytest.mark.parametrize("size", [0, -1, 1.5, "20"])
def test_project_rejects_invalid_table_page_size(tmp_path, size, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"tablePageSize": size}}), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path.parent / "out.html")])
    assert "tablePageSize" in capsys.readouterr().err


def test_project_overrides_hover_card_limits(tmp_path) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"hoverCard": {"excerptCharacters": 100, "metadataEntries": 0}}}),
        encoding="utf-8",
    )
    output = tmp_path.parent / f"{tmp_path.name}.html"
    assert main(["--source", str(tmp_path), "--output", str(output)]) == 0
    store = re.search(
        r'<script id="report-data"[^>]*>(.*?)</script>',
        output.read_text(encoding="utf-8"), re.DOTALL,
    )
    assert store
    preview = decode_report_data(store[0])["hoverCard"]
    assert preview["excerptCharacters"] == 100
    assert preview["metadataEntries"] == 0
    assert preview["showDelayMilliseconds"] >= 0


def test_project_overrides_reading_and_print_readiness(tmp_path, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {
            "printReadyTimeoutMilliseconds": 8000,
            "reading": {"paragraphWarningLines": 4, "headingSpaceBeforeEm": 1,
                        "headingSpaceAfterEm": 0.25, "paragraphMinimumLines": 3},
        }}),
        encoding="utf-8",
    )
    output = tmp_path.parent / f"{tmp_path.name}.html"
    assert main(["--source", str(tmp_path), "--output", str(output)]) == 0
    store = re.search(
        r'<script id="report-data"[^>]*>(.*?)</script>',
        output.read_text(encoding="utf-8"), re.DOTALL,
    )
    assert store
    paper = decode_report_data(store[0])["paper"]
    assert paper == {"widthMillimeters": 210, "heightMillimeters": 297, "marginMillimeters": 20}
    assert decode_report_data(store[0])["printReadyTimeoutMilliseconds"] == 8000
    assert decode_report_data(store[0])["reading"] == {
        "theme": "light", "paged": True, "codeFontPoints": 8,
        "headingSpaceBeforeEm": 1, "headingSpaceAfterEm": 0.25, "paragraphMinimumLines": 3,
        "pingPeriodMilliseconds": 250, "pingCount": 4, "pingScale": 6,
    }


def test_project_accepts_ping_scale_at_configured_limit(tmp_path) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"reading": {"pingScale": 10}}}),
        encoding="utf-8",
    )
    output = tmp_path.parent / f"{tmp_path.name}.html"

    assert main(["--source", str(tmp_path), "--output", str(output)]) == 0
    store = re.search(
        r'<script id="report-data"[^>]*>(.*?)</script>',
        output.read_text(encoding="utf-8"), re.DOTALL,
    )
    assert store
    assert decode_report_data(store[0])["reading"]["pingScale"] == 10


@pytest.mark.parametrize("embed", [True, False])
def test_pdf_embedding_can_be_disabled_without_affecting_other_assets(tmp_path, embed):
    (tmp_path / "chapter.md").write_text("# Chapter\n\n![PDF](source.pdf) ![Other](source.txt)")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n")
    (tmp_path / "source.pdf").write_bytes(b"%PDF-example")
    (tmp_path / "source.txt").write_text("Other attachment")
    (tmp_path / "cfg.json").write_text(json.dumps({"report": {"embedPdfs": embed}}))
    output = tmp_path.parent / f"{tmp_path.name}.html"
    assert main(["--source", str(tmp_path), "--output", str(output), "--embed-attachments"]) == 0
    report = output.read_text(encoding="utf-8")
    decoded = json.dumps(decode_report_data(report))
    assert ("data:application/pdf;base64," in decoded) == embed
    assert "data:application/octet-stream;base64," in decoded
    if not embed:
        assert (tmp_path / "source.pdf").as_uri() in decoded


def test_project_figure_dimensions_are_configurable_and_bounded(tmp_path, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"figures": {
            "proseWidthMultiplier": 1.8, "viewportGutterRem": 1.25, "viewportHeightRatio": 0.65,
        }}}),
        encoding="utf-8",
    )
    output = tmp_path.parent / f"{tmp_path.name}.html"

    assert main(["--source", str(tmp_path), "--output", str(output)]) == 0
    report = output.read_text(encoding="utf-8")
    data = decode_report_data(report)
    assert {key: data["figures"][key] for key in (
        "proseWidthMultiplier", "viewportGutterRem", "viewportHeightRatio",
    )} == {
        "proseWidthMultiplier": 1.8, "viewportGutterRem": 1.25, "viewportHeightRatio": 0.65,
    }
    assert data["figures"]["plotlyDelivery"] == "embedded"
    output.unlink()
    for invalid in ({"proseWidthMultiplier": 2.6}, {"viewportHeightRatio": 0.2},
                    {"viewportHeightRatio": 1.1}):
        (tmp_path / "cfg.json").write_text(
            json.dumps({"report": {"figures": invalid}}), encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="2"):
            main(["--source", str(tmp_path), "--output", str(output)])
        assert "figures" in capsys.readouterr().err


@pytest.mark.parametrize("reading", [
    {"paragraphWarningLines": 0}, {"paragraphLineCharacters": 0},
    {"codeFontPoints": 0}, {"paged": "true"}, {"theme": "sepia"},
    {"pingPeriodMilliseconds": 0}, {"pingCount": 0}, {"pingScale": 1},
    {"pingScale": 11},
    {"headingSpaceBeforeEm": -1}, {"headingSpaceBeforeEm": 3},
    {"headingSpaceAfterEm": -1}, {"headingSpaceAfterEm": 2},
    {"paragraphMinimumLines": 1}, {"paragraphMinimumLines": 5},
])
def test_project_rejects_invalid_reading_settings(tmp_path, reading, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(json.dumps({"report": {"reading": reading}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path.parent / "out.html")])
    assert "reading" in capsys.readouterr().err


@pytest.mark.parametrize(("removed", "replacement"), [
    ({"theme": "dark"}, "Light appearance"), ({"paged": False}, "obsHtml: {layout: paged}"),
])
def test_project_rejects_removed_startup_settings_with_replacement(
    tmp_path, removed, replacement, capsys,
) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(json.dumps({"report": {"reading": removed}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path.parent / "out.html")])
    error = capsys.readouterr().err
    assert f"report.reading.{next(iter(removed))} was removed" in error
    assert replacement in error


def test_paragraph_warnings_are_converter_only_and_source_located(tmp_path, capsys) -> None:
    manifest = tmp_path / "manifest.md"
    manifest.write_text("- [[chapter]]\n", encoding="utf-8")
    note = tmp_path / "chapter.md"
    prefix = "---\nstatus: draft\n---\n# Chapter\n\n"
    note.write_text(prefix + "word " * 80 + "\n\n```text\n" + "code " * 300 + "\n```\n",
                    encoding="utf-8")
    assert main(["--source", str(tmp_path), "--check"]) == 0
    assert capsys.readouterr().err == ""
    note.write_text(prefix + "word " * 81, encoding="utf-8")
    assert main(["--source", str(tmp_path), "--check"]) == 0
    warning = capsys.readouterr().err
    assert f"{note}:6: long paragraph (6 estimated lines" in warning
    assert not (tmp_path / "report.html").exists()
    output = tmp_path.parent / f"{tmp_path.name}.html"
    assert main(["--source", str(tmp_path), "--output", str(output)]) == 0
    assert "Warning:" in capsys.readouterr().err
    html = output.read_text(encoding="utf-8")
    assert "data-paragraph-lines" not in html
    assert "data-reading-status" not in html
    assert "long paragraph" not in html
    note.write_text(prefix + "word " * 40 + "\n\n" + "word " * 41, encoding="utf-8")
    assert main(["--source", str(tmp_path), "--check"]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("check", [False, True])
def test_paragraph_diagnostics_reuse_collected_body_parse_and_source(
    tmp_path, monkeypatch, capsys, check,
) -> None:
    from markdown_it import MarkdownIt

    note = tmp_path / "chapter.md"
    body = "# Chapter\n\n" + "word " * 81 + "\n"
    note.write_text("---\nstatus: draft\n---\n" + body, encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    counts = {"body_parses": 0, "source_reads": 0}
    original_parse, original_read = MarkdownIt.parse, Path.read_text

    def parse(markdown, source, *args, **kwargs):
        if source == body:
            counts["body_parses"] += 1
        return original_parse(markdown, source, *args, **kwargs)

    def read(path, *args, **kwargs):
        if path == note:
            counts["source_reads"] += 1
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(MarkdownIt, "parse", parse)
    monkeypatch.setattr(Path, "read_text", read)
    output = tmp_path.parent / f"{tmp_path.name}.html"
    arguments = ["--source", str(tmp_path), "--output", str(output)]
    assert main(arguments + (["--check"] if check else [])) == 0
    assert output.exists() == (not check)
    captured = capsys.readouterr()
    assert captured.err == (
        f"Warning: {note}:6: long paragraph "
        "(6 estimated lines at 80 characters; maximum 5). "
        "Split it into shorter paragraphs.\n"
    )
    assert "long paragraph" not in captured.out
    assert counts == {"body_parses": 2, "source_reads": 1}


def test_home_paragraph_diagnostics_measure_only_authored_abstract(tmp_path, capsys) -> None:
    manifest = tmp_path / "manifest.md"
    long_text = "word " * 81
    manifest.write_text(
        f"---\ntitle: {'title ' * 81}\nsubtitle: {'subtitle ' * 81}\n---\n"
        "- [[chapter]]\n\n" + long_text + "\n",
        encoding="utf-8",
    )
    (tmp_path / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
    assert main(["--source", str(tmp_path), "--check"]) == 0
    captured = capsys.readouterr()
    assert captured.err == (
        f"Warning: {manifest}:7: long paragraph "
        "(6 estimated lines at 80 characters; maximum 5). "
        "Split it into shorter paragraphs.\n"
    )
    assert "long paragraph" not in captured.out


def test_paragraph_warnings_measure_prose_not_tables_math_or_link_payloads(tmp_path, capsys) -> None:
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "chapter.md").write_text(
        "# Chapter\n\n| Source | Formula |\n| --- | --- |\n| " + "word " * 200 +
        " | value |\n\n[Download](data:application/octet-stream;base64," + "YWJj" * 1000 +
        ")\n\n$$\n" + "x+" * 300 + "x\n$$\n\n[[chapter|Short note link]]\n",
        encoding="utf-8",
    )
    assert main(["--source", str(tmp_path), "--check"]) == 0
    assert capsys.readouterr().err == ""


def test_project_paper_setting_is_rejected_with_manifest_migration(tmp_path, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"paper": {"widthMillimeters": 216}}}), encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path.parent / "out.html")])
    assert "report.paper was removed" in capsys.readouterr().err


@pytest.mark.parametrize("timeout", [0, -1, "15000", 120001])
def test_project_rejects_invalid_print_readiness_timeout(tmp_path, timeout, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"printReadyTimeoutMilliseconds": timeout}}), encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path.parent / "out.html")])
    assert "printReadyTimeoutMilliseconds" in capsys.readouterr().err


@pytest.mark.parametrize("settings", [
    {"excerptCharacters": 0},
    {"metadataEntries": -1},
    {"showDelayMilliseconds": "fast"},
    {"showDelayMilliseconds": -1},
    {"metadataValueCharacters": 1},
])
def test_project_rejects_invalid_hover_card_limits(tmp_path, settings, capsys) -> None:
    (tmp_path / "chapter.md").write_text("# Chapter", encoding="utf-8")
    (tmp_path / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"report": {"hoverCard": settings}}), encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="2"):
        main(["--source", str(tmp_path), "--output", str(tmp_path.parent / "out.html")])
    assert "hoverCard" in capsys.readouterr().err
