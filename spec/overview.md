# Overview

This specification accompanies obs, the core that reads an Obsidian-compatible Markdown vault
into one JSON Document. Its design inputs describe the supported Markdown and its capabilities,
the Document, the core's configuration and command-line interface, and the contract under which
an adapter renders a Document into an artifact.

It makes no statement about any one adapter. An adapter's own specification describes its output
and is an outside source here, like any other: the References list names it, and its entry opens
the specification as built with that adapter.
