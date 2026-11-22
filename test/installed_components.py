"""Install a fixture adapter as a component in the test's machine folder, as obs-components would
(spec/design_input/components.md, Installed components); test/conftest.py gives each test its own folder."""
import json
from pathlib import Path

from obs import components


def install_adapter(manifest: dict[str, object]) -> Path:
    """``manifest`` as the installed adapter component of its name; the component's folder."""
    folder = components.local_folder() / "components" / str(manifest["name"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "adapter.json").write_text(json.dumps(manifest), encoding="utf-8")
    entries = components.installed()
    entries[str(manifest["name"])] = {"name": str(manifest["name"]), "kind": "adapter", "version": "1.0.0",
                                      "commit": "0" * 40}
    (folder.parent.parent / "components.json").write_text(
        json.dumps({"components": [entries[name] for name in sorted(entries)]}), encoding="utf-8")
    return folder
