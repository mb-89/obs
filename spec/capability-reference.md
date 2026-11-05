# Capability reference

The capability notes in [[capabilities/manifest|Capabilities]] own the supported
input vocabulary. [[architecture#Document-adapter contract|Architecture]] owns the neutral
contract boundary; this note provides its documentation projection.

Every Markdown authoring example in a capability note is valid input: read as a note, the
core accepts it and finds the note's capability in it, so an example cannot drift from what the
core accepts. An example that is a YAML mapping alone is a frontmatter fragment.
`test/test_capability_examples.py` checks every example and names the note, the example's line
and the core's error.

```base
filters: 'kind == "capability"'
properties:
  capability.id: {displayName: ID}
  capability.summary: {displayName: Summary}
  capability.authoring: {displayName: How to author}
  capability.dependsOn: {displayName: Depends on}
views:
  - type: table
    name: Capabilities
    order: [capability.id, capability.summary, capability.authoring, capability.dependsOn]
```
