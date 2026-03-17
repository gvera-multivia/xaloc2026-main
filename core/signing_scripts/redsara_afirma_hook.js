(function(callbackName, blockExternalLaunch) {
    if (window.__xaloc_afirma_hooked) return;
    window.__xaloc_afirma_hooked = true;
    window.__afirma_url = window.__afirma_url || null;
    window.__afirma_source = window.__afirma_source || null;
    var shouldBlock = !!blockExternalLaunch;

    var isAfirma = function(s) {
        return s && /^(afirma|xalocafirma):\/\//i.test(String(s));
    };
    var capture = function(uri, source) {
        try { window.__afirma_url = String(uri); } catch(e) {}
        try { window.__afirma_source = String(source || 'unknown'); } catch(e) {}
        try { window[callbackName](String(uri)); } catch(e) {}
        return true;
    };
    var captureAttr = function(name, value, source) {
        var key = String(name || '').toLowerCase();
        if (key !== 'href' && key !== 'src' && key !== 'action') return false;
        if (!isAfirma(value)) return false;
        return capture(value, source || ('attr:' + key));
    };
    var wrapLocationProperty = function(target, source) {
        if (!target || target.__xalocLocationWrapped) return;
        try {
            var desc = Object.getOwnPropertyDescriptor(target, 'location');
            if (!desc || !desc.set) return;
            Object.defineProperty(target, 'location', {
                configurable: true,
                enumerable: !!desc.enumerable,
                get: function() {
                    if (desc.get) return desc.get.call(this);
                    return desc.value;
                },
                set: function(url) {
                    if (isAfirma(url)) {
                        capture(url, source);
                        if (shouldBlock) return;
                    }
                    return desc.set.call(this, url);
                }
            });
            target.__xalocLocationWrapped = true;
        } catch(e) {}
    };
    var wrapPropertySetter = function(proto, prop, source) {
        if (!proto) return;
        try {
            var desc = Object.getOwnPropertyDescriptor(proto, prop);
            if (!desc || !desc.set || proto['__xalocWrap_' + prop]) return;
            Object.defineProperty(proto, prop, {
                configurable: true,
                enumerable: !!desc.enumerable,
                get: function() {
                    if (desc.get) return desc.get.call(this);
                    return desc.value;
                },
                set: function(value) {
                    if (isAfirma(value)) {
                        capture(value, source);
                        if (shouldBlock) return;
                    }
                    return desc.set.call(this, value);
                }
            });
            proto['__xalocWrap_' + prop] = true;
        } catch(e) {}
    };

    // 1. HTMLElement.prototype.click - cubre la mayoria de implementaciones AutoScript
    var origClick = HTMLElement.prototype.click;
    HTMLElement.prototype.click = function() {
        var href = this.getAttribute ? this.getAttribute('href') : null;
        if (!href && this.href) href = this.href;
        if (isAfirma(href)) {
            capture(href, 'HTMLElement.click');
            if (shouldBlock) return;
        }
        return origClick.apply(this, arguments);
    };

    // 2. dispatchEvent - cubre AutoScript que usa new MouseEvent('click')
    var origDispatch = EventTarget.prototype.dispatchEvent;
    EventTarget.prototype.dispatchEvent = function(evt) {
        if (evt && evt.type === 'click') {
            var href = this.getAttribute ? this.getAttribute('href') : null;
            if (!href && this.href) href = this.href;
            if (isAfirma(href)) {
                capture(href, 'dispatchEvent:click');
                if (shouldBlock) return true;
            }
        }
        return origDispatch.apply(this, arguments);
    };

    // 3. Captura global de clicks en el documento (useCapture=true)
    document.addEventListener('click', function(e) {
        var el = e.target;
        while (el) {
            var href = el.getAttribute ? el.getAttribute('href') : null;
            if (!href && el.href) href = el.href;
            if (isAfirma(href)) {
                capture(href, 'document.click');
                if (shouldBlock) {
                    try { e.preventDefault(); } catch(_) {}
                    try { e.stopPropagation(); } catch(_) {}
                    try { e.stopImmediatePropagation(); } catch(_) {}
                }
                break;
            }
            el = el.parentElement;
        }
    }, true);

    // 4. window.open
    var origOpen = window.open;
    window.open = function(url) {
        if (isAfirma(url)) {
            capture(url, 'window.open');
            if (shouldBlock) return null;
        }
        return origOpen ? origOpen.apply(window, arguments) : null;
    };

    // 5. location.replace y location.assign
    try {
        var origReplace = location.replace.bind(location);
        location.replace = function(url) {
            if (isAfirma(url)) {
                capture(url, 'location.replace');
                if (shouldBlock) return;
            }
            return origReplace(url);
        };
    } catch(e) {}
    try {
        var origAssign = location.assign.bind(location);
        location.assign = function(url) {
            if (isAfirma(url)) {
                capture(url, 'location.assign');
                if (shouldBlock) return;
            }
            return origAssign(url);
        };
    } catch(e) {}

    // 6. location.href = "afirma://..." - asignacion directa (patron comun en AutoScript)
    try {
        var origHrefDesc = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
        if (origHrefDesc && origHrefDesc.set) {
            Object.defineProperty(Location.prototype, 'href', {
                get: function() { return origHrefDesc.get.call(this); },
                set: function(url) {
                    if (isAfirma(url)) {
                        capture(url, 'location.href');
                        if (shouldBlock) return;
                    }
                    origHrefDesc.set.call(this, url);
                },
                configurable: true,
            });
        }
    } catch(e) {}

    // 7. document.location = "afirma://..." - ruta oficial en AutoScript para Chrome.
    try { wrapLocationProperty(Document.prototype, 'document.location'); } catch(e) {}
    try {
        if (window.HTMLDocument && window.HTMLDocument.prototype) {
            wrapLocationProperty(window.HTMLDocument.prototype, 'document.location');
        }
    } catch(e) {}
    try { wrapLocationProperty(document, 'document.location.instance'); } catch(e) {}

    // 8. setAttribute / setAttributeNode y setters directos de iframe/form/anchor.
    try {
        var origSetAttr = Element.prototype.setAttribute;
        Element.prototype.setAttribute = function(name, value) {
            if (captureAttr(name, value, 'setAttribute:' + String(name || '').toLowerCase()) && shouldBlock) {
                return;
            }
            return origSetAttr.call(this, name, value);
        };
    } catch(e) {}
    try {
        var origSetAttrNode = Element.prototype.setAttributeNode;
        Element.prototype.setAttributeNode = function(attr) {
            var name = attr && attr.name;
            var value = attr && attr.value;
            if (captureAttr(name, value, 'setAttributeNode:' + String(name || '').toLowerCase()) && shouldBlock) {
                return attr;
            }
            return origSetAttrNode.call(this, attr);
        };
    } catch(e) {}
    try { wrapPropertySetter(HTMLIFrameElement.prototype, 'src', 'iframe.src'); } catch(e) {}
    try { wrapPropertySetter(HTMLAnchorElement.prototype, 'href', 'anchor.href'); } catch(e) {}
    try { wrapPropertySetter(HTMLFormElement.prototype, 'action', 'form.action'); } catch(e) {}

    // 9. MutationObserver - detecta <a href="afirma://..."> e <iframe src="afirma://...">
    var observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
            if (!m.addedNodes) return;
            m.addedNodes.forEach(function(node) {
                if (!node.querySelectorAll) return;
                node.querySelectorAll('a[href^="afirma://"], a[href^="xalocafirma://"]')
                    .forEach(function(a) { capture(a.href, 'mutation.anchor'); });
                node.querySelectorAll('iframe[src^="afirma://"], iframe[src^="xalocafirma://"]')
                    .forEach(function(f) { capture(f.src, 'mutation.iframe'); });
                if (node.href && isAfirma(node.href)) capture(node.href, 'mutation.node.href');
                if (node.src && isAfirma(node.src)) capture(node.src, 'mutation.node.src');
            });
        });
    });
    var startObserver = function() {
        var root = document.documentElement || document.body || null;
        if (!root) return false;
        observer.observe(root, { childList: true, subtree: true });
        return true;
    };
    if (!startObserver()) {
        document.addEventListener('DOMContentLoaded', function onReady() {
            document.removeEventListener('DOMContentLoaded', onReady, false);
            startObserver();
        }, false);
    }
})
