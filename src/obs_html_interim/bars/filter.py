from obs_html_interim.bars import BarDefinition
from obs_html_interim.bars._query import render_query_input
from obs_html_interim.content import Chapter


def render(_chapters: list[Chapter]) -> str:
    return (
        f'{render_query_input("filter", "Filter document")}'
        '<p class="filter-status" data-filter-status aria-live="polite">All chapters.</p>'
        '<div class="filter-browser" data-filter-browser>'
        '<section class="filter-browser-section" data-filter-presets-section hidden>'
        '<h3>Presets</h3><div class="filter-pills" data-filter-presets data-transient-content></div>'
        '</section>'
        '<section class="filter-browser-section" data-filter-selections-section hidden>'
        '<h3>Selected</h3><div class="filter-pills" data-filter-selections data-transient-content></div>'
        '</section>'
        '<section class="filter-browser-section">'
        '<h3>Fields</h3><div class="filter-fields" data-filter-fields data-transient-content></div>'
        '</section></div>'
    )


BAR = BarDefinition(
    key="filter",
    label="Filter",
    icon="filter",
    help="Filter document content",
    order=20,
    render=render,
)
