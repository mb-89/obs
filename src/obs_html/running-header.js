(() => {
    const text = value => Array.isArray(value) ? value.join(", ") : value || "";
    const content = (metadata, slug = "home", section = "") => [
        [metadata.product?.name, metadata["document type"]].filter(Boolean).join(" · "),
        text(slug === "home" ? metadata.confidentiality : section),
    ];
    const snapshot = (root, metadata) => {
        root.querySelector("#running-header-script").dataset.headerMetadata = JSON.stringify(metadata);
    };
    globalThis.obsRunningHeader = Object.freeze({content, snapshot});

    const metadata = JSON.parse(document.querySelector("#running-header-script").dataset.headerMetadata);
    const opening = document.createElement("div");
    opening.className = "reader-opening";
    const header = document.createElement("header");
    header.className = "paper-header";
    content(metadata).filter(value => String(value).trim()).forEach(value => {
        const line = document.createElement("span");
        line.textContent = value;
        header.append(line);
    });
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    status.setAttribute("aria-busy", "true");
    status.textContent = "Opening HTML…";
    opening.append(header, status);
    document.querySelector("[data-chapter-body]").replaceChildren(opening);
})();
