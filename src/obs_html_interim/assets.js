/* Presentation only: actions and accessible names remain with their consumers. */
(() => {
    const model = JSON.parse(document.querySelector("[data-artifact-data]").textContent);
    const catalog = model.assets;
    const entry = name => {
        if (!catalog || !Object.hasOwn(catalog, name)) throw new Error(`Unknown semantic asset: ${name}`);
        let value = catalog[name];
        while (value.ref) value = catalog[value.ref];
        return value;
    };
    const color = name => {
        if (entry(name).type !== "color") throw new Error(`Expected color asset: ${name}`);
        return `var(--asset-${[...new TextEncoder().encode(name)].map(
            byte => byte.toString(16).padStart(2, "0")).join("")})`;
    };
    const icon = (name, state) => {
        const resource = entry(name);
        if (resource.type === "icon") return resource.value;
        if (resource.type !== "appearance") throw new Error(`Expected icon appearance: ${name}`);
        const selected = state ?? resource.defaultState;
        if (resource.states && !Object.hasOwn(resource.states, selected)) {
            throw new Error(`Semantic asset ${name}: unknown or missing state=${selected}`);
        }
        const fields = {...resource, ...resource.states?.[selected]};
        if (!fields.icon) throw new Error(`Semantic asset ${name}: state=${selected}: missing icon`);
        return {...entry(fields.icon).value, ...(fields.color ? {color: fields.color} : {})};
    };
    const set = (element, name, state) => {
        const definition = icon(name, state);
        element.classList.add("resource-icon");
        element.classList.toggle("resource-icon--monochrome", Boolean(definition.monochrome));
        element.style.removeProperty("--resource-icon-mask");
        element.dataset.icon = name;
        const selected = state ?? entry(name).defaultState;
        if (selected !== undefined) element.dataset.iconState = selected;
        else delete element.dataset.iconState;
        element.setAttribute("aria-hidden", "true");
        if (definition.color) element.style.color = color(definition.color);
        else element.style.removeProperty("color");
        if (Object.hasOwn(definition, "glyph")) element.textContent = definition.glyph;
        else {
            const image = document.createElement("img");
            image.alt = "";
            image.dataset.iconAsset = definition.asset;
            const projectMask = () => {
                if (definition.monochrome && image.parentElement === element && image.hasAttribute("src")) {
                    element.style.setProperty("--resource-icon-mask", `url(${JSON.stringify(image.src)})`);
                }
            };
            if (definition.monochrome) image.addEventListener("load", projectMask, {once: true});
            element.replaceChildren(image);
            const key = definition.asset.slice("obs-asset:".length);
            const asset = model.embeddedAssets?.[key];
            if (typeof asset === "string") image.src = asset;
            else if (asset && globalThis.obsPayload) globalThis.obsPayload.activate(image, "src", key, asset);
            else throw new Error(`Missing icon asset: ${name}`);
            projectMask();
        }
        return element;
    };
    const create = (name, state) => set(document.createElement("span"), name, state);
    const append = (control, name, state) => {
        control.append(create(name, state));
        return control;
    };
    const replace = (control, name, state) => {
        control.replaceChildren(create(name, state));
        return control;
    };
    const hydrate = root => {
        const icons = [...root.querySelectorAll("[data-icon]")];
        if (root.matches?.("[data-icon]")) icons.unshift(root);
        icons.filter(element => icon(element.dataset.icon, element.dataset.iconState).asset)
            .forEach(element => set(element, element.dataset.icon, element.dataset.iconState));
    };
    const restore = root => root.querySelectorAll("[data-icon]").forEach(element => {
        const definition = icon(element.dataset.icon, element.dataset.iconState);
        if (!definition.asset) return;
        element.style.removeProperty("--resource-icon-mask");
        const image = element.querySelector("img");
        if (image) {
            image.removeAttribute("src");
            image.dataset.iconAsset = definition.asset;
        }
    });
    globalThis.obsAssets = Object.freeze({create, set, append, replace, entry, icon, color, hydrate, restore});
    hydrate(document);
})();
