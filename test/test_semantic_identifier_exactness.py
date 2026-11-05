"""Semantic IDs are exact data, including at the schema/regex boundary."""
import json

import pytest
import yaml

from obs_html.cli import main
from obs_html.content import ContentError, validate_base_definition
from obs_html.report_data import decode_report_data
from obs_html.semantic_assets import SemanticAssets, markup
from test_browser import run_browser_script
from test_named_icons import write_index


LONG_NAME = "a" * 33 + "." + "b" * 33
SUFFIXES = ["\n", "\r", "\r\n", "\t", " ", "\u2028", "\u2029", "\u00a0"]


def _definition(name):
    return {"properties": {"help": {"obsHtml": {"icon": {
        "name": name, "label": "Help", "help": "Existing operation",
    }}}}, "views": [{"type": "table", "order": ["help"]}]}


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_shared_python_identifier_consumers_reject_trailing_whitespace(tmp_path, suffix):
    name = "icon.help" + suffix
    with pytest.raises(ValueError, match="Invalid icon name"):
        markup(name)
    with pytest.raises(ContentError, match="Invalid base definition"):
        validate_base_definition(_definition(name), tmp_path / "invalid.base")
    for assets in (
        {"local" + suffix: {"type": "icon", "value": {"glyph": "X"}}},
        {"alias": {"ref": name}},
        {"appearance": {"type": "appearance", "icon": {"ref": "icon.help"},
                        "states": {"active" + suffix: {}}}},
        {"appearance": {"type": "appearance", "icon": {"ref": "icon.help"},
                        "states": {"active": {}}, "defaultState": "active" + suffix}},
    ):
        (tmp_path / "assets.json").write_text(json.dumps({"schemaVersion": 1, "assets": assets}),
                                             encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid semantic asset index"):
            SemanticAssets(tmp_path, "assets.json")


def test_browser_and_python_share_exact_identifier_acceptance(tmp_path):
    names = ["icon.help", LONG_NAME, "a" * 64, ".".join(["a" * 63] * 4)]
    invalid = ["icon.help" + suffix for suffix in SUFFIXES] + [
        " icon.help", "icon. help", "icon.\nhelp", "icon..help",
        ".icon.help", "icon.help.", "a" * 65, ".".join(["a" * 63] * 5),
    ]
    expected = [True] * len(names) + [False] * len(invalid)
    definitions = [_definition(name) for name in names + invalid]
    for definition, accepted in zip(definitions, expected, strict=True):
        if accepted:
            validate_base_definition(definition, tmp_path / "valid.base")
            assert markup(definition["properties"]["help"]["obsHtml"]["icon"]["name"])
        else:
            with pytest.raises(ContentError):
                validate_base_definition(definition, tmp_path / "invalid.base")
            with pytest.raises(ValueError):
                markup(definition["properties"]["help"]["obsHtml"]["icon"]["name"])
    run_browser_script(r"""
const results = payload.definitions.map(definition => {
    try { context.obsBases.validate(definition); return true; }
    catch (error) { return false; }
});
assert.deepEqual(results, payload.expected);
""", {"definitions": definitions, "expected": expected})


def test_exact_name_fragment_still_projects_real_resource_markup(tmp_path):
    write_index(tmp_path / "assets.json", {LONG_NAME: {"glyph": "LONG"}})
    assets = SemanticAssets(tmp_path, "assets.json")
    assert f'aria-hidden="true">LONG</span>' in assets.resolve_markup(markup(LONG_NAME))
    assert 'aria-hidden="true">?</span>' in assets.resolve_markup(markup("icon.help"))
    assert '<img data-icon-asset="obs-asset:' in assets.resolve_markup(markup("filter"))


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("name", [LONG_NAME, "icon.help\n", "icon.help "])
def test_tiny_real_base_cli_preserves_exact_id_boundary(tmp_path, capsys, name, check):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
    (source / "chapter.md").write_text(
        "```base\n" + yaml.safe_dump(_definition(name), sort_keys=False) + "```\n", encoding="utf-8")
    write_index(source / "assets.json", {LONG_NAME: {"glyph": "LONG"}})
    (source / "cfg.json").write_text('{"report":{"assetIndex":"assets.json"}}', encoding="utf-8")
    output = tmp_path / "report.html"
    arguments = ["--source", str(source), "--output", str(output)] + (["--check"] if check else [])
    if name == LONG_NAME:
        assert main(arguments) == 0
        if not check:
            data = decode_report_data(output.read_text(encoding="utf-8"))
            assert data["assets"][LONG_NAME]["value"] == {"glyph": "LONG"}
    else:
        with pytest.raises(SystemExit) as failure:
            main(arguments)
        assert failure.value.code == 2
        assert "Invalid base definition" in capsys.readouterr().err
        assert not output.exists()


@pytest.mark.parametrize("name", ["a..b", "a" * 65, "a." + "b" * 65,
                                   ".".join(["a" * 63] * 5), "a/b", "a b"])
def test_all_semantic_consumers_reject_invalid_identifier_profiles(tmp_path, name):
    definition = {"properties": {"icon": {"obsHtml": {"icon": {
        "name": name, "label": "Invalid", "help": "Not selectable",
    }}}}, "views": [{"type": "table", "order": ["icon"]}]}
    with pytest.raises(ContentError, match="Invalid base definition"):
        validate_base_definition(definition, tmp_path / "invalid.base")
    with pytest.raises(ValueError, match="Invalid icon name"):
        markup(name)
