from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from html import escape
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from typing import Callable, Sequence

from jsonschema import Draft202012Validator

from obs_html.bars import BarDefinition, discover_bars
from obs_html.config import REMOVED_READING_SETTINGS, FilterPreset
from obs_html.semantic_assets import SemanticAssets, markup as icon_markup
from obs_html.content import (
  Chapter,
  ChapterContent,
  Manifest,
  NoteReferenceIndex,
  ContentError,
  COVER_PEOPLE_FIELDS,
  collect_notes,
  collect_mark_backlinks,
  css_snippets,
  note_css_classes,
  read_chapter_content,
  read_manifest,
  render_chapter,
  render_inline,
  query_profile,
  paragraph_warnings,
  figure_warnings,
  external_link_warnings,
  quantity_label,
)
from obs_html.report_data import encode_report_data, prepare_report_scripts, serialize_report_data
from obs_html.styles import load_style
from obs_html.timings import stage


DOCK_DIRECTIONS = (
  ("left", "left", "vertical"),
  ("right", "right", "vertical"),
  ("top", "up", "horizontal"),
  ("bottom", "down", "horizontal"),
)

_EMBEDDED_URI_ATTRIBUTE = re.compile(
  r"""(?P<prefix>\b(?:src|href)\s*=\s*)(?P<quote>["'])"""
  r"""(?P<uri>data:[^"'\s<>]+;base64,[A-Za-z0-9+/=]+)(?P=quote)""",
  re.IGNORECASE,
)


def _visit_strings(value: object, visit: Callable[[str], None]) -> None:
  if isinstance(value, str):
    visit(value)
  elif isinstance(value, list):
    for item in value:
      _visit_strings(item, visit)
  elif isinstance(value, dict):
    for item in value.values():
      _visit_strings(item, visit)


def _transform_strings(value: object, transform: Callable[[str], str]) -> object:
  if isinstance(value, str):
    return transform(value)
  if isinstance(value, list):
    return [_transform_strings(item, transform) for item in value]
  if isinstance(value, dict):
    return {key: _transform_strings(item, transform) for key, item in value.items()}
  return value


def _deduplicate_embedded_assets(data: dict[str, object]) -> None:
  uri_counts: dict[str, int] = {}

  def count_uris(text: str) -> None:
    for match in _EMBEDDED_URI_ATTRIBUTE.finditer(text):
      uri = match.group("uri")
      uri_counts[uri] = uri_counts.get(uri, 0) + 1

  _visit_strings(data, count_uris)
  assets: dict[str, str] = dict(data.get("embeddedAssets", {}))
  owners = {uri: key for key, uri in assets.items() if isinstance(uri, str)}
  repeated_uris = {uri for uri, count in uri_counts.items() if count > 1 or uri in owners}
  if not repeated_uris:
    return

  def replace_repeated_uri(match: re.Match[str]) -> str:
    uri = match.group("uri")
    if uri not in repeated_uris:
      return match.group(0)
    asset_id = owners.get(uri) or hashlib.sha256(uri.encode("ascii")).hexdigest()
    previous = assets.setdefault(asset_id, uri)
    if previous != uri:
      raise ValueError("Embedded asset identifier collision.")
    return f'{match.group("prefix")}{match.group("quote")}obs-asset:{asset_id}{match.group("quote")}'

  transformed = _transform_strings(
    data, lambda text: _EMBEDDED_URI_ATTRIBUTE.sub(replace_repeated_uri, text),
  )
  data.clear()
  data.update(transformed)
  data["embeddedAssets"] = assets


def render_report(
  manifest_path: Path,
  chapters: list[Chapter],
  command_runner: Callable[[str], str] | None = None,
  facet_distinct_ratio: float = 0.5,
  filter_presets: Sequence[FilterPreset] = (),
  bordered_tags: Sequence[str] = (),
  table_page_size: int | None = None,
  hover_card: dict[str, int] | None = None,
  print_setup: dict[str, object] | None = None,
  print_ready_timeout_milliseconds: int | None = None,
  reading: dict[str, str | bool | float] | None = None,
  figures: dict[str, float | str] | None = None,
  figure_references: dict[str, list[str]] | None = None,
  warning_handler: Callable[[str], None] | None = None,
  embed_pdfs: bool = True,
  table_icon_width_pixels: int | None = None,
  data_compression: str | None = None,
  manifest: Manifest | None = None,
  table_detail_font_size_points: int | None = None,
  trusted_runtime_bundle: tuple[str, str] | None = None,
  dock_pane_minimum_pixels: int | None = None,
  guided_card: dict[str, int] | None = None,
  table_column_minimum_pixels: int | None = None,
  table_compact_column_minimum_pixels: int | None = None,
  asset_index: str | Path | None = None,
  inactive_icon_opacity: float | None = None,
  generator_provenance: dict[str, str] | None = None,
  target_provenance: dict[str, str] | None = None,
  embed_attachments: bool = False,
  css_snippet_folder: str | None = None,
  style_folder: Path | None = None,
) -> str:
    vault_root = manifest_path.resolve().parent
    style = load_style(style_folder)
    assets = SemanticAssets(vault_root, asset_index or style.asset_index)
    stylesheet = style.stylesheet
    query_script = files("obs_html").joinpath("query.js").read_text(encoding="utf-8")
    table_script = files("obs_html").joinpath("table.js").read_text(encoding="utf-8")
    transaction_script = files("obs_html").joinpath("canonical-transaction.js").read_text(encoding="utf-8")
    script = files("obs_html").joinpath("report.js").read_text(encoding="utf-8")
    manifest = manifest or read_manifest(manifest_path)
    title = _document_title(manifest, manifest_path)
    if css_snippet_folder is None:
      css_snippet_folder = json.loads(
        files("obs_html").joinpath("cfg.json").read_text(encoding="utf-8")
      )["input"]["cssSnippetFolder"]
    # Author snippets follow the packaged styles so they win at equal specificity, as in Obsidian.
    author_styles = "".join(
      f'\n  <style data-css-snippet="{escape(name, quote=True)}">{css}</style>'
      for name, css in css_snippets(vault_root, css_snippet_folder, manifest.presentation["cssSnippets"])
    )
    bars = discover_bars()
    bar_scripts = "\n".join(f"\n{bar.script}" for bar in bars if bar.script)
    report_data = _serialize_report_data(
      chapters,
      vault_root,
      command_runner,
      facet_distinct_ratio,
      filter_presets,
      bordered_tags,
      table_page_size,
      manifest,
      manifest_path,
      hover_card,
      print_setup,
      print_ready_timeout_milliseconds,
      reading,
      figures,
      warning_handler,
      embed_pdfs,
      table_icon_width_pixels,
      table_detail_font_size_points,
      dock_pane_minimum_pixels,
      table_column_minimum_pixels,
      table_compact_column_minimum_pixels,
      assets,
      inactive_icon_opacity,
      generator_provenance,
      target_provenance,
      guided_card,
      embed_attachments=embed_attachments,
      figure_references=figure_references,
    )
    card_assets = ""
    if "data-record-cards" in report_data:
        card_js = files("obs_html").joinpath("cards.js").read_text(encoding="utf-8")
        card_assets = f'<script id="cards-script">{card_js}</script>'
    property_assets = ""
    if "data-property-editor" in report_data:
        property_js = files("obs_html").joinpath("properties.js").read_text(encoding="utf-8")
        property_assets = f'<script id="property-editor-script">{property_js}</script>'
    figure_assets = ""
    if "data-report-figure" in report_data or "data-engineering-figure" in report_data:
        figure_css = files("obs_html").joinpath("figures.css").read_text(encoding="utf-8")
        figure_js = files("obs_html").joinpath("figures.js").read_text(encoding="utf-8")
        plotly = ""
        if 'data-figure-kind=\\"plot\\"' in report_data:
            figure_settings = json.loads(
                files("obs_html").joinpath("cfg.json").read_text(encoding="utf-8")
            )["report"]["figures"] | (figures or {})
            if figure_settings["plotlyDelivery"] == "cdn":
                plotly = (
                    f'<script id="plotly-script" src="{figure_settings["plotlyCdnUrl"]}" '
                    f'integrity="{figure_settings["plotlyCdnIntegrity"]}" crossorigin="anonymous" '
                    'data-optional-runtime></script>'
                )
            else:
                plotly = (
                    '<script id="plotly-script">/* '
                    + files("obs_html").joinpath("vendor", "plotly.LICENSE").read_text(encoding="utf-8")
                    + " */\n"
                    + files("obs_html").joinpath("vendor", "plotly-basic.min.js.LICENSE.txt").read_text(encoding="utf-8")
                    + "\n"
                    + files("obs_html").joinpath("vendor", "plotly-basic.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
                    + "</script>"
                )
        figure_assets = f'<style id="figure-styles">{figure_css}</style>{plotly}<script id="figure-script">{figure_js}</script>'

    model = json.loads(report_data)
    startup = model["reading"]
    reader_startup = "".join(
      f"    {line}\n" for line in files("obs_html").joinpath("reader-startup.js").read_text(encoding="utf-8")
      .replace("READER_THEME", json.dumps(startup["theme"]))
      .replace("READER_PAGED", json.dumps(startup["paged"])).splitlines()
    )
    report_island = encode_report_data(model, data_compression)
    runtime_head = ""
    runtime_script = ""
    if trusted_runtime_bundle:
        runtime_id, runtime_source = trusted_runtime_bundle
        runtime_head = f'<meta name="obs-trusted-runtime" content="{escape(runtime_id, quote=True)}">'
        runtime_script = (
            f'<script id="trusted-application-runtime" '
            f'data-runtime-bundle="{escape(runtime_id, quote=True)}">'
            + re.sub(r"</script", r"<\\/script", runtime_source, flags=re.IGNORECASE)
            + "</script>"
        )
    return prepare_report_scripts(assets.resolve_markup(f"""<!doctype html>
<html lang="en" data-theme="{escape(startup['theme'])}">
<head>
  <meta charset="utf-8">
  {runtime_head}
  <script id="reader-startup-script">
{reader_startup}  </script>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{escape(title)}</title>
  <style id="report-styles">
{stylesheet}
  </style>
  <style id="semantic-asset-styles">{assets.css()}</style>{author_styles}
</head>
<body>
  <div class="app-shell" inert>
    {_render_dock_region("top")}
    {_render_dock_region("left")}
    <main class="reader-shell">
      <div class="frontmatter-nav-zone">
        <button class="frontmatter-toggle" type="button" data-frontmatter-toggle
                aria-label="Show frontmatter" aria-expanded="false"
                aria-controls="frontmatter-panel" title="Show frontmatter" hidden>
          {icon_markup("frontmatter")}
        </button>
      </div>
      <div class="chapter-scroll" data-chapter-scroll tabindex="-1">
        <section class="frontmatter-panel" id="frontmatter-panel" data-frontmatter-panel
                 aria-label="Frontmatter" hidden>
          <table>
            <thead><tr><th scope="col">Field</th><th scope="col">Value</th></tr></thead>
            <tbody data-frontmatter-body data-transient-content></tbody>
          </table>
        </section>
        <article class="chapter" data-active-chapter>
          <div class="chapter-body" data-chapter-body data-transient-content>
          </div>
        </article>
      </div>
      <div class="chapter-nav-zone chapter-nav-zone--previous">
        <button class="icon-button chapter-nav" type="button" data-step="-1"
                aria-label="Previous chapter" title="Previous chapter"></button>
      </div>
      <div class="chapter-nav-zone chapter-nav-zone--next">
        <button class="icon-button chapter-nav" type="button" data-step="1"
                aria-label="Next chapter" title="Next chapter"></button>
      </div>
    </main>
    {_render_dock_region("right")}
    {_render_dock_region("bottom")}
  </div>

  <script id="running-header-script" data-header-metadata="{escape(serialize_report_data(model['document']['metadata']), quote=True)}">
{files("obs_html").joinpath("running-header.js").read_text(encoding="utf-8")}
  </script>
  <button class="icon-button menu-button" type="button" data-menu-button
          aria-label="Open bars menu" aria-expanded="false" title="Bars" disabled>{icon_markup("menu")}</button>
  <section class="bars-menu" data-bars-menu aria-label="Bars" hidden>
    {''.join(_render_menu_row(bar) for bar in bars)}
  </section>

  <div class="bar-parking" data-bar-parking hidden>
    {''.join(_render_bar(bar, chapters) for bar in bars)}
  </div>

  {report_island}
  <script id="obs-comments" type="application/json" data-comment-island>{_empty_comment_island()}</script>
  <script id="query-script">
{query_script}
  </script>
  <script id="base-schema" type="application/json">{files("obs_html").joinpath("base.schema.json").read_text(encoding="utf-8")}</script>
  <script type="application/json" data-json-schema="assets.schema.json">{files("obs_html").joinpath("assets.schema.json").read_text(encoding="utf-8")}</script>
  <script id="property-editor-schema" type="application/json">{files("obs_html").joinpath("property-editor.schema.json").read_text(encoding="utf-8")}</script>
  <script id="yaml-script">
/* {files("obs_html").joinpath("vendor", "js-yaml.LICENSE").read_text(encoding="utf-8")} */
{files("obs_html").joinpath("vendor", "js-yaml.min.js").read_text(encoding="utf-8")}
  </script>
  <script id="base-script">
{files("obs_html").joinpath("base.js").read_text(encoding="utf-8")}
  </script>
  <script id="data-table-script">
{table_script}
  </script>
  <script id="zip-rewrite-script">{files("obs_html").joinpath("zip-rewrite.js").read_text(encoding="utf-8")}</script>
  <script id="payload-script">{files("obs_html").joinpath("payloads.js").read_text(encoding="utf-8")}</script>
  <script id="assets-script">{files("obs_html").joinpath("assets.js").read_text(encoding="utf-8")}</script>
  <script id="canonical-transaction-script">
{transaction_script}
  </script>
  <script id="report-script">
{files("obs_html").joinpath("hover-card.js").read_text(encoding="utf-8")}
{files("obs_html").joinpath("guided-card.js").read_text(encoding="utf-8")}
{script}
  </script>
  {figure_assets}
  {card_assets}
  {property_assets}
  <script id="pages-script">
{files("obs_html").joinpath("pages.js").read_text(encoding="utf-8")}
  </script>
  <script id="storage-script">

{files("obs_html").joinpath("storage.js").read_text(encoding="utf-8")}
  </script>
  <script id="bar-scripts">
{bar_scripts}
  </script>
  {runtime_script}
</body>
</html>
"""))


def _paper(choice: dict[str, str], print_setup: dict[str, object]) -> dict[str, float]:
  """Resolve the manifest's obsHtml.print choice to physical paper geometry."""
  sizes = print_setup["paperSizes"]
  if choice["paper"] not in sizes:
    raise ContentError(
      f"Manifest obsHtml.print.paper must be one of {', '.join(sizes)}; got {choice['paper']!r}."
    )
  margin = float(choice["margin"].removesuffix("mm"))
  paper = {**sizes[choice["paper"]], "marginMillimeters": int(margin) if margin.is_integer() else margin}
  limits = json.loads(files("obs_html").joinpath("cfg.schema.json").read_text(encoding="utf-8"))
  error = next(Draft202012Validator(limits["$defs"]["paper"]).iter_errors(paper), None)
  if error is not None:
    raise ContentError(f"Manifest obsHtml.print.margin {choice['margin']} is out of range: {error.message}.")
  return paper


def _document_title(manifest: Manifest, manifest_path: Path) -> str:
    title = manifest.metadata.get("title")
    if title:
        return str(title).strip()
    product = manifest.metadata.get("product")
    if isinstance(product, dict) and product.get("name"):
        return str(product["name"]).strip()
    for field in ("document name", "project name", "project"):
        identity = manifest.metadata.get(field)
        if isinstance(identity, str) and identity.strip():
            return identity.strip()
        if isinstance(identity, dict) and isinstance(identity.get("name"), str) and identity["name"].strip():
            return identity["name"].strip()
    return manifest_path.stem


def _serialize_report_data(
  chapters: list[Chapter],
  vault_root: Path,
  command_runner: Callable[[str], str] | None,
  facet_distinct_ratio: float,
  filter_presets: Sequence[FilterPreset],
  bordered_tags: Sequence[str],
  table_page_size: int | None,
  manifest: Manifest,
  manifest_path: Path,
  hover_card: dict[str, int] | None,
  print_setup: dict[str, object] | None,
  print_ready_timeout_milliseconds: int | None,
  reading: dict[str, str | bool | float] | None,
  figures: dict[str, float | str] | None,
  warning_handler: Callable[[str], None] | None,
  embed_pdfs: bool,
  table_icon_width_pixels: int | None,
  table_detail_font_size_points: int | None,
  dock_pane_minimum_pixels: int | None,
  table_column_minimum_pixels: int | None,
  table_compact_column_minimum_pixels: int | None,
  assets: SemanticAssets,
  inactive_icon_opacity: float | None,
  generator_provenance: dict[str, str] | None,
  target_provenance: dict[str, str] | None,
  guided_card: dict[str, int] | None = None,
  embed_attachments: bool = False,
  figure_references: dict[str, list[str]] | None = None,
) -> str:
  title = _document_title(manifest, manifest_path)
  home = Chapter(0, title, "home", manifest_path, "", "home", vault_root)
  # Render the title as text, never as authored Markdown.
  home_document = read_chapter_content(home, manifest.abstract)
  toc = [home.slug, *(chapter.slug for chapter in chapters)]
  with stage("parse"):
    notes, documents_by_path, reference_index = collect_notes(
      manifest_path, chapters, home, home_document, manifest.metadata, embed_pdfs,
      embed_attachments, figure_references=figure_references,
    )
  documents = [documents_by_path[note.source_path] for note in notes]
  for document in documents:
    for table in document.tables:
      assets.normalize_definition(table.definition)
  report_defaults = json.loads(
    files("obs_html").joinpath("cfg.json").read_text(encoding="utf-8")
  )["report"]
  reading_settings = report_defaults["reading"] | (reading or {})
  for key, replacement in REMOVED_READING_SETTINGS.items():
    if key in reading_settings:
      raise ValueError(f"report.reading.{key} was removed: {replacement}")
  presentation = manifest.presentation
  print_settings = print_setup or report_defaults["print"]
  # Light is a product invariant; the opening layout is the author's manifest declaration.
  reading_settings = {"theme": "light", "paged": presentation["layout"] == "paged", **reading_settings}
  bottom_line = presentation["bottomLine"]
  bottom_line_card = (
    render_inline(bottom_line["title"], home, notes, vault_root, embed_pdfs, reference_index)
    if bottom_line["title"] else "",
    bottom_line["position"],
  )
  if warning_handler is not None:
    included_metadata = {note.source_path: document.frontmatter
                         for note, document in zip(notes, documents, strict=True)}
    for note, document in zip(notes, documents, strict=True):
      if note.generated == "home":
        document = replace(
          read_chapter_content(note, manifest.abstract),
          _body_line_offset=manifest._abstract_line_offset,
        )
      for diagnostic in paragraph_warnings(
        note, document, int(reading_settings["paragraphWarningLines"]),
        int(reading_settings["paragraphLineCharacters"]),
      ) + figure_warnings(note, document, reference_index):
        warning_handler(diagnostic)
      for diagnostic in external_link_warnings(note, document, included_metadata):
        warning_handler(diagnostic)
  _validate_marker_identities(notes, documents)
  mark_backlinks = collect_mark_backlinks(notes, documents, vault_root, reference_index)
  data = {
    "assets": assets.resources,
    "embeddedAssets": assets.embedded_assets,
    "document": {
      "title": title,
      "metadata": {key: value for key, value in manifest.metadata.items() if key != "obsHtml"},
      "pages": presentation["pages"],
      "generation": {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "generator": generator_provenance or {
          "name": "obs-html", "version": version("obs-html"), "commit": "unknown",
        },
        "target": target_provenance or {
          "name": vault_root.name, "version": "unknown", "commit": "unknown",
        },
      },
    },
    "paper": _paper(presentation["print"], print_settings),
    "wideTableEdgeMillimeters": print_settings["wideTableEdgeMillimeters"],
    "reading": {key: value for key, value in reading_settings.items()
                if key not in {"paragraphWarningLines", "paragraphLineCharacters"}},
    "figures": figures if figures is not None else report_defaults["figures"],
    "printReadyTimeoutMilliseconds": print_ready_timeout_milliseconds
      if print_ready_timeout_milliseconds is not None else report_defaults["printReadyTimeoutMilliseconds"],
    "hoverCard": hover_card if hover_card is not None else report_defaults["hoverCard"],
    "tablePageSize": table_page_size if table_page_size is not None else report_defaults["tablePageSize"],
    "inactiveIconOpacity": inactive_icon_opacity
      if inactive_icon_opacity is not None else report_defaults["inactiveIconOpacity"],
    "tableColumnMinimumPixels": table_column_minimum_pixels
      if table_column_minimum_pixels is not None else report_defaults["tableColumnMinimumPixels"],
    "tableCompactColumnMinimumPixels": table_compact_column_minimum_pixels
      if table_compact_column_minimum_pixels is not None else report_defaults["tableCompactColumnMinimumPixels"],
    "dockPaneMinimumPixels": dock_pane_minimum_pixels
      if dock_pane_minimum_pixels is not None else report_defaults["dockPaneMinimumPixels"],
    "guidedCard": guided_card if guided_card is not None else report_defaults["guidedCard"],
    "tableIconWidthPixels": table_icon_width_pixels
      if table_icon_width_pixels is not None else report_defaults["tableIconWidthPixels"],
    "tableDetailFontSizePoints": table_detail_font_size_points
      if table_detail_font_size_points is not None else report_defaults["tableDetailFontSizePoints"],
    "facetDistinctRatio": facet_distinct_ratio,
    "query": query_profile(
      presentation["query"], home, notes, vault_root, documents_by_path, reference_index,
    ),
    "filterPresets": [
      {"label": preset.label, "expression": preset.expression}
      for preset in filter_presets
    ],
    "toc": toc,
    "notes": [
      {
        "depth": chapter.depth,
        "title": chapter.title,
        "slug": chapter.slug,
        "sourcePath": chapter.source_path.relative_to(vault_root).as_posix(),
        "generated": chapter.generated,
        "cssClasses": note_css_classes(document.frontmatter, chapter.source_path),
        "frontmatter": document.frontmatter,
        "editableProperties": document.editable_properties,
        "frontmatterHtml": _render_frontmatter_html(
          document.frontmatter, chapter, notes, vault_root, embed_pdfs, reference_index,
        ),
        "bottomLineHtml": render_inline(
          document.bottom_line,
          chapter,
          notes,
          vault_root,
          embed_pdfs,
          reference_index,
        ) if document.bottom_line else "",
        **({"valueLabel": quantity_label(document.frontmatter)}
           if document.frontmatter.get("kind") == "quantity" and "value" in document.frontmatter else {}),
        "definitionHtml": render_inline(
          str(document.frontmatter["definition"]), chapter, notes, vault_root, embed_pdfs,
          reference_index,
        ) if document.frontmatter.get("kind") == "glossary" else "",
        "marks": [
          {
            "kind": mark.kind,
            "label": mark.label,
            "text": mark.text,
            "html": render_inline(mark.text, chapter, notes, vault_root, embed_pdfs, reference_index),
            "anchor": mark.anchor,
            "backlinks": mark_backlinks[(mark.kind, mark.label)],
          }
          for mark in document.marks
        ],
        "tables": [
          {
            "key": table.key, "definition": table.definition,
          }
          for table in document.tables
        ],
        "html": (
          _document_heading(
            title, manifest.metadata, home, notes, vault_root, embed_pdfs, reference_index,
            compact=presentation["heading"] == "compact",
          )
          if chapter.generated == "home" else ""
        ) + render_chapter(
          chapter,
          notes,
          vault_root,
          command_runner,
          document=document,
          bordered_tags=bordered_tags,
          embed_pdfs=embed_pdfs,
          include_plot_fallback=(figures or {}).get("plotlyDelivery", "embedded") != "cdn",
          reference_index=reference_index,
          bottom_line_card=bottom_line_card,
        ),
      }
      for chapter, document in zip(notes, documents, strict=True)
    ]
  }
  data = _transform_strings(data, assets.resolve_markup)
  _deduplicate_embedded_assets(data)
  return serialize_report_data(data)


def _render_frontmatter_html(
  metadata: dict[str, object], chapter: Chapter, notes: list[Chapter], vault_root: Path,
  embed_pdfs: bool = True,
  reference_index: NoteReferenceIndex | None = None,
) -> dict[str, str]:
  rendered: dict[str, str] = {}

  def text(value: object) -> str:
    if value is None:
      return "null"
    if isinstance(value, bool):
      return "true" if value else "false"
    return str(value)

  def add(field: str, value: object) -> None:
    if isinstance(value, dict):
      if value:
        for key, item in value.items():
          add(f"{field}.{key}" if field else key, item)
      elif field:
        rendered[field] = "{}"
    elif isinstance(value, list):
      if not value:
        rendered[field] = "[]"
      elif all(not isinstance(item, (dict, list)) for item in value):
        rendered[field] = ", ".join(
          inline(item)
          for item in value
        )
      else:
        for index, item in enumerate(value):
          add(f"{field}.{index}", item)
    elif field:
      rendered[field] = inline(value)

  def inline(value: object) -> str:
    source = text(value)
    if re.fullmatch(r"https?://[^\s<>]+", source, re.IGNORECASE):
      source = f"<{source}>"
    return render_inline(source, chapter, notes, vault_root, embed_pdfs, reference_index)

  add("", metadata)
  return rendered


def _document_heading(
  title: str, metadata: dict[str, object], home: Chapter, notes: list[Chapter], vault_root: Path,
  embed_pdfs: bool = True,
  reference_index: NoteReferenceIndex | None = None,
  compact: bool = False,
) -> str:
  def value(item: object) -> str:
    return escape(", ".join(item) if isinstance(item, list) else str(item))

  product = metadata.get("product", {})
  subtitle = (render_inline(metadata["subtitle"], home, notes, vault_root, embed_pdfs, reference_index)
              if "subtitle" in metadata else "")
  if compact:
    # One line of the document's identity; the remaining cover fields belong to the cover box only.
    product_text = " ".join(value(product[key]) for key in ("name", "version") if key in product)
    parts = [
      ("cover-organization", value(metadata.get("organization", ""))),
      ("cover-product", product_text),
      ("cover-type", value(metadata.get("document type", ""))),
    ]
    line = "".join(f'<span class="{name}">{text}</span>' for name, text in parts if text)
    if metadata.get("title") != "":
      line += f'<h1 class="document-title">{escape(title)}</h1>'
    if subtitle:
      line += f'<span class="document-subtitle">{subtitle}</span>'
    return ('<header class="document-heading document-heading--compact">'
            f'<div class="compact-heading">{line}</div></header>\n')
  product_html = "".join(f'<div>{value(product[key])}</div>' for key in ("name", "version") if key in product)
  band = (
    '<span class="cover-template">' + value(metadata.get("template", "")) + '</span>'
    '<span class="cover-organization">' + value(metadata.get("organization", "")) + '</span>'
  )
  facts = [(key.title(), metadata[key]) for key in (*COVER_PEOPLE_FIELDS, "sap number", "legal entity")
           if key in metadata]
  facts_html = "".join(f"<dt>{escape(key)}</dt><dd>{value(item)}</dd>" for key, item in facts)
  legal = "".join(f'<p class="cover-{key}">{value(metadata[key])}</p>'
                  for key in ("copyright", "confidentiality") if key in metadata)
  return (
    '<header class="document-heading">'
    + (f'<div class="cover-product">{product_html}</div>' if product_html else "")
    + f'<div class="cover-band">{band}</div>'
    + '<div class="cover-frame">'
    + (f'<h1 class="document-title">{escape(title)}</h1>' if metadata.get("title") != "" else "")
    + (f'<p class="cover-type">{value(metadata["document type"])}</p>' if "document type" in metadata else "")
    + (f'<div class="document-subtitle">{subtitle}</div>' if subtitle else "")
    + legal + '</div>'
    + f'<div class="cover-facts-frame"><dl class="cover-facts">{facts_html}</dl></div></header>\n'
  )


def _validate_marker_identities(
  chapters: list[Chapter], documents: list[ChapterContent]
) -> None:
  owners: dict[tuple[str, str], Path] = {}
  for chapter, document in zip(chapters, documents, strict=True):
    for mark in document.marks:
      identity = (mark.kind, mark.label)
      if identity in owners:
        raise ContentError(
          f"Duplicate paragraph marker #mark/{mark.kind}/{mark.label} in "
          f"{owners[identity]} and {chapter.source_path}"
        )
      owners[identity] = chapter.source_path


def _empty_comment_island() -> str:
  return json.dumps(
    {"version": 2, "annotations": [], "reviewers": [], "reviews": []},
    ensure_ascii=True,
    separators=(",", ":"),
  )


def _render_bar(bar: BarDefinition, chapters: list[Chapter]) -> str:
    return (
        f'<aside class="dock-bar bar--{escape(bar.key)}" data-bar="{escape(bar.key)}" '
        f'aria-label="{escape(bar.label)}" hidden>'
        '<header class="dock-bar-header">'
        f'<span class="bar-icon bar-icon--{escape(bar.key)}" aria-hidden="true">'
        f'{icon_markup(bar.icon)}</span>'
        f"<h2>{escape(bar.label)}</h2>"
        f"{bar.header_actions}"
        f'<button type="button" class="icon-button dock-bar-close" data-bar-close="{escape(bar.key)}" '
        f'aria-label="Close {escape(bar.label)}" title="Close {escape(bar.label)}">{icon_markup("close")}</button>'
        "</header>"
        f'<div class="dock-bar-content">{bar.render(chapters)}</div>'
        "</aside>"
    )


def _render_menu_row(bar: BarDefinition) -> str:
    buttons = "".join(
      f'<button class="icon-button dock-button" type="button" '
      f'data-dock-bar="{escape(bar.key)}" data-dock-direction="{direction}" '
      f'aria-label="Dock {escape(bar.label)} {direction}" aria-pressed="false" '
      f'title="Dock {escape(bar.label)} {direction}">{icon_markup(icon)}</button>'
        for direction, icon, _orientation in DOCK_DIRECTIONS
    )
    return (
      '<div class="bars-menu-row">'
      f'<span class="bar-identity" data-hover-help="{escape(bar.help)}">'
      f'<span class="bar-icon bar-icon--{escape(bar.key)}" aria-hidden="true">'
      f'{icon_markup(bar.icon)}</span>'
      f"<span>{escape(bar.label)}</span></span>"
      f'<div class="dock-controls" role="group" aria-label="Dock {escape(bar.label)}">'
      f"{buttons}</div></div>"
    )


def _render_dock_region(direction: str) -> str:
    orientation = next(
      orientation
      for candidate, _icon, orientation in DOCK_DIRECTIONS
      if candidate == direction
    )
    return (
      f'<div class="dock-region dock-region--{direction}" data-dock-region="{direction}">'
      f'<div class="dock-resize-handle" data-dock-resize="{direction}" role="separator" '
      f'aria-label="Resize {direction} bars" aria-orientation="{orientation}" tabindex="0" '
      f'data-hover-help="Drag to resize {direction} bars; double-click to reset"></div>'
      "</div>"
    )
