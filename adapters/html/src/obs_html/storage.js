(() => {
    const showWarning = (setting) => {
        const warning = document.getElementById(`storage-warning-${setting}`);
        if (warning) warning.hidden = false;
    };
    globalThis.obsStorage = Object.freeze({
        read(key, setting) {
            try {
                return localStorage.getItem(key);
            } catch {
                showWarning(setting);
                return null;
            }
        },
        write(key, value, setting) {
            try {
                localStorage.setItem(key, value);
                return true;
            } catch {
                showWarning(setting);
                return false;
            }
        },
    });
})();
