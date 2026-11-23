"""The component command, obs-components: list the components the checkout's remotes and their owners offer,
and install, update and remove them in the machine folder (spec/design_input/components.md)."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


OWNER = "spec/design_input/components.md"
CHECKOUT = Path(__file__).resolve().parents[2]
"""The folder the core runs from; the component command needs it to be a Git checkout of obs."""
TOPIC = "component"
"""The repository topic that marks an owner's repository as a component repository."""
VARIABLE = "OBS_LOCAL_FOLDER"
"""Names the machine folder instead of ``obs`` in the user's configuration folder."""
KINDS = {"adapter": "adapter.json", "style": "style.css"}
"""Each kind obs knows and the file at the root of a release's tree that makes it one, the first that
a tree holds deciding."""
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
"""A component's name, the repository's name in lowercase."""
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_TAG = re.compile(r"v(?P<version>" + _VERSION.pattern + ")")
"""A release tag; a repository's other tags, such as a moving ``v1``, are none of obs's."""
NO_KIND = ""
"""The kind of a release whose tree holds no kind's entry file: not a component of obs."""


class ComponentError(ValueError):
    """A component command that cannot be carried out; its message names the remedy."""


class ListingError(Exception):
    """A host that cannot list an owner's repositories; the message says why."""


@dataclass(frozen=True)
class Address:
    """A remote's address split into its host, its owner and its repository."""
    address: str
    host: str
    owner: str
    repository: str

    def sibling(self, repository: str) -> str:
        """The address of the owner's ``repository``, reached the way this one is."""
        suffix = ".git" if self.address.endswith(".git") else ""
        stem = self.address[:len(self.address) - len(suffix)]
        return stem[:len(stem) - len(self.repository)] + repository + suffix


def parse_address(address: str) -> Address | None:
    """The host, owner and repository of ``address``, or None for one that names no host and owner
    (a local path): ``scheme://[user@]host[:port]/…/owner/repository`` or ``[user@]host:…/owner/repository``."""
    if "://" in address:
        parsed = urllib.parse.urlsplit(address)
        host, path = parsed.hostname or "", parsed.path
    else:
        match = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(?!//)(.+)", address)
        if match is None or len(match.group(1)) == 1:  # C:\path is a Windows path, not a host.
            return None
        host, path = match.groups()
    parts = [part for part in path.split("/") if part]
    if not host or len(parts) < 2:
        return None
    repository = parts[-1].removesuffix(".git")
    return Address(address, host.lower(), parts[-2], repository) if repository else None


def _token(host: str = "github.com") -> str | None:
    """The person's login token for ``host``, the way gh reads it: on github.com GH_TOKEN or GITHUB_TOKEN,
    on any other host GH_ENTERPRISE_TOKEN or GITHUB_ENTERPRISE_TOKEN, else what
    ``gh auth token --hostname <host>`` prints."""
    variables = ("GH_TOKEN", "GITHUB_TOKEN") if host == "github.com" else ("GH_ENTERPRISE_TOKEN",
                                                                         "GITHUB_ENTERPRISE_TOKEN")
    for variable in variables:
        if os.environ.get(variable):
            return os.environ[variable]
    if shutil.which("gh") is None:
        return None
    try:
        completed = subprocess.run(["gh", "auth", "token", "--hostname", host], capture_output=True, text=True,
                                   timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (completed.stdout.strip() or None) if completed.returncode == 0 else None


def _get_json(url: str, token: str | None) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "obs-components"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read().decode("utf-8")).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        raise ListingError(f"HTTP {error.code}{': ' + message if message else ''}") from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ListingError(str(getattr(error, "reason", error))) from error


def github_repositories(owner: str, host: str = "github.com") -> list[str]:
    """The names of ``owner``'s repositories on ``host`` that carry the topic, through GitHub's repository
    search at the host's API (``api.<host>``), with the person's login for that host where there is one."""
    token, names, page = _token(host), [], 1
    query = urllib.parse.quote(f"topic:{TOPIC} user:{owner} fork:true")
    while True:
        result = _get_json(f"https://api.{host}/search/repositories?q={query}&per_page=100&page={page}", token)
        items = result.get("items", []) if isinstance(result, dict) else []
        names += [item["name"] for item in items if isinstance(item, dict) and isinstance(item.get("name"), str)]
        if len(items) < 100 or page == 10:  # The search answers at most 1000 results.
            return names
        page += 1


LISTINGS: dict[str, Callable[[str], list[str]]] = {}
"""A host whose owners are listed some other way than GitHub's repository search; none but in tests."""


def listing(host: str) -> Callable[[str], list[str]]:
    """How obs asks ``host`` for an owner's component repositories: every remote's host the same way,
    through GitHub's repository search at its API, unless LISTINGS names another way."""
    return LISTINGS.get(host) or (lambda owner: github_repositories(owner, host))


@dataclass(frozen=True)
class Release:
    kind: str
    """The kind its repository's newest release's tree holds, or NO_KIND."""
    name: str
    version: tuple[int, int, int]
    tag: str
    commit: str
    repository: str

    @property
    def number(self) -> str:
        return ".".join(map(str, self.version))

    @property
    def refusal(self) -> str:
        """Why the release is not a component of obs."""
        return f"its release {self.tag} holds neither {' nor '.join(KINDS.values())} at its root"


def kind_of(names: set[str]) -> str:
    """The kind a release's tree is, from the names at its root, or NO_KIND."""
    return next((kind for kind, entry in KINDS.items() if entry in names), NO_KIND)


def repository_name(address: str) -> str:
    """The component name of the repository at ``address``: its repository's name in lowercase."""
    parsed = parse_address(address)
    name = parsed.repository if parsed else re.split(r"[/\\]", address.rstrip("/\\"))[-1].removesuffix(".git")
    return name.lower()


def _run(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, check=False)


def _failure(completed: subprocess.CompletedProcess, default: str) -> str:
    return (completed.stderr.strip().splitlines() or [default])[-1]


class Git:
    """The component command's one door to Git (components.md, The component command): every Git call
    it makes. Each read of a repository takes the checkout's folder, whose Git configuration rewrites
    the address (url.<base>.insteadOf); a failure is Git's last message line."""

    def toplevel(self, folder: Path) -> Path | None:
        """The top folder of the Git checkout holding ``folder``, or None where it is no checkout;
        OSError where Git cannot run."""
        completed = _run("-C", str(folder), "rev-parse", "--show-toplevel")
        return None if completed.returncode else Path(completed.stdout.strip())

    def remotes(self, folder: Path) -> list[tuple[str, str]]:
        """The checkout's remotes in the order Git lists them, each with its configured address ("" for
        none)."""
        names = _run("-C", str(folder), "remote").stdout.split()
        return [(name, _run("-C", str(folder), "config", "--get", f"remote.{name}.url").stdout.strip())
                for name in names]

    def tags(self, folder: Path, address: str) -> list[tuple[str, str]] | str:
        """Each tag reference of ``address`` with the object it names, as ``git ls-remote --tags`` lists
        them (an annotated tag also as ``<tag>^{}`` with its commit), or Git's message."""
        completed = _run("-C", str(folder), "ls-remote", "--tags", address)
        if completed.returncode:
            return _failure(completed, "git ls-remote failed")
        lines = [line.partition("\t") for line in completed.stdout.splitlines()]
        return [(reference, commit) for commit, _, reference in lines]

    def root_names(self, folder: Path, address: str, tag: str) -> set[str] | str:
        """The names at the root of the tree ``tag`` of ``address`` points to, fetched shallow and, where
        the host allows it, without the files' contents; or Git's message."""
        with tempfile.TemporaryDirectory(prefix="obs-components-") as temporary:
            git = str(Path(temporary) / "git")
            for step in (["init", "-q", "--bare", git],
                         ["--git-dir", git, "fetch", "-q", "--depth", "1", "--filter=blob:none",
                          self.url(folder, address), f"refs/tags/{tag}"]):
                completed = _run(*step)
                if completed.returncode:
                    return _failure(completed, "git fetch failed")
            completed = _run("--git-dir", git, "ls-tree", "--name-only", "FETCH_HEAD")
            if completed.returncode:
                return _failure(completed, "git ls-tree failed")
            return set(completed.stdout.splitlines())

    def fetch(self, folder: Path, address: str, tag: str, into: Path) -> str | None:
        """The tree of ``tag`` of ``address`` written into the empty folder ``into``, with no Git folder;
        None, or Git's message where it cannot be fetched. Git's objects go beside ``into``."""
        git = str(into.parent / "git")
        for step in (["init", "-q", "--bare", git],
                     ["--git-dir", git, "fetch", "-q", "--depth", "1", self.url(folder, address),
                      f"refs/tags/{tag}"],
                     ["--git-dir", git, "--work-tree", str(into), "checkout", "-q", "-f", "FETCH_HEAD", "--", "."]):
            completed = _run(*step)
            if completed.returncode:
                return _failure(completed, "git failed")
        return None

    @staticmethod
    def url(folder: Path, address: str) -> str:
        """``address`` as the checkout's Git configuration rewrites it (url.<base>.insteadOf)."""
        return _run("-C", str(folder), "ls-remote", "--get-url", address).stdout.strip() or address


GIT = Git()
"""The door every Git call goes through; the tests put their fake host in its place."""


def checkout() -> Path:
    """The Git checkout of obs the core runs from."""
    try:
        top = GIT.toplevel(CHECKOUT)
    except OSError as error:
        raise ComponentError(f"cannot run git: {error}. Install Git; see {OWNER} (The component command)") from error
    if top is None:
        raise ComponentError(f"obs runs from {CHECKOUT}, which is no Git checkout. Run obs-components from a clone of "
                          f"obs's repository; see {OWNER} (The component command)")
    return top


def repositories(folder: Path, warn: Callable[[str], None]) -> list[str]:
    """The addresses to read, in order: for each remote, its own repository where its host lists it with
    the topic, then the owner's other repositories with the topic, by name; a remote's own repository
    also where its host cannot list its owner. Each address once, at its first place."""
    found: list[str] = []
    for remote, address in GIT.remotes(folder):
        if not address:
            continue
        parsed = parse_address(address)
        if parsed is None:
            found.append(address)
            warn(f"remote {remote}: its address {address} names no host and owner to list; reading its own "
                 f"repository only")
            continue
        lister = listing(parsed.host)
        try:
            listed = lister(parsed.owner)
        except ListingError as error:
            found.append(address)
            warn(f"remote {remote}: host {parsed.host} cannot list owner {parsed.owner}: {error}; reading its own "
                 f"repository only (a private owner needs a login: GH_TOKEN, GITHUB_TOKEN or gh auth login)")
            continue
        marked = {name.lower(): name for name in listed}
        if parsed.repository.lower() in marked:
            found.append(address)
        found += [parsed.sibling(marked[name]) for name in sorted(marked) if name != parsed.repository.lower()]
    return list(dict.fromkeys(found))


def _releases_of(folder: Path, address: str, warn: Callable[[str], None]) -> list[Release]:
    listed = GIT.tags(folder, address)
    if isinstance(listed, str):
        warn(f"repository {address}: cannot be read: {listed}")
        return []
    commits: dict[str, str] = {}
    for reference, commit in listed:
        tag = reference.removeprefix("refs/tags/")
        if _TAG.fullmatch(tag.removesuffix("^{}")) is None:
            continue
        if tag.endswith("^{}"):  # An annotated tag's commit.
            commits[tag[:-3]] = commit
        else:
            commits.setdefault(tag, commit)
    name = repository_name(address)
    found = [(_version(tag[1:]), tag, commit) for tag, commit in commits.items()]
    if not found:
        return []
    if _NAME.fullmatch(name) is None:
        warn(f"repository {address}: its name {name} is no component name (1 to 32 letters, digits and dashes, "
             f"starting with a letter or digit); skipped")
        return []
    newest = max(found)
    names = GIT.root_names(folder, address, newest[1])
    if isinstance(names, str):
        warn(f"repository {address}: release {newest[1]} cannot be read: {names}")
        return []
    kind = kind_of(names)
    return [Release(kind, name, version, tag, commit, address) for version, tag, commit in found]


def offered(folder: Path, warn: Callable[[str], None]) -> dict[str, dict[tuple[int, int, int], Release]]:
    """Each offered component's releases by version, each version from its first repository in order; a
    name only repositories that are not components of obs offer has releases of NO_KIND."""
    by_name: dict[str, dict[tuple[int, int, int], Release]] = {}
    no_kind: dict[str, dict[tuple[int, int, int], Release]] = {}
    kinds: dict[str, dict[str, list[str]]] = {}
    for address in repositories(folder, warn):
        for release in _releases_of(folder, address, warn):
            if release.kind == NO_KIND:
                no_kind.setdefault(release.name, {}).setdefault(release.version, release)
                continue
            kinds.setdefault(release.name, {}).setdefault(release.kind, [])
            if address not in kinds[release.name][release.kind]:
                kinds[release.name][release.kind].append(address)
            by_name.setdefault(release.name, {}).setdefault(release.version, release)
    for name, offered_kinds in kinds.items():
        if len(offered_kinds) > 1:
            named = "; ".join(f"{kind} from {', '.join(addresses)}" for kind, addresses in sorted(offered_kinds.items()))
            warn(f"component {name} is offered as several kinds ({named}); none is offered until one of them stops")
            del by_name[name]
    # A repository that is not a component of obs is listed with its reason only where no other offers its name.
    return {**{name: offers for name, offers in no_kind.items() if name not in kinds}, **by_name}


def local_folder() -> Path:
    """The machine folder: OBS_LOCAL_FOLDER where set and not empty, else ``obs`` in the user's
    configuration folder."""
    if os.environ.get(VARIABLE):
        return Path(os.environ[VARIABLE])
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "obs"


def _list_path() -> Path:
    return local_folder() / "components.json"


def installed() -> dict[str, dict[str, str]]:
    """The machine's installed components by name, as components.json lists them."""
    path = _list_path()
    if not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["components"]
        return {entry["name"]: {key: str(entry[key]) for key in ("name", "kind", "version", "commit")}
                for entry in entries}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ComponentError(f"{path}: components: cannot be read ({error}). Remove the file and install the components "
                          f"again; see {OWNER} (Installed components)") from error


def _write_list(entries: dict[str, dict[str, str]]) -> None:
    path = _list_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"components": [entries[name] for name in sorted(entries)]}, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _version(text: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in text.split("."))


def _check_entry(release: Release, tree: Path) -> str:
    """The kind the fetched ``tree`` is; an adapter's ``adapter.json`` must name the component."""
    kind = kind_of({path.name for path in tree.iterdir()})
    if kind == NO_KIND:
        raise ComponentError(f"{release.name} {release.number}: is not a component of obs: {release.refusal}. Install "
                             f"another version; see {OWNER} (A component)")
    if kind != "adapter":
        return kind
    entry = KINDS[kind]
    try:
        declared = json.loads((tree / entry).read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        declared = None
    if declared != release.name:
        raise ComponentError(f"{release.name} {release.number}: {entry}: the release {release.tag} of "
                             f"{release.repository} holds no {entry} naming {release.name!r} at its root. Install "
                             f"another version; see {OWNER} (Choosing)")
    return kind


def install(folder: Path, release: Release) -> None:
    """Install ``release`` in the machine folder, replacing the installed version only once the
    fetched tree holds its kind's entry file."""
    components = local_folder() / "components"
    components.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".install-{release.name}-", dir=components))
    try:
        tree = staging / "tree"
        tree.mkdir()
        failure = GIT.fetch(folder, release.repository, release.tag, tree)
        if failure is not None:
            raise ComponentError(f"{release.name} {release.number}: cannot be fetched from {release.repository}: "
                                 f"{failure}. Check that the repository can be read, then install again; see {OWNER} "
                                 f"(Choosing)")
        kind = _check_entry(release, tree)
        target = components / release.name
        if target.exists():
            target.replace(staging / "previous")
        tree.replace(target)
        entries = installed()
        entries[release.name] = {"name": release.name, "kind": kind, "version": release.number,
                                 "commit": release.commit}
        _write_list(entries)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def remove(name: str) -> None:
    entries = installed()
    if name not in entries:
        raise ComponentError(f"remove: {name}: is not installed. Name an installed component (obs-components lists them); "
                          f"see {OWNER} (Choosing)")
    shutil.rmtree(local_folder() / "components" / name, ignore_errors=True)
    del entries[name]
    _write_list(entries)


def _choose(releases: dict[str, dict[tuple[int, int, int], Release]], command: str, name: str,
            version: str | None) -> Release:
    offers = releases.get(name)
    if not offers:
        names = ", ".join(sorted(releases)) or "none"
        raise ComponentError(f"{command}: {name}: no repository offers this component; offered: {names}. Name an offered "
                          f"component, or add a remote that reaches it; see {OWNER} (Listing)")
    newest = offers[max(offers)]
    if newest.kind == NO_KIND:
        raise ComponentError(f"{command}: {name}: is not a component of obs: {newest.refusal}. Name a component "
                             f"obs-components lists with its kind; see {OWNER} (A component)")
    if version is None:
        return newest
    if _VERSION.fullmatch(version) is None or _version(version) not in offers:
        numbers = ", ".join(offers[key].number for key in sorted(offers))
        raise ComponentError(f"{command}: {name} {version}: no repository offers this version; offered: {numbers}. "
                          f"Name an offered version as <major>.<minor>.<patch>; see {OWNER} (Choosing)")
    return offers[_version(version)]


def _table(releases: dict[str, dict[tuple[int, int, int], Release]]) -> list[str]:
    present = installed()
    rows = [("component", "kind", "installed", "newest", "repository")]
    for name in sorted(set(releases) | set(present)):
        offers = releases.get(name, {})
        newest = offers[max(offers)] if offers else None
        entry = present.get(name)
        current = entry["version"] if entry else "not installed"
        kind = (newest.kind or "-") if newest else entry["kind"]
        update = bool(entry and newest and _VERSION.fullmatch(entry["version"])
                      and newest.version > _version(entry["version"]))
        rows.append((name, kind, current, newest.number if newest else "-",
                     (newest.repository if newest else "-") + ("  (update)" if update else "")
                     + (f"  (not a component of obs: {newest.refusal})" if newest and not newest.kind else "")))
    widths = [max(len(row[column]) for row in rows) for column in range(4)]
    return ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)) + "  " + row[4] for row in rows]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obs-components",
        description="List the components the checkout's remotes and their owners offer, with installed and newest "
                    "versions, and install, update or remove one in the machine folder (OBS_LOCAL_FOLDER, else obs "
                    "in the user's configuration folder). Nothing installs unasked.")
    commands = parser.add_subparsers(dest="command")
    chosen = commands.add_parser("install", help="Install the newest offered release of NAME, or VERSION.")
    chosen.add_argument("name", metavar="NAME")
    chosen.add_argument("version", metavar="VERSION", nargs="?", help="<major>.<minor>.<patch>")
    commands.add_parser("update", help="Update the installed NAME to its newest offered release.").add_argument(
        "name", metavar="NAME")
    commands.add_parser("remove", help="Remove the installed NAME.").add_argument("name", metavar="NAME")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)

    def warn(message: str) -> None:
        print(f"obs-components: warning: {message}", file=sys.stderr)

    try:
        name = getattr(options, "name", None)
        if name is not None and _NAME.fullmatch(name.lower()) is None:
            raise ComponentError(f"{options.command}: {name}: is no component name (1 to 32 letters, digits and "
                              f"dashes, starting with a letter or digit, compared without case). Name a component as obs-components lists it; "
                              f"see {OWNER} (A component)")
        name = name.lower() if name is not None else None
        if options.command == "remove":
            remove(name)
            print(f"obs-components: removed {name}")
            return 0
        folder = checkout()
        if options.command == "update" and name not in installed():
            raise ComponentError(f"update: {name}: is not installed. Install it with obs-components install {name}; "
                              f"see {OWNER} (Choosing)")
        releases = offered(folder, warn)
        if options.command is None:
            print("\n".join(_table(releases)))
            return 0
        release = _choose(releases, options.command, name, getattr(options, "version", None))
        current = installed().get(name)
        if options.command == "update" and current["version"] == release.number:
            print(f"obs-components: {name} {release.number} is the newest offered release; nothing changed")
            return 0
        install(folder, release)
        print(f"obs-components: installed {name} {release.number} ({release.kind}) from {release.repository}")
    except ComponentError as error:
        raise SystemExit(f"obs-components: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
