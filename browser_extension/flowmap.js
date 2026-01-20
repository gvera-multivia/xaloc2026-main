// flowmap.js
// Builds a compact "structure + actions" representation from the extension raw recording.

(() => {
  const FLOWMAP_VERSION = 'flowmap-v1';

  const safeTrim = (v) => (typeof v === 'string' ? v.trim() : null);

  // Synchronous SHA-1 (hex) for stable IDs (e.g., select options store).
  // Based on the standard SHA-1 algorithm; kept dependency-free for MV3 service workers.
  const sha1Hex = (input) => {
    const utf8 = new TextEncoder().encode(String(input ?? ''));

    const rotl = (n, s) => (n << s) | (n >>> (32 - s));
    const toHex8 = (n) => (n >>> 0).toString(16).padStart(8, '0');

    const ml = utf8.length * 8;
    const withOne = new Uint8Array(((utf8.length + 9 + 63) >> 6) << 6);
    withOne.set(utf8);
    withOne[utf8.length] = 0x80;
    const view = new DataView(withOne.buffer);
    // Append length (big-endian) in last 8 bytes.
    view.setUint32(withOne.length - 4, ml >>> 0, false);
    view.setUint32(withOne.length - 8, Math.floor(ml / 0x100000000) >>> 0, false);

    let h0 = 0x67452301;
    let h1 = 0xEFCDAB89;
    let h2 = 0x98BADCFE;
    let h3 = 0x10325476;
    let h4 = 0xC3D2E1F0;

    const w = new Uint32Array(80);
    for (let i = 0; i < withOne.length; i += 64) {
      for (let t = 0; t < 16; t++) w[t] = view.getUint32(i + t * 4, false);
      for (let t = 16; t < 80; t++) w[t] = rotl(w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16], 1) >>> 0;

      let a = h0, b = h1, c = h2, d = h3, e = h4;
      for (let t = 0; t < 80; t++) {
        let f, k;
        if (t < 20) { f = (b & c) | (~b & d); k = 0x5A827999; }
        else if (t < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1; }
        else if (t < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC; }
        else { f = b ^ c ^ d; k = 0xCA62C1D6; }
        const temp = (rotl(a, 5) + f + e + k + w[t]) >>> 0;
        e = d; d = c; c = rotl(b, 30) >>> 0; b = a; a = temp;
      }

      h0 = (h0 + a) >>> 0;
      h1 = (h1 + b) >>> 0;
      h2 = (h2 + c) >>> 0;
      h3 = (h3 + d) >>> 0;
      h4 = (h4 + e) >>> 0;
    }

    return (toHex8(h0) + toHex8(h1) + toHex8(h2) + toHex8(h3) + toHex8(h4)).toLowerCase();
  };

  const isoToMs = (iso) => {
    const t = Date.parse(iso);
    return Number.isFinite(t) ? t : null;
  };

  const pickSelectors = (interaction) => {
    const candidates = Array.isArray(interaction?.locatorCandidates) ? interaction.locatorCandidates : [];
    const css = candidates
      .filter(c => c && c.type === 'css' && typeof c.value === 'string' && c.value.trim())
      .map(c => c.value.trim());
    const unique = [];
    for (const s of css) {
      if (!unique.includes(s)) unique.push(s);
      if (unique.length >= 3) break;
    }
    return {
      bestSelector: unique[0] || null,
      altSelectors: unique.slice(1, 3)
    };
  };

  const computeElementKey = (interaction) => {
    const tag = safeTrim(interaction?.element?.tag);
    const attrs = interaction?.element?.attributes || {};
    const id = safeTrim(attrs.id);
    if (id) return id;

    const name = safeTrim(attrs.name);
    const labelText = safeTrim(interaction?.context?.labelText);
    if (name) {
      const base = `${name}|${tag || ''}|${labelText || ''}`.trim();
      if (base.length <= 120) return base;
      return `ek_${sha1Hex(base).slice(0, 16)}`;
    }

    const { bestSelector } = pickSelectors(interaction);
    if (bestSelector) return bestSelector;

    const fallback = `${tag || 'EL'}|${labelText || ''}`.trim();
    if (fallback.length <= 120) return fallback || `ek_${sha1Hex(JSON.stringify(interaction || {})).slice(0, 16)}`;
    return `ek_${sha1Hex(fallback).slice(0, 16)}`;
  };

  const normalizeAction = (interaction) => {
    const tag = safeTrim(interaction?.element?.tag);
    const attrs = interaction?.element?.attributes || {};
    const inputType = safeTrim(attrs.type)?.toLowerCase() || null;
    const rawAction = safeTrim(interaction?.action);
    const state = interaction?.state || {};

    if (rawAction === 'click') return { action: 'click' };
    if (rawAction === 'submit') return { action: 'submit' };

    if (rawAction === 'upload') {
      const names = Array.isArray(state.files) ? state.files.filter(Boolean) : [];
      return { action: 'upload', fileMeta: names.length ? { names, count: names.length } : undefined };
    }

    if (rawAction === 'fill') return { action: 'fill', value: state.value };

    if (rawAction === 'change') {
      if (tag === 'SELECT') {
        return { action: 'select', selectedValue: state.value, selectedText: state.selectedText };
      }
      if (tag === 'INPUT' && (inputType === 'checkbox' || inputType === 'radio')) {
        const checked = !!state.checked;
        return { action: checked ? 'check' : 'uncheck', checked };
      }
      if (tag === 'INPUT' && inputType === 'file') {
        const names = Array.isArray(state.files) ? state.files.filter(Boolean) : [];
        return { action: 'upload', fileMeta: names.length ? { names, count: names.length } : undefined };
      }
      if (state.value != null) return { action: 'fill', value: state.value };
      return { action: 'click' };
    }

    return { action: rawAction || 'click' };
  };

  const stepSignature = (step) => {
    const base = {
      action: step.action,
      ref: step.ref || null,
      url: step.url || null,
      value: step.value ?? null,
      checked: step.checked ?? null,
      selectedValue: step.selectedValue ?? null,
      selectedText: step.selectedText ?? null,
      fileMeta: step.fileMeta ? { count: step.fileMeta.count, names: step.fileMeta.names } : null,
      note: step.note || null
    };
    return JSON.stringify(base);
  };

  const pushStep = (steps, step, tsMs) => {
    const prev = steps.length ? steps[steps.length - 1] : null;
    const replaceable = step.action === 'fill' || step.action === 'select' || step.action === 'check' || step.action === 'uncheck' || step.action === 'upload';

    if (prev) {
      if (replaceable && prev.action === step.action && prev.ref && step.ref && prev.ref === step.ref) {
        steps[steps.length - 1] = step;
        return;
      }
      const prevMs = prev.__tsMs;
      if (typeof prevMs === 'number' && typeof tsMs === 'number' && (tsMs - prevMs) <= 300) {
        if (stepSignature(prev) === stepSignature(step)) return;
      }
    }

    steps.push(step);
  };

  const stripInternal = (obj) => {
    if (!obj || typeof obj !== 'object') return obj;
    const out = Array.isArray(obj) ? [] : {};
    for (const [k, v] of Object.entries(obj)) {
      if (k.startsWith('__')) continue;
      out[k] = (v && typeof v === 'object') ? stripInternal(v) : v;
    }
    return out;
  };

  const maybeAdd = (obj, key, value) => {
    if (value == null) return;
    if (Array.isArray(value) && value.length === 0) return;
    if (typeof value === 'string' && value.trim() === '') return;
    obj[key] = value;
  };

  const storeSelectOptions = (flowmap, topUrl, frameUrl, bestSelector, selectOptions) => {
    if (!Array.isArray(selectOptions) || selectOptions.length === 0) return null;
    const tuples = selectOptions.map(o => [String(o?.value ?? ''), String(o?.text ?? '')]);
    const hash = sha1Hex(`${topUrl}|${frameUrl || ''}|${bestSelector || ''}|${JSON.stringify(tuples)}`);
    const optionsId = `opt_${hash.slice(0, 12)}`;
    if (!flowmap.selectOptionsStore[optionsId]) {
      flowmap.selectOptionsStore[optionsId] = {
        count: tuples.length,
        hash: `sha1:${hash}`,
        options: tuples
      };
    }
    return { optionsId, optionsCount: tuples.length };
  };

  const computeVisitHeading = (visit) => {
    const interactions = Array.isArray(visit?.interactions) ? visit.interactions : [];
    for (const it of interactions) {
      const h = safeTrim(it?.context?.heading);
      if (h) return h;
    }
    return null;
  };

  const removeWrapperLabelClicks = (steps) => {
    if (!Array.isArray(steps) || steps.length < 2) return steps;
    const out = [];
    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      const next = steps[i + 1];
      if (step?.action === 'click' && step.__rawTag === 'LABEL' && next && (next.action === 'check' || next.action === 'uncheck')) {
        const forId = step.__rawFor;
        if (forId && next.__rawId && next.__rawId === forId) continue;
      }
      out.push(step);
    }
    return out;
  };

  const computeEndedAt = (visit, startedAt) => {
    const interactions = Array.isArray(visit?.interactions) ? visit.interactions : [];
    for (let i = interactions.length - 1; i >= 0; i--) {
      const ts = safeTrim(interactions[i]?.ts);
      if (ts) return ts;
    }
    return startedAt;
  };

  // Public API: buildFlowMap(rawRecording) -> flowMap
  const buildFlowMap = (rawRecording) => {
    const raw = rawRecording && typeof rawRecording === 'object' ? rawRecording : {};
    const rawMeta = raw.meta || {};

    const flowmap = {
      meta: {
        version: FLOWMAP_VERSION,
        startedAt: rawMeta.startedAt || new Date().toISOString(),
        endedAt: rawMeta.endedAt || rawMeta.startedAt || new Date().toISOString(),
        source: 'my-extension',
        rawFile: 'recording.raw.json'
      },
      selectOptionsStore: {},
      pages: []
    };

    const pages = Array.isArray(raw.pages) ? raw.pages : [];
    for (const page of pages) {
      const topUrl = safeTrim(page?.topUrl);
      if (!topUrl) continue;

      const outPage = { topUrl, visits: [] };
      const visits = Array.isArray(page?.visits) ? page.visits : [];
      for (let vIndex = 0; vIndex < visits.length; vIndex++) {
        const visit = visits[vIndex] || {};
        const startedAt = safeTrim(visit.startedAt) || flowmap.meta.startedAt;
        const endedAt = computeEndedAt(visit, startedAt);

        const elementsByKey = new Map();
        const elements = [];
        const framesByKey = new Map(); // frameKey -> frameUrl
        const steps = [];

        // Always include a navigate step to make visits self-contained.
        steps.push({ action: 'navigate', url: topUrl, __tsMs: isoToMs(startedAt) });

        const interactions = Array.isArray(visit.interactions) ? visit.interactions : [];
        for (const it of interactions) {
          const ts = safeTrim(it?.ts) || startedAt;
          const tsMs = isoToMs(ts);

          const elementKey = computeElementKey(it);
          const tag = safeTrim(it?.element?.tag);
          const attrs = it?.element?.attributes || {};
          const id = safeTrim(attrs.id);
          const name = safeTrim(attrs.name);
          const type = safeTrim(attrs.type);

          const { bestSelector, altSelectors } = pickSelectors(it);
          const labelText = safeTrim(it?.context?.labelText);
          const heading = safeTrim(it?.context?.heading);

          const frameUrl = safeTrim(it?.frameUrl);
          let frameKey = null;
          if (frameUrl && frameUrl !== topUrl) {
            frameKey = `frm_${sha1Hex(frameUrl).slice(0, 10)}`;
            if (!framesByKey.has(frameKey)) framesByKey.set(frameKey, frameUrl);
          }

          if (!elementsByKey.has(elementKey)) {
            const elOut = { elementKey };
            maybeAdd(elOut, 'tag', tag);
            if (tag === 'INPUT') maybeAdd(elOut, 'type', type);
            maybeAdd(elOut, 'id', id);
            maybeAdd(elOut, 'name', name);
            maybeAdd(elOut, 'bestSelector', bestSelector);
            maybeAdd(elOut, 'altSelectors', altSelectors);
            maybeAdd(elOut, 'labelText', labelText);
            maybeAdd(elOut, 'heading', heading);
            maybeAdd(elOut, 'frameKey', frameKey);
            elementsByKey.set(elementKey, elOut);
            elements.push(elOut);
          }

          // Select options store + element annotation (once).
          if (tag === 'SELECT') {
            const existing = elementsByKey.get(elementKey);
            if (existing && !existing.optionsId) {
              const opt = storeSelectOptions(flowmap, topUrl, frameUrl, bestSelector, it?.selectOptions);
              if (opt) {
                existing.optionsId = opt.optionsId;
                existing.optionsCount = opt.optionsCount;
              }
            } else if (existing && existing.optionsId && Array.isArray(it?.selectOptions) && it.selectOptions.length) {
              // If options changed dynamically, add a new optionsId and update element to latest.
              const opt = storeSelectOptions(flowmap, topUrl, frameUrl, bestSelector, it.selectOptions);
              if (opt && opt.optionsId !== existing.optionsId) {
                existing.optionsId = opt.optionsId;
                existing.optionsCount = opt.optionsCount;
              }
            }
          }

          const norm = normalizeAction(it);
          const step = { action: norm.action, __tsMs: tsMs };
          if (norm.action !== 'navigate') step.ref = elementKey;

          if (norm.action === 'fill') maybeAdd(step, 'value', norm.value);
          if (norm.action === 'select') {
            maybeAdd(step, 'selectedValue', norm.selectedValue);
            maybeAdd(step, 'selectedText', norm.selectedText);
          }
          if (norm.action === 'check' || norm.action === 'uncheck') maybeAdd(step, 'checked', norm.checked);
          if (norm.action === 'upload') maybeAdd(step, 'fileMeta', norm.fileMeta);

          // Internal metadata to support noise removal.
          step.__rawTag = tag;
          step.__rawFor = safeTrim(attrs.for);
          step.__rawId = id;

          pushStep(steps, step, tsMs);
        }

        const cleanedSteps = removeWrapperLabelClicks(steps);

        const visitOut = {
          visitIndex: vIndex + 1,
          startedAt,
          endedAt,
          steps: stripInternal(cleanedSteps),
          elements: stripInternal(elements)
        };

        const visitHeading = computeVisitHeading(visit);
        maybeAdd(visitOut, 'heading', visitHeading);

        if (framesByKey.size) {
          visitOut.frames = Array.from(framesByKey.entries()).map(([k, u]) => ({ frameKey: k, frameUrl: u }));
        }

        outPage.visits.push(visitOut);
      }

      flowmap.pages.push(outPage);
    }

    // Update endedAt if raw had none.
    if (!rawMeta.endedAt) {
      let maxMs = isoToMs(flowmap.meta.startedAt) || 0;
      let maxIso = flowmap.meta.startedAt;
      for (const p of flowmap.pages) {
        for (const v of p.visits) {
          const ms = isoToMs(v.endedAt);
          if (typeof ms === 'number' && ms >= maxMs) {
            maxMs = ms;
            maxIso = v.endedAt;
          }
        }
      }
      flowmap.meta.endedAt = maxIso;
    }

    return flowmap;
  };

  // Expose globally for background.js (importScripts).
  self.buildFlowMap = buildFlowMap;
})();

