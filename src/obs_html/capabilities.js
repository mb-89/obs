// Canaries: probe, before any feature runs, what the host lets this HTML do.
// One registry entry per browser capability; adding a capability is one entry.
// A probe returns true (allowed), false (refused) or undefined (unknown); unknown counts as limited.
(() => {
    const view = globalThis.window || globalThis;
    // The sandbox tokens of every frame up to the top, intersected: null outside any sandbox,
    // undefined where a frame hides its permissions (a cross-origin or sandboxed host).
    const sandbox = (() => {
        let tokens = null;
        let current = view;
        while (current.top && current !== current.top) {
            const frame = current.frameElement;
            if (!frame) return undefined;
            if (frame.hasAttribute("sandbox")) {
                const own = frame.getAttribute("sandbox").toLowerCase().split(/\s+/).filter(Boolean);
                tokens = tokens ? new Set(own.filter((token) => tokens.has(token))) : new Set(own);
            }
            current = current.parent;
        }
        return tokens;
    })();
    const sandboxAllows = (token) => sandbox === null ? true : sandbox?.has(token);
    const registry = [
        {
            key: "history", feature: "Chapter addresses",
            blocks: "address changes, so the address bar and browser Back do not follow chapters",
            remedy: "Open the HTML file directly in a browser to use chapter addresses and Back.",
            probe() {
                const address = view.location.href;
                view.history.replaceState(view.history.state, "", "#obs-capability-canary");
                view.history.replaceState(view.history.state, "", address);
                return true;
            },
        },
        {
            key: "storage", feature: "Saved settings",
            blocks: "browser storage, so reader settings are not kept",
            remedy: "Open the HTML file directly in a browser to keep reader settings.",
            probe() {
                const key = "obs-capability-canary";
                view.localStorage.setItem(key, "1");
                view.localStorage.removeItem(key);
                return true;
            },
        },
        {
            key: "printing", feature: "Print to PDF",
            blocks: "the print dialog",
            remedy: "Open the HTML file directly in a browser to print.",
            probe: () => sandboxAllows("allow-modals"),
        },
        {
            key: "dialogs", feature: "Dialogs",
            blocks: "browser dialogs, so messages appear in the page instead",
            remedy: "Open the HTML file directly in a browser for browser dialogs.",
            probe: () => sandboxAllows("allow-modals"),
        },
        {
            key: "downloads", feature: "Downloads",
            blocks: "downloads, so Download HTML, the source archive and attachments may not save",
            remedy: "Open the HTML file directly in a browser to download.",
            probe: () => sandboxAllows("allow-downloads"),
        },
        {
            key: "clipboard", feature: "Clipboard",
            blocks: "clipboard access, so Copy comments cannot copy",
            remedy: "Open the HTML file directly in a browser to copy comments.",
            probe() {
                if (typeof view.navigator?.clipboard?.writeText !== "function") return false;
                const policy = view.document.permissionsPolicy || view.document.featurePolicy;
                return policy ? policy.allowsFeature("clipboard-write") : view === view.top || undefined;
            },
        },
        {
            key: "popups", feature: "Separate windows",
            blocks: "new windows, so guided cards open inside the page",
            remedy: "Open the HTML file directly in a browser to open cards in their own window.",
            probe: () => sandboxAllows("allow-popups"),
        },
    ];
    const limits = registry.flatMap(({key, feature, blocks, remedy, probe}) => {
        let allowed;
        try {
            allowed = probe();
        } catch {
            allowed = false;
        }
        if (allowed === true) return [];
        const reason = allowed === false
            ? `The page showing this HTML blocks ${blocks}.`
            : `The page showing this HTML may block ${blocks}; this HTML cannot check.`;
        return [Object.freeze({key, feature, reason, remedy, refused: allowed === false})];
    });
    const limit = (key) => limits.find((entry) => entry.key === key) || null;
    globalThis.obsCapabilities = Object.freeze({
        limits: Object.freeze(limits),
        limit,
        // The message a degraded control shows inline when used, or "" where the feature is allowed.
        explain(key) {
            const entry = limit(key);
            return entry ? `${entry.feature} is limited here: ${entry.reason} ${entry.remedy}` : "";
        },
    });

})();
