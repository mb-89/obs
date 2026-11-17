"""The way from a page to its vault, or none (spec/design_input/architecture.md, Adapter call)."""

from __future__ import annotations

import ntpath
import os
import posixpath

import pytest

from obs.vault_link import vault_link

POSIX_HOME = "/home/user"
WINDOWS_HOME = "C:\\Users\\user"


@pytest.mark.parametrize(("destination", "vault", "expected"), [
    ("/w/proj/page.html", "/w/proj/notes", "notes"),  # D is P.
    ("/w/proj/site/page.html", "/w/proj/notes", "../notes"),  # D one below P.
    ("/w/proj/site/deep/page.html", "/w/proj/notes", "../../notes"),  # D two below P.
    ("/w/proj/site/../page.html", "/w/proj/notes", "notes"),  # Made absolute as written.
    ("/home/user/se-site/index.html", "/home/user/SE", "../SE"),  # P is the home folder itself.
    ("/w/proj/site/page.html", "/w/proj/My Notes ü", "../My Notes ü"),  # Kept as it is, not encoded.
    ("/w/other/page.html", "/w/proj/notes", None),  # D beside P.
    ("/w/page.html", "/w/proj/notes", None),  # D above P.
    ("/w/proj/notes/page.html", "/w/proj/notes", None),  # D is V.
    ("/w/proj/notes/out/page.html", "/w/proj/notes", None),  # D inside V.
    ("/site/page.html", "/notes", None),  # P is the root.
    ("/home/shared/site/page.html", "/home/shared", None),  # P is /home.
    ("/var/home/shared/site/page.html", "/var/home/shared", None),  # P is a folder named home, elsewhere.
    ("/var/home/site/page.html", "/var/home/notes", None),
    ("/usr/home/site/page.html", "/usr/home/notes", None),
    ("/users/site/page.html", "/users/shared", None),  # P named Users in lower case.
    ("/Users/public/page.html", "/Users/shared", None),
    ("/w/site/page.html", POSIX_HOME, None),  # V is the builder's home folder.
    ("/srv/site/page.html", "/srv/user", None),  # V bears the home folder's name elsewhere.
    ("/srv/site/page.html", "/srv/USER", None),  # In any letter case.
    ("/w/proj/site/page.html", "/w/proj/notes:2026", None),  # Parts requirement 3 refuses.
    ("/w/proj/site/page.html", "/w/proj/a\\b", None),
    ("/w/proj/site/page.html", "/w/proj/-notes", None),
    ("/w/proj/site/page.html", "/w/proj/no\ttes", None),
])
def test_the_posix_way_from_a_page_to_its_vault(destination, vault, expected) -> None:
    assert vault_link(destination, vault, paths=posixpath, home=POSIX_HOME) == expected


@pytest.mark.parametrize(("destination", "vault", "expected"), [
    ("D:\\w\\proj\\page.html", "D:\\w\\proj\\notes", "notes"),
    ("D:\\w\\proj\\site\\page.html", "D:\\w\\proj\\notes", "../notes"),
    ("D:\\w\\proj\\site\\deep\\page.html", "D:\\w\\proj\\notes", "../../notes"),
    ("d:\\W\\PROJ\\site\\page.html", "D:\\w\\proj\\notes", "../notes"),  # Windows ignores letter case.
    ("D:\\w\\proj\\site\\page.html", "D:\\w\\proj\\My Notes ü", "../My Notes ü"),
    ("D:\\w\\other\\page.html", "D:\\w\\proj\\notes", None),
    ("D:\\w\\proj\\notes\\page.html", "D:\\w\\proj\\notes", None),
    ("D:\\w\\proj\\NOTES\\out\\page.html", "D:\\w\\proj\\notes", None),
    ("D:\\site\\page.html", "D:\\Vault", None),  # P is a drive's root.
    ("D:\\site\\page.html", "C:\\w\\notes", None),  # Another drive.
    ("C:\\Users\\public\\page.html", "C:\\Users\\shared", None),  # P is a drive's Users.
    ("C:\\Users\\user\\site\\page.html", WINDOWS_HOME, None),  # V is the home folder.
    ("D:\\srv\\site\\page.html", "D:\\srv\\User", None),  # V bears its name.
    ("D:\\w\\proj\\site\\page.html", "D:\\w\\proj\\-notes", None),
])
def test_the_windows_way_from_a_page_to_its_vault(destination, vault, expected) -> None:
    assert vault_link(destination, vault, paths=ntpath, home=WINDOWS_HOME) == expected


def test_the_home_folder_defaults_to_the_builders(tmp_path, monkeypatch) -> None:
    home = tmp_path / "user"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert vault_link(str(tmp_path / "site" / "page.html"), str(home)) is None
    assert vault_link(str(tmp_path / "site" / "page.html"), str(tmp_path / "notes")) == "../notes"


def test_relative_paths_are_made_absolute_from_the_current_folder(tmp_path, monkeypatch) -> None:
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")

    assert vault_link(os.path.join("site", "page.html"), "notes", home=str(tmp_path / "user")) == "../notes"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="the system has no symlinks")
def test_a_symlinked_page_folder_keeps_its_own_name(tmp_path) -> None:
    (tmp_path / "proj" / "notes").mkdir(parents=True)
    (tmp_path / "elsewhere" / "site").mkdir(parents=True)
    try:
        (tmp_path / "proj" / "site").symlink_to(tmp_path / "elsewhere" / "site", target_is_directory=True)
    except OSError:
        pytest.skip("the system refuses symlinks")

    assert vault_link(str(tmp_path / "proj" / "site" / "page.html"), str(tmp_path / "proj" / "notes"),
                      home=str(tmp_path / "user")) == "../notes"
