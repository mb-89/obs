(() => {
    const archive = document.getElementById("obs-source-archive");
    if (!archive) return;
    document.querySelector("[data-source-exports]").hidden = false;
    const filename = "obs-html-source.zip";
    const status = (message, failed = false) => {
        const target = document.querySelector("[data-archive-status]") ||
            document.querySelector("[data-export-status]");
        target.textContent = message;
        target.hidden = false;
        if (failed) console.error(message);
    };
    const bytes = () => globalThis.obsPayload ? globalThis.obsPayload.bytes() :
        Uint8Array.from(atob(archive.textContent.trim()), char => char.charCodeAt(0));
    const attach = async (source) => {
        const {PDFDocument, PDFName, PDFDict, PDFArray, PDFSignature} = globalThis.PDFLib;
        const pdf = await PDFDocument.load(source);
        if (pdf.catalog.has(PDFName.of("Perms")) ||
            pdf.getForm().getFields().some(field => field instanceof PDFSignature)) {
            throw new Error("Signed PDFs cannot be modified.");
        }
        const names = pdf.catalog.lookupMaybe(PDFName.of("Names"), PDFDict);
        const files = names?.lookupMaybe(PDFName.of("EmbeddedFiles"), PDFDict);
        const hasName = (tree) => {
            const entries = tree.lookupMaybe(PDFName.of("Names"), PDFArray);
            if (entries) {
                for (let index = 0; index < entries.size(); index += 2) {
                    if (entries.lookup(index).decodeText() === filename) return true;
                }
            }
            const children = tree.lookupMaybe(PDFName.of("Kids"), PDFArray);
            return children ? children.asArray().some(child => hasName(pdf.context.lookup(child, PDFDict))) : false;
        };
        if (files && hasName(files)) throw new Error(`PDF already contains ${filename}.`);
        await pdf.attach(await bytes(), filename, {
            mimeType: "application/zip", description: "Source inputs and generator for this document",
            afRelationship: globalThis.PDFLib.AFRelationship.Source,
        });
        return pdf.save();
    };
    let busy = false;
    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = ".pdf,application/pdf";
    picker.hidden = true;
    picker.dataset.transientView = "";
    document.body.append(picker);
    document.addEventListener("click", (event) => {
        if (!event.target.closest("[data-source-attach]") || busy) return;
        event.preventDefault();
        picker.value = "";
        picker.click();
    });
    picker.addEventListener("change", async () => {
        const file = picker.files[0];
        if (!file || busy) return;
        busy = true;
        let url;
        try {
            const result = await attach(await file.arrayBuffer());
            url = URL.createObjectURL(new Blob([result], {type: "application/pdf"}));
            const link = document.createElement("a");
            link.href = url;
            link.download = `${file.name.replace(/\.pdf$/i, "")}-with-source.pdf`;
            document.body.append(link);
            link.click();
            link.remove();
            status("PDF with source ZIP downloaded.");
        } catch (error) {
            status(`Could not attach source ZIP: ${error.message}`, true);
        } finally {
            if (url) setTimeout(() => URL.revokeObjectURL(url), 60000);
            busy = false;
        }
    });
    globalThis.obsArchive = {attach};
})();
