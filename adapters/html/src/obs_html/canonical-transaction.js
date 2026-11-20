((root, factory) => {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    root.ObsHtmlCanonicalTransaction = api;
})(typeof globalThis === "undefined" ? this : globalThis, () => {
    "use strict";

    const createCanonicalTransaction = ({revision, stage, commit}) => {
        if (typeof revision !== "function" || typeof stage !== "function" ||
                typeof commit !== "function") {
            throw new TypeError("Canonical transaction requires revision, stage, and commit owners.");
        }

        const stageCandidate = async ({expectedRevision, notes, assetChanges, sourceChanges = []}) => {
            if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 0 ||
                    !Array.isArray(notes) || !Array.isArray(assetChanges) || !Array.isArray(sourceChanges)) {
                throw new Error("Invalid canonical transaction candidate.");
            }
            if (revision() !== expectedRevision) {
                throw new Error("Canonical transaction revision conflict before staging.");
            }
            const candidate = await stage({expectedRevision, notes, assetChanges, sourceChanges});
            if (revision() !== expectedRevision) {
                throw new Error("Canonical transaction revision conflict during staging.");
            }
            let committed = false;
            return Object.freeze({
                commit() {
                    if (committed) throw new Error("Canonical transaction was already committed.");
                    if (revision() !== expectedRevision) {
                        throw new Error("Canonical transaction revision conflict at commit.");
                    }
                    commit(candidate);
                    committed = true;
                },
            });
        };

        return Object.freeze({stage: stageCandidate});
    };

    return Object.freeze({createCanonicalTransaction});
});
