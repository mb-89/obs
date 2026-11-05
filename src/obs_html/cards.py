"""Bounded Markdown cards; only record selection and aggregation enter the browser."""
from functools import cache
from html import escape
from importlib.resources import files
import json

from jsonschema import Draft202012Validator
import yaml
from obs_html.markdown import shared_authoring_markdown


@cache
def _schema():
    return json.loads(files("obs_html").joinpath("cards.schema.json").read_text(encoding="utf-8"))


@cache
def _validator():
    return Draft202012Validator(_schema())


@cache
def _count_query_validator():
    return Draft202012Validator({"$ref": "#/$defs/countQuery", "$defs": _schema()["$defs"]})


def parse_card_spec(text, source_path, place="cards fence"):
    from obs.input import input_error, schema_error
    from obs_html.content import ContentError

    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ContentError(str(input_error(
            source_path, place, f"is not valid YAML: {error}",
            "Write JSON or YAML; see capabilities/cards-metrics",
        ))) from error
    error = schema_error(list(_validator().iter_errors(spec)), source_path,
                         "capabilities/cards-metrics", place=place)
    if error:
        raise ContentError(str(error))
    for index, card in enumerate(spec["cards"]):
        if any(token.type == "fence" and token.info.strip() == "cards"
               for token in shared_authoring_markdown().parse(card["body"])):
            raise ContentError(str(input_error(
                source_path, f"{place}, cards[{index}].body", "contains a nested cards fence",
                "Move the inner cards fence out of the card body; see capabilities/cards-metrics",
            )))
    return spec


def validate_count_query(query, source_path, field="query"):
    from obs.input import schema_error
    from obs_html.content import ContentError

    error = schema_error(list(_count_query_validator().iter_errors(query)), source_path,
                         "capabilities/queries", field=field)
    if error:
        raise ContentError(str(error))


def render_cards(text, render_body, source_path, source_metadata=None):
    from obs_html.content import ContentError

    spec = parse_card_spec(text, source_path)
    cards = []
    for card in spec["cards"]:
        series = card.get("obsHtml", {}).get("metricsFrom")
        if series:
            if source_metadata is None:
                raise ContentError("Cards metric series requires a canonical source.")
            value = source_metadata(series["sourceNote"])
            for part in series["property"].split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if not isinstance(value, list):
                raise ContentError(f"Cards metric series source must be a list: {series['property']}")
            labels = set()
            for item in value:
                fields = [item.get(series[key]) if isinstance(item, dict) else None
                          for key in ("labelProperty", "distinctProperty")]
                if any(not isinstance(field, str) or not field.strip() for field in fields) \
                        or fields[0] in labels:
                    raise ContentError("Cards metric series requires unique labels and nonempty field names.")
                labels.add(fields[0])
        metrics = [dict(metric) for metric in card.get("metrics", [])]
        for metric in metrics:
            if "secondary" in metric:
                metric["valueHtml"] = render_body(
                    f'[[{metric["from"]}]] ([[{metric["secondary"]}]])'
                ).strip().removeprefix("<p>").removesuffix("</p>")
        payload = escape(json.dumps(metrics, ensure_ascii=False), quote=True)
        slots = "".join(
            f'<div data-record-metric="{index}" role="status" aria-busy="true">Calculating…</div>'
            for index in range(len(metrics)))
        metric_class = f'record-metrics--{card["metricStyle"]}' if card.get("metricStyle") else ""
        series_data = f' data-record-series="{escape(json.dumps(series), quote=True)}"' if series else ""
        cards.append(
            f'<section class="content-card record-card" data-record-card="{payload}"{series_data}>'
            f'<header class="content-card-title">{escape(card["title"])}</header>'
            + (f'<div class="record-metrics {metric_class}">{slots}</div>'
               if metrics or series else "")
            + render_body(card["body"]) + "</section>"
        )
    return '<div class="record-cards" data-record-cards>' + "".join(cards) + "</div>\n"
