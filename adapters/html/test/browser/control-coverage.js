// The control-coverage sweep: a function expression that Playwright evaluates inside an opened
// artifact (this adapter's or the interim reference's), used by test/test_parity_browser.py.
//
// For the given views and bar layouts it opens every chapter and finds every visible
// interactive control (links, buttons, inputs, selects, summaries and ARIA buttons, links,
// checkboxes, switches and tabs). A control is fine when `document.elementFromPoint` at the
// centre of one of its visible parts returns the control, one of its descendants or its label, either
// where it stands or once scrolled to the middle of its scroller (horizontally only as far as
// needed, as a reader would scroll). Anything else is a fault naming the control and what lies
// over it. A control covered where it stands but uncovered once scrolled is not a fault: the
// reader reaches it, as with any scrolled content.
//
// One exception, from obs's artifact-ui.md: on narrow screens an open bar overlays the reader on
// purpose, so a reader control the bar overlays, even in part, is hidden, not covered. The
// chapter controls (previous and next) are not exempt: they stay reachable.
//
// Argument: {views: ["pages", "continuous"], layouts: [null | [bar, direction], ...],
// firstChapterLayouts: [...]}; the latter run on the first chapter only. Returns a list of
// {view, layout, chapter, controls, faults: [{control, covering}]}.
async (_, {views, layouts, firstChapterLayouts}) => {
    const CONTROLS = 'a[href], button, input:not([type="hidden"]), select, textarea, summary, ' +
        '[role="button"], [role="link"], [role="checkbox"], [role="switch"], [role="tab"], ' +
        '[contenteditable="true"]';
    const OWNERS = `${CONTROLS}, [data-dock-resize], [data-bar], [data-dock-region], .chapter-nav-zone`;

    const name = (element) => {
        const text = (element.getAttribute("aria-label") || element.getAttribute("title") ||
            element.textContent || element.getAttribute("placeholder") || "")
            .trim().replace(/\s+/g, " ").slice(0, 40);
        const kind = element.tagName.toLowerCase() + (element.classList[0] ? `.${element.classList[0]}` : "");
        return text ? `${kind} "${text}"` : kind;
    };
    const box = (element) => [...element.getClientRects()].find((rect) => rect.width >= 2 && rect.height >= 2);
    const shown = (element) => element.checkVisibility({visibilityProperty: true}) && Boolean(box(element));

    // The visible parts of a control, largest first: each of its boxes (a wrapped link has one
    // per line) cut by the viewport and by every ancestor that clips its overflow. Their centres
    // are where a reader points.
    const seen = (element) => {
        const clips = [{left: 0, top: 0, right: innerWidth, bottom: innerHeight}];
        for (let parent = element.parentElement; parent; parent = parent.parentElement) {
            const style = getComputedStyle(parent);
            if (style.overflowX !== "visible" || style.overflowY !== "visible") clips.push(parent.getBoundingClientRect());
            if (style.position === "fixed") break;
        }
        const parts = [];
        for (const rect of element.getClientRects()) {
            if (rect.width < 2 || rect.height < 2) continue;
            const left = Math.max(rect.left, ...clips.map((clip) => clip.left));
            const top = Math.max(rect.top, ...clips.map((clip) => clip.top));
            const right = Math.min(rect.right, ...clips.map((clip) => clip.right));
            const bottom = Math.min(rect.bottom, ...clips.map((clip) => clip.bottom));
            if (right - left < 1 || bottom - top < 1) continue;
            parts.push({
                area: (right - left) * (bottom - top), x: (left + right) / 2, y: (top + bottom) / 2,
                whole: left === rect.left && top === rect.top && right === rect.right && bottom === rect.bottom,
            });
        }
        return parts.sort((one, other) => other.area - one.area);
    };

    // Whether an open bar overlays (part of) the control, as narrow screens do on purpose.
    const overlaid = (control) => [...document.querySelectorAll("[data-dock-region]")]
        .filter((region) => getComputedStyle(region).position === "fixed" && region.checkVisibility())
        .some((region) => {
            const bar = region.getBoundingClientRect(), own = control.getBoundingClientRect();
            return own.left < bar.right && own.right > bar.left && own.top < bar.bottom && own.bottom > bar.top;
        });

    // What lies over the control at that point; "" when the control (or its label) is on top.
    const covering = (control, spot) => {
        const hit = document.elementFromPoint(spot.x, spot.y);
        if (!hit) return "nothing: the point is outside the viewport";
        if (control.contains(hit) || [...(control.labels || [])].some((label) => label.contains(hit))) return "";
        if (control.closest(".reader-shell") && !control.matches("[data-step]") && overlaid(control)) return "";
        return name(hit.closest(OWNERS) || hit);
    };

    // A control is reachable when the reader can point at one of its visible parts.
    const check = () => {
        const controls = [...document.querySelectorAll(CONTROLS)].filter(shown);
        const pending = new Set(controls);
        const sweep = () => {
            for (const control of pending) {
                if (seen(control).some((part) => part.whole && !covering(control, part))) pending.delete(control);
            }
        };
        const faults = [];
        sweep();
        for (const control of controls) {
            if (!pending.has(control)) continue;
            control.scrollIntoView({block: "center", inline: "nearest", behavior: "instant"});
            const parts = seen(control);
            const over = parts.length ? parts.map((part) => covering(control, part)) : ["nothing: it cannot be scrolled into view"];
            pending.delete(control);
            if (over.every(Boolean)) faults.push({control: name(control), covering: over[0]});
            sweep();
        }
        return {controls: controls.length, faults};
    };

    const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const open = async (slug) => {
        await obsArtifact.activateChapter(slug);
        await obsArtifact.whenChapterReady();
        for (let wait = 0; wait < 200 && document.querySelector(".reader-pending"); wait++) {
            await new Promise((resolve) => setTimeout(resolve, 25));
        }
    };
    const chapters = [...document.querySelectorAll("[data-toc-tree] a")]
        .map((link) => link.getAttribute("href").slice(1)).filter((slug) => !slug.includes("/"));
    const results = [];
    for (const view of views) {
        obsPages.setPaged(view === "pages");
        for (const [index, chapter] of chapters.entries()) {
            await open(chapter);
            for (const layout of index ? layouts : [...layouts, ...firstChapterLayouts]) {
                if (layout) obsArtifact.openBar(...layout);
                await frame();
                results.push({view, layout, chapter, ...check()});
                if (layout) obsArtifact.closeBar(layout[0]);
            }
        }
    }
    return results;
}
