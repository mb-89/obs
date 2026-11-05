import os
import shutil
import subprocess
from pathlib import Path

import pytest


CHECKOUT = Path(__file__).resolve().parents[1]


@pytest.mark.e2e
@pytest.mark.parametrize("editable", [True, False], ids=["editable", "copy"])
def test_installed_tool_generates_from_outside_the_checkout(tmp_path, editable) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH.")
    environment = {**os.environ, "UV_TOOL_DIR": str(tmp_path / "tools"),
                   "UV_TOOL_BIN_DIR": str(tmp_path / "bin")}
    environment.pop("VIRTUAL_ENV", None)
    install = [uv, "tool", "install", *(["--editable"] if editable else []), str(CHECKOUT)]
    installed = subprocess.run(install, cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert installed.returncode == 0, installed.stderr
    try:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "manifest.md").write_text("- [[chapter]]\n", encoding="utf-8")
        (vault / "chapter.md").write_text("# Installed\n\nBody.\n", encoding="utf-8")
        executable = tmp_path / "bin" / ("obs-html.exe" if os.name == "nt" else "obs-html")

        def obs_html(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run([str(executable), *arguments], cwd=tmp_path, env=environment,
                                  capture_output=True, text=True)

        built = obs_html("--source", "vault", "--output", "out/document.html")
        assert built.returncode == 0, built.stderr
        assert (tmp_path / "out" / "document.html").read_text(encoding="utf-8").startswith("<!doctype html>")

        archived = obs_html("--source", "vault", "--output", "out/evidence.html", "--embed-source")
        if editable:
            assert archived.returncode == 0, archived.stderr
        else:
            assert archived.returncode == 2
            assert "--embed-source requires the generator checkout" in archived.stderr
    finally:
        subprocess.run([uv, "tool", "uninstall", "obs-html"], cwd=tmp_path, env=environment,
                       capture_output=True, text=True)
