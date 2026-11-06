---
obs: {bless: pending}
---
# Where the answer is kept

A reader's verdicts must be kept where the decision can be read again later.

```pugh
title: Where the answer is kept
chosen: html
criteria:
  - {key: places, label: Places that hold it, weight: 3, better: lower}
  - {key: readable, label: Readable as the decision, weight: 2, better: higher, kind: judged}
candidates:
  - {key: export, label: Comment export, what: A document-level comment in the comment export., values: {places: 2},
     losses: The verdict lives beside the decision.}
  - {key: html, label: Answered artifact, what: obs-document --answers builds the artifact with the answers in it.,
     values: {places: 1}, marks: {readable: 2}, wins: The changed artifact is its own record.}
  - {key: json, label: Answers file alone, what: The answers.json the server writes., values: {places: 1},
     marks: {readable: -1}, losses: Read without the decision it answers.}
datum: {prefer: [export]}
```
