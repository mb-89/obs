(() => {
    const input = document.querySelector("[data-search-input]");
    const status = document.querySelector("[data-search-status]");
    const results = document.querySelector("[data-search-results]");
    const renderLimit = 200;
    let activeQuery = globalThis.obsQuery.compile("");
    let hits = [];
    let current = -1;

    const metadataRanges = (query, field, value) => query.ranges(field, "").length
        + query.ranges(value, [field.toLocaleLowerCase(), `frontmatter.${field.toLocaleLowerCase()}`]).length;

    const textExcerpt = (text, query) => {
        const first = query.ranges(text, "text")[0]?.[0] || 0;
        const start = Math.max(0, first - 55);
        const value = text.slice(start, start + 180).trim();
        return `${start > 0 ? "..." : ""}${value}${start + 180 < text.length ? "..." : ""}`;
    };

    const excerpt = (hit, query) => {
        if (hit.kind === "row") {
            const text = hit.text.all;
            return query.ranges(text, "text").length ? textExcerpt(text, query) : hit.text.label;
        }
        const record = hit.chapter;
        const metadataMatch = record.metadataEntries.find(([field, value]) =>
            metadataRanges(query, field, value));
        if (metadataMatch) return `${metadataMatch[0]}: ${metadataMatch[1]}`;
        return textExcerpt(record.text, query);
    };

    const title = (hit) => hit.kind === "row"
        ? `${hit.chapter.title} \u203a ${hit.tableName || "Table"} \u203a ${hit.text.label}`
        : hit.chapter.title;

    const search = () => {
        let query;
        try {
            query = globalThis.obsQuery.compile(input.value);
        } catch (error) {
            status.textContent = error.message;
            return;
        }
        activeQuery = query;
        current = -1;
        results.replaceChildren();
        if (query.empty) {
            hits = [];
            status.textContent = "Type to search.";
            return;
        }
        hits = globalThis.obsArtifact.searchHits().filter((hit) => query.match(hit.target));
        status.textContent = `${hits.length} result${hits.length === 1 ? "" : "s"}`
            + (hits.length > renderLimit ? `; first ${renderLimit} listed.` : ".");
        hits.slice(0, renderLimit).forEach((hit, index) => {
            const item = document.createElement("li");
            const link = document.createElement("a");
            link.href = `#${hit.slug}`;
            link.dataset.searchResult = hit.slug;
            link.dataset.searchHit = String(index);
            link.textContent = title(hit);
            const summary = document.createElement("p");
            summary.textContent = excerpt(hit, query);
            item.append(link, summary);
            results.append(item);
        });
    };

    const reveal = async (index) => {
        const hit = hits[index];
        if (!hit) return false;
        current = index;
        status.textContent = `${index + 1} of ${hits.length} results.`;
        results.querySelectorAll("[aria-current]").forEach(link => link.removeAttribute("aria-current"));
        const link = results.querySelector(`[data-search-hit="${index}"]`);
        link?.setAttribute("aria-current", "true");
        link?.scrollIntoView({block: "nearest"});
        return globalThis.obsArtifact.activateSearchResult(hit.slug, activeQuery, hit);
    };

    const bar = input.closest("[data-bar]");
    const isOpen = () => globalThis.obsArtifact.isBarOpen("search");
    const openSearch = () => {
        globalThis.obsArtifact.openBar("search");
        input.focus();
        input.select();
    };
    const closeSearch = () => {
        globalThis.obsArtifact.closeBar("search");
        if (!bar?.contains(document.activeElement)) return;
        document.querySelector(".chapter-scroll")?.focus({preventScroll: true});
    };
    const step = async (direction) => {
        if (!hits.length) return openSearch();
        const count = hits.length;
        const keepFocus = document.activeElement === input;
        const revealed = await reveal(current < 0 ? (direction > 0 ? 0 : count - 1)
            : (current + direction + count) % count);
        if (keepFocus && isOpen()) input.focus({preventScroll: true});
        return revealed;
    };
    document.addEventListener("keydown", (event) => {
        if (event.defaultPrevented || event.altKey) return;
        const key = event.key.toLowerCase();
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && key === "f") {
            event.preventDefault();
            if (isOpen() && document.activeElement === input) closeSearch();
            else openSearch();
        } else if (event.key === "F3" && !event.ctrlKey && !event.metaKey) {
            event.preventDefault();
            step(event.shiftKey ? -1 : 1);
        } else if (event.key === "Escape" && isOpen() &&
                (bar?.contains(event.target) || !event.target.closest?.(
                    "input, textarea, select, [contenteditable], [role=menu], [role=dialog], details[open], .dock-bar"))) {
            if (bar?.contains(event.target)) event.preventDefault();
            closeSearch();
        }
    }, true);

    results.addEventListener("click", (event) => {
        const link = event.target.closest("[data-search-result]");
        if (!link) return;
        event.preventDefault();
        event.stopPropagation();
        reveal(Number(link.dataset.searchHit));
    });
    input.addEventListener("input", search);
    document.addEventListener("obs-artifact-filter", () => { if (!activeQuery.empty) search(); });
    globalThis.obsSearch = {reveal, step, get hits() { return hits; }, get current() { return current; }};
})();
