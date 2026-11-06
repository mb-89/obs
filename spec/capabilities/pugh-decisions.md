---
kind: capability
capability:
  id: pugh-decisions
  summary: Decide between options as a Pugh matrix whose bottom line, matrix and weight sensitivity a reader sees as one figure.
  authoring: Write a pugh fence holding one decision matrix in YAML, with an optional chosen option and each option's short label and sentence.
  dependsOn: ["[[capabilities/figures]]"]
  source: "[[input-model#Pugh decision figures]]"
---

## What it does

A decision is written as a Pugh matrix: options marked against a datum on weighted criteria.
A ```` ```pugh ```` fence holds one matrix in YAML, or a figure fence of kind `pugh`
([[capabilities/figures]]) holds it under `content` or in a `source` file. The core checks it
and carries it as data; it decides nothing.

An adapter decides the matrix with ctrl's engine, `src/core/pugh.js` of github.com/mb-89/ctrl,
carried unchanged from ctrl's commit `2839d765ff04d5586f1f0199203bbebf2d03cd22`. The engine's
own note, ctrl's `design/output/pugh.md`, owns the matrix's shape ("The matrix file") and every
rule of the decision. [[input-model#Pugh decision figures]] owns what obs adds.

## Authoring example

````markdown
```pugh
title: Which message queue
chosen: managed
criteria:
  - {key: latency, label: p99 latency (ms), weight: 3, better: lower}
  - {key: ops, label: Ease of operation, weight: 2, better: higher, kind: judged}
candidates:
  - {key: current, label: Current queue, short: Now, what: The queue we run today.,
     values: {latency: 12}}
  - {key: managed, label: Managed queue, short: Managed, what: A hosted queue we rent.,
     values: {latency: 14}, marks: {ops: [2, 1, 2]}}
datum: {prefer: [current]}
```
````
