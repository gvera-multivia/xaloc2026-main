(function () {
    console.log('[RECORDER] Script starting on:', window.location.href);

    if (window._recorder_injected) {
        console.log('[RECORDER] Already injected, skipping.');
        return;
    }
    window._recorder_injected = true;
    console.log('[RECORDER] Injecting recorder...');

    // =====================================================
    // HELPER FUNCTIONS
    // =====================================================

    function getXPath(element) {
        if (!element) return '';
        if (element.id !== '') return `//*[@id="${element.id}"]`;
        if (element === document.body) return element.tagName;

        var ix = 0;
        var siblings = element.parentNode ? element.parentNode.childNodes : [];
        for (var i = 0; i < siblings.length; i++) {
            var sibling = siblings[i];
            if (sibling === element) return getXPath(element.parentNode) + '/' + element.tagName + '[' + (ix + 1) + ']';
            if (sibling.nodeType === 1 && sibling.tagName === element.tagName) ix++;
        }
        return '';
    }

    function getCssSelector(element) {
        if (!element) return '';
        if (element.id) return `#${element.id}`;
        let path = [];
        while (element && element.nodeType === Node.ELEMENT_NODE) {
            let selector = element.nodeName.toLowerCase();
            if (element.id) {
                selector += `#${element.id}`;
                path.unshift(selector);
                break;
            }
            let sib = element, nth = 1;
            while (sib = sib.previousElementSibling) {
                if (sib.nodeName.toLowerCase() == selector) nth++;
            }
            if (nth != 1) selector += `:nth-of-type(${nth})`;
            path.unshift(selector);
            element = element.parentNode;
        }
        return path.join(" > ");
    }

    function getLabel(el) {
        // Try multiple ways to get a label
        if (el.labels && el.labels.length > 0) {
            return el.labels[0].innerText.trim();
        }
        // aria-label
        if (el.getAttribute('aria-label')) {
            return el.getAttribute('aria-label');
        }
        // aria-labelledby
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const labelEl = document.getElementById(labelledBy);
            if (labelEl) return labelEl.innerText.trim();
        }
        // placeholder
        if (el.placeholder) {
            return el.placeholder;
        }
        // title
        if (el.title) {
            return el.title;
        }
        // Nearby text (previous sibling or parent td/th)
        const prev = el.previousElementSibling;
        if (prev && prev.tagName === 'LABEL') {
            return prev.innerText.trim();
        }
        const parent = el.closest('td, th, div, span');
        if (parent) {
            const prevCell = parent.previousElementSibling;
            if (prevCell && (prevCell.tagName === 'TD' || prevCell.tagName === 'TH')) {
                return prevCell.innerText.trim().substring(0, 50);
            }
        }
        return null;
    }

    function getSelectOptions(el) {
        if (el.tagName !== 'SELECT') return null;
        const options = [];
        for (let opt of el.options) {
            options.push({
                value: opt.value,
                text: opt.text,
                selected: opt.selected
            });
        }
        return options;
    }

    function buildFieldData(el) {
        const data = {
            tagName: el.tagName,
            type: el.type || null,
            name: el.name || null,
            id: el.id || null,
            value: null,
            label: getLabel(el),
            placeholder: el.placeholder || null,
            required: el.required || false,
            disabled: el.disabled || false
        };

        // Get value based on element type
        if (el.tagName === 'SELECT') {
            data.value = el.value;
            data.selectedText = el.options[el.selectedIndex]?.text || null;
            data.options = getSelectOptions(el);
        } else if (el.type === 'checkbox' || el.type === 'radio') {
            data.checked = el.checked;
            data.value = el.value;
        } else if (el.type === 'file') {
            // Can't get real path but we know files were selected
            data.value = el.value; // Will be C:\fakepath\...
            data.files = el.files ? el.files.length : 0;
        } else {
            data.value = el.value || null;
        }

        return data;
    }

    function buildLocators(el) {
        const locators = [];

        // ID selector (most reliable)
        if (el.id) {
            locators.push({ kind: 'id', value: el.id, selector: `#${el.id}` });
        }

        // Name selector
        if (el.name) {
            locators.push({ kind: 'name', value: el.name, selector: `[name="${el.name}"]` });
        }

        // Label
        const label = getLabel(el);
        if (label) {
            locators.push({ kind: 'label', value: label, selector: `getByLabel('${label}')` });
        }

        // Text content (for buttons/links)
        if (['BUTTON', 'A', 'SPAN'].includes(el.tagName)) {
            const text = el.innerText?.trim();
            if (text && text.length < 50) {
                locators.push({ kind: 'text', value: text, selector: `getByText('${text}')` });
            }
        }

        // CSS selector
        locators.push({ kind: 'css', value: getCssSelector(el), selector: getCssSelector(el) });

        // XPath
        locators.push({ kind: 'xpath', value: getXPath(el), selector: getXPath(el) });

        return locators;
    }

    function sendEvent(action, el, extraData = {}) {
        const actionData = {
            ts: new Date().toISOString(),
            url: window.location.href,
            title: document.title,
            action: action,
            field: buildFieldData(el),
            locators: buildLocators(el),
            ...extraData
        };

        console.log(`[RECORDER] Event: ${action} on ${el.id || el.name || el.tagName}`, actionData.field);

        if (window.record_action) {
            window.record_action(actionData);
        } else {
            console.warn('[RECORDER] window.record_action NOT available!');
        }
    }

    // =====================================================
    // EVENT HANDLERS
    // =====================================================

    // Track focus to know when user is interacting with inputs
    let lastFocusedInput = null;
    let lastFocusedValue = null;

    document.addEventListener('focusin', (e) => {
        const el = e.target;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            lastFocusedInput = el;
            lastFocusedValue = el.value;
            console.log('[RECORDER] Focus on:', el.id || el.name || el.tagName);
        }
    }, true);

    // Capture blur to detect text input changes
    document.addEventListener('focusout', (e) => {
        const el = e.target;
        if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') &&
            el === lastFocusedInput &&
            el.value !== lastFocusedValue) {

            const inputType = el.type || 'text';
            if (!['checkbox', 'radio', 'file', 'submit', 'button', 'reset', 'hidden'].includes(inputType)) {
                sendEvent('fill', el);
            }
        }
        lastFocusedInput = null;
        lastFocusedValue = null;
    }, true);

    // Change event for select, checkbox, radio, file
    document.addEventListener('change', (e) => {
        const el = e.target;
        console.log('[RECORDER] Change event on:', el.tagName, el.type, el.id || el.name);

        if (el.tagName === 'SELECT') {
            sendEvent('select', el);
        } else if (el.type === 'checkbox') {
            sendEvent(el.checked ? 'check' : 'uncheck', el);
        } else if (el.type === 'radio') {
            sendEvent('select_radio', el);
        } else if (el.type === 'file') {
            sendEvent('upload', el);
        }
        // Text inputs are handled by focusout
    }, true);

    // Click events for buttons, links, and other interactive elements
    document.addEventListener('click', (e) => {
        const el = e.target;

        // Find the clickable element (might be a child of button/link)
        const clickable = el.closest('button, a, input[type="submit"], input[type="button"], [role="button"], [onclick]');

        if (clickable) {
            sendEvent('click', clickable);
        } else if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) {
            // These will be handled by change event, skip
        } else if (el.onclick || el.hasAttribute('onclick')) {
            // Element has onclick handler
            sendEvent('click', el);
        }
    }, true);

    // Form submit
    document.addEventListener('submit', (e) => {
        const form = e.target;
        sendEvent('submit', form, {
            formAction: form.action,
            formMethod: form.method
        });
    }, true);

    // =====================================================
    // DOM SNAPSHOT (captures all form fields on page)
    // =====================================================

    function captureFormSnapshot() {
        const forms = document.querySelectorAll('form');
        const snapshot = {
            url: window.location.href,
            title: document.title,
            timestamp: new Date().toISOString(),
            forms: []
        };

        forms.forEach((form, formIndex) => {
            const formData = {
                id: form.id || null,
                name: form.name || null,
                action: form.action || null,
                method: form.method || 'GET',
                fields: []
            };

            // Get all form fields
            const fields = form.querySelectorAll('input, select, textarea');
            fields.forEach(field => {
                formData.fields.push(buildFieldData(field));
            });

            snapshot.forms.push(formData);
        });

        // Also capture fields outside forms
        const orphanFields = document.querySelectorAll('input:not(form input), select:not(form select), textarea:not(form textarea)');
        if (orphanFields.length > 0) {
            const orphanForm = {
                id: null,
                name: 'orphan_fields',
                fields: []
            };
            orphanFields.forEach(field => {
                orphanForm.fields.push(buildFieldData(field));
            });
            snapshot.forms.push(orphanForm);
        }

        return snapshot;
    }

    // Send initial snapshot
    setTimeout(() => {
        const snapshot = captureFormSnapshot();
        if (snapshot.forms.length > 0) {
            console.log('[RECORDER] DOM Snapshot:', snapshot);
            if (window.record_action) {
                window.record_action({
                    ts: new Date().toISOString(),
                    url: window.location.href,
                    action: 'page_snapshot',
                    snapshot: snapshot
                });
            }
        }
    }, 1000); // Wait for page to stabilize

    console.log('[RECORDER] Event listeners attached. record_action available:', !!window.record_action);
})();
