---
obs: {bless: pending}
---
# Which swipes walk the deck

On touch, a horizontal swipe moves to the previous or next chapter; a verdict is always a key.

```pugh
title: Which swipes walk the deck
chosen: outside
criteria:
  - {key: lost, label: Scrolls taken from a box, weight: 3, better: lower}
  - {key: reach, label: Where a swipe walks, weight: 1, better: higher, kind: judged}
candidates:
  - {key: everywhere, label: Every swipe, what: Any horizontal swipe walks., values: {lost: 3}, marks: {reach: 2}}
  - {key: outside, label: Outside scrolling boxes, what: A swipe that starts in a box that scrolls sideways stays there.,
     values: {lost: 0}, marks: {reach: 1}}
datum: {prefer: [everywhere]}
checklist:
  - {item: "Does a swipe ever give a verdict?", answer: "No: verdicts are keys.", pass: true}
```
