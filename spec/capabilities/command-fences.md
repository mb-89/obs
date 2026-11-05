---
kind: capability
capability:
  id: command-fences
  summary: Request authorized command-derived document content.
  authoring: Use a cmd fence and run it only through the explicit execution boundary.
  dependsOn: ["[[capabilities/markdown]]"]
  source: "[[input-model#Command-derived content]]"
---

## What it does

Request authorized command-derived document content.

## Authoring example

````markdown
```cmd
echo Derived content
```
````

## Authorization

The core runs command fences while it builds the Document, and only when the build is authorized:
`obs-document --source <manifest> --execute-commands`. Every fence runs from the vault root:
producers (`cmd silent`) first, in path and source order, before the vault is read for
conversion, then each other fence where it appears. A timeout, set by `execution.commandTimeoutSeconds`
of the core configuration (`src/obs/config.schema.json` owns the default), or a nonzero exit fails
the build, and no Document is written.

Without the authorization, producers do not run and a rendering fence fails the build with the
input error of [[input-model#Chapter content]]: the fence's note and place (`cmd fence 2`), and
the remedy, `--execute-commands`. Adapters never run commands; they render what the node carries
([[architecture#Document-adapter contract]]).

## Document node

A `command-fences` node carries the fence's `source`. A producer carries `silent: true` and
renders nothing; every other fence carries `output`, its captured stdout and stderr. The node's
attributes are defined by `src/obs/document.schema.json`.

## Captured output

A Document never carries the build machine's absolute paths in captured output. Before the core
puts output in its node, it replaces:

- paths inside the vault root, the command's working directory, with paths relative to it (the
  root itself becomes `.`);
- the home folder with `~`;
- every other absolute path, such as temporary and virtual-environment folders, with the
  placeholder `<local-path>`.

Commands run with a minimal environment, so an environment dump carries nothing machine-specific
beyond the paths replaced above. They inherit only `PATH`, `PATHEXT`, `SYSTEMROOT`, `WINDIR`,
`COMSPEC` (to find and start programs), `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA` (per-user
tool settings and caches), `TMPDIR`, `TEMP`, `TMP` (temporary folders) and `LANG`, `LC_ALL` (text
encoding), where they are set; a command that needs more sets it itself.

The core then checks the finished output for the vault root and the home folder and fails naming
the fence's note; a hit is an obs defect to report, not an authoring error. Adapters check their
finished artifact for what authored content may expose (the HTML adapter: its README, section
"Command fences").
