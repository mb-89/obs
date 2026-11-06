---
kind: capability
capability:
  id: equation-figures
  summary: Plot symbolic equations whose variables move live within their ranges, solved once by the core.
  authoring: Write a figure fence of kind equations with SymPy equations, their variables (quantity notes or own defaults, ranges and units) and the initial plot.
  dependsOn: ["[[capabilities/figures]]", "[[capabilities/quantities]]"]
  source: "[[input-model#Equation figures]]"
---

## What it does

A figure of kind `equations` ([[capabilities/figures]]) shows symbolic equations or a system
of them, algebraic or differential, as a 2D plot whose variables a reader moves within their
ranges. Variables are quantity notes ([[capabilities/quantities]]) or carry their own default,
range and unit.

The core parses and checks the equations, solves them where it can, and puts everything a live
plot needs into the Document as expression trees.

A curve plots at every value inside its
variables' ranges, special ones included: where the exact solution is undefined at a value (the
oscillator below at critical damping, ζ = 1), the core gives its limit there, or has the reader's
page solve that curve numerically. [[input-model#Equation figures]] owns the fence, the range rule
and the Document body.

## Authoring example

````markdown
```figure
version: 1
kind: equations
caption: Engine torque over speed for three throttle positions.
content:
  equations: T = T_max*throttle*(1 - (n/n_max)**2)
  variables:
    n: "[[engineSpeed]]"
    n_max: {default: 6000, unit: rpm}
    T_max: {default: 250, unit: N*m}
    throttle: {default: 1, range: [0, 1]}
    T: {unit: N*m}
  plot:
    x: n
    y: T
    family: {variable: throttle, values: [0.25, 0.5, 1]}
```
^torque
````

The quantity note the example's `[[engineSpeed]]` names:

```text engine-speed.md
---
kind: quantity
value: 3000
unit: rpm
range: [800, 6000]
aliases: [engineSpeed]
source: "[[example]]"
---
# Engine speed
```

A differential equation names the function's variable in `of` and its initial value and slope:

```yaml
equations: y'' + 2*zeta*w*y' + w**2*y = w**2*u
variables:
  t: {default: 0, range: [0, 10], unit: s}
  y: {of: t, initial: [0, 0]}
  zeta: {default: 0.3, range: [0.05, 2]}
  w: {default: 2, range: [0.5, 5], unit: 1/s}
  u: {default: 1}
plot: {x: t, y: y}
```

A parallel-coordinates plot sweeps a grid of the other movable variables: each line is one
combination, each axis a variable or a computed value, here the settling time and the error
area of each step response. [[input-model#Equation figures]] owns `grid` and `computed`.

```yaml
plot:
  x: t
  y: y
  parallelCoordinates: true
  grid: {zeta: {values: [0.2, 0.5, 0.8, 1.3]}, w: {steps: 4}}
  computed:
    - {name: settling, summary: settlingTime, of: y, tolerance: 0.02}
    - {name: error area, summary: absoluteArea, of: u - y}
```
