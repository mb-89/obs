# SharePoint and OneDrive preview: feasibility research

Status: findings record. SharePoint/OneDrive preview stays a desired experience, but is not
investigated further (user, 4 Nov 2026). The diagnostic generator
`scripts/sharepoint_diagnostic.py` and its test were deleted; restore them with
`git restore --source 32eae7f -- scripts/sharepoint_diagnostic.py test/test_sharepoint_diagnostic.py`.
Researched 2026-10-23. No generator or delivered artifact changes made.

## Desired experience

Readers should be able to open an artifact from a SharePoint document library or
OneDrive without downloading it first. The user reports that the old tracing
artifact mostly works there, except its Sankey diagram, whereas current obs-html
artifacts do not display useful content.

Distinguish two targets: readable document preview and full interactive artifact
execution. Neither is guaranteed merely because the service accepts an HTML upload.

## Findings from the actual files

### Tenant probe results, 2026-10-23

User screenshots of the uploaded diagnostic confirm classic scripts, modern
syntax, module scripts, JSON islands/DOM initialization, event listeners, inline
event attributes, MutationObserver, canvas, inline CSS/SVG and data-URI SVG work.
The preview is framed. Both localStorage and sessionStorage throw SecurityError:
the sandbox lacks allow-same-origin. The pinned Plotly CDN script failed to load;
the screenshots alone do not distinguish network, CSP, CORS, and integrity causes.
Blanket JavaScript blocking is disproven for this viewing path.

An embedded-minified variant is available at
`data/data_output/sharepoint-preview-spike-embedded.html` (about 1.08 MB).
Its initial revision had an accidental nested-license-comment syntax error,
confirmed locally and corrected; that initial failure was not a host limitation.
The corrected version renders Plotly in a local allow-scripts iframe sandbox
without allow-same-origin, with storage denied and zero network requests.
User screenshots confirm the corrected embedded variant loads Plotly 2.35.3 and
renders the graph in SharePoint. Storage access remains denied.
No generator or delivered artifact was changed by these probe revisions.

Storage implications: current application-level localStorage use is remembered
appearance (`src/obs_html/bars/settings.js`) and reviewer name
(`src/obs_html/bars/comments.js`), both already catch access failures. Review data
is saved in downloaded HTML, not localStorage. In-memory state can support editing
for the lifetime of the open preview but cannot survive reload. Download/save
permission in the actual sandbox is not established by Blob URL creation alone;
test it independently before promising review persistence there.

The current generator emits an empty chapter container and stores chapter HTML in
a JSON script island; JavaScript populates the visible artifact
(`src/obs_html/renderer.py:213-214,240`). This affects the entire artifact, not
only Plotly or CDN-backed diagrams.

In Chrome with JavaScript disabled, the current `leaves.html` and `obs-html.html`
each expose only the menu icon as visible body text. This reproduces an important
failure mode locally, but does not prove the tenant uses that exact restriction.
The self-artifact does not load an external script, so CDN removal alone cannot
explain or fix both artifacts.

The available legacy artifact has no external script tags.
With JavaScript disabled it shows a shell and "Loading trace data", not the full
trace artifact. This file was regenerated today; it is not proven to be the exact
old file the user viewed successfully in SharePoint. Do not conclude that the
user's working old version is static or that its Sankey failure is CDN-related.

## Microsoft documentation and limits

- [Allow or prevent custom scripts](https://learn.microsoft.com/en-us/sharepoint/allow-or-prevent-custom-script):
  custom script is restricted by default on modern SharePoint sites and OneDrive.
  Temporary allowance on a SharePoint site resets within 24 hours; individual
  OneDrive custom-script allowance is not available.
- [Security considerations of allowing custom script](https://learn.microsoft.com/en-us/sharepoint/security-considerations-of-allowing-custom-script):
  Microsoft discusses scripts in HTML pages in document libraries and recommends
  SharePoint Framework (SPFx) for governed interactive solutions.
  Importantly, it also says blocking custom script does not stop scripts already
  inserted. These administrative controls must not be equated with a precise
  description of the file-preview sandbox or its runtime script policy.

The reviewed documentation does not establish the exact HTML click-to-preview
pipeline for this tenant: sanitization, iframe sandbox, CSP, forced download,
and supported markup/assets remain unverified. Upload acceptance does not prove
preview support. Neither changing a filename extension nor moving scripts to/from
a CDN is a supported way to bypass host restrictions.

## Feasible directions, pending evidence

1. A pre-rendered, script-independent artifact surface could make content readable
   when JavaScript is unavailable, provided the actual preview accepts the HTML
   and required styling/images. Enhance that surface when scripts can execute.
   Query tables and diagrams must be rendered too, not just chapter headings.
   This would be a preview representation, not a restoration of all interactions.
2. If the service refuses useful HTML preview altogether, provide a PDF companion.
   That is a separate viewing artifact, not native interactive HTML support.
3. Full interaction may require organization-approved web hosting or an SPFx
   viewer. That is a deployment/integration project, not a formatting-only fix.
   Do not weaken tenant security settings as a generator prerequisite.

Do not reverse the approved optional CDN delivery decision on speculation.
Inlining dependencies helps only when script execution is permitted and external
asset loading is the actual failure.

## Proposed requirement, not yet approved

### User constraints clarified after research

- Test small files by uploading them to the existing SharePoint location; the user
  will report what is visible and which interactions work.
- Do not require corporate IT involvement, tenant policy changes, app-catalog
  deployment, or approval to run code. SPFx is therefore not the chosen route.
- Do not duplicate artifact data or store parallel static diagram fallbacks merely
  for preview compatibility.
- Prefer one readable HTML/DOM representation enhanced by JavaScript, if feasible.
  Without JavaScript, unavailable dynamic features should have a concise message
  telling readers to download the HTML and open it directly in a browser.
- Script cannot detect a blocked-script environment if it never runs. Baseline
  content and any no-script notice must exist before runtime initialization.
  A no-script notice alone does not cover every sanitizer/sandbox, so validate the
  real SharePoint path rather than relying on automatic "preview mode" detection.
- First determine whether scripts are blocked at all in the actual preview.
  The local disabled-JavaScript experiment is a hypothesis, not tenant evidence.

### Follow-up design direction after successful embedded-library probe

- Loss of remembered appearance and reviewer name is acceptable in preview.
- Centralize optional browser-storage access behind a shared capability boundary.
  Appearance persistence is superseded by the opening-state rule in [[artifact-ui]]:
  appearance is session-only and has no storage warning. The capability boundary
  and warning below now apply only to remembered settings such as reviewer name.
  If storage is unavailable, keep the control usable with in-memory state and show
  a small yellow exclamation indicator beside the affected control. Its tooltip
  should explain that the setting will not be remembered in this environment.
  Make the explanation available on keyboard focus and to assistive technology.
  Storage denial alone must not be labelled definitive proof of SharePoint preview.
  Suggested wording: "This setting cannot be remembered in this environment.
  Download the HTML and open it directly in your browser for full functionality."
  Do not promise persistence locally if that browser also denies storage.
- Embedded libraries are a viable compatibility option, confirmed for Plotly by
  the tenant probe. This does not yet prove the entire artifact works: investigate
  current-artifact initialization and test navigation, tables, review, edited-HTML
  download and printing separately in the same preview.
- Minified generated HTML, CSS and JavaScript are acceptable; generated output
  need not be readable. Keep authored sources readable and reproduction archives
  faithful to those sources. Evaluate proper syntax-aware minification at the
  build boundary, not regex whitespace removal. Preserve licenses, script-island
  data, meaningful text whitespace, identifiers used across scripts, and reviewed
  HTML save/reopen behavior.
- Measure size and generation-time impact before selecting tooling. Vendored
  Plotly is already minified; minifying it again is not a meaningful saving.
  These are future implementation directions, not changes to today's delivery.

### Recommended next check

Use a diagnostic copy of an actual generated artifact, not another generic API
spike. Keep published deliverables untouched. Embed the existing minified
dependencies and expose initialization errors visibly in that diagnostic copy.
First reproduce it locally in an allow-scripts sandbox without allow-same-origin;
then upload the same copy to the user's SharePoint library. Fix demonstrated
failures surgically rather than adding a separate static representation.

Check content/navigation, tables/filtering, diagrams/expansion, appearance and
reviewer-name controls, comments/decisions/field edits, downloaded edited HTML
reopened locally, and PDF export. Mark host-restricted actions explicitly with
the download-and-open remedy.

The artifact now does this itself: in a limited host its capability canaries
raise Limited functionality warnings; see
[Artifact UI](artifact-ui.md#dock-menu) (the notice center) for the warnings and
the registry that lists the browser capabilities the artifact depends on. Defer minification until compatibility works so
format transformations do not obscure diagnosis.

For agreed SharePoint/OneDrive viewing paths, artifacts should offer a readable,
script-independent representation of chapters, tables, and diagrams without
requiring a download. Preserve the existing interactive standalone artifact when
scripts are available. If HTML preview is unsupported by the target service,
document that boundary and offer an explicit PDF viewing alternative instead of
claiming native compatibility.

Acceptance must include the real tenant viewing path, not just a local browser
test with JavaScript disabled. Reading support and interactive support must be
reported separately.

## Next evidence to collect (if the investigation resumes)

The diagnostic generator wrote an isolated artifact to
`data/data_output/sharepoint-preview-spike.html`. It tests static content, script
execution, DOM/JSON initialization, graphics, browser APIs, and pinned CDN loading
independently. It contains no company artifact data or automatic telemetry.
Compare local-browser results with the same file in SharePoint preview.
This is a research probe, not a generator behavior change.
Keep actual-artifact diagnostic generation reproducible from ordinary generated HTML
without changing chapter data or authored generation settings. Its error banner
must not intercept artifact controls.

The user reports seeing JavaScript-calculated abstract numbers in the old trace
preview. Treat this as evidence against assuming blanket script blocking. Establish
whether the exact uploaded file computes those numbers on opening or stores them
in its saved markup. Prioritize a selective script/API/asset/initialization failure
comparison before proposing an HTML-first redesign.

- Compare the exact working old trace file and current file in the same library,
  browser, and opening method; record whether links open a preview frame, raw
  document, or download.
- Determine which old-artifact actions actually work: chapter switching, filtering,
  editing, and Sankey rendering. Visible text alone is not proof scripts execute.
- Inspect browser console/network errors and response headers, including CSP and
  iframe sandbox restrictions, without uploading company artifacts elsewhere.
- Use a tiny approved probe in the same tenant to test static text, embedded
  styling/images/SVG, inline JavaScript, and version-pinned external JavaScript
  separately. No tenant configuration changes are needed for this diagnosis.
- Only then select static preview, PDF companion, or approved interactive hosting.
