"""Install a fixture adapter as a plugin in the test's machine folder, as obs-plugins would
(spec/design_input/plugins.md, Installed plugins); test/conftest.py gives each test its own folder."""
import json
from pathlib import Path

from obs import plugins


def install_adapter(manifest: dict[str, object]) -> Path:
    """``manifest`` as the installed adapter plugin of its name; the plugin's folder."""
    folder = plugins.local_folder() / "plugins" / str(manifest["name"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "adapter.json").write_text(json.dumps(manifest), encoding="utf-8")
    entries = plugins.installed()
    entries[str(manifest["name"])] = {"name": str(manifest["name"]), "kind": "adapter", "version": "1.0.0",
                                      "commit": "0" * 40}
    (folder.parent.parent / "plugins.json").write_text(
        json.dumps({"plugins": [entries[name] for name in sorted(entries)]}), encoding="utf-8")
    return folder
