"""The fakes of the core's doors that start a process (spec/design_input/quality.md, Testing boundaries):
test/conftest.py puts each in its door's place for every test, and a door's contract test, marked
``pytest.mark.door("<name>")``, keeps the real one and shows that its fake answers alike.

A fake asked for what it does not know fails the test, naming the mark.
"""
import contextlib
import io
import itertools
import os
import shlex
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from obs import components, sources


NAMES = ("component-git", "source-git", "adapter", "shell", "part")
"""The doors a test may mark as its contract with ``pytest.mark.door``."""


class UnknownToFake(AssertionError):
    """A door's fake was asked for what it does not know; the message names the remedy."""


def refuse(door: str, asked: object) -> UnknownToFake:
    return UnknownToFake(f"test/doors.py: the fake of the door {door!r} does not know {asked!r}. Give the fake "
                         f"what the test needs, or make the test the door's contract test with "
                         f'pytest.mark.door("{door}") (spec/design_input/quality.md, Testing boundaries)')


COMPONENT_HOST = "https://example.test/"
"""Where the components fake's repositories are reached: COMPONENT_HOST<owner>/<repository>.git."""


@dataclass
class Repository:
    """A repository in memory: its tree as each commit left it, and each tag with its commit."""
    files: dict[str, str] = field(default_factory=lambda: {})
    tags: dict[str, tuple[str, str, dict[str, str], bool]] = field(default_factory=dict)
    """Each tag's object, its commit, the commit's tree and whether the tag is annotated."""


class ComponentGit:
    """The fake of components.GIT: checkouts with their remotes, and a host of repositories in memory
    with the topic listing it answers for each owner (components.LISTINGS)."""

    def __init__(self) -> None:
        self.checkouts: dict[Path, dict[str, str]] = {}
        self.repositories: dict[str, Repository] = {}
        self.topics: dict[str, list[str]] = {}
        self._objects = itertools.count(1)

    # What a test sets up.

    def checkout(self, folder: Path, **remotes: str) -> Path:
        """``folder`` as a Git checkout whose remotes are ``remotes``, name to address."""
        self.checkouts[folder] = dict(remotes)
        return folder

    def add_remote(self, folder: Path, name: str, address: str) -> None:
        self.checkouts[folder][name] = address

    def repository(self, owner: str, name: str, releases: dict[str, dict[str, str]], topic: bool = True,
                   annotated: bool = True) -> str:
        """The repository ``name`` of ``owner``, started with a README.md, with one commit and tag per
        release, its files added to the tree as a commit in a work tree adds them; its address."""
        address = f"{COMPONENT_HOST}{owner}/{name}.git"
        repository = self.repositories.setdefault(address, Repository(files={"README.md": name}))
        for tag, files in releases.items():
            repository.files = {**repository.files, **files}
            commit = self._object()
            repository.tags[tag] = (self._object() if annotated else commit, commit, dict(repository.files),
                                    annotated)
        if topic:
            self.topics.setdefault(owner, []).append(name)
        return address

    def listing(self, owner: str) -> list[str]:
        """The host's topic listing of ``owner``, as components.LISTINGS asks it."""
        if owner not in self.topics:
            raise components.ListingError("HTTP 422: The listed users cannot be searched")
        return self.topics[owner]

    # The door, as components.Git answers.

    def toplevel(self, folder: Path) -> Path | None:
        return folder if folder in self.checkouts else None

    def remotes(self, folder: Path) -> list[tuple[str, str]]:
        return sorted(self.checkouts[folder].items())  # git remote lists them by name.

    def tags(self, folder: Path, address: str) -> list[tuple[str, str]] | str:
        repository = self._read(folder, address)
        if repository is None:
            return f"fatal: repository '{address}' not found"
        listed = []
        for tag, (named, commit, _, annotated) in sorted(repository.tags.items()):
            listed.append((f"refs/tags/{tag}", named))
            if annotated:
                listed.append((f"refs/tags/{tag}^{{}}", commit))
        return listed

    def root_names(self, folder: Path, address: str, tag: str) -> set[str] | str:
        tree = self._tree(folder, address, tag)
        return tree if isinstance(tree, str) else {path.split("/")[0] for path in tree}

    def fetch(self, folder: Path, address: str, tag: str, into: Path) -> str | None:
        tree = self._tree(folder, address, tag)
        if isinstance(tree, str):
            return tree
        for path, text in tree.items():
            (into / path).parent.mkdir(parents=True, exist_ok=True)
            (into / path).write_text(text, encoding="utf-8")
        return None

    def _read(self, folder: Path, address: str) -> Repository | None:
        if folder not in self.checkouts:
            raise refuse("git", f"a read of {address} from {folder}, which is no checkout the fake knows")
        return self.repositories.get(address)

    def _tree(self, folder: Path, address: str, tag: str) -> dict[str, str] | str:
        repository = self._read(folder, address)
        if repository is None:
            return f"fatal: repository '{address}' not found"
        if tag not in repository.tags:
            return f"fatal: couldn't find remote ref refs/tags/{tag}"
        return repository.tags[tag][2]

    def _object(self) -> str:
        return f"{next(self._objects):040x}"


SOURCE_COMMIT = "5" * 40
"""The commit the source archive's fake names for obs's checkout."""
SOURCE_ORIGIN = "https://example.test/obs/obs.git"
SOURCE_LOCKFILES = ("src/obs/diagrams/package-lock.json", "uv.lock")
"""The lockfiles Git tracks in obs's checkout, as its contract test shows."""


class SourceGit:
    """The fake of sources.run_git: obs's checkout, the one the core runs from, at SOURCE_COMMIT with its
    origin SOURCE_ORIGIN; a folder outside it is no checkout, as Git answers."""

    def __init__(self) -> None:
        self.checkout = sources.PACKAGE.resolve().parents[1]

    def __call__(self, folder: Path, *arguments: str) -> subprocess.CompletedProcess:
        command = ["git", "-C", str(folder), *arguments]
        inside = Path(folder).resolve().is_relative_to(self.checkout)
        if not inside:
            return subprocess.CompletedProcess(command, 128, "", "fatal: not a git repository (or any of the parent "
                                                                 "directories): .git\n")
        if list(arguments) == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, f"{self.checkout}\n", "")
        if list(arguments) == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, f"{SOURCE_COMMIT}\n", "")
        if list(arguments) == ["ls-files", "-z", "--", *sources.LOCKFILES]:
            return subprocess.CompletedProcess(command, 0, "".join(f"{name}\0" for name in SOURCE_LOCKFILES), "")
        if list(arguments) == ["remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(command, 0, f"{SOURCE_ORIGIN}\n", "")
        raise refuse("source-git", command)


def python_code(command: list[str]) -> str | None:
    """The code of ``command`` where it is the test interpreter's ``-c CODE``, else None."""
    if len(command) >= 3 and command[0] in (sys.executable, "python") and command[1] == "-c":
        return command[2]
    return None


def run_python(code: str, arguments: list[str], cwd: Path, environment: dict[str, str] | None,
               stdout: io.StringIO | None, stderr: io.StringIO | None) -> int:
    """``python -c code arguments`` in this process, as the interpreter runs it: in ``cwd`` with
    ``sys.argv`` and, where given, only ``environment``; its output into ``stdout`` and ``stderr`` where
    given, else on ours; its exit code, an uncaught exception's traceback on stderr and code 1."""
    saved = sys.argv, os.getcwd(), dict(os.environ)
    code_number = 0
    with contextlib.ExitStack() as stack:
        if stdout is not None:
            stack.enter_context(contextlib.redirect_stdout(stdout))
        if stderr is not None:
            stack.enter_context(contextlib.redirect_stderr(stderr))
        try:
            sys.argv = ["-c", *arguments]
            os.chdir(cwd)
            if environment is not None:
                os.environ.clear()
                os.environ.update(environment)
            exec(compile(code, "<string>", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
        except SystemExit as exit_:
            if exit_.code is None or isinstance(exit_.code, int):
                code_number = exit_.code or 0
            else:
                print(exit_.code, file=sys.stderr)
                code_number = 1
        except Exception:  # noqa: BLE001 - the interpreter prints any uncaught exception.
            kind, error, trace = sys.exc_info()
            traceback.print_exception(kind, error, trace.tb_next)  # From the code's own frame on.
            code_number = 1
        finally:
            sys.stdout.flush()
            sys.argv = saved[0]
            os.chdir(saved[1])
            os.environ.clear()
            os.environ.update(saved[2])
    return code_number


class AdapterProcess:
    """The fake of document.run_adapter: an adapter whose command is the test interpreter's ``-c CODE``
    runs in this process (run_python); ``calls`` holds each command."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], cwd: Path, capture: bool) -> subprocess.CompletedProcess:
        self.calls.append(list(command))
        code = python_code(command)
        if code is None:
            raise refuse("adapter", command)
        out, err = (io.StringIO(), io.StringIO()) if capture else (None, None)
        returncode = run_python(code, command[3:], cwd, None, out, err)
        return subprocess.CompletedProcess(command, returncode, out.getvalue() if capture else None,
                                           err.getvalue() if capture else None)


class Shell:
    """The fake of commands.run_shell: ``answers`` maps a command to its exit code and output; else
    ``echo WORDS`` prints its words and the test interpreter's ``"PYTHON" -c "CODE"`` runs in this
    process (run_python). ``calls`` holds each command."""

    def __init__(self) -> None:
        self.answers: dict[str, tuple[int, str]] = {}
        self.calls: list[str] = []

    def __call__(self, command: str, cwd: Path, environment: dict[str, str] | None,
                 timeout_seconds: int) -> subprocess.CompletedProcess:
        self.calls.append(command)
        if command in self.answers:
            code, output = self.answers[command]
            return subprocess.CompletedProcess(command, code, output)
        words = shlex.split(command)
        if words[:1] == ["echo"]:
            return subprocess.CompletedProcess(command, 0, " ".join(words[1:]) + "\n")
        code = python_code(words)
        if code is None:
            raise refuse("shell", command)
        output = io.StringIO()
        returncode = run_python(code, words[3:], cwd, environment, output, output)
        return subprocess.CompletedProcess(command, returncode, output.getvalue())


class PartProcess:
    """A part's process as test/suite.py's PartProcess gives it, following its fake Part: it ends at
    once, or, where the Part hangs, every wait with a timeout times out at once, as the cap would, until
    an interrupt it answers (Part.answer) or a stop ends it."""

    def __init__(self, part: "Part", command: list[str], cwd: Path) -> None:
        self.part, self.command, self.cwd = part, command, cwd
        self.returncode: int | None = None if part.hangs else part.returncode
        self.stopped = False

    def communicate(self, timeout: float | None = None) -> tuple[str, None]:
        if self.returncode is None:
            if timeout is None:
                raise refuse("part", "a wait without a timeout for a part that hangs and was not stopped")
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.part.output, None

    def interrupt(self) -> None:
        if self.returncode is None and self.part.answer is not None:
            self.part.answer(self.command, self.cwd)
            self.returncode = 2

    def stop(self) -> None:
        self.stopped = True
        if self.returncode is None:
            self.returncode = -9


class Part:
    """The fake of test/suite.py's start_part: each part's process ends at once with ``returncode`` and
    ``output``, or, where ``hangs``, runs past the cap; ``started`` is called with its command and folder
    as it starts, ``answer`` where an interrupt reaches it (None: it ignores the interrupt). ``processes``
    holds each one started."""

    def __init__(self) -> None:
        self.returncode, self.output, self.hangs = 0, "", False
        self.started = None
        self.answer = None
        self.processes: list[PartProcess] = []

    def __call__(self, command: list[str], cwd: Path) -> PartProcess:
        if self.started is not None:
            self.started(command, cwd)
        self.processes.append(PartProcess(self, list(command), cwd))
        return self.processes[-1]
