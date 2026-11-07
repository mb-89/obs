"""Test tiers, strict environment mode and the skip summary.

Tiers (highest wins): external > browser > dom > unit. A test gets the tier of the
most expensive dependency found in its own source, the test-module helpers and constants it
references, and its test-module fixtures. An explicit ``@pytest.mark.<tier>`` always wins.

A bare ``pytest`` runs every tier except external, which runs only when selected with
``-m external``; a test named by its node id runs whatever its tier.
"""
import ast
import inspect
import os
import re
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

TIERS = ("unit", "dom", "browser", "external")
STRICT_VARIABLE = "OBS_HTML_STRICT"
EVIDENCE = {
    "external": re.compile(r"OBS_HTML_TEST_AUTHORED_ARTIFACT|OBS_HTML_ARTIFACT_DATA_PROOF|OBS_HTML_TEST_IMPORTED_SNAPSHOT"),
    "browser": re.compile(r"OBS_HTML_TEST_NATIVE_BROWSER|sync_playwright|\.chromium\b"),
    "dom": re.compile(
        r"OBS_HTML_TEST_DOM_MODULE|linkedom|which\([\"']node[\"']\)|[\[(][\"']node[\"']"
        r"|run_artifact_dom_contract|run_browser_script"),
}


def strict() -> bool:
    return os.environ.get(STRICT_VARIABLE) == "1"


class _Sources:
    """Collects the source a test depends on inside the test package.

    Every xdist worker classifies every collected test, so each module's file is resolved and
    parsed once (``_Module``) and each function's source is read from that parse, not tokenized
    again per function."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.functions: dict[object, str] = {}
        self.modules: dict[str, _Module | None] = {}

    def module(self, module: types.ModuleType | None) -> "_Module | None":
        """The parsed test-package module, or None for a module outside the package or its conftest."""
        file = getattr(module, "__file__", None)
        if not file:
            return None
        if file not in self.modules:
            path = Path(file).resolve()
            local = path.parent == self.root and path.name != "conftest.py"
            self.modules[file] = _Module(inspect.getsource(module)) if local else None
        return self.modules[file]

    def collect(self, function, seen: set, parts: list[str]) -> None:
        function = inspect.unwrap(function)
        if function in seen or not isinstance(function, types.FunctionType):
            return
        module = self.module(sys.modules.get(function.__module__))
        if module is None:
            return
        seen.add(function)
        if function not in self.functions:
            self.functions[function] = module.source(function)
        parts.append(self.functions[function])
        for name in _names(function.__code__):
            value = function.__globals__.get(name)
            if isinstance(value, types.FunctionType):
                self.collect(value, seen, parts)
            elif name in module.assignments:
                parts.append(module.assignments[name])


class _Module:
    """One test module's source, parsed once: its module-level assignments by name and each
    function definition's lines, decorators included, by its first line."""

    def __init__(self, source: str):
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
        self.assignments: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.assignments[target.id] = ast.get_source_segment(source, node) or ""
        self.definitions: dict[int, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
                self.definitions[first] = "".join(lines[first - 1:node.end_lineno])

    def source(self, function) -> str:
        """The function's source: its definition's lines, or for a lambda, what inspect reads."""
        found = self.definitions.get(function.__code__.co_firstlineno)
        if found is not None:
            return found
        try:
            return inspect.getsource(function)
        except (OSError, TypeError):
            return ""


def _names(code) -> set[str]:
    names = set(code.co_names)
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            names |= _names(constant)
    return names


class _Evidence:
    """What a test depends on inside the test package: its source text."""

    def __init__(self, item, sources: _Sources):
        self.functions: set = set()
        parts: list[str] = []
        function = getattr(item, "function", None)
        if function is not None:
            sources.collect(function, self.functions, parts)
            for definitions in getattr(item, "_fixtureinfo").name2fixturedefs.values():
                for definition in definitions:
                    sources.collect(definition.func, self.functions, parts)
        for marker in item.iter_markers("skipif"):
            parts.extend(str(argument) for argument in (*marker.args, *marker.kwargs.values()))
        self.text = "\n".join(parts)


def classify(item, sources: _Sources, evidence: _Evidence | None = None) -> str:
    explicit = [tier for tier in TIERS if item.get_closest_marker(tier)]
    if explicit:
        return max(explicit, key=TIERS.index)
    if getattr(item, "function", None) is None:
        return "unit"
    text = (evidence or _Evidence(item, sources)).text
    for tier in reversed(TIERS[1:]):
        if EVIDENCE[tier].search(text):
            return tier
    return "unit"


def _explicitly_named(config) -> set[str]:
    return {argument.replace("\\", "/") for argument in config.args if "::" in argument}


def modify_items(config, items) -> None:
    sources = _Sources(Path(__file__).parent)
    tiers = {}
    for item in items:
        tier = classify(item, sources)
        tiers[item.nodeid] = tier
        item.add_marker(tier)
    config.stash[_TIER_KEY] = tiers
    if config.option.markexpr:
        return
    named = _explicitly_named(config)
    keep, drop = [], []
    for item in items:
        chosen = (tiers[item.nodeid] != "external"
                  or any(item.nodeid.startswith(name) for name in named))
        (keep if chosen else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
    config.stash[_DESELECTED_KEY] = Counter(tiers[item.nodeid] for item in drop)


_TIER_KEY = pytest.StashKey[dict]()
_DESELECTED_KEY = pytest.StashKey[Counter]()
_SKIPS_KEY = pytest.StashKey[list]()


def make_report(item, report) -> None:
    if not report.skipped or hasattr(report, "wasxfail"):
        return
    reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
    reason = reason.removeprefix("Skipped: ")
    item.config.stash.setdefault(_SKIPS_KEY, []).append((item.nodeid, reason))
    if strict():
        report.outcome = "failed"
        report.longrepr = (
            f"{STRICT_VARIABLE}=1 turns this environment-dependent skip into a failure:\n  {reason}"
        )


def worker_finish(config) -> None:
    """In an xdist worker, hand its tiers and skips to the controller, which writes the summary."""
    output = getattr(config, "workeroutput", None)
    if output is not None:
        output["obs_tiers"] = {
            "tiers": config.stash.get(_TIER_KEY, {}),
            "deselected": dict(config.stash.get(_DESELECTED_KEY, Counter())),
            "skips": config.stash.get(_SKIPS_KEY, []),
        }


def node_down(config, node) -> None:
    """On the xdist controller, take a finished worker's tiers (every worker collects the same
    items) and add its skips."""
    data = getattr(node, "workeroutput", {}).get("obs_tiers")
    if data:
        config.stash[_TIER_KEY] = data["tiers"]
        config.stash[_DESELECTED_KEY] = Counter(data["deselected"])
        config.stash.setdefault(_SKIPS_KEY, []).extend(tuple(skip) for skip in data["skips"])


def terminal_summary(terminalreporter, config) -> None:
    write = terminalreporter.write_line
    terminalreporter.section("tiers and skips")
    tiers = config.stash.get(_TIER_KEY, {})
    deselected = config.stash.get(_DESELECTED_KEY, Counter())
    collected = Counter(tiers.values())
    ran = {tier: collected[tier] - deselected[tier] for tier in TIERS if collected[tier] - deselected[tier]}
    write("selected tiers: " + (", ".join(f"{tier} {count}" for tier, count in ran.items()) or "none"))
    if deselected:
        write("deselected tiers: " + ", ".join(f"{tier} {deselected[tier]}" for tier in TIERS if deselected[tier])
              + "  (external needs hand-supplied inputs: `-m external`)")
    skips = config.stash.get(_SKIPS_KEY, [])
    mode = "on: skips fail" if strict() else "off: set OBS_HTML_STRICT=1 to make them fail"
    write(f"environment skips: {len(skips)} (strict mode {mode})")
    for reason, count in Counter(reason for _, reason in skips).most_common():
        write(f"  {count:4d} x {reason}")
