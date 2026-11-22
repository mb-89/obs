"""The component command, obs-components (spec/design_input/components.md): owners searched through a fake host
listing, component repositories as local bare repositories reached through Git's url.insteadOf, and a
machine folder below the test's own temporary folder. No test reaches the network."""
import json
import subprocess
from pathlib import Path

import pytest

from obs import components
from obs.adapter import AdapterError, adapter_location, load_adapter
from obs.document import main as document_main

OWNER = "spec/design_input/components.md"
HOST = "https://example.test/"
IDENTITY = ["-c", "user.name=obs test", "-c", "user.email=obs-test@example.invalid", "-c", "init.defaultBranch=main"]


def git(folder: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *IDENTITY, "-C", str(folder), *arguments], capture_output=True, text=True,
                               check=True)
    return completed.stdout


def adapter_files(name: str) -> dict[str, str]:
    return {"adapter.json": json.dumps({"name": name, "command": ["python", "-c", "pass"], "contractVersion": 1,
                                        "capabilities": ["manifest"]})}


class Host:
    """Bare repositories below ``root/<owner>/<repository>.git``, reached as HOST<owner>/<repository>.git,
    and the topic listing a fake host answers for each owner."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.topics: dict[str, list[str]] = {}

    def repository(self, owner: str, name: str, releases: dict[str, dict[str, str]], topic: bool = True) -> str:
        bare = self.root / owner / f"{name}.git"
        work = self.root / "work" / owner / name
        if not bare.exists():
            bare.parent.mkdir(parents=True, exist_ok=True)
            git(self.root, "init", "-q", "--bare", str(bare))
            work.mkdir(parents=True)
            git(work, "init", "-q")
            git(work, "remote", "add", "origin", str(bare))
            (work / "README.md").write_text(name, encoding="utf-8")
            git(work, "add", "-A")
            git(work, "commit", "-qm", "start")
            git(work, "push", "-q", "origin", "HEAD:main")
        for tag, files in releases.items():
            for path, text in files.items():
                (work / path).write_text(text, encoding="utf-8")
            git(work, "add", "-A")
            git(work, "commit", "-qm", tag, "--allow-empty")
            git(work, "tag", "-a", tag, "-m", tag)
            git(work, "push", "-q", "origin", "HEAD:main", tag)
        if topic:
            self.topics.setdefault(owner, []).append(name)
        return f"{HOST}{owner}/{name}.git"

    def listing(self, owner: str) -> list[str]:
        if owner not in self.topics:
            raise components.ListingError("HTTP 422: The listed users cannot be searched")
        return self.topics[owner]


@pytest.fixture
def host(tmp_path, monkeypatch) -> Host:
    fake = Host(tmp_path / "host")
    fake.root.mkdir()
    monkeypatch.setattr(components, "LISTINGS", {"example.test": fake.listing})
    return fake


@pytest.fixture
def checkout(tmp_path, monkeypatch, host) -> Path:
    """A checkout of obs whose remote origin is alice's repository obs, which carries no topic."""
    folder = tmp_path / "checkout"
    folder.mkdir()
    git(folder, "init", "-q")
    git(folder, "config", f"url.{host.root.as_uri()}/.insteadOf", HOST)
    host.repository("alice", "obs", {}, topic=False)
    git(folder, "remote", "add", "origin", f"{HOST}alice/obs.git")
    monkeypatch.setattr(components, "CHECKOUT", folder)
    return folder


@pytest.fixture
def machine(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "machine"
    monkeypatch.setenv("OBS_LOCAL_FOLDER", str(folder))
    return folder


def listed(capsys) -> tuple[dict[str, list[str]], str]:
    """The listing's rows by component name, and its warnings."""
    assert components.main([]) == 0
    captured = capsys.readouterr()
    rows = [line.split() for line in captured.out.splitlines()[1:]]
    return {row[0]: row[1:] for row in rows}, captured.err


def test_a_remotes_owner_offers_its_topic_repositories_with_no_remote_added(host, checkout, machine, capsys) -> None:
    first = host.repository("alice", "obs-a", {"obs-component/adapter/a/v1.0.0": adapter_files("a"),
                                               "obs-component/adapter/a/v1.2.0": adapter_files("a")})
    second = host.repository("alice", "obs-b", {"obs-component/style/b/v0.1.0": {"style.css": "body {}"}})

    rows, warnings = listed(capsys)

    assert rows == {"a": ["adapter", "not", "installed", "1.2.0", first],
                    "b": ["style", "not", "installed", "0.1.0", second]}
    assert warnings == ""
    assert git(checkout, "remote").split() == ["origin"]


def test_another_owners_component_is_found_once_one_of_its_repositories_is_a_remote(
        host, checkout, machine, capsys) -> None:
    offered = host.repository("bob", "obs-c", {"obs-component/adapter/c/v2.0.0": adapter_files("c")})
    host.repository("bob", "notes", {}, topic=False)
    assert "c" not in listed(capsys)[0]

    git(checkout, "remote", "add", "bob", f"{HOST}bob/notes.git")

    assert listed(capsys)[0]["c"] == ["adapter", "not", "installed", "2.0.0", offered]


def test_an_owner_the_host_cannot_list_is_one_warning_and_its_remotes_repository_is_still_read(
        host, checkout, machine, capsys) -> None:
    own = host.repository("carol", "own", {"obs-component/adapter/own/v1.0.0": adapter_files("own")}, topic=False)
    git(checkout, "remote", "add", "carol", own)

    rows, warnings = listed(capsys)

    assert rows["own"][-1] == own
    [warning] = [line for line in warnings.splitlines() if "remote carol" in line]
    assert warning.startswith("obs-components: warning: remote carol: host example.test cannot list owner carol")


def test_a_host_without_a_listing_is_one_warning(host, checkout, machine, capsys, monkeypatch) -> None:
    monkeypatch.setattr(components, "LISTINGS", {})
    host.repository("alice", "obs", {"obs-component/adapter/self/v1.0.0": adapter_files("self")}, topic=False)

    rows, warnings = listed(capsys)

    assert rows["self"][-1] == f"{HOST}alice/obs.git"
    assert len(warnings.splitlines()) == 1 and "remote origin: host example.test" in warnings


def test_the_newest_release_wins_and_a_tie_goes_to_the_first_remote(host, checkout, machine, capsys) -> None:
    host.repository("alice", "obs-d", {"obs-component/adapter/d/v1.0.0": adapter_files("d")})
    newer = host.repository("bob", "obs-d", {"obs-component/adapter/d/v1.1.0": adapter_files("d")})
    tie = host.repository("alice", "obs-e", {"obs-component/adapter/e/v1.0.0": adapter_files("e")})
    host.repository("bob", "obs-e", {"obs-component/adapter/e/v1.0.0": adapter_files("e")})
    git(checkout, "remote", "add", "upstream", f"{HOST}bob/obs-d.git")  # git remote lists it after origin.

    rows, _ = listed(capsys)

    assert rows["d"][-1] == newer
    assert rows["e"][-1] == tie


def test_a_malformed_tag_and_a_repository_of_two_components_are_warnings(host, checkout, machine, capsys) -> None:
    broken = host.repository("alice", "obs-f", {"obs-component/adapter/f/v1.0": adapter_files("f")})
    mixed = host.repository("alice", "obs-g", {"obs-component/adapter/g/v1.0.0": adapter_files("g"),
                                               "obs-component/adapter/h/v1.0.0": adapter_files("h")})

    rows, warnings = listed(capsys)

    assert rows == {}
    assert f"repository {broken}: tag obs-component/adapter/f/v1.0 is no release" in warnings
    assert f"repository {mixed}: carries releases of several components (adapter g, adapter h)" in warnings


def test_install_update_and_remove_change_only_the_machine_folder_and_its_list(
        host, checkout, machine, capsys) -> None:
    host.repository("alice", "obs-a", {"obs-component/adapter/a/v1.0.0": adapter_files("a")})
    state = (git(checkout, "status", "--porcelain", "--ignored"), git(checkout, "for-each-ref"),
             sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*")))

    assert components.main(["install", "a", "1.0.0"]) == 0
    entry = json.loads((machine / "components.json").read_text(encoding="utf-8"))
    assert [{key: item[key] for key in ("name", "kind", "version")} for item in entry["components"]] == [
        {"name": "a", "kind": "adapter", "version": "1.0.0"}]
    assert set(entry["components"][0]) == {"name", "kind", "version", "commit"}
    assert json.loads((machine / "components" / "a" / "adapter.json").read_text(encoding="utf-8"))["name"] == "a"
    assert not (machine / "components" / "a" / ".git").exists()
    assert listed(capsys)[0]["a"][:3] == ["adapter", "1.0.0", "1.0.0"]

    host.repository("alice", "obs-a", {"obs-component/adapter/a/v1.1.0": adapter_files("a")}, topic=False)
    rows, _ = listed(capsys)
    assert rows["a"][-1] == "(update)"
    assert components.main(["update", "a"]) == 0
    assert installed_versions(machine) == {"a": "1.1.0"}

    assert components.main(["remove", "a"]) == 0
    assert installed_versions(machine) == {}
    assert sorted(path.name for path in (machine / "components").iterdir()) == []
    assert sorted(path.name for path in machine.iterdir()) == ["components", "components.json"]
    assert state == (git(checkout, "status", "--porcelain", "--ignored"), git(checkout, "for-each-ref"),
                     sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*")))
    assert "example.test" not in (machine / "components.json").read_text(encoding="utf-8")


def installed_versions(machine: Path) -> dict[str, str]:
    entries = json.loads((machine / "components.json").read_text(encoding="utf-8"))["components"]
    return {entry["name"]: entry["version"] for entry in entries}


def test_a_release_without_its_entry_file_leaves_the_installed_version(host, checkout, machine) -> None:
    host.repository("alice", "obs-a", {"obs-component/adapter/a/v1.0.0": adapter_files("a")})
    host.repository("alice", "obs-a", {"obs-component/adapter/a/v2.0.0": {"adapter.json": '{"name": "other"}'}},
                    topic=False)
    assert components.main(["install", "a", "1.0.0"]) == 0

    with pytest.raises(SystemExit) as refused:
        components.main(["install", "a"])

    assert str(refused.value).startswith("obs-components: a 2.0.0: adapter.json: ")
    assert OWNER in str(refused.value)
    assert installed_versions(machine) == {"a": "1.0.0"}
    assert sorted(path.name for path in (machine / "components").iterdir()) == ["a"]


@pytest.mark.parametrize(("arguments", "field"), [
    (["install", "nothing"], "install: nothing: "),
    (["install", "a", "9.9.9"], "install: a 9.9.9: "),
    (["update", "a"], "update: a: "),
    (["remove", "a"], "remove: a: "),
    (["install", "Bad_Name"], "install: Bad_Name: "),
])
def test_a_choice_nothing_offers_or_installed_fails_naming_it(host, checkout, machine, arguments, field) -> None:
    host.repository("alice", "obs-a", {"obs-component/adapter/a/v1.0.0": adapter_files("a")})

    with pytest.raises(SystemExit) as refused:
        components.main(arguments)

    assert str(refused.value).startswith(f"obs-components: {field}")
    assert OWNER in str(refused.value)
    assert not (machine / "components.json").exists()


def test_the_command_needs_a_checkout(tmp_path, monkeypatch, machine) -> None:
    monkeypatch.setattr(components, "CHECKOUT", tmp_path)
    with pytest.raises(SystemExit) as refused:
        components.main([])
    assert str(tmp_path) in str(refused.value) and OWNER in str(refused.value)


@pytest.mark.parametrize(("address", "parts"), [
    ("https://github.com/alice/obs.git", ("github.com", "alice", "obs")),
    ("ssh://git@github.com:22/alice/obs.git", ("github.com", "alice", "obs")),
    ("git@github.com:alice/obs.git", ("github.com", "alice", "obs")),
    ("http://proxy@127.0.0.1:8080/git/alice/obs", ("127.0.0.1", "alice", "obs")),
    ("/srv/git/obs.git", None),
    ("C:\\repositories\\obs", None),
    ("file:///srv/alice/obs.git", None),
])
def test_an_address_names_its_host_owner_and_repository(address, parts) -> None:
    parsed = components.parse_address(address)
    assert (parsed and (parsed.host, parsed.owner, parsed.repository)) == parts


def test_a_found_repository_is_reached_the_way_its_remote_is() -> None:
    assert components.parse_address("git@github.com:alice/obs.git").sibling("obs-a") == "git@github.com:alice/obs-a.git"
    assert components.parse_address("https://github.com/alice/obs").sibling("obs-a") == "https://github.com/alice/obs-a"


def test_github_lists_an_owners_topic_repositories_through_its_search(monkeypatch) -> None:
    asked = []

    def answer(url, token):
        asked.append(url)
        return {"items": [{"name": "obs-a"}, {"name": "obs-b"}]}

    monkeypatch.setattr(components, "_get_json", answer)
    monkeypatch.setattr(components, "_token", lambda: None)

    assert components.github_repositories("alice") == ["obs-a", "obs-b"]
    assert asked == ["https://api.github.com/search/repositories?q=topic%3Aobs-component%20user%3Aalice%20fork%3Atrue"
                     "&per_page=100&page=1"]


def test_the_machine_folder_is_obs_in_the_configuration_folder_unless_named(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OBS_LOCAL_FOLDER", "")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(components.sys, "platform", "linux")
    assert components.local_folder() == tmp_path / "obs"
    monkeypatch.setenv("OBS_LOCAL_FOLDER", str(tmp_path / "elsewhere"))
    assert components.local_folder() == tmp_path / "elsewhere"


def test_a_build_finds_its_adapter_among_the_installed_components(host, checkout, machine) -> None:
    host.repository("alice", "obs-a", {"obs-component/adapter/a/v1.0.0": adapter_files("a")})
    with pytest.raises(AdapterError) as absent:
        load_adapter("a")
    assert "--adapter: a: " in str(absent.value) and "obs-components install a" in str(absent.value)

    assert components.main(["install", "a"]) == 0

    assert load_adapter("a")["name"] == "a"
    assert adapter_location("a").folder == machine / "components" / "a"


def test_a_component_of_another_kind_is_no_adapter(host, checkout, machine) -> None:
    host.repository("alice", "obs-b", {"obs-component/style/b/v0.1.0": {"style.css": "body {}"}})
    assert components.main(["install", "b"]) == 0
    with pytest.raises(AdapterError) as refused:
        load_adapter("b")
    assert "--adapter: b: " in str(refused.value) and OWNER in str(refused.value)


def test_the_html_adapter_in_obss_tree_is_the_component_html(machine) -> None:
    location = adapter_location("html")
    assert location.manifest == components.CHECKOUT / "adapters" / "html" / "adapter.json"
    assert location.folder == components.CHECKOUT
    assert not (components.CHECKOUT / "adapters.json").exists()


def test_obs_document_hands_components_to_the_component_command(host, checkout, machine, capsys) -> None:
    host.repository("alice", "obs-a", {"obs-component/adapter/a/v1.0.0": adapter_files("a")})
    assert document_main(["components"]) == 0
    assert capsys.readouterr().out.splitlines()[1].split()[0] == "a"
