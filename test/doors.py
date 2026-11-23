"""The fakes of the core's doors that start a process (spec/design_input/quality.md, Testing boundaries):
test/conftest.py puts each in its door's place for every test, and a door's contract test, marked
``pytest.mark.door("<name>")``, keeps the real one and shows that its fake answers alike.

A fake asked for what it does not know fails the test, naming the mark.
"""
import itertools
from dataclasses import dataclass, field
from pathlib import Path

from obs import components


NAMES = ("component-git",)
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
