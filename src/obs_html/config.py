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
REMOVED_REPORT_SETTINGS = {
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


def load_config(config_path: Path, override_path: Path | None = None) -> Config:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if override_path is not None:
        override = json.loads(override_path.read_text(encoding="utf-8"))
        report = override.get("report", {}) if isinstance(override, dict) else {}
        reading = report.get("reading", {}) if isinstance(report, dict) else {}
        for key, replacement in REMOVED_READING_SETTINGS.items():
            if isinstance(reading, dict) and key in reading:
                raise ValueError(f"report.reading.{key} was removed: {replacement}")
        for key, replacement in REMOVED_REPORT_SETTINGS.items():
            if isinstance(report, dict) and key in report:
                raise ValueError(f"report.{key} was removed: {replacement}")
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
        facet_distinct_ratio=config["report"]["facetDistinctRatio"],
        bordered_tags=tuple(config["report"].get("borderedTags", [])),
        table_page_size=config["report"]["tablePageSize"],
        table_column_minimum_pixels=config["report"]["tableColumnMinimumPixels"],
        table_compact_column_minimum_pixels=config["report"]["tableCompactColumnMinimumPixels"],
        table_icon_width_pixels=config["report"]["tableIconWidthPixels"],
        table_detail_font_size_points=config["report"]["tableDetailFontSizePoints"],
        dock_pane_minimum_pixels=config["report"]["dockPaneMinimumPixels"],
        hover_card=config["report"]["hoverCard"],
        print_setup=config["report"]["print"],
        print_ready_timeout_milliseconds=config["report"]["printReadyTimeoutMilliseconds"],
        reading=config["report"]["reading"],
        figures=config["report"]["figures"],
        embed_pdfs=config["report"]["embedPdfs"],
        data_compression=config["report"]["dataCompression"],
        asset_index=config["report"].get("assetIndex"),
        inactive_icon_opacity=config["report"]["inactiveIconOpacity"],
        guided_card=config["report"]["guidedCard"],
        filter_presets=tuple(
            FilterPreset(label=item["label"], expression=item["expression"])
            for item in config["report"]["filterPresets"]
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
