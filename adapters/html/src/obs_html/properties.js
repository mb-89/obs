(() => {
    "use strict";
    const editors = () => document.querySelectorAll("[data-property-editor]");
    const refresh = () => editors().forEach(editor => {
        const note = globalThis.obsArtifact.records.find(record => record.slug === editor.dataset.propertyNote);
        if (note && note.editableProperties?.[editor.dataset.propertyField]) {
            editor.value = note.frontmatter[editor.dataset.propertyField];
            if (editor.hasAttribute("data-property-single-line")) {
                editor.dataset.propertyOriginalDisplay = editor.value;
            }
        }
    });
    document.addEventListener("change", event => {
        const editor = event.target.closest?.("[data-property-editor]");
        if (!editor) return;
        if (editor.hasAttribute("data-property-single-line") &&
                editor.value === editor.dataset.propertyOriginalDisplay) return;
        try {
            globalThis.obsArtifact.commitProperty(editor.dataset.propertyNote, editor.dataset.propertyField, editor.value);
            editor.setCustomValidity("");
        } catch (error) {
            editor.setCustomValidity(error.message);
            editor.reportValidity();
        }
    });
    document.addEventListener("keydown", event => {
        if (event.target.matches?.("[data-property-editor]") && event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.target.blur();
        }
    });
    document.addEventListener("obs-canonical-property-change", refresh);
    new MutationObserver(mutations => {
        if (mutations.some(mutation => [...mutation.addedNodes].some(node => node.nodeType === 1 &&
            (node.matches("[data-property-editor]") || node.querySelector("[data-property-editor]"))))) refresh();
    }).observe(document.body, {childList: true, subtree: true});
    refresh();
})();
