---
kind: adapter-behavior
capability:
  id: live-data
  summary: Let a Base declare where newer values of its rows are read when the page opens, checked against the rows the build selected.
  authoring: Add obsHtml.liveSource to a Base, then run obs-html --check-rendered on the built page.
  dependsOn: ["bases", "registers"]
  source: "[[generic-tables#Current data]]"
---

# Live data

Reader: whoever declares, in a Base, where newer values of its rows come from, or changes how
obs-html checks such a declaration.

[[generic-tables#Current data]] owns the declaration, its refusals, the mapping rules and the
check; this note shows how to author one.

## Authoring

Add `obsHtml.liveSource` to the Base, in a `base` fence or a `.base` file. Each row is a note
whose path follows from its key, here `issues/widgets-12.md` for the item `{repo: widgets,
number: 12}`, and whose frontmatter holds the fields the declaration maps:

```yaml
obsHtml:
  liveSource:
    name: Example Tracker
    key: [repo, number]
    changed: updated
    notePath: "issues/{repo}-{number}.md"
    fields:
      number: number
      state: {path: state, lowercase: true}
      labels: labels
      updated: updated_at
      pullRequest: pull_request.url
    derive:
      status:
      - {where: [{field: labels, equals: planned}], keep: true}
      - {where: [{field: state, equals: closed}], value: Done}
      - {where: [{field: labels, equals: backlogged}], value: Backlog}
      - {where: [{field: labels, equals: needs-you}], value: Needs you}
      - {where: [{field: labels, equals: running}], value: Running}
      - {where: [{field: labels, equals: ready}], value: Next}
      - {keep: true}
    fillNew: {where: title}
    bodyPath: body
    exclude: [{field: pullRequest, exists: true}]
    changes:
    - provider: connector
      server: Example Tracker
      tool: list_issues
      rows: issues
      next: {cursor: pageInfo.endCursor, more: pageInfo.hasNextPage, input: after}
      maxPages: 3
      requests:
      - set: {repo: widgets}
        input: {owner: example-org, repo: widgets, since: "{since}", orderBy: UPDATED_AT, direction: ASC, perPage: 100}
    - provider: web
      next: link
      maxPages: 3
      fields: {labels: "labels[].name"}
      requests:
      - set: {repo: widgets}
        url: "https://api.example.test/repos/example-org/widgets/issues?state=all&since={since}&sort=updated&direction=asc&per_page=100"
```

The build refuses a declaration it can tell is wrong by its shape, at its field. Whether the
declaration fits the rows is told only in the page: after declaring a source, build the HTML and
run `obs-html --check-rendered` on it. A row whose key, `changed` instant, note path or derived
value the declaration does not reproduce fails that check with one console error naming the
table, the note, the check and the field, and the table keeps its saved rows.
