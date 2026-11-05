(() => {
    const inertType = "application/x-obs-html-script";
    const fail = (error) => {
        const message = document.createElement("p");
        message.id = "artifact-initialization-error";
        message.setAttribute("role", "alert");
        message.textContent = `HTML could not be opened: ${error.message}`;
        document.querySelector("[data-chapter-body]")?.replaceChildren(message);
        if (!message.isConnected || message.closest("[inert]")) document.body.prepend(message);
        document.documentElement.dataset.artifactStatus = "error";
    };
    const streamBytes = async (bytes, Stream) => {
        const source = new ReadableStream({
            start(controller) { controller.enqueue(bytes); controller.close(); },
        });
        return new Uint8Array(await new Response(source.pipeThrough(new Stream("gzip"))).arrayBuffer());
    };
    const escapeJson = (text) => text.replace(/</g, "\\u003c");
    const encode = async (serialized, compression) => {
        if (!["gzip", "none"].includes(compression)) throw new Error("Unsupported document data compression.");
        const text = escapeJson(JSON.stringify(JSON.parse(serialized)));
        if (compression === "none") return {text, type: "application/json"};
        if (typeof CompressionStream === "undefined") throw new Error("Gzip HTML saving is not supported by this browser.");
        const raw = new TextEncoder().encode(text);
        const bytes = await streamBytes(raw, CompressionStream);
        let binary = "";
        for (let offset = 0; offset < bytes.length; offset += 32768) {
            binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
        }
        const encoded = btoa(binary);
        const overhead = "application/octet-stream".length - "application/json".length +
            ' data-encoding="gzip"'.length;
        return encoded.length + overhead < raw.length
            ? {text: encoded, type: "application/octet-stream", encoding: "gzip"}
            : {text, type: "application/json"};
    };
    const writeIsland = async (island, serialized) => {
        const encoded = await encode(serialized, island.dataset.compression || "none");
        island.textContent = encoded.text;
        island.type = encoded.type;
        if (encoded.encoding) island.dataset.encoding = encoded.encoding;
        else delete island.dataset.encoding;
    };
    const restoreScripts = (root) => root.querySelectorAll("script[data-obs-runtime]").forEach((script) => {
        script.type = inertType;
    });
    const work = [];
    let opening = true;
    const paint = () => new Promise(resolve =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)));
    globalThis.obsStartup = Object.freeze({
        yield: paint,
        defer(label, run) {
            if (opening) work.push({label, run});
            else paint().then(run).catch(fail);
        },
    });
    const parsed = document.readyState === "loading"
        ? new Promise((resolve) => document.addEventListener("DOMContentLoaded", resolve, {once: true}))
        : Promise.resolve();
    const dataReady = parsed.then(async () => {
        document.documentElement.dataset.artifactStatus = "loading";
        document.querySelector(".app-shell")?.setAttribute("inert", "");
        document.querySelector("[data-menu-button]")?.setAttribute("disabled", "");
        await paint();
        const island = document.querySelector("[data-artifact-data]");
        if (!island) throw new Error("Canonical artifact data is missing.");
        let text = island.textContent;
        if (island.dataset.encoding === "gzip") {
            if (island.type !== "application/octet-stream") throw new Error("Invalid gzip artifact data type.");
            if (typeof DecompressionStream === "undefined") throw new Error("Gzip HTML opening is not supported by this browser.");
            const binary = atob(text.replace(/\s/g, ""));
            const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
            text = new TextDecoder("utf-8", {fatal: true}).decode(await streamBytes(bytes, DecompressionStream));
        } else if (island.dataset.encoding || island.type !== "application/json") {
            throw new Error("Unsupported artifact data encoding.");
        }
        const data = JSON.parse(text);
        if (!data || typeof data !== "object" || Array.isArray(data) ||
                !Array.isArray(data.notes) || !Array.isArray(data.toc)) {
            throw new Error("Invalid canonical artifact model.");
        }
        island.textContent = escapeJson(text);
        island.type = "application/json";
        delete island.dataset.encoding;
        return data;
    });
    globalThis.obsArtifactTransport = Object.freeze({encode, writeIsland, restoreScripts});
    globalThis.obsHtmlDataReady = dataReady;
    globalThis.obsHtmlReady = dataReady.then(async () => {
        for (const original of document.querySelectorAll(`script[type="${inertType}"]`)) {
            await paint();
            const script = document.createElement("script");
            for (const {name, value} of original.attributes) {
                if (name !== "type") script.setAttribute(name, value);
            }
            script.textContent = original.textContent;
            const loaded = script.src ? new Promise((resolve, reject) => {
                script.onload = resolve;
                // Optional network runtimes (CDN Plotly) degrade to their own notices.
                script.onerror = () => script.hasAttribute("data-optional-runtime")
                    ? resolve()
                    : reject(new Error(`Runtime could not be loaded: ${script.id}`));
            }) : null;
            let failure;
            const scriptError = (event) => { failure = event.error || new Error(event.message); };
            globalThis.addEventListener("error", scriptError);
            try {
                original.replaceWith(script);
            } finally {
                globalThis.removeEventListener("error", scriptError);
            }
            if (failure) throw failure;
            if (loaded) await loaded;
        }
        const selected = document.querySelector('meta[name="obs-trusted-runtime"]')?.content || "";
        globalThis.obsArtifact?.validateApplicationRuntime?.(selected);
        document.querySelector(".app-shell")?.removeAttribute("inert");
        document.querySelector("[data-menu-button]")?.removeAttribute("disabled");
        document.dispatchEvent(new CustomEvent("obs-html-interactive"));
        for (const task of work) {
            await paint();
            await task.run();
        }
        opening = false;
        document.documentElement.dataset.artifactStatus = "ready";
        document.dispatchEvent(new CustomEvent("obs-html-ready"));
    });
    globalThis.obsHtmlReady.catch(fail);
})();
