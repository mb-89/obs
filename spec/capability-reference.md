# Capability reference

The capability notes in [[capabilities/manifest|Capabilities]] own the supported
input vocabulary. [[architecture#Document-adapter contract|Architecture]] owns the neutral
contract boundary; this note provides its documentation projection.

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
