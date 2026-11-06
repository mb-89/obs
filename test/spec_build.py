"""obs's spec, built once per run and shared by the core's and every adapter's tests.

Reader: a test that reads obs's spec Document, and whoever changes how the suite builds it;
quality.md, Testing boundaries, owns the rule.

Each kind in BUILDS is built at most once per run: ``document``, the spec's Document with its
capability reference, which every adapter renders itself, and ``adapter-spec``, the HTML adapter's
specification as the spec's producer fence (ADAPTER_SPEC_NOTE) builds it. The first process of the run that
asks builds it under a lock, in the run's folder, and every other
process, of any part, reads what it built. test/suite.py makes the run's folder and names it in
RUN_FOLDER for its parts, and the core's controller starts the Document build as its session
starts (``start``); a focused run (a part's own pytest) builds in its pytest base folder, only
where a test asks.
A build's folder is named by a hash of its inputs (INPUTS: the spec vault without what its
producers write, the core's and the HTML adapter's sources, and this build), so changed inputs are never served a stale build. Each build appends its kind and key to
COUNTER in the run's folder, which test/suite.py reads at the run's end: where one kind was built
twice, the run fails.

The build runs the spec's commands and producers in its vault, offline: the core's
test/offline_obs_document.py serves each remote image as a placeholder, and serves the adapter
specification fence the run's ``adapter-spec`` build (``serve_adapter_spec``), in this build and
in every other build of a copy of the vault in the run. They write only what the producers write
into the vault's generated design_output, as any build of the spec does.

A test that needs another build of the spec (another option, a copied vault) copies the vault
and builds only that variant. ``own_builds`` names a test that builds the spec itself; the
core's test/structure/test_spec_builds.py and the adapter's test/structure/test_quality.py
refuse one outside their named exceptions.
"""
import ast
import hashlib
import re
import os
import shlex
import shutil
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path

from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec"
# The variable test/suite.py names the run's folder in.
RUN_FOLDER = "OBS_SPEC_BUILD"
# In the run's folder: one line per build, its kind and its inputs' key.
COUNTER = "builds.txt"
# The Document build's files, in its folder.
DOCUMENT, CAPABILITIES = "spec.json", "capabilities.json"
# What a build reads, relative to ROOT; GENERATED parts of a path are no input.
INPUTS = ("spec", "src", "adapters/html/src", "adapters/html/spec", "adapters.json", "adapters/html/adapter.json",
          "uv.lock", "test/offline_obs_document.py", "test/spec_build.py")
GENERATED = {"design_output", "__pycache__", "node_modules"}
# The core's obs-document without the network.
OFFLINE_DOCUMENT = ROOT / "test" / "offline_obs_document.py"


class SpecBuildError(Exception):
    """A shared build of obs's spec failed; the message names the step, its command and its output."""


def _run(command, what: str, run: Path, cwd: Path = ROOT, shell: bool = False, **variables: str) -> None:
    """Run a build step, with the run's folder in RUN_FOLDER for test/offline_obs_document.py."""
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    environment.update({RUN_FOLDER: str(run), **variables})
    result = subprocess.run(command, cwd=cwd, env=environment, shell=shell, text=True, encoding="utf-8",
                            capture_output=True, timeout=900)
    if result.returncode:
        shown = command if shell else " ".join(command)
        raise SpecBuildError(f"test/spec_build.py: {what} failed: {shown} (in {cwd})\n"
                             f"{result.stdout[-2000:]}{result.stderr[-2000:]}")


def build_document(folder: Path) -> None:
    """obs's spec as the core's Document, with the capability reference built from its notes."""
    capabilities = SPEC / "capabilities"
    _run([sys.executable, "-m", "obs.capabilities", "--notes", str(capabilities),
          "--coverage", str(capabilities / "coverage.json"), "--output", str(folder / CAPABILITIES)],
         "building the capability reference with the core", folder.parent)
    _run([sys.executable, str(OFFLINE_DOCUMENT), "--document", str(folder / DOCUMENT),
          "--source", str(SPEC / "manifest.md"), "--capability-reference", str(folder / CAPABILITIES),
          "--execute-commands"], "building obs's spec Document with the core, without the network", folder.parent)


# The spec's note whose producer fence builds the HTML adapter's specification.
ADAPTER_SPEC_NOTE = SPEC / "appendix" / "references" / "obs-html-specification.md"


def adapter_spec_fence() -> tuple[str, str]:
    """The adapter specification's producer fence: its command, and the file it writes relative to
    the vault."""
    from obs.note import parser, read_note

    [command] = [token.content.strip() for token in parser().parse(read_note(ADAPTER_SPEC_NOTE).body)
                 if token.type == "fence" and token.info.strip().split() == ["cmd", "silent"]]
    words = shlex.split(command)
    return command, words[words.index("--build-own-spec") + 1]


def build_adapter_spec(folder: Path) -> None:
    """The HTML adapter's specification, built by the spec's own producer fence in ``folder``, with
    this checkout's obs, as uv run finds it from the vault."""
    command, _produced = adapter_spec_fence()
    _run(command, "building the HTML adapter's specification with the spec's producer fence", folder.parent,
         cwd=folder, shell=True, UV_PROJECT=str(ROOT))


BUILDS = {"document": build_document, "adapter-spec": build_adapter_spec}
# The inputs' key, computed once per process.
_keys: dict[str, str] = {}


def inputs_key() -> str:
    """A hash of every input file's path and bytes."""
    if "inputs" not in _keys:
        digest = hashlib.sha256()
        for top in INPUTS:
            path = ROOT / top
            files = [path] if path.is_file() else sorted(path.rglob("*"))
            for file in files:
                parts = file.relative_to(ROOT).parts
                if GENERATED & set(parts) or any(part.startswith(".") for part in parts) or not file.is_file():
                    continue
                digest.update(file.relative_to(ROOT).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
        _keys["inputs"] = digest.hexdigest()[:16]
    return _keys["inputs"]


def base(tmp_path_factory) -> Path:
    """The run's folder: test/suite.py's, or in a focused run the pytest base folder all workers share."""
    if os.environ.get(RUN_FOLDER):
        return Path(os.environ[RUN_FOLDER])
    root = tmp_path_factory.getbasetemp()
    return root.parent if os.environ.get("PYTEST_XDIST_WORKER") else root


def built(run: Path, kind: str) -> Path:
    """The folder holding the run's build of ``kind`` (a key of BUILDS), built once and counted."""
    key = inputs_key()
    folder = run / f"{kind}-{key}"
    with FileLock(f"{folder}.lock"):
        if not (folder / ".built").is_file():
            folder.mkdir(parents=True, exist_ok=True)
            BUILDS[kind](folder)
            with (run / COUNTER).open("a", encoding="utf-8") as counter:
                counter.write(f"{kind} {key}\n")
            (folder / ".built").touch()
    return folder


# The controller's background build, which finish() waits for.
_started: list[threading.Thread] = []


def start(config) -> threading.Thread | None:
    """From the core's ``pytest_sessionstart``: in a run of the complete suite (RUN_FOLDER set),
    start the run's Document build in a thread of the part's controller, before its workers start
    and collect; the thread. It builds through ``built``, so a test that needs the build waits on
    the same lock and the count stays one. A build that fails keeps its error to itself: the test
    that needs the build builds it again and reports it. A worker leaves this to its controller,
    and a focused run builds only where a test asks."""
    if hasattr(config, "workerinput") or not os.environ.get(RUN_FOLDER):
        return None
    run = Path(os.environ[RUN_FOLDER])

    def build() -> None:
        try:
            built(run, "document")
        except Exception:  # Reported by the test that needs the build, which builds it again.
            pass

    thread = threading.Thread(target=build, name="obs-spec-build", daemon=True)
    thread.start()
    _started.append(thread)
    return thread


def finish() -> None:
    """From the core's ``pytest_sessionfinish``: wait for the build ``start`` started."""
    while _started:
        _started.pop().join()


def serve_adapter_spec(command: str, vault: Path) -> bool:
    """For test/offline_obs_document.py's producers: where ``command`` is the adapter specification's
    producer fence, copy the run's ``adapter-spec`` build (the run's folder named in RUN_FOLDER) to
    the file the fence writes in ``vault``; whether it was that fence."""
    fence, produced = adapter_spec_fence()
    if command != fence:
        return False
    if not os.environ.get(RUN_FOLDER):
        raise SpecBuildError(f"test/spec_build.py: {RUN_FOLDER} names no run folder, so the adapter "
                             "specification's producer has no shared build to read. Remedy: run "
                             "test/offline_obs_document.py with the run's folder in it (spec_build.base).")
    target = vault / produced
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(built(Path(os.environ[RUN_FOLDER]), "adapter-spec") / produced, target)
    return True


def counts(run: Path) -> Counter:
    """How often each kind was built in the run's folder."""
    counter = run / COUNTER
    lines = counter.read_text(encoding="utf-8").splitlines() if counter.is_file() else []
    return Counter(line.split()[0] for line in lines if line.strip())


# What builds a vault: the core's build and its CLI, by the module a test imports them from, and
# by the commands and scripts that run them.
BUILDER_IMPORTS = {"obs.document": {"build_document", "main"}}
BUILDER_WORDS = {"obs-document", "obs.document", "OFFLINE_DOCUMENT"}
# The copy of the spec vault the core's conftest.py hands a test.
SPEC_COPY = "spec_vault"
# A path whose segments after its root are these names the spec vault or its manifest.
SPEC_PATHS = (("spec",), ("spec", "manifest.md"))


def _builders(module: ast.Module) -> set[str]:
    """The names a module calls a builder by: ``build_document``, ``main`` or ``document.main``."""
    names = {"build_document"}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module:
            names |= {alias.asname or alias.name for alias in node.names
                      if alias.name in BUILDER_IMPORTS.get(node.module, ())}
            names |= {f"{alias.asname or alias.name}.{function}" for alias in node.names
                      for function in BUILDER_IMPORTS.get(f"{node.module}.{alias.name}", ())}
    return names


def _call_names(call: ast.Call) -> set[str]:
    target = call.func
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Attribute):
        return {target.attr} | ({f"{target.value.id}.{target.attr}"} if isinstance(target.value, ast.Name) else set())
    return set()


def _builds(call: ast.Call, builders: set[str]) -> bool:
    """Whether the call runs a builder, in process or as a command."""
    if _call_names(call) & builders:
        return True
    words = {node.value for node in ast.walk(call) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    words |= {node.id for node in ast.walk(call) if isinstance(node, ast.Name)}
    words |= {node.attr for node in ast.walk(call) if isinstance(node, ast.Attribute)}
    return bool(words & BUILDER_WORDS)


def _segments(node: ast.AST) -> tuple[ast.AST, tuple[str, ...]]:
    """A path ``root / "a" / "b"`` as its root and its constant segments ("a", "b")."""
    segments = []
    while (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant)
           and isinstance(node.right.value, str)):
        segments.insert(0, node.right.value)
        node = node.left
    return node, tuple(segments)


def _unwrapped(node: ast.AST) -> ast.AST:
    """``str(path)``, ``Path(path)`` and ``path.resolve()`` as ``path``."""
    while True:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"str", "Path"} \
                and len(node.args) == 1:
            node = node.args[0]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "resolve":
            node = node.func.value
        else:
            return node


def _is_spec(node: ast.AST, roots: re.Pattern, names: set[str]) -> bool:
    """Whether the node is a path to the spec vault, or its manifest, of obs's checkout or of a copy."""
    node = _unwrapped(node)
    if isinstance(node, ast.Name) and node.id in names:
        return True
    root, segments = _segments(node)
    if root is node:
        return False
    root = _unwrapped(root)
    if isinstance(root, ast.Name) and root.id in names:  # a copy's or the spec's manifest
        return segments == ("manifest.md",)
    return segments in SPEC_PATHS and bool(roots.fullmatch(ast.unparse(root)))


def _names_spec(node: ast.AST, roots: re.Pattern, names: set[str]) -> bool:
    return any(_is_spec(child, roots, names) for child in ast.walk(node))


def _named(statements, roots: str, known_roots: set[str], known_specs: set[str]) -> tuple[re.Pattern, set[str]]:
    """What denotes obs's checkout and the names of the spec vault in a body, to a fixpoint: a name
    assigned a root or a spec path, and the destination a spec path is copied to (``copytree``)."""
    root_names, spec_names = set(known_roots), set(known_specs)
    assignments = [(node.targets[0].id, node.value) for statement in statements for node in ast.walk(statement)
                   if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)]
    copies = [(call.args[1], call.args[0]) for statement in statements for call in ast.walk(statement)
              if isinstance(call, ast.Call) and "copytree" in _call_names(call) and len(call.args) >= 2]
    while True:
        pattern = re.compile("|".join([roots, *map(re.escape, sorted(root_names))]))
        more_roots = {name for name, value in assignments if pattern.fullmatch(ast.unparse(_unwrapped(value)))}
        more_specs = {name for name, value in assignments if _is_spec(value, pattern, spec_names)}
        more_specs |= {target.id for target, source in copies
                       if isinstance(target, ast.Name) and _is_spec(source, pattern, spec_names)}
        if more_roots <= root_names and more_specs <= spec_names:
            return pattern, spec_names
        root_names |= more_roots
        spec_names |= more_specs


def own_builds(path: Path, roots: str, exceptions: set[str]) -> list[str]:
    """Each function of a test module that builds obs's spec, or a copy of its vault, itself: it calls
    a builder (BUILDER_IMPORTS, BUILDER_WORDS) and names the spec vault. A function that stands in for
    ``build_document`` builds nothing. ``roots`` is a regular expression for what denotes obs's
    checkout in the module; ``exceptions`` are the functions allowed a build of their own, each of
    which must still be one, in the module checked."""
    module = ast.parse(path.read_text(encoding="utf-8-sig"))
    builders = _builders(module)
    top = [statement for statement in module.body if isinstance(statement, ast.Assign)]
    module_pattern, module_specs = _named(top, roots, set(), set())
    module_roots = {statement.targets[0].id for statement in top if isinstance(statement.targets[0], ast.Name)
                    and module_pattern.fullmatch(ast.unparse(_unwrapped(statement.value)))}
    functions = [node for statement in module.body
                 for node in ([statement] if isinstance(statement, ast.FunctionDef) else
                              [item for item in statement.body if isinstance(item, ast.FunctionDef)]
                              if isinstance(statement, ast.ClassDef) else [])]

    def stands_in(function: ast.FunctionDef) -> bool:
        return any("setattr" in _call_names(call) and any(
            isinstance(argument, ast.Constant) and argument.value == "build_document" for argument in call.args)
            for call in ast.walk(function) if isinstance(call, ast.Call))

    stand_ins = {function.name for function in functions if stands_in(function)}
    found, built = [], set()
    for function in functions:
        arguments = {argument.arg for argument in function.args.args}
        if function.name in stand_ins or arguments & stand_ins:
            continue
        pattern, names = _named(function.body, roots, module_roots, module_specs | ({SPEC_COPY} & arguments))
        building = [call for call in ast.walk(function) if isinstance(call, ast.Call) and _builds(call, builders)
                    and _names_spec(call, pattern, names)]
        if not building:
            continue
        built.add(function.name)
        if function.name not in exceptions:
            found.append(f"{function.name}: {path.name}:{building[0].lineno} builds obs's spec itself; read the "
                         "run's shared build (test/spec_build.py), or copy the vault, build only that variant "
                         "and name the test with why among the structure test's exceptions")
    found += [f"{name}: {path.name} has no such test that builds obs's spec, which the exceptions name; remove "
              "it from them" for name in sorted(exceptions - built)]
    return found
