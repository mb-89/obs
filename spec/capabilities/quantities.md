---
kind: capability
capability:
  id: quantities
  summary: Express named numeric values and their canonical sources.
  authoring: Author a quantity note with its supported numeric frontmatter.
  dependsOn: ["[[capabilities/queries]]", "[[capabilities/markdown-frontmatter]]"]
  source: "[[input-model#Numeric-value notes]]"
---

## What it does

Express named numeric values and their canonical sources.

## Authoring example

```markdown
---
kind: quantity
value: 42
unit: kN
aliases: [maxLoad]
source: "[[load-calculation]]"
---
```

## Frontmatter

[[input-model#Numeric-value notes]] owns why a quantity is a note; this list owns its fields.

- `kind: quantity` makes the note a quantity.
- Exactly one of `value`, a finite number without its unit, or `query`, a count query
  `{where, from?, distinct?}` ([[capabilities/count-query]]).
- `unit`, optional: the display unit, a physical unit the core parses: an SI or common
  engineering unit with an optional prefix, or a product or quotient of them, such as `mm`,
  `kN`, `N*m`, `km/h`, `rpm` or `%`. Without `unit` the value is a plain number. An unknown
  unit fails the build naming the note, the unit and the remedy.
- `range`, optional: `[minimum, maximum]`, two finite numbers in the note's unit with the
  minimum first, the domain the quantity may take. A `value` lies inside it, bounds included.
- `aliases`: exactly one variable-style alias (a letter, then up to 39 letters, digits or
  underscores), as a string or a one-item list. Authors reference the quantity as
  `[[alias]]`.
- `source`: a string or a list of strings that links at least one supporting note.

The core validates every quantity note the Document includes
([[input-model#Chapter content]]); a quantity note nothing reaches is not validated. An
invalid included one fails the build with a message that names the note, the field and the remedy, for example:

```text
Quantity note vault/load.md: value must be a finite number, not '12 kN'; write the bare number and put the unit in unit.
```

## Document node

An included quantity note gets a `quantities` node with its frontmatter as `metadata` and its
`quantity`; the same `quantity` is on the note's record, so an adapter that renders a link to the
note finds it there.

A `quantity` holds the display `unit` as authored (empty for a plain number),
its `dimension`, the nonzero exponent of each base dimension (`{length: 1, time: -1}` for
`km/h`, `{}` for a plain number or `%`), and, with a `value`, that value and `siValue`, the value
in SI base units (`value: 2, unit: km` has `siValue: 2000`). A `range` adds `siRange`, both
bounds in SI base units.

A count query's quantity has no value: the count is evaluated live. An
adapter converts between units from `siValue` and `dimension` alone, without a unit library of
its own; `document.schema.json` (`$defs/quantity`) owns the shape.

## Arithmetic

The core adds and subtracts quantities of one dimension across units (`obs.quantity`'s `add`
and `subtract`): `2 m` plus `5 mm` is `2.005 m`, the result in the left quantity's unit.
Combining quantities of different dimensions, a count without a value, or two temperatures in an
offset unit such as `degC` fails with a message that names both notes and the remedy.
