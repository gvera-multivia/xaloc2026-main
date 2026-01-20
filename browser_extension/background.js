let isRecording = false;
let session = {
  meta: {},
  pages: []
};
let currentVisitByTab = {}; // tabId -> { pageIndex, visitIndex }

importScripts('flowmap.js');

// Debounce storage
let storageTimer = null;
const saveSession = () => {
  if (storageTimer) clearTimeout(storageTimer);
  storageTimer = setTimeout(() => {
    chrome.storage.local.set({ session });
  }, 1000);
};

// Initialize or load state
chrome.storage.local.get(['session', 'isRecording'], (result) => {
  if (result.session) session = result.session;
  if (result.isRecording) isRecording = result.isRecording;
});

// Helper: UUID
const uuidv4 = () => {
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
  );
}

// Navigation Handler
const handleNavigation = (details) => {
  if (!isRecording) return;
  if (details.frameId !== 0) return; // Only top-level navigation

  const tabId = details.tabId;
  const url = details.url;
  const now = new Date().toISOString();

  // Find existing page or create new
  let pageIndex = session.pages.findIndex(p => p.topUrl === url);
  if (pageIndex === -1) {
    session.pages.push({
      topUrl: url,
      visits: []
    });
    pageIndex = session.pages.length - 1;
  }

  // Create new visit
  const visitId = uuidv4();
  session.pages[pageIndex].visits.push({
    visitId: visitId,
    startedAt: now,
    interactions: []
  });
  const visitIndex = session.pages[pageIndex].visits.length - 1;

  currentVisitByTab[tabId] = { pageIndex, visitIndex };
  saveSession();

  console.log(`Navigation detected: ${url} (Page ${pageIndex}, Visit ${visitIndex})`);
};

chrome.webNavigation.onCommitted.addListener(handleNavigation);
chrome.webNavigation.onHistoryStateUpdated.addListener(handleNavigation);

// Message Handler
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab ? sender.tab.id : null;

  if (message.type === 'START_RECORDING') {
    isRecording = true;
    session = {
      meta: {
        startedAt: new Date().toISOString(),
        browser: 'chrome/edge',
        version: '0.1'
      },
      pages: []
    };
    currentVisitByTab = {};
    chrome.storage.local.set({ isRecording, session });

    // If starting on an existing page, register it as a visit immediately
    // Note: This requires activeTab permission or getting current tab from sender if available,
    // but often START is sent from popup, which doesn't have a sender.tab.
    // We will handle initial visit creation when the popup sends the message and we query active tabs.
    // However, if the popup is context specific, it might trigger.
    // Best effort:
    chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
        if(tabs && tabs[0]) {
            handleNavigation({
                tabId: tabs[0].id,
                url: tabs[0].url,
                frameId: 0
            });
        }
    });

    sendResponse({ status: 'started' });
  }
  else if (message.type === 'STOP_RECORDING') {
    isRecording = false;
    session.meta.endedAt = new Date().toISOString();
    chrome.storage.local.set({ isRecording, session });
    sendResponse({ status: 'stopped', session: session });
  }
  else if (message.type === 'GET_STATUS') {
    sendResponse({ isRecording, session });
  }
  else if (message.type === 'INTERACTION') {
    if (!isRecording) return;

    // Ensure we have a visit reference
    if (tabId && !currentVisitByTab[tabId]) {
         // Fallback: if we missed navigation
         if (sender.tab) {
            handleNavigation({
                tabId: tabId,
                url: sender.tab.url,
                frameId: 0
            });
         }
    }

    if (tabId && currentVisitByTab[tabId]) {
      const { pageIndex, visitIndex } = currentVisitByTab[tabId];
      // Double check bounds
      if (session.pages[pageIndex] && session.pages[pageIndex].visits[visitIndex]) {
          session.pages[pageIndex].visits[visitIndex].interactions.push(message.data);
          saveSession();

          // Notify popup of update (if open)
          const count = session.pages.reduce((acc, p) => acc + p.visits.reduce((acc2, v) => acc2 + v.interactions.length, 0), 0);
          chrome.runtime.sendMessage({ type: 'UPDATE_COUNT', count }).catch(() => {});
      }
    }
  }
  else if (message.type === 'BUILD_FLOWMAP') {
    try {
      const rawRecording = typeof message.rawRecording === 'string'
        ? JSON.parse(message.rawRecording)
        : message.rawRecording;
      const flowmap = self.buildFlowMap(rawRecording);
      sendResponse({ ok: true, flowmap });
    } catch (err) {
      sendResponse({ ok: false, error: String(err && err.message ? err.message : err) });
    }
  }

  return true; // async response
});
