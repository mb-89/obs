from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jsonschema import validate


SCHEMA_PATH = Path(__file__).with_name("cfg.schema.json")
REMOVED_READING_SETTINGS = {
    "theme": "every opening starts in Light appearance; readers switch appearance in Settings.",
    "paged": "declare the opening layout in the manifest frontmatter as obsHtml: {layout: paged} "
             "or obsHtml: {layout: scrolling}.",
}
RENAMED_KEYS = {"report": "artifact"}
REMOVED_ARTIFACT_SETTINGS = {
    "paper": "declare the document's paper in the manifest frontmatter as "
             "obsHtml: {print: {paper: A4, margin: 20mm}}.",
    "query": "declare the global query profile in the manifest frontmatter as obsHtml: {query: ...}.",
}


@dataclass(frozen=True)
class FilterPreset:
    label: str
    expression: str


@dataclass(frozen=True)
class Config:
    manifest_filename: str
    project_config_filename: str
    figure_references: dict[str, list[str]]
    css_snippet_folder: str
    style_folder: str | None
    command_timeout_seconds: int
    rendered_check_timeout_seconds: int
    timing_relative_threshold: float
    timing_absolute_threshold_seconds: float
    facet_distinct_ratio: float
    filter_presets: tuple[FilterPreset, ...]
    bordered_tags: tuple[str, ...]
    table_page_size: int
    table_column_minimum_pixels: int
    table_compact_column_minimum_pixels: int
    table_icon_width_pixels: int
    table_detail_font_size_points: int
    dock_pane_minimum_pixels: int
    hover_card: dict[str, int]
    print_setup: dict[str, object]
    print_ready_timeout_milliseconds: int
    reading: dict[str, str | bool | float]
    figures: dict[str, float | str]
    embed_pdfs: bool
    data_compression: str
    asset_index: str | None
    inactive_icon_opacity: float
    guided_card: dict[str, int]


def _reject_renamed_keys(configuration: object, path: Path) -> None:
    for old, new in RENAMED_KEYS.items():
        if isinstance(configuration, dict) and old in configuration:
            raise ValueError(
                f"{path}: configuration key '{old}' was renamed to '{new}'; rename the key in that file."
            )


def load_config(config_path: Path, override_path: Path | None = None) -> Config:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _reject_renamed_keys(config, config_path)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if override_path is not None:
        override = json.loads(override_path.read_text(encoding="utf-8"))
        _reject_renamed_keys(override, override_path)
        artifact = override.get("artifact", {}) if isinstance(override, dict) else {}
        reading = artifact.get("reading", {}) if isinstance(artifact, dict) else {}
        for key, replacement in REMOVED_READING_SETTINGS.items():
            if isinstance(reading, dict) and key in reading:
                raise ValueError(f"artifact.reading.{key} was removed: {replacement}")
        for key, replacement in REMOVED_ARTIFACT_SETTINGS.items():
            if isinstance(artifact, dict) and key in artifact:
                raise ValueError(f"artifact.{key} was removed: {replacement}")
        config = _merge(config, override)
    validate(instance=config, schema=schema)
    return Config(
        manifest_filename=config["input"]["manifestFilename"],
        project_config_filename=config["input"]["projectConfigFilename"],
        figure_references=config["input"]["figureReferences"],
        css_snippet_folder=config["input"]["cssSnippetFolder"],
        style_folder=config["input"]["styleFolder"],
        command_timeout_seconds=config["execution"]["commandTimeoutSeconds"],
        rendered_check_timeout_seconds=config["execution"]["renderedCheckTimeoutSeconds"],
        timing_relative_threshold=config["timings"]["relativeThreshold"],
        timing_absolute_threshold_seconds=config["timings"]["absoluteThresholdSeconds"],
        facet_distinct_ratio=config["artifact"]["facetDistinctRatio"],
        bordered_tags=tuple(config["artifact"].get("borderedTags", [])),
        table_page_size=config["artifact"]["tablePageSize"],
        table_column_minimum_pixels=config["artifact"]["tableColumnMinimumPixels"],
        table_compact_column_minimum_pixels=config["artifact"]["tableCompactColumnMinimumPixels"],
        table_icon_width_pixels=config["artifact"]["tableIconWidthPixels"],
        table_detail_font_size_points=config["artifact"]["tableDetailFontSizePoints"],
        dock_pane_minimum_pixels=config["artifact"]["dockPaneMinimumPixels"],
        hover_card=config["artifact"]["hoverCard"],
        print_setup=config["artifact"]["print"],
        print_ready_timeout_milliseconds=config["artifact"]["printReadyTimeoutMilliseconds"],
        reading=config["artifact"]["reading"],
        figures=config["artifact"]["figures"],
        embed_pdfs=config["artifact"]["embedPdfs"],
        data_compression=config["artifact"]["dataCompression"],
        asset_index=config["artifact"].get("assetIndex"),
        inactive_icon_opacity=config["artifact"]["inactiveIconOpacity"],
        guided_card=config["artifact"]["guidedCard"],
        filter_presets=tuple(
            FilterPreset(label=item["label"], expression=item["expression"])
            for item in config["artifact"]["filterPresets"]
        ),
    )


def _merge(defaults: dict[str, object], overrides: dict[str, object]) -> dict[str, object]:
    merged = dict(defaults)
    for key, value in overrides.items():
        default = merged.get(key)
        if isinstance(default, dict) and isinstance(value, dict):
            merged[key] = _merge(default, value)
        else:
            merged[key] = value
    return merged
