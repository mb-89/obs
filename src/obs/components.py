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
TOPIC = "obs-component"
"""The repository topic that marks an owner's repository as a component repository."""
VARIABLE = "OBS_LOCAL_FOLDER"
"""Names the machine folder instead of ``obs`` in the user's configuration folder."""
ENTRY_FILES = {"adapter": "adapter.json"}
"""Each kind obs knows and the file at the root of a release's tree that makes it one."""
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_TAG = re.compile(r"obs-component/(?P<kind>[a-z]+)/(?P<name>[a-z0-9][a-z0-9-]{0,31})/v(?P<version>"
                  + _VERSION.pattern + ")")
_PREFIX = "obs-component/"


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


def _token() -> str | None:
    """The person's GitHub login token: GH_TOKEN, GITHUB_TOKEN, or what ``gh auth token`` prints."""
    for variable in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(variable):
            return os.environ[variable]
    if shutil.which("gh") is None:
        return None
    try:
        completed = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30, check=False)
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


def github_repositories(owner: str) -> list[str]:
    """The names of ``owner``'s repositories on github.com that carry the topic, through GitHub's
    repository search, with the person's login where there is one."""
    token, names, page = _token(), [], 1
    query = urllib.parse.quote(f"topic:{TOPIC} user:{owner} fork:true")
    while True:
        result = _get_json(f"https://api.github.com/search/repositories?q={query}&per_page=100&page={page}", token)
        items = result.get("items", []) if isinstance(result, dict) else []
        names += [item["name"] for item in items if isinstance(item, dict) and isinstance(item.get("name"), str)]
        if len(items) < 100 or page == 10:  # The search answers at most 1000 results.
            return names
        page += 1


LISTINGS: dict[str, Callable[[str], list[str]]] = {"github.com": github_repositories}
"""Each host obs can ask for an owner's component repositories, and how."""


@dataclass(frozen=True)
class Release:
    kind: str
    name: str
    version: tuple[int, int, int]
    tag: str
    commit: str
    repository: str

    @property
    def number(self) -> str:
        return ".".join(map(str, self.version))


def _git(checkout: Path, *arguments: str) -> subprocess.CompletedProcess:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", "-C", str(checkout), *arguments], capture_output=True, text=True,
                          encoding="utf-8", env=environment, check=False)


def checkout() -> Path:
    """The Git checkout of obs the core runs from."""
    try:
        completed = _git(CHECKOUT, "rev-parse", "--show-toplevel")
    except OSError as error:
        raise ComponentError(f"cannot run git: {error}. Install Git; see {OWNER} (The component command)") from error
    if completed.returncode:
        raise ComponentError(f"obs runs from {CHECKOUT}, which is no Git checkout. Run obs-components from a clone of "
                          f"obs's repository; see {OWNER} (The component command)")
    return Path(completed.stdout.strip())


def repositories(folder: Path, warn: Callable[[str], None]) -> list[str]:
    """The addresses to read, in order: for each remote, its own repository, then the repositories
    its host lists for its owner with the topic, by name; each address once, at its first place."""
    names = _git(folder, "remote").stdout.split()
    found: list[str] = []
    for remote in names:
        address = _git(folder, "config", "--get", f"remote.{remote}.url").stdout.strip()
        if not address:
            continue
        found.append(address)
        parsed = parse_address(address)
        if parsed is None:
            warn(f"remote {remote}: its address {address} names no host and owner to list; reading its own "
                 f"repository only")
            continue
        listing = LISTINGS.get(parsed.host)
        if listing is None:
            warn(f"remote {remote}: host {parsed.host} has no repository listing obs knows, so owner "
                 f"{parsed.owner} is not searched; reading its own repository only")
            continue
        try:
            listed = listing(parsed.owner)
        except ListingError as error:
            warn(f"remote {remote}: host {parsed.host} cannot list owner {parsed.owner}: {error}; reading its own "
                 f"repository only (a private owner needs a login: GH_TOKEN, GITHUB_TOKEN or gh auth login)")
            continue
        found += [parsed.sibling(name) for name in sorted(set(listed)) if name != parsed.repository]
    return list(dict.fromkeys(found))


def _releases_of(folder: Path, address: str, warn: Callable[[str], None]) -> list[Release]:
    completed = _git(folder, "ls-remote", "--tags", address)
    if completed.returncode:
        detail = (completed.stderr.strip().splitlines() or ["git ls-remote failed"])[-1]
        warn(f"repository {address}: cannot be read: {detail}")
        return []
    commits: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        commit, _, reference = line.partition("\t")
        tag = reference.removeprefix("refs/tags/")
        if not tag.startswith(_PREFIX):
            continue
        if tag.endswith("^{}"):  # An annotated tag's commit.
            commits[tag[:-3]] = commit
        else:
            commits.setdefault(tag, commit)
    releases = []
    for tag, commit in commits.items():
        match = _TAG.fullmatch(tag)
        if match is None:
            warn(f"repository {address}: tag {tag} is no release (obs-component/<kind>/<name>/v<major>.<minor>.<patch>); "
                 f"skipped")
            continue
        version = tuple(int(part) for part in match["version"].split("."))
        releases.append(Release(match["kind"], match["name"], version, tag, commit, address))
    components = sorted({(release.kind, release.name) for release in releases})
    if len(components) > 1:
        named = ", ".join(f"{kind} {name}" for kind, name in components)
        warn(f"repository {address}: carries releases of several components ({named}); none is offered from it")
        return []
    return releases


def offered(folder: Path, warn: Callable[[str], None]) -> dict[str, dict[tuple[int, int, int], Release]]:
    """Each offered component's releases by version, each version from its first repository in order."""
    by_name: dict[str, dict[tuple[int, int, int], Release]] = {}
    kinds: dict[str, dict[str, list[str]]] = {}
    for address in repositories(folder, warn):
        for release in _releases_of(folder, address, warn):
            kinds.setdefault(release.name, {}).setdefault(release.kind, [])
            if address not in kinds[release.name][release.kind]:
                kinds[release.name][release.kind].append(address)
            by_name.setdefault(release.name, {}).setdefault(release.version, release)
    for name, offered_kinds in kinds.items():
        if len(offered_kinds) > 1:
            named = "; ".join(f"{kind} from {', '.join(addresses)}" for kind, addresses in sorted(offered_kinds.items()))
            warn(f"component {name} is offered as several kinds ({named}); none is offered until one of them stops")
            del by_name[name]
    return by_name


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


def _fetch(folder: Path, release: Release, into: Path) -> None:
    """The release's tree, fetched from its repository into the empty folder ``into``."""
    url = _git(folder, "ls-remote", "--get-url", release.repository).stdout.strip() or release.repository
    git = into.parent / "git"
    steps = [["init", "-q", "--bare", str(git)],
             ["--git-dir", str(git), "fetch", "-q", "--depth", "1", url, f"refs/tags/{release.tag}"],
             ["--git-dir", str(git), "--work-tree", str(into), "checkout", "-q", "-f", "FETCH_HEAD", "--", "."]]
    for step in steps:
        completed = subprocess.run(["git", *step], capture_output=True, text=True, encoding="utf-8",
                                   env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, check=False)
        if completed.returncode:
            detail = (completed.stderr.strip().splitlines() or ["git failed"])[-1]
            raise ComponentError(f"{release.name} {release.number}: cannot be fetched from {release.repository}: {detail}. "
                              f"Check that the repository can be read, then install again; see {OWNER} (Choosing)")


def _check_entry(release: Release, tree: Path) -> None:
    entry = ENTRY_FILES.get(release.kind)
    if entry is None:
        return
    try:
        declared = json.loads((tree / entry).read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        declared = None
    if declared != release.name:
        raise ComponentError(f"{release.name} {release.number}: {entry}: the release {release.tag} of "
                          f"{release.repository} holds no {entry} naming {release.name!r} at its root. Install "
                          f"another version; see {OWNER} (Choosing)")


def install(folder: Path, release: Release) -> None:
    """Install ``release`` in the machine folder, replacing the installed version only once the
    fetched tree holds its kind's entry file."""
    components = local_folder() / "components"
    components.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".install-{release.name}-", dir=components))
    try:
        tree = staging / "tree"
        tree.mkdir()
        _fetch(folder, release, tree)
        _check_entry(release, tree)
        target = components / release.name
        if target.exists():
            target.replace(staging / "previous")
        tree.replace(target)
        entries = installed()
        entries[release.name] = {"name": release.name, "kind": release.kind, "version": release.number,
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
    if version is None:
        return offers[max(offers)]
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
        kind = newest.kind if newest else entry["kind"]
        update = bool(entry and newest and _VERSION.fullmatch(entry["version"])
                      and newest.version > _version(entry["version"]))
        rows.append((name, kind, current, newest.number if newest else "-",
                     (newest.repository if newest else "-") + ("  (update)" if update else "")))
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
        if name is not None and _NAME.fullmatch(name) is None:
            raise ComponentError(f"{options.command}: {name}: is no component name (1 to 32 lowercase letters, digits and "
                              f"dashes, starting with a letter or digit). Name a component as obs-components lists it; "
                              f"see {OWNER} (A component)")
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
