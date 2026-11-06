"""The core's `obs-document` without the network, for a test that runs the core as a subprocess.

Reader: whoever runs the core as a subprocess of a test, as the run's shared build of obs's spec
(test/spec_build.py) and the HTML adapter's archive rebuild
(adapters/html/test/test_spec_archive_rebuild.py) do.

Runs in the core's environment, with obs-document's arguments:
`uv run --offline --project <core> python <core>/test/offline_obs_document.py --document ... --source ...`.
The build's one network read, `obs.vault.fetch_remote`, serves every remote image as a badge-sized
placeholder SVG, as the core's own tests replace it, so the subprocess never reaches the network.
"""
import sys

from obs import document, vault

PLACEHOLDER = (b"<svg xmlns='http://www.w3.org/2000/svg' width='120' height='28'/>", "image/svg+xml")


def fetch(_url: str) -> tuple[bytes, str]:
    return PLACEHOLDER


if __name__ == "__main__":
    vault.fetch_remote = fetch
    raise SystemExit(document.main(sys.argv[1:]))
