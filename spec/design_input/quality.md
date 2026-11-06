# Quality

The system favors local reasoning and local changes. A feature owner should be able to
change one cohesive module while generic infrastructure discovers and integrates the
result.

## Glossary

This glossary owns the project's vocabulary; other notes link here instead of redefining a
term (user, 5 Nov 2026).

- **Document**: the core's versioned JSON intermediate representation of one manifest. Its
  shape is owned by [[architecture#Document-adapter contract|the Document-adapter contract]].
- **artifact**: what an adapter puts out from a Document, such as obs-html's HTML file and
  the PDF printed from it.
- **note**: one Markdown file in a vault, with optional frontmatter, addressed by wikilinks.
- **file**: any file on disk, whatever its role: a note, an attachment, a configuration or
  schema file, or generated output.
- **vault**: the folder of notes and attachments that a build reads. Links and assets
  resolve within it, and nothing is written back into it.

## Knowledge ownership

SPOT, single point of truth, everywhere: code, configuration, design, process and agent
definitions alike. Keeping the same fact in two places is an anti-pattern (user, 4 Nov 2026).

- State a fact or contract only in the file that owns and controls it.
- When another document or agent needs that fact, refer to its owner with a link, embed,
  schema reference, generated output, or other derived view instead of paraphrasing it.
- Do not narrate implementation behavior in prose that cannot enforce that behavior.
- User-facing reference material should be generated from the implementation owner when
  practical; CLI documentation, for example, embeds live `--help` output.
- Agent responses identify the owner when discussing facts outside the current task's
  ownership boundary.
- Generated and collected views are disposable. Owners remain the single source of truth.
- A note with only frontmatter is valid. Never repeat frontmatter fields as body prose merely
  to make links or table details readable; render the owning metadata correctly instead.
  Bodies contain only additional discussion, not a second transcription of the row.
- Generated-artifact data ownership is defined by [[architecture]]; views must consume that
  owner rather than serializing parallel copies.

## Change locality

- Every behavior or extension has one clear owning file or narrowly scoped package.
- Generic consumers discover implementations through conventions and small contracts;
  they do not maintain parallel lists, switch statements, or duplicated metadata.
- A local extension carries the information required by its generic contract. Shared
  infrastructure infers integration from it.
- Shared styling uses semantic primitives in the central stylesheet. Extensions compose
  those primitives instead of adding local color or layout values.
- Reuse existing UI primitives for equivalent content, including untitled information cards;
  do not introduce a parallel implementation merely because a heading is absent.
- Tests verify public contracts and discovery behavior so extensions inherit coverage
  from generic tests.
- Find the owning local module before editing, and change the owner rather than synchronizing
  several derived representations.
- Treat a reported instance as evidence of an error class. Fix its shared cause at the owning
  mechanism, with regression coverage for representative variants; do not special-case the
  shown artifact, record, heading or screenshot.
- When a change appears to require edits across many files, first improve the ownership
  boundary or derive repeated data from one source of truth.
- Keep generated output derived; never hand-edit it.

## Testing boundaries

- Treat filesystem access, subprocesses, clocks, browser printing/storage, and network assets as
  explicit adapters ("doors"). Exercise each adapter's real functionality once at its boundary;
  test callers against controlled fakes rather than repeating external work in every test.
- Keep transformations and query evaluation pure where practical. Inject inputs/results at
  the boundary, not arbitrary internal implementation details.
- Reuse small, intention-revealing fixtures. Keep one end-to-end smoke path alongside focused
  tests of failure, cancellation, timeout, and retry behavior.
- Assert observable results and explicit expected outcomes, not source-code substrings or
  agreement between two implementations that might share the same bug.
- An expected value that a fixture, note or configuration owns (a register's row count, a
  palette colour) is read from that owner, not copied into the test as a literal.
- DOM tests use a controlled browser adapter for deterministic interactions. Native browser
  printing and layout remain separate integration checks; a mocked print call does not verify
  a PDF's visual output.
- Write a focused regression test before implementing a feature. Select tests by owning module
  or feature with pytest paths and `-k`; do not run unrelated integration scenarios on each edit.
  Reserve the full test suite for a requested commit.
- Give browser features independently selectable tests and small fixtures. Share expensive
  adapter startup within a selected module; do not require the end-to-end scenario to test a
  local interaction. Prefer extracting pure transformations only when they have a cohesive owner.
- The complete suite (`test/suite.py`) runs its parts side by side and each part's tests in
  parallel worker processes, one per CPU (pytest-xdist). A module's tests share a worker, so its module fixtures are built
  once per run; each worker starts one browser and gives every test fresh contexts in it.
- An input many tests read, such as obs's spec Document, a fixture artifact or the parity
  builds, is built once per run by `built_once` in the part's `conftest.py` and shared by every
  worker; the tests only read it.
- A committed fixture Document (an adapter's `test/fixtures/documents`) is rebuilt from its vault
  by the current core in every run of the complete suite; a refused vault or a stale Document
  fails, naming the vault and the core's message or the first differing JSON path.
- No test reaches the network. Each part's `test/network_guard.py` fails a test that opens a
  connection to anything but loopback, naming the test, the host and the remedy; a subprocess a
  test starts reads remote data from a fake too, as the parity gate's `obs-document` does.
- Browser checks are batched: a sweep evaluates a whole layout in one page evaluation, a test
  reaches into a frame through its `Frame`, and a step waits for an event the artifact gives,
  never for a fixed time.
- The suite passes on Windows and Linux alike. Tests build paths with the platform's path
  API, run real producer commands through the test interpreter rather than shell builtins,
  and compare exact bytes the test itself wrote. A test that genuinely needs one platform
  (PowerShell, native pickers) is skipped elsewhere with a reason, never failed.
- Tier names and meanings are owned by the pytest markers in `pyproject.toml`; assignment from
  dependency evidence is owned by `test/tiers.py`.
- Structure tests, which check what a spec note owns and where it points, live in
  `test/structure/test_<note>.py`, one file per note, so changes to different notes touch
  different test files.
- A bare `uv run pytest`, and so the complete suite, runs the unit and dom tiers and every
  browser or e2e test that does not reach the interim adapter (`obs_html_interim`). The interim
  adapter's browser and e2e tests run only with `uv run pytest --gate`: the adapter's parity gate
  compares the interim adapter, and the cutover removes them with it. `test/tiers.py` decides
  what reaches the interim adapter from the same source evidence as the tiers.
- The browser tier needs `OBS_HTML_TEST_NATIVE_BROWSER`
  set to the absolute path of a Chromium or Chrome executable (for example `/usr/bin/chromium`
  or `C:\Program Files\Google\Chrome\Application\chrome.exe`). Playwright's own browser
  downloads are not used. Unset, its tests skip; set to a browser that cannot start, they fail
  with a message from `test/browser_pool.py` that names the variable.
- Unit, dom and browser tiers run without a paired checkout: representative data comes from
  small vendored fixtures under `test/fixtures`.
- Tests that call a paired application are e2e, including data it reads through
  a snapshot named by an environment variable; tests that read hand-supplied data
  such as that snapshot themselves are external.

### Test feedback time

Table detail expansion must not re-render the whole artifact or recompute all review items.
Profile a large real artifact in a native browser and measure expansion latency before and
after changes. Keep embedded assets and large payloads single-owned; measure artifact byte
composition before optimizing size, without dropping source material or weakening portability.

#mark/open_point/test_feedback_time

Measure test durations and separate fast module checks from expensive integration checks.
What feedback-time budgets should we enforce for each, and which setup or scenario costs
should be reduced first? Use measured timings rather than treating a passing test as waste.

## Diagnostics and review hygiene

- Review a coherent change before declaring it complete. Trace each changed public behavior
  through its owner, callers and focused tests; inspect real layout for visual requirements.
- Audit knowledge ownership during review: CLI usage belongs to executable help, configuration
  defaults and limits to configuration/schema, reference values to their manifest, source syntax
  to the input contract, and presentation requirements to the UI/table design owners.
  Consumers link to or derive from those owners, rather than maintaining copied explanations.
- Audit duplicated processing across languages. For each input, list every place that
  parses, validates, filters or flattens it, in Python, JavaScript, PowerShell or any other
  language; more than one place needs a stated reason. Then ask which code should not exist
  in the user's picture of the system, and check whether it does.

  Code reviews and retros answer both questions in a section of their own. Known cases to
  check against are the two Bases filter evaluators (`filter-evaluator-conformance`) and
  metadata flattened twice (`metadata-flatten-once`) in `spec/backlog/`.
- Distinguish normative design decisions from current implementation descriptions. Keep review
  findings in generated design output with evidence, impact, disposition and remaining questions;
  do not turn an implementation snapshot into a second authoritative specification.
- Put repeatable source checks in the existing CLI's `--check` path and regression tests,
  not disposable inspection scripts. Check mode never executes authored commands or writes
  generated output; unsupported syntax and broken references are errors, not silent omissions.
- A clean valid input must not produce system-generated warnings. Fix mechanical causes in
  code or trivial formatting, but never change content intent merely to silence a diagnostic.
  Surface genuine runtime failures explicitly; do not hide warnings or return success-shaped
  empty data after invalid input.
- Review the review itself: separate fixed defects, verified limitations, and judgment-dependent
  content decisions. Do not claim native browser/PDF verification from mocks or invent a
  migration when its source is unavailable.

This quality requirement applies across parsing, configuration, rendering, controls,
documentation, and future frontmatter behavior.

See [[architecture]] for current ownership boundaries and [[artifact-ui]] for UI intent.
