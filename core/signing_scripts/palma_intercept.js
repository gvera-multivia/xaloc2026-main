() => {
    if (window.__xaloc_afirma_interceptor_installed) return;
    window.__xaloc_afirma_interceptor_installed = true;
    const blockExternalLaunch = __BLOCK_EXTERNAL_LAUNCH__;

    window.__afirma_url = window.__afirma_url || null;
    window.__afirma_source = window.__afirma_source || null;

    const captureAfirma = (url, source) => {
        if (typeof url !== 'string') return false;
        if (!/^(afirma|xalocafirma):\/\//i.test(url)) return false;
        window.__afirma_url = url;
        window.__afirma_source = source || 'unknown';
        console.debug('[xaloc] afirma:// capturado via', window.__afirma_source, url.substring(0, 120));
        return true;
    };

    // Capture window.open('afirma://...')
    const _origOpen = window.open.bind(window);
    window.open = function(url, ...rest) {
        const captured = captureAfirma(url, 'window.open');
        if (captured && blockExternalLaunch) return null;
        return _origOpen(url, ...rest);
    };

    const captureFromAttr = (value, source) => {
        try { return captureAfirma(value, source); } catch(_e) {}
        return false;
    };

    // Capture navigation APIs that often emit afirma:// in Sedipualba.
    try {
        const _origAssign = window.location.assign.bind(window.location);
        window.location.assign = function(url) {
            const captured = captureAfirma(url, 'location.assign');
            if (captured && blockExternalLaunch) return;
            return _origAssign(url);
        };
    } catch(e) {
        // ignore
    }
    try {
        const _origReplace = window.location.replace.bind(window.location);
        window.location.replace = function(url) {
            const captured = captureAfirma(url, 'location.replace');
            if (captured && blockExternalLaunch) return;
            return _origReplace(url);
        };
    } catch(e) {
        // ignore
    }
    try {
        const hrefDesc = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
        if (hrefDesc && hrefDesc.set && hrefDesc.get) {
            Object.defineProperty(Location.prototype, 'href', {
                configurable: true,
                enumerable: hrefDesc.enumerable,
                get: function() { return hrefDesc.get.call(this); },
                set: function(url) {
                    const captured = captureAfirma(url, 'location.href');
                    if (captured && blockExternalLaunch) return;
                    return hrefDesc.set.call(this, url);
                }
            });
        }
    } catch(e) {
        // ignore
    }

    // Capture clicks on <a href="afirma://...">.
    document.addEventListener('click', function(ev) {
        const el = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
        if (el) {
            const href = el.href || el.getAttribute('href') || '';
            const captured = captureAfirma(href, 'anchor-click-capture');
            if (captured && blockExternalLaunch) {
                try { ev.preventDefault(); } catch(_e) {}
                try { ev.stopPropagation(); } catch(_e) {}
                try { ev.stopImmediatePropagation(); } catch(_e) {}
            }
        }
    }, true);

    // Capture programmatic HTMLAnchorElement.click().
    try {
        const _origAnchorClick = HTMLAnchorElement.prototype.click;
        HTMLAnchorElement.prototype.click = function(...args) {
            const href = this.href || this.getAttribute('href') || '';
            const captured = captureAfirma(href, 'anchor-prototype-click');
            if (captured && blockExternalLaunch) return;
            return _origAnchorClick.apply(this, args);
        };
    } catch(e) {
        // ignore
    }

    // Capture setAttribute('href'|'src'|'action', 'afirma://...').
    try {
        const _origSetAttr = Element.prototype.setAttribute;
        Element.prototype.setAttribute = function(name, value) {
            const key = String(name || '').toLowerCase();
            if (key === 'href' || key === 'src' || key === 'action') {
                const captured = captureFromAttr(value, `setAttribute:${key}`);
                if (captured && blockExternalLaunch) return;
            }
            return _origSetAttr.call(this, name, value);
        };
    } catch(e) {
        // ignore
    }

    // Capture submit actions that can carry afirma:// in form.action.
    try {
        const _origFormSubmit = HTMLFormElement.prototype.submit;
        HTMLFormElement.prototype.submit = function(...args) {
            let captured = false;
            try { captured = captureFromAttr(this && this.action, 'form.submit.action'); } catch(_e) {}
            if (captured && blockExternalLaunch) return;
            return _origFormSubmit.apply(this, args);
        };
    } catch(e) {
        // ignore
    }

    // requestSubmit can trigger action navigation without calling submit() in some flows.
    try {
        const _origRequestSubmit = HTMLFormElement.prototype.requestSubmit;
        HTMLFormElement.prototype.requestSubmit = function(...args) {
            let captured = false;
            try { captured = captureFromAttr(this && this.action, 'form.requestSubmit.action'); } catch(_e) {}
            if (captured && blockExternalLaunch) return;
            return _origRequestSubmit.apply(this, args);
        };
    } catch(e) {
        // ignore
    }

    // Capture synthetic dispatches where target/action can contain afirma://
    try {
        const _origDispatch = EventTarget.prototype.dispatchEvent;
        EventTarget.prototype.dispatchEvent = function(ev) {
            try {
                const self = this || null;
                const target = (ev && ev.target) || self;
                captureFromAttr(self && self.href, 'dispatchEvent:self.href');
                captureFromAttr(self && self.src, 'dispatchEvent:self.src');
                captureFromAttr(self && self.action, 'dispatchEvent:self.action');
                captureFromAttr(target && target.href, 'dispatchEvent:target.href');
                captureFromAttr(target && target.src, 'dispatchEvent:target.src');
                captureFromAttr(target && target.action, 'dispatchEvent:target.action');
            } catch(_e) {}
            return _origDispatch.call(this, ev);
        };
    } catch(e) {
        // ignore
    }

    // Capture direct invocation patterns that may bypass click handlers.
    try {
        const _origSetTimeout = window.setTimeout.bind(window);
        window.setTimeout = function(fn, delay, ...rest) {
            if (typeof fn === 'string' && /(afirma|xalocafirma):\/\//i.test(fn)) {
                const m = fn.match(/(?:afirma|xalocafirma):\/\/[^'"\s)]+/i);
                if (m && m[0]) {
                    captureAfirma(m[0], 'setTimeout-string');
                }
            }
            return _origSetTimeout(fn, delay, ...rest);
        };
    } catch(e) {
        // ignore
    }
}
