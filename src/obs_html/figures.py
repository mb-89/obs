"""Figures from the Document's FigureDescriptors: Plotly plots and Sankey diagrams.

A descriptor carries neutral data, panels with axes, and provenance (the core's
figure.schema.json). This adapter reads two shapes of ``data``: ``sankey`` (a graph valid
against sankey.schema.json) and ``traces`` (numeric series drawn on the descriptor's panels).
"""
from __future__ import annotations

import json
import math
from functools import cache
from html import escape
from importlib.resources import files

from jsonschema import Draft202012Validator

from .sankey import COUNT_LABELS
from .timings import stage as timed


class FigureError(ValueError):
    """A FigureDescriptor's data does not match a figure this adapter draws."""


@cache
def _sankey_validator():
    return Draft202012Validator(
        json.loads(files("obs_html").joinpath("sankey.schema.json").read_text(encoding="utf-8")))


def _sankey_graph(graph):
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
        f'<figure class="engineering-figure figure-sankey" data-report-figure data-engineering-figure data-figure-kind="sankey" data-figure-spec="{encoded}"{identity}>'
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


@timed("figures")
def render_descriptor(descriptor: dict, anchor: str) -> str:
    """Render one FigureDescriptor as an interactive figure with a printable form."""
    data = descriptor["data"]
    name = descriptor["id"]
    identity = f' id="{escape(anchor, quote=True)}"'
    if "sankey" in data:
        graph, nodes = _sankey_graph(data["sankey"])
        return _render_sankey(graph, nodes, "", name, "", name, identity=identity,
                              count_labels=COUNT_LABELS | data.get("countLabels", {}))
    if "traces" in data:
        payload = {**_plot(descriptor), "kind": "plot", "source": name, "alt": name}
        encoded = escape(json.dumps(payload, separators=(",", ":"), allow_nan=False), quote=True)
        return (
            f'<figure class="engineering-figure" data-report-figure data-engineering-figure '
            f'data-figure-kind="plot" data-figure-spec="{encoded}"{identity}>'
            '<div class="figure-live" aria-label="Interactive figure"></div></figure>\n'
        )
    raise FigureError(f"Figure {name}: descriptor data must carry 'sankey' or 'traces'.")


def _plot(descriptor: dict) -> dict:
    """Plotly data and layout: one x/y axis pair per panel, placed by the panel grid."""
    panels = descriptor["panels"]
    rows = max(panel["grid"]["row"] + panel["grid"]["rowSpan"] for panel in panels)
    columns = max(panel["grid"]["column"] + panel["grid"]["columnSpan"] for panel in panels)
    layout: dict[str, object] = {}
    axes: dict[str, tuple[str, str]] = {}
    for index, panel in enumerate(panels, start=1):
        if len(panel["axes"]) != 2:
            raise FigureError(f"Figure {descriptor['id']}: panel {panel['id']} needs an x and a y axis.")
        suffix = "" if index == 1 else str(index)
        grid = panel["grid"]
        domains = {
            "x": [grid["column"] / columns, (grid["column"] + grid["columnSpan"]) / columns],
            "y": [1 - (grid["row"] + grid["rowSpan"]) / rows, 1 - grid["row"] / rows],
        }
        for letter, axis in zip("xy", panel["axes"]):
            limits = axis["limits"]
            log = axis["scale"] == "log"
            if log and (limits["minimum"] <= 0 or limits["maximum"] <= 0):
                raise FigureError(f"Figure {descriptor['id']}: log axis {axis['id']} needs positive limits.")
            layout[f"{letter}axis{suffix}"] = {
                "title": {"text": axis["label"]}, "type": "log" if log else "linear",
                "range": [math.log10(limits["minimum"]), math.log10(limits["maximum"])] if log
                else [limits["minimum"], limits["maximum"]],
                "domain": domains[letter],
                **({"anchor": f"{'y' if letter == 'x' else 'x'}{suffix}"} if suffix else {}),
            }
        axes[panel["id"]] = (f"x{suffix}", f"y{suffix}")
    traces = descriptor["data"]["traces"]
    if not isinstance(traces, list) or not 1 <= len(traces) <= 64:
        raise FigureError(f"Figure {descriptor['id']}: traces must be a list of 1–64 series.")
    data = []
    for trace in traces:
        panel = trace.get("panel", panels[0]["id"])
        if panel not in axes:
            raise FigureError(f"Figure {descriptor['id']}: trace names unknown panel {panel!r}.")
        x, y = trace.get("x"), trace.get("y")
        if (not isinstance(x, list) or not isinstance(y, list) or len(x) != len(y) or not x
                or not all(_finite(value) for value in x + y)):
            raise FigureError(f"Figure {descriptor['id']}: each trace needs equally long finite x and y lists.")
        data.append({
            "x": x, "y": y, "type": "scatter", "mode": trace.get("mode", "lines"),
            "name": str(trace.get("label", "")), "xaxis": axes[panel][0], "yaxis": axes[panel][1],
            "showlegend": bool(trace.get("label")),
            **({"line": {"color": trace["color"]}, "marker": {"color": trace["color"]}}
               if "color" in trace else {}),
        })
    return {"data": data, "layout": layout}


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
