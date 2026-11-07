# Quality

The system favors local reasoning and local changes. A feature owner should be able to
change one cohesive module while generic infrastructure discovers and integrates the
result.

## Glossary

This glossary owns the project's vocabulary; other notes link here instead of redefining a
term (user, 5 Nov 2026).

- **Document**: the core's versioned JSON intermediate representation of one manifest. Its
  shape is owned by [[architecture#Document-adapter contract|the Document-adapter contract]].
- **artifact**: what an adapter puts out from a Document, such as a web page and
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
- Each runtime has one selection resolver, and every count, distinct value and drill-down
  reads a note's property through it, never through a lookup of its own, so all of them follow
  [[capabilities/bases#Comparisons]].

  The core's is `obs.selection.note_value` (with the
  note's marks for a query condition, `obs.selection.conditions_select`); the browser's is
  `obsQuery.propertyTexts`, which the adapter's specification that ships it owns.

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
  parallel worker processes, one per CPU (pytest-xdist). Each part's worker groups start heaviest
  first, weighed by their test time in the part's last run the suite recorded; without a record
  they keep their order.

  A module's tests share a worker, so its module fixtures are built
  once per run; each worker starts one browser and leases every test a page from its pool, made
  blank between tests as a fresh context shows it. The adapter's browsers keep their frame rate
  capped: uncapped, every frame wait draws as fast as the CPU allows, which the parallel suite
  pays for in every other test.
- The adapter's browser tests run on Playwright's `chromium-headless-shell`, which costs about half
  the CPU of full Chromium per page. The checks whose behaviour can differ in the shell run on
  full Chromium, the browser the PDF path finds, as a small named set: print and PDF export, the
  viewer fixture's sandboxed frame and the startup marks.

  A test states its engine by the fixture
  it takes; the adapter's `test/structure/test_quality.py` names the set and refuses a
  full-Chromium test outside it, and its `test/conftest.py` fails, with the remedy, where the shell
  is not installed.

  The suite's setup (`test/suite.py`) names the shell and installs it with Playwright where
  Playwright's browsers folder holds none; CI runs that setup and installs nothing itself.
- A browser test opens what shared fixtures give it: a leased page, and an artifact built once (by
  a fixture through `built_once`, or by the adapter's `test/artifacts.py`); several read-only
  checks of one artifact share one page load. It neither builds an artifact nor starts
  Playwright or a browser itself.

  It adds no init script, since in the preview's srcdoc frames
  one can run after the artifact's own scripts, and reads the artifact's timings from the
  artifact's own performance marks. The adapter's `test/structure/test_quality.py` refuses a
  test that does otherwise.
- An input many tests read, such as a fixture artifact or the spec artifact, is built once per
  run by `built_once` in the part's `conftest.py` and shared by every worker; the tests only read
  it.
- obs's spec is built once per run of the complete suite and shared by the core and every
  adapter: `test/spec_build.py` builds its Document in a folder `test/suite.py` makes for the
  run, named by a hash of the build's inputs, and counts each build there; the suite fails where
  one was built twice.

  The core's controller starts that build as its session starts, before its workers collect.

  So is an adapter's specification that a producer fence of
  the spec builds: every build of the spec in the run, a test's copy of the vault too, is served
  that one build.

  A test that needs another build
  of the spec copies the vault and builds only that variant; the core's
  `test/structure/test_spec_builds.py` and the adapter's `test/structure/test_quality.py` refuse
  a test that builds the spec otherwise, except the named few, such as the adapter's archive
  rebuild, which rebuilds the spec from its own source archive.
- A committed fixture Document (an adapter's `test/fixtures/documents`) is rebuilt from its vault
  by the current core in every run of the complete suite; a refused vault or a stale Document
  fails, naming the vault and the core's message or the first differing JSON path.
- The adapter's browser tier tests every reader feature once, on its feature fixture: a small
  vault with a few chapters in which every feature of the feature registry appears, so the tier
  does not grow with the spec. A test fails where a registered feature is missing from it.

  The spec artifact serves only the checks that need the real spec: its startup budget, its
  content model, a printed spec chapter and its archive rebuild.
- No test can hang the suite. Each test of the core and of every adapter has its tier's timeout
  (pytest-timeout), a measured multiple of the tier's slowest test, which `test/bounds.py` owns
  with its measurement; a test past it fails, naming itself and its timeout.

  Bounds are measured, never typed: each complete-suite run records every passed test's time on
  its host, and a tier's slowest test is the slowest over that host's recent runs, or the
  committed measurement while the host has too few, which also caps it: a test past a multiple
  of the committed measurement fails the suite.

  A run that did not complete (a module failed to collect, pytest stopped with an error, or no
  test ran) records nothing, and the suite names it; a recorded run without a timed test counts
  for nothing.

  `test/bounds.py` (COMMITTED) names how and where the committed measurement is taken.

  The adapter's page pools launch their browsers with an explicit timeout, before the timeout
  of the first test that needs one starts, and draw a first page: a cold launch is no test's time.

  Where a pool's
  browser dies while a test holds one of its pages, that test fails, "browser crashed", naming
  the engine; where a test past its timeout held one, the pool ends that browser. Either way, the
  next test gets a fresh browser.

  A page that does not answer while it is released, a locked page among them, is not waited on:
  past a timeout the pool ends its browser, and the next lease gets a fresh one.

  `test/suite.py` caps the whole run: at its cap it stops each part still running and names the
  part and the tests it was running.

  CI runs the complete suite on runners whose speed differs: one commit's parts took 104.6 s on
  one run and 150.1 s on its re-run. So CI spreads the suite over shards, one job each
  (`test/suite.py --shard`).

  CI does not fail a run past the suite's time limit, which se's local gate enforces on the
  whole suite; `test/suite.py` names the runner's CPUs and says in each job's log, as a warning
  annotation, when its run is past the limit.
- The adapter's chapter sweep (`test/chapter_sweep.py`) is the one browser check that does not
  lease the pool's pages. It opens every chapter of an artifact and scrolls it, a step where a
  page that locks its main thread is expected.

  So the sweeps run in a child process with its
  own headless shell, one per test process, kept from one sweep to the next, and each sweep has
  a hard timeout under the test's own: a locked page ends the child's process tree, the test names
  the chapter it was on, the next sweep starts a fresh child, and no other test's browser is
  touched.

  Its test sweeps every committed fixture Document, at a desktop and a phone viewport, without
  and with reduced motion, in the complete suite.

  Each artifact at each viewport is a test of its
  own, so one test's time is one viewport's, within its tier's measured bound. The
  phone draws at device scale 1: the sweep looks for a page that stops answering and for console
  errors, not at what a person reads.
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
- A bare `uv run pytest`, and so the complete suite, runs every tier except external, which
  needs inputs from outside the repository and runs only when selected with `-m external`.
- The browser tier needs `OBS_HTML_TEST_NATIVE_BROWSER`
  set to the absolute path of a Chromium or Chrome executable (for example `/usr/bin/chromium`
  or `C:\Program Files\Google\Chrome\Application\chrome.exe`). Playwright's own browser
  downloads are not used. Unset, its tests skip; set to a browser that cannot start, they
  fail with a message from `test/test_authored_artifact_browser.py` naming it.
- Unit, dom and browser tiers run without a paired checkout: representative data comes from
  small vendored fixtures under `test/fixtures`.
- Tests that call a paired application, or read hand-supplied data such as a snapshot named by
  an environment variable, are external.

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

See [[architecture]] for current ownership boundaries; an adapter's specification owns its UI
intent.
