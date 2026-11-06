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
