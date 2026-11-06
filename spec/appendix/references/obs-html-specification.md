---
title: obs-html specification
url: https://github.com/mb-89/obs/blob/main/adapters/html/spec/manifest.md
description: "The HTML adapter's own specification: everything about its output, including its option namespace and trusted extensions, such as attachment replacement, the example of an adapter documenting its own extension. The attached file is that specification, built with the adapter."
accessed: 2026-11-06
---

obs treats the HTML adapter's specification like any outside source: this note stands for it,
and the build of obs's specification builds it with the adapter into the attached file.

```cmd silent
uv run python -m obs.capabilities --notes capabilities --output design_output/obs-html-specification.capabilities.json
```

```cmd silent
uv run obs-document --source ../adapters/html/spec/manifest.md --document design_output/obs-html-specification.json --capability-reference design_output/obs-html-specification.capabilities.json --execute-commands
```

```cmd silent
uv run obs-document --document design_output/obs-html-specification.json --capability-reference design_output/obs-html-specification.capabilities.json --adapter html --adapter-config ../adapters.json --destination design_output/obs-html-specification.html
```

![obs-html specification](../../design_output/obs-html-specification.html)
