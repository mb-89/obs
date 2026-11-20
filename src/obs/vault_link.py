"""The way from a page's folder to the vault folder, or none where a rule is in doubt.

Pure and of the standard library alone: it reads no file, and ``paths`` is ``os.path``,
``posixpath`` or ``ntpath`` (spec/design_input/architecture.md, Adapter call).
"""

from __future__ import annotations

import os
import unicodedata
from types import ModuleType

# A name holding one of these could not stand as one part of a link (the adapter refuses them).
REFUSED_CHARACTERS = frozenset("/\\:")
# Parent folders that hold every person's home folder: a page beside one could be anyone's.
SHARED_PARENTS = frozenset({"home", "users"})


def vault_link(destination: str, vault: str, paths: ModuleType = os.path, home: str | None = None) -> str | None:
    """The link from DESTINATION's folder D to the vault folder V, such as ``../notes``.

    Both are made absolute as written, without resolving symlinks: the browser resolves the link
    against the page's address, so no symlink target's folder enters the page. With P the vault's
    parent, the result is ``name`` where D is P and ``../`` k times then ``name`` where D lies k
    folders below P. Privacy wins over reach, so it is None where D is not P or below it, or is V
    or inside it; where V's name is empty, starts with ``-`` or holds ``/``, ``\\``, ``:`` or a
    control character; where P is a file-system root or a folder named ``home`` or ``Users`` in
    any letter case; where V is the builder's ``home`` folder (by default ``~``) or bears its name
    in any letter case; and where no relative way exists (another drive).
    """
    folder = paths.dirname(paths.abspath(destination))
    vault = paths.abspath(vault)
    parent, name = paths.dirname(vault), paths.basename(vault)
    if not _usable_name(name) or paths.dirname(parent) == parent:
        return None
    if paths.basename(parent).casefold() in SHARED_PARENTS:
        return None
    home = paths.abspath(paths.expanduser("~") if home is None else home)
    if paths.normcase(vault) == paths.normcase(home) or name.casefold() == paths.basename(home).casefold():
        return None
    try:
        way = paths.relpath(folder, parent)
    except ValueError:
        return None
    parts = [] if way == paths.curdir else way.replace(paths.altsep or paths.sep, paths.sep).split(paths.sep)
    if parts and (parts[0] == paths.pardir or paths.normcase(parts[0]) == paths.normcase(name)):
        return None
    return "../" * len(parts) + name


def _usable_name(name: str) -> bool:
    return bool(name) and not name.startswith("-") and not any(
        character in REFUSED_CHARACTERS or unicodedata.category(character) == "Cc" for character in name)
