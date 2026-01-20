(function() {
    if (window._recorder_injected) return;
    window._recorder_injected = true;

    function getXPath(element) {
        if (element.id !== '') return `//*[@id="${element.id}"]`;
        if (element === document.body) return element.tagName;

        var ix = 0;
        var siblings = element.parentNode.childNodes;
        for (var i = 0; i < siblings.length; i++) {
            var sibling = siblings[i];
            if (sibling === element) return getXPath(element.parentNode) + '/' + element.tagName + '[' + (ix + 1) + ']';
            if (sibling.nodeType === 1 && sibling.tagName === element.tagName) ix++;
        }
    }

    function getCssSelector(element) {
        if (element.id) return `#${element.id}`;
        let path = [];
        while (element.nodeType === Node.ELEMENT_NODE) {
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

    function getCandidateLocators(el) {
        const candidates = [];

        // 1. getByRole (approximate)
        const role = el.getAttribute('role');
        if (role) {
             candidates.push({kind: 'getByRole', value: role, matches: 1});
        } else {
             // Implicit roles
             if (el.tagName === 'BUTTON' || (el.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(el.type))) {
                 candidates.push({kind: 'getByRole', value: 'button', matches: 1});
             } else if (el.tagName === 'A') {
                 candidates.push({kind: 'getByRole', value: 'link', matches: 1});
             } else if (el.tagName === 'INPUT' && el.type === 'checkbox') {
                 candidates.push({kind: 'getByRole', value: 'checkbox', matches: 1});
             } else if (el.tagName === 'INPUT' && el.type === 'radio') {
                 candidates.push({kind: 'getByRole', value: 'radio', matches: 1});
             }
        }

        // 2. getByLabel
        if (el.labels && el.labels.length > 0) {
            candidates.push({kind: 'getByLabel', value: el.labels[0].innerText.trim(), matches: 1});
        } else {
             const ariaLabel = el.getAttribute('aria-label');
             if (ariaLabel) candidates.push({kind: 'getByLabel', value: ariaLabel, matches: 1});
             const ariaLabelledBy = el.getAttribute('aria-labelledby');
             if (ariaLabelledBy) {
                 const labelEl = document.getElementById(ariaLabelledBy);
                 if (labelEl) candidates.push({kind: 'getByLabel', value: labelEl.innerText.trim(), matches: 1});
             }
        }

        // 3. getByPlaceholder
        const placeholder = el.getAttribute('placeholder');
        if (placeholder) candidates.push({kind: 'getByPlaceholder', value: placeholder, matches: 1});

        // 4. text=
        if (['BUTTON', 'A', 'LABEL', 'SPAN', 'DIV'].includes(el.tagName) && el.innerText.trim().length > 0 && el.innerText.trim().length < 50) {
            candidates.push({kind: 'text', value: el.innerText.trim(), matches: 1});
        }

        // 5. css
        candidates.push({kind: 'css', value: getCssSelector(el), matches: 1});

        // 6. xpath
        candidates.push({kind: 'xpath', value: getXPath(el), matches: 1});

        return candidates;
    }

    function getContext(el) {
        // Find closest form or section
        const form = el.closest('form');
        const section = el.closest('section, div[class*="section"], div[id*="section"]');

        // Find closest label if not directly associated
        let label = null;
        if (el.labels && el.labels.length > 0) {
            label = el.labels[0].innerText.trim();
        }

        return {
            form: !!form,
            section: section ? (section.getAttribute('aria-label') || section.getAttribute('id') || 'unknown') : null,
            nearby_text: label
        };
    }

    function getFingerprint() {
        // Collect visible buttons and labels to detect screen changes
        // Using a simple strategy: text content of buttons and labels
        try {
            const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]'))
                .filter(el => el.offsetParent !== null) // check visibility
                .map(el => (el.innerText || el.value || el.id || '').trim())
                .filter(t => t.length > 0)
                .sort() // sort to be order-independent
                .join('|');

            const labels = Array.from(document.querySelectorAll('label'))
                .filter(el => el.offsetParent !== null)
                .map(el => (el.innerText || '').trim())
                .filter(t => t.length > 0)
                .sort()
                .join('|');

            return buttons + "::" + labels;
        } catch (e) {
            return "";
        }
    }

    function handler(event) {
        const el = event.target;
        if (!el) return;

        // Skip non-interactive elements for click unless they are likely clickable
        if (event.type === 'click') {
            const interactive = el.closest('button, a, input[type="submit"], input[type="button"], [role="button"]');
            if (!interactive && !el.onclick) return; // naive check
        }

        const actionData = {
            ts: new Date().toISOString(),
            url: window.location.href,
            title: document.title,
            h1: document.querySelector('h1')?.innerText,
            fingerprint: getFingerprint(),
            action: event.type,
            field: {
                tagName: el.tagName,
                type: el.type || null,
                name: el.name || null,
                id: el.id || null,
                value: el.value || null,
                label: (el.labels && el.labels.length > 0) ? el.labels[0].innerText.trim() : null
            },
            locators: getCandidateLocators(el),
            context: getContext(el)
        };

        // Special handling for fill (change event on input/textarea)
        if (event.type === 'change' && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {
            if (el.type === 'checkbox' || el.type === 'radio') {
                actionData.action = el.checked ? 'check' : 'uncheck';
            } else if (el.tagName === 'SELECT') {
                actionData.action = 'select';
                actionData.field.value = el.value;
            } else if (el.type === 'file') {
                 actionData.action = 'upload';
                 // We can't get the real path, but we know it happened
            } else {
                actionData.action = 'fill';
            }
        }

        if (event.type === 'click') {
             // Avoid double recording if click triggered change? No, change usually happens on blur.
             // But clicking a submit button is important.
             // If it's an input/textarea/select, we generally ignore click and wait for change/focus?
             // Actually, clicking an input usually just focuses it. We care about 'fill'.
             if (el.tagName === 'INPUT' && (el.type !== 'submit' && el.type !== 'button' && el.type !== 'checkbox' && el.type !== 'radio' && el.type !== 'file')) {
                 return;
             }
             if (el.tagName === 'TEXTAREA') return;
             if (el.tagName === 'SELECT') return;
        }

        if (window.record_action) {
            window.record_action(actionData);
        }
    }

    // Capture events
    document.addEventListener('click', handler, true);
    document.addEventListener('change', handler, true);
    // submit event?
    document.addEventListener('submit', (e) => {
         const actionData = {
            ts: new Date().toISOString(),
            url: window.location.href,
            title: document.title,
            h1: document.querySelector('h1')?.innerText,
            fingerprint: getFingerprint(),
            action: 'submit',
            locators: [], // usually on the form
            context: {}
        };
         if (window.record_action) window.record_action(actionData);
    }, true);

    console.log("Recorder injected");
})();
