"""Read-only portable figures and a deliberately bounded numeric expression sampler."""
from __future__ import annotations

import ast
import base64
import json
import math
import mimetypes
import operator
import re
from functools import cache
from html import escape, unescape
from importlib.resources import files
from pathlib import Path
from xml.etree import ElementTree

import yaml
from jsonschema import Draft202012Validator

from .sankey import COUNT_LABELS
from .timings import stage


class FigureError(ValueError):
    """An authored figure violates its data-only input contract."""


@cache
def _schema():
    return json.loads(files("obs_html").joinpath("figure.schema.json").read_text(encoding="utf-8"))


@cache
def _figure_validator():
    return Draft202012Validator(_schema())


@cache
def _sankey_validator():
    schema = _schema()
    return Draft202012Validator(
        {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/sankeyGraph"},
    )


def _finite(value):
    if isinstance(value, list):
        if not value or len(value) > 2048:
            raise FigureError("Figure arrays require 1–2048 values.")
        if any(isinstance(item, list) for item in value):
            raise FigureError("Figure parameters are one-dimensional numeric arrays.")
        return [_finite(item) for item in value]
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise FigureError("Figure values must be finite numbers or numeric arrays.")
    return value


def _binary(fn, left, right):
    if isinstance(left, list) or isinstance(right, list):
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                raise FigureError("Figure array lengths differ.")
            return [_binary(fn, a, b) for a, b in zip(left, right)]
        return [_binary(fn, a, right) for a in left] if isinstance(left, list) else [
            _binary(fn, left, b) for b in right
        ]
    return _finite(fn(left, right))


def _power(a, b):
    if abs(b) > 256:
        raise FigureError("Figure exponent exceeds the bounded numeric language.")
    return a ** b


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: _power}
_FUNCS = {"sqrt": math.sqrt, "exp": math.exp, "log": math.log,
          "sf": lambda x: math.erfc(x / math.sqrt(2)) / 2}
_REDUCE = {"sum": sum, "mean": lambda x: sum(x) / len(x), "prod": math.prod}


def _expression(expression):
    if not isinstance(expression, str) or len(expression) > 2048:
        raise FigureError("Figure equation must be a bounded expression string.")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise FigureError(f"Invalid figure equation: {error}") from error
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise FigureError("Figure equation has too many terms.")

    def visit(node, names):
        if isinstance(node, ast.Expression):
            return visit(node.body, names)
        if isinstance(node, ast.Constant):
            return _finite(node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _binary(_OPS[type(node.op)], visit(node.left, names), visit(node.right, names))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return _binary(operator.mul, -1 if isinstance(node.op, ast.USub) else 1, visit(node.operand, names))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and len(node.args) == 1 and not node.keywords):
            name = node.func.id
            value = visit(node.args[0], names)
            if name in _REDUCE:
                return _finite(_REDUCE[name](value if isinstance(value, list) else [value]))
            if name in _FUNCS:
                return _binary(lambda a, _: _FUNCS[name](a), value, 0)
        raise FigureError("Unsupported figure expression; only bounded arithmetic and named math calls are allowed.")

    return lambda names: visit(tree, names)


def compile_plot(spec, parameters):
    """Sample data expressions without eval, imports, attributes or authored execution."""
    try:
        if not isinstance(parameters, dict):
            raise FigureError("Figure parameters must be a JSON object.")
        samples = spec["samples"]
        if isinstance(samples, bool) or not isinstance(samples, int) or not 2 <= samples <= 2000:
            raise FigureError("Figure samples must be an integer between 2 and 2000.")
        lo, hi = _finite(spec["domain"])
        if lo >= hi:
            raise FigureError("Figure domain must increase.")
        names = {}
        for name, value in parameters.items():
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name == "x":
                raise FigureError("Invalid figure parameter name.")
            names[name] = _finite(value)
        equations = []
        for name, expression in spec["equations"].items():
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name in names or name == "x":
                raise FigureError("Figure equation names must be unique and cannot replace parameters.")
            equations.append((name, _expression(expression)))
        if not equations or len(equations) > 64:
            raise FigureError("Figure requires 1–64 equations.")
        xs = [lo + (hi - lo) * i / (samples - 1) for i in range(samples)]
        columns = {name: [] for name, _ in equations}
        for x in xs:
            env = {**names, "x": x}
            for name, evaluate in equations:
                env[name] = _finite(evaluate(env))
                columns[name].append(env[name])
        data = []
        for trace in spec["traces"]:
            tx = trace.get("at", xs)
            if isinstance(tx, str):
                tx = names[tx]
            ys = columns[trace["y"]]
            if "at" in trace:
                ys = []
                for x in _finite(tx):
                    env = {**names, "x": x}
                    for name, evaluate in equations:
                        env[name] = _finite(evaluate(env))
                    ys.append(env[trace["y"]])
            if any(isinstance(y, list) for y in ys):
                raise FigureError("A plotted equation must reduce to one number per sample.")
            data.append({
                "x": tx, "y": ys, "type": "scatter", "mode": trace.get("mode", "lines"),
                "name": trace["label"], "yaxis": trace.get("axis", "y"),
                "showlegend": trace.get("legend", True),
                "marker": {"color": trace.get("color"), "symbol": trace.get("marker", "circle")},
                "line": {"color": trace.get("color"), "dash": trace.get("dash", "solid"),
                         "width": trace.get("width", 2)},
            })
        if not 1 <= len(data) <= 64:
            raise FigureError("Figure requires 1–64 traces.")
        return {"data": data, "layout": spec.get("layout", {})}
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError, RecursionError) as error:
        if isinstance(error, FigureError):
            raise
        raise FigureError(f"Invalid figure plot: {error}") from error


def _asset(name, note, vault):
    if not isinstance(name, str):
        raise FigureError("Figure asset path must be a string.")
    path = (note.parent / name).resolve()
    if not path.is_relative_to(vault.resolve()):
        raise FigureError("Figure asset escapes the vault.")
    if not path.is_file():
        raise FigureError(f"Missing figure asset: {name}")
    return path


def _sankey_graph(source):
    if source.stat().st_size > 4 * 1024 * 1024:
        raise FigureError("Sankey source JSON exceeds 4 MiB.")
    graph = json.loads(source.read_text(encoding="utf-8"))
    errors = list(_sankey_validator().iter_errors(graph))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        if error.validator == "maxItems":
            detail = f"has more than {error.validator_value} items"
        elif error.validator == "minItems":
            detail = f"requires at least {error.validator_value} items"
        else:
            detail = error.message[:160]
        raise FigureError(f"Invalid Sankey graph at {location}: {detail}.")
    nodes = graph["nodes"]
    by_id = {}
    for node in nodes:
        if node["id"] in by_id:
            raise FigureError(f"Invalid Sankey graph: duplicate node id {node['id']!r}.")
        by_id[node["id"]] = node
        if node["stage"] < 0 and node.get("placement") not in {"above", "below"}:
            raise FigureError("Invalid Sankey graph: negative stages require explicit sink placement.")
    sources = {link["source"] for link in graph["links"]}
    for node in nodes:
        if "branchSource" in node:
            anchor = by_id.get(node["branchSource"])
            if anchor is None or anchor.get("placement", "flow") != "flow":
                raise FigureError("Invalid Sankey graph: branchSource must name an existing flow node.")
    if any(node.get("placement") in {"above", "below"} and node["id"] in sources for node in nodes):
        raise FigureError("Invalid Sankey graph: placed sinks must not have outgoing links.")
    for link in graph["links"]:
        value = link["value"]
        if isinstance(value, bool) or not math.isfinite(value):
            raise FigureError("Invalid Sankey graph: link values must be finite numbers.")
        source_node = by_id.get(link["source"])
        target_node = by_id.get(link["target"])
        if source_node is None or target_node is None:
            raise FigureError("Invalid Sankey graph: every link endpoint must name an existing node.")
        placed_sink = target_node.get("placement") in {"above", "below"}
        if source_node["stage"] >= target_node["stage"] and not placed_sink:
            raise FigureError("Invalid Sankey graph: each link must move to a later stage.")
    return graph, by_id


def _sankey_number(value):
    return format(value, ".6g")


def _render_sankey(graph, nodes, caption, source_name, caption_html, alt="", source_note=None,
                   *, layout_width=0, identity="", count_labels=COUNT_LABELS):
    stages = sorted({node["stage"] for node in graph["nodes"]})
    columns = {stage: [] for stage in stages}
    incoming = {node["id"]: 0.0 for node in graph["nodes"]}
    outgoing = {node["id"]: 0.0 for node in graph["nodes"]}
    links_from = {node["id"]: [] for node in graph["nodes"]}
    links_to = {node["id"]: [] for node in graph["nodes"]}
    for node in graph["nodes"]:
        columns[node["stage"]].append(node)
    for link in graph["links"]:
        outgoing[link["source"]] += link["value"]
        incoming[link["target"]] += link["value"]
        links_from[link["source"]].append(link)
        links_to[link["target"]].append(link)
    weights = {
        node["id"]: max(incoming[node["id"]], outgoing[node["id"]])
        for node in graph["nodes"]
    }
    largest_column = max(sum(weights[node["id"]] for node in column) for column in columns.values())
    label_width = max(len(node["label"]) for node in graph["nodes"]) * 7 + 24
    stage_spacing = max(180, label_width)
    width = max(700, 160 + stage_spacing * (len(stages) - 1))
    tallest_column = max(len(column) for column in columns.values())
    above = max(sum(node.get("placement") == "above" for node in column) for column in columns.values())
    below = max(sum(node.get("placement") == "below" for node in column) for column in columns.values())
    height = max(680, 120 + tallest_column * 24) + (above + below) * 60
    left, right = 80, width - 80
    def stage_x(index):
        return (left + right) / 2 if len(stages) == 1 else left + (right - left) * index / (len(stages) - 1)

    top, bottom = 52 + above * 60, height - 52 - below * 60
    available = bottom - top
    node_gap = 12
    min_node_height = 10
    high = available / max(largest_column, 1)

    def column_height(column, scale):
        flow = [node for node in column if node.get("placement", "flow") == "flow"]
        return sum(max(min_node_height, weights[node["id"]] * scale) for node in flow) + node_gap * (len(flow) - 1)

    low = 0.0
    for _ in range(64):
        scale = (low + high) / 2
        if any(column_height(column, scale) > available for column in columns.values()):
            high = scale
        else:
            low = scale
    scale = low
    positions = {}
    for index, stage in enumerate(stages):
        x = stage_x(index)
        column = columns[stage]
        used = column_height(column, scale)
        y = top + (available - used) / 2
        rails = {"above": 0, "below": 0}
        for node in column:
            placement = node.get("placement", "flow")
            if placement in rails:
                rail = rails[placement]
                rails[placement] += 1
                bar_width = max(40, min(120, 40 + max(0, weights[node["id"]] - 1) * 0.9))
                source_stages = [nodes[link["source"]]["stage"] for link in links_to[node["id"]]]
                source_x = stage_x(stages.index(max(source_stages))) if source_stages else x
                positions[node["id"]] = {
                    "x": (source_x + x) / 2 - bar_width / 2,
                    "y": 52 + rail * 60 if placement == "above" else bottom + 40 + rail * 60,
                    "height": 8, "width": bar_width, "horizontal": True,
                }
                continue
            node_height = max(min_node_height, weights[node["id"]] * scale)
            positions[node["id"]] = {"x": x, "y": y, "height": node_height, "width": 18}
            y += node_height + node_gap

    link_centers = {}
    for node_id, links in links_from.items():
        position = positions[node_id]
        total = outgoing[node_id] * scale
        y = position["y"] + (position["height"] - total) / 2
        for link in links:
            thickness = link["value"] * scale
            link_centers[id(link)] = (y + thickness / 2, None)
            y += thickness
    for node_id, links in links_to.items():
        position = positions[node_id]
        total = incoming[node_id] * scale
        y = position["y"] + (position["height"] - total) / 2
        for link in links:
            thickness = link["value"] * scale
            source_y, _ = link_centers[id(link)]
            link_centers[id(link)] = (source_y, y + thickness / 2)
            y += thickness

    encoded = escape(json.dumps(
        {"caption": caption, "alt": alt, "source": source_name, **graph,
         "countLabels": count_labels,
         **({"sourceNote": source_note} if source_note else {})},
        separators=(",", ":"), allow_nan=False,
    ), quote=True)
    incoming_series = {
        (link["series"], link["target"]): link
        for link in graph["links"] if "series" in link
    }
    for link in graph["links"]:
        incoming_link = incoming_series.get((link.get("series"), link["source"]))
        if incoming_link is not None:
            _, end_y = link_centers[id(link)]
            link_centers[id(link)] = (link_centers[id(incoming_link)][1], end_y)
    if graph.get("branchLayout") == "split":
        from .sankey import split_layout
        width, height, scale, positions, centers = split_layout(
            graph, minimum_width=layout_width, count_labels=count_labels,
        )
        link_centers = {id(link): center for link, center in zip(graph["links"], centers)}
    accessible_name = alt or caption or source_name
    parts = [
        f'<figure class="engineering-figure figure-sankey" data-artifact-figure data-engineering-figure data-figure-kind="sankey" data-figure-spec="{encoded}"{identity}>'
        f'<svg xmlns="http://www.w3.org/2000/svg" class="sankey-canvas" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(accessible_name, quote=True)}" style="--sankey-width:{width}px">'
        f'<title>{escape(accessible_name)}</title>'
    ]
    for link in graph["links"]:
        source_node, target_node = nodes[link["source"]], nodes[link["target"]]
        start_y, end_y = link_centers[id(link)]
        source_position = positions[link["source"]]
        target_position = positions[link["target"]]
        start_x = source_position["x"] + source_position["width"]
        end_x = target_position["x"]
        if target_position.get("horizontal"):
            fraction = max(0, min(1, (start_y - source_position["y"]) / max(1, source_position["height"])))
            reverse = (graph.get("branchLayout") == "split" and
                       (target_position["x"] + target_position["width"] / 2 - start_x) *
                       (target_position["y"] + 4 - source_position["y"] - source_position["height"] / 2) > 0)
            end_x += (1 - fraction if reverse else fraction) * target_position["width"]
            end_y = target_position["y"] + target_position["height"] / 2
        control = (end_x - start_x) * (0.5 if graph.get("branchLayout") == "split" else 0.45)
        path = (
            f"M {_sankey_number(start_x)} {_sankey_number(start_y)} "
            f"C {_sankey_number((start_x + end_x) / 2)} {_sankey_number(start_y)}, "
            f"{_sankey_number(end_x)} {_sankey_number((start_y + end_y) / 2)}, "
            f"{_sankey_number(end_x)} {_sankey_number(end_y)}"
        ) if target_position.get("horizontal") else _path(start_x, start_y, end_x, end_y, control)
        color = link.get("color") or source_node.get("color") or target_node.get("color") or "#73869a"
        label = link.get("label") or _sankey_number(link["value"])
        description = f'{source_node["label"]} → {target_node["label"]}: {label} ({_sankey_number(link["value"])})'
        thickness = link["value"] * scale
        series = f' data-series="{escape(link["series"], quote=True)}"' if "series" in link else ""
        dash = ' stroke-dasharray="10 10"' if link.get("originColor") else ""
        parts.append(
            f'<path class="sankey-link"{series} data-flow-value="{_sankey_number(link["value"])}" '
            f'd="{path}" fill="none" '
            f'stroke="{color}"{dash} stroke-opacity=".48" stroke-width="{_sankey_number(thickness)}">'
            f'<title>{escape(description)}</title></path>'
        )
        if link.get("originColor"):
            parts.append(
                f'<path class="sankey-origin"{series} d="{path}" '
                f'fill="none" stroke="{link["originColor"]}" stroke-opacity=".48" '
                f'stroke-width="{_sankey_number(thickness)}" stroke-dasharray="10 10" stroke-dashoffset="10"/>'
            )
        if thickness >= 24:
            parts.append(
                f'<text class="sankey-link-label" x="{_sankey_number((start_x + end_x) / 2)}" '
                f'y="{_sankey_number((start_y + end_y) / 2 + 4)}" text-anchor="middle">'
                f'{escape(label)}</text>'
            )
    for node in graph["nodes"]:
        position = positions[node["id"]]
        node_x, node_y = position["x"], position["y"]
        node_height = position["height"]
        color = node.get("color", "#587894")
        label_x = position.get("labelX", node_x + position["width"] / 2)
        lower = not position["upper"] if position.get("horizontal") and graph.get("branchLayout") == "split" else node.get("placement") == "below"
        lines = node["label"].split("\n")
        label_y = position.get("labelY", node_y + 22 if lower else node_y - 7 - (len(lines) - 1) * 14)
        label_html = escape(node["label"])
        if graph.get("branchLayout") == "split":
            label_html = ""
            for index, line in enumerate(lines):
                label_html += (f'<tspan x="{_sankey_number(label_x)}" dy="{"1.15em" if index else "0"}">'
                               f'{escape(line)}</tspan>')
        total_in = _sankey_number(incoming[node["id"]])
        total_out = _sankey_number(outgoing[node["id"]])
        parts.append(
            f'<g class="sankey-node" data-node-id="{escape(node["id"], quote=True)}">'
            f'<rect x="{_sankey_number(node_x)}" y="{_sankey_number(node_y)}" width="{_sankey_number(position["width"])}" '
            f'height="{_sankey_number(node_height)}" rx="2" fill="{color}">'
            f'<title>{escape(node["label"])}; incoming {total_in}, outgoing {total_out}</title></rect>'
            f'<text x="{_sankey_number(label_x)}" y="{_sankey_number(label_y)}" '
            f'text-anchor="{position.get("labelAnchor", "middle")}" class="sankey-label">{label_html}'
            f'<title>{escape(node["label"])}</title></text></g>'
        )
    parts.append("</svg>")
    if caption_html:
        parts.append(f"<figcaption>{caption_html}</figcaption>")
    parts.append("</figure>\n")
    return "".join(parts)


def _path(start_x, start_y, end_x, end_y, control):
    return (
        f"M {_sankey_number(start_x)} {_sankey_number(start_y)} "
        f"C {_sankey_number(start_x + control)} {_sankey_number(start_y)}, "
        f"{_sankey_number(end_x - control)} {_sankey_number(end_y)}, "
        f"{_sankey_number(end_x)} {_sankey_number(end_y)}"
    )


def _plain_text(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", "", html))).strip()


def figure_spec(text: str) -> dict:
    spec = yaml.safe_load(text)
    errors = list(_figure_validator().iter_errors(spec))
    if errors:
        raise FigureError(errors[0].message)
    return spec


@stage("figures")
def render_figure(
    text: str, note: Path, vault: Path, *, render_caption=escape,
    include_plot_fallback: bool = True, number: str | None = None, anchor: str | None = None,
) -> str:
    try:
        spec = figure_spec(text)
        paragraphs = spec.get("caption", "")
        rendered = (
            [render_caption(paragraph) for paragraph in paragraphs] if isinstance(paragraphs, list)
            else [render_caption(paragraphs)] if paragraphs else []
        )
        # Accessible names use the rendered caption text, not its Markdown/wikilink source.
        caption = " ".join(_plain_text(paragraph) for paragraph in rendered)
        number_html = (
            f'<span class="figure-number">{escape(number)}:</span> ' if number and paragraphs else ""
        )
        caption_html = "".join(
            f"<p data-figure-caption-review>{number_html if index == 0 else ''}{paragraph}</p>"
            for index, paragraph in enumerate(rendered)
        ) if isinstance(paragraphs, list) else (
            number_html + rendered[0] if rendered else ""
        )
        caption_element = f"<figcaption>{caption_html}</figcaption>" if caption_html else ""
        identity = (f' id="{escape(anchor, quote=True)}"' if anchor else "") + (
            f' data-figure-number="{escape(number, quote=True)}"' if number_html else ""
        )
        source = _asset(spec["source"], note, vault)
        if spec["kind"] == "image":
            mime = mimetypes.guess_type(source.name)[0]
            if mime is None or not mime.startswith("image/"):
                raise FigureError("An image figure source must be an image asset.")
            uri = f"data:{mime};base64," + base64.b64encode(source.read_bytes()).decode("ascii")
            return (
                f'<figure class="artifact-figure" data-artifact-figure{identity}>'
                f'<img src="{uri}" alt="{escape(spec.get("alt") or caption or spec["source"], quote=True)}">'
                f'{caption_element}</figure>\n'
            )
        if spec["kind"] == "sankey":
            graph, nodes = _sankey_graph(source)
            return _render_sankey(
                graph, nodes, caption, spec["source"], caption_html, spec.get("alt", ""),
                spec.get("sourceNote"), identity=identity,
                count_labels=COUNT_LABELS | spec.get("countLabels", {}),
            )
        fallback = _asset(spec["fallback"], note, vault)
        svg = fallback.read_bytes()
        root = ElementTree.fromstring(svg)
        if root.tag != "{http://www.w3.org/2000/svg}svg" or not root.get("viewBox"):
            raise FigureError("Figure fallback must be SVG with a viewBox.")
        bounds = _finite([float(value) for value in re.split(r"[,\s]+", root.get("viewBox").strip())])
        if len(bounds) != 4 or bounds[2] <= 0 or bounds[3] <= 0:
            raise FigureError("Figure fallback viewBox must have positive width and height.")
        values = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise FigureError("Figure source must be a JSON object.")
        if spec["kind"] == "plot":
            payload = compile_plot(spec, values)
        else:
            if values.get("version") != 1 or not isinstance(values.get("panels"), list):
                raise FigureError("SVG figure source requires version 1 and panels.")
            seen = set()
            for panel in values["panels"]:
                if not isinstance(panel["id"], str) or not panel["id"] or not isinstance(panel["title"], str):
                    raise FigureError("SVG panel ids and titles must be strings.")
                box = _finite(panel["box"])
                if len(box) != 4 or box[2] <= 0 or box[3] <= 0 or panel["id"] in seen:
                    raise FigureError("SVG panels need unique ids and positive viewport boxes.")
                seen.add(panel["id"])
            if not 1 <= len(seen) <= 64:
                raise FigureError("SVG figure requires 1–64 panels.")
            payload = values
        payload["kind"] = spec["kind"]
        payload["viewBox"] = root.get("viewBox")
        payload["source"] = spec["source"]
        payload["fallback"] = spec["fallback"]
        payload["alt"] = spec.get("alt") or caption or spec["source"]
        uri = "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")
        encoded = escape(json.dumps(payload, separators=(",", ":"), allow_nan=False), quote=True)
        caption = escape(spec.get("alt") or caption or spec["source"])
        static_image = (
            f'<img class="figure-default" src="{uri}" alt="{caption}">'
            if spec["kind"] != "plot" or include_plot_fallback else ""
        )
        return (
            f'<figure class="engineering-figure" data-artifact-figure data-engineering-figure data-figure-kind="{spec["kind"]}" data-figure-spec="{encoded}"{identity}>'
            f'{static_image}'
            '<div class="figure-live" aria-label="Interactive figure"></div>'
            f'{caption_element}</figure>\n'
        )
    except (yaml.YAMLError, json.JSONDecodeError, ElementTree.ParseError, OSError,
            KeyError, TypeError, ValueError, OverflowError, RecursionError) as error:
        if isinstance(error, FigureError):
            raise
        raise FigureError(f"Invalid figure in {note}: {error}") from error
