---
title: obs-html specification
url: https://github.com/mb-89/obs/blob/main/adapters/html/spec/manifest.md
description: "The HTML adapter's own specification: everything about its output, including its option namespace and trusted extensions, such as attachment replacement, the example of an adapter documenting its own extension. The attached file is that specification, built with the adapter."
accessed: 2026-11-06
---

obs treats the HTML adapter's specification like any outside source: this note stands for it,
and the build of obs's specification builds it into the attached file with the command the
adapter's package offers for it. The command reads the specification from the installed package,
so this producer reads nothing outside obs's vault and the vault's source archive rebuilds it.

```cmd silent
uv run obs-html --build-own-spec design_output/obs-html-specification.html
```

![obs-html specification](../../design_output/obs-html-specification.html)
