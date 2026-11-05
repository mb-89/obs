from html import escape
from obs_html.semantic_assets import markup


WARNING_MESSAGE = (
    "This setting cannot be remembered in this environment. "
    "Download the HTML and open it directly in your browser for full functionality."
)


def warning_markup(setting: str) -> str:
    setting_id = escape(setting, quote=True)
    warning_id = f"storage-warning-{setting_id}"
    message = escape(WARNING_MESSAGE)
    return (
        f'<span class="storage-warning" id="{warning_id}" '
        f'data-storage-warning="{setting_id}" hidden>'
        f'<button class="storage-warning-button" type="button" aria-label="{message}" '
        f'data-hover-help="{message}">{markup("warning")}</button>'
        "</span>"
    )
