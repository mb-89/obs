---
title: obs
document type: Design specification
subtitle: "![Obsidian](https://img.shields.io/badge/Obsidian-7C3AED?style=for-the-badge&logo=obsidian&logoColor=white) → ![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white)"
product:
  name: ""
  version: ""
organization: ""
template: ""
sap number: ""
authors: ""
reviewers: ""
approvers: ""
copyright: ""
confidentiality: ""
legal entity: ""
ignored: true
obsHtml:
  layout: paged
  pages:
    - page: cover
    - page: abstract
      title: Abstract
    - page: contents
      title: Contents
---

- [[overview|Overview]]
- [[design_input/product|Product]]
  - [[design_input/input-model|Input model]]
    - [[capability-reference|Capability reference]]
- [[design_input/architecture|Architecture]]
  - [[design_input/quality|Quality]]
  - [[design_input/cli|CLI]]
- [[appendix/appendix|Appendix]]
  - [[appendix/references|References]]

This specification describes obs: how an Obsidian-compatible Markdown vault becomes one JSON
Document, and the contract under which any adapter renders that Document.
