(() => {
    const input = document.querySelector("[data-theme-select]");
    const root = document.documentElement;
    const apply = (value) => {
        input.value = value;
        root.dataset.theme = value;
        globalThis.obsAssets.replace(document.querySelector("[data-theme-icon]"), `theme.${value}`);
    };

    apply(JSON.parse(document.querySelector("[data-report-data]").textContent).reading.theme);
    input.addEventListener("change", () => apply(input.value));
    document.querySelector("[data-pages-toggle]").addEventListener("change", (event) => {
        globalThis.obsPages.setPaged(event.target.checked);
    });
    document.querySelector("[data-export-pdf]").addEventListener("click", async () => {
        const message = document.querySelector("[data-export-status]");
        message.hidden = true;
        try {
            await globalThis.obsPages.exportPDF();
        } catch (error) {
            message.textContent = `PDF export failed: ${error.message}`;
            message.hidden = false;
            console.error(message.textContent);
        }
    });
})();
