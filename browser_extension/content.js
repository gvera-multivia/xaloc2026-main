// content.js

// --- State & Config ---
let isRecording = false;

// --- Helpers ---

// Generate CSS Path (Simplified)
const getCssPath = (el) => {
    if (!(el instanceof Element)) return;
    const path = [];
    while (el.nodeType === Node.ELEMENT_NODE) {
        let selector = el.nodeName.toLowerCase();
        if (el.id) {
            selector += '#' + el.id;
            path.unshift(selector);
            break;
        } else {
            let sib = el, nth = 1;
            while (sib = sib.previousElementSibling) {
                if (sib.nodeName.toLowerCase() == selector) nth++;
            }
            if (nth != 1) selector += ":nth-of-type("+nth+")";
        }
        path.unshift(selector);
        el = el.parentNode;
    }
    return path.join(" > ");
};

const getLocatorCandidates = (el) => {
    const candidates = [];

    // 1. ID
    if (el.id) candidates.push({ type: 'css', value: `#${el.id}`, uniqueness: 1 });

    // 2. Name
    if (el.name) candidates.push({ type: 'css', value: `[name="${el.name}"]`, uniqueness: 1 });

    // 3. Label Text
    if (el.id) {
        const label = document.querySelector(`label[for="${el.id}"]`);
        if (label) candidates.push({ type: 'label', value: label.innerText.trim() });
    }
    // Label wrapper
    const parentLabel = el.closest('label');
    if (parentLabel) candidates.push({ type: 'label', value: parentLabel.innerText.trim() });

    // 4. Aria Label
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) candidates.push({ type: 'aria', value: ariaLabel });

    // 5. Text content (for buttons/links)
    if (['BUTTON', 'A'].includes(el.tagName) || el.getAttribute('role') === 'button') {
        const text = el.innerText.trim();
        if (text) candidates.push({ type: 'text', value: text });
    }

    // 6. CSS Path fallback
    candidates.push({ type: 'css', value: getCssPath(el) });

    return candidates;
};

const getContext = (el) => {
    const context = {
        labelText: null,
        heading: null,
        formOuterHTML: null
    };

    // Label
    if (el.id) {
        const label = document.querySelector(`label[for="${el.id}"]`);
        if (label) context.labelText = label.innerText.trim();
    }
    if (!context.labelText) {
        const parentLabel = el.closest('label');
        if (parentLabel) context.labelText = parentLabel.innerText.trim();
    }

    // Heading (closest previous)
    let curr = el;
    while(curr && curr !== document.body) {
        let sibling = curr.previousElementSibling;
        while(sibling) {
            if (/^H[1-6]$/.test(sibling.tagName)) {
                context.heading = sibling.innerText.trim();
                break;
            }
            sibling = sibling.previousElementSibling;
        }
        if (context.heading) break;
        curr = curr.parentElement;
    }

    // Form context
    const form = el.closest('form');
    if (form) {
        // Truncate to avoid massive JSON
        context.formOuterHTML = form.outerHTML.substring(0, 500) + '...';
    }

    return context;
};

const getActionableElement = (target) => {
    const interestTags = ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'LABEL'];
    let el = target;
    while (el && el !== document.body) {
        if (interestTags.includes(el.tagName)) return el;
        if (el.getAttribute('role') === 'button') return el;
        el = el.parentElement;
    }
    return target; // Fallback
};

const serializeSelectOptions = (selectEl) => {
    const options = Array.from(selectEl.options).map(opt => ({
        value: opt.value,
        text: opt.text,
        selected: opt.selected,
        disabled: opt.disabled
    }));
    return options;
};

// --- Event Handlers ---

const handleInteraction = (type, event) => {
    if (!isRecording) return;

    const target = event.target;
    // Special check for shadow DOM or anything weird? keeping it simple for MVP.

    const actionable = getActionableElement(target);
    if (!actionable) return;

    const interaction = {
        ts: new Date().toISOString(),
        action: type, // Default, might be refined
        frameUrl: window.location.href,
        element: {
            tag: actionable.tagName,
            outerHTML: actionable.outerHTML,
            attributes: {}
        },
        state: {},
        selectOptions: [],
        context: getContext(actionable),
        locatorCandidates: getLocatorCandidates(actionable),
        notes: {
            crossOriginFrameBlocked: false
        }
    };

    // Attributes
    for (let attr of actionable.attributes) {
        interaction.element.attributes[attr.name] = attr.value;
    }

    // State specific
    if (actionable.tagName === 'INPUT') {
        const inputType = actionable.type.toLowerCase();
        if (inputType === 'checkbox' || inputType === 'radio') {
            interaction.action = actionable.checked ? 'check' : 'uncheck';
            interaction.state.checked = actionable.checked;
            interaction.state.value = actionable.value;
            // Map 'check/uncheck' to 'change' if generic preference,
            // but prompt asked for 'change' for checkbox/radio.
            // The prompt says: "change para select, checkbox, radio".
            interaction.action = 'change'; // Normalize to change as per requirements
        } else if (inputType === 'file') {
             interaction.action = 'upload';
             if (actionable.files) {
                 interaction.state.files = Array.from(actionable.files).map(f => f.name);
             }
        } else {
            interaction.action = 'fill';
            interaction.state.value = actionable.value;
        }
    } else if (actionable.tagName === 'TEXTAREA') {
        interaction.action = 'fill';
        interaction.state.value = actionable.value;
    } else if (actionable.tagName === 'SELECT') {
        interaction.action = 'change'; // Explicit requirement
        interaction.state.value = actionable.value;
        interaction.state.selectedText = actionable.options[actionable.selectedIndex]?.text;
        interaction.selectOptions = serializeSelectOptions(actionable);
    }

    // Filter logic: ignore clicks on text inputs (handled by blur)
    if (type === 'click') {
        if (actionable.tagName === 'INPUT' && !['submit', 'button', 'reset', 'checkbox', 'radio', 'image', 'file'].includes(actionable.type)) {
            return;
        }
        if (actionable.tagName === 'SELECT') return;
        if (actionable.tagName === 'TEXTAREA') return;
    }

    chrome.runtime.sendMessage({ type: 'INTERACTION', data: interaction });
};

// --- Listeners ---

// Click
document.addEventListener('click', (e) => handleInteraction('click', e), true);

// Change (for select, checkbox, radio, file)
document.addEventListener('change', (e) => {
    handleInteraction('change', e);
}, true);

// Blur (for text inputs)
document.addEventListener('blur', (e) => {
    const el = e.target;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.tagName === 'INPUT' && ['checkbox', 'radio', 'button', 'submit', 'reset', 'file'].includes(el.type)) return;
        handleInteraction('fill', e);
    }
}, true);

// Submit
document.addEventListener('submit', (e) => {
   handleInteraction('submit', e);
}, true);


// --- Init ---
chrome.storage.local.get(['isRecording'], (res) => {
    isRecording = !!res.isRecording;
});

chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.isRecording) {
        isRecording = changes.isRecording.newValue;
    }
});
