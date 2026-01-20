const toggleBtn = document.getElementById('toggleBtn');
const statusDiv = document.getElementById('status');
const exportSection = document.getElementById('export-section');
const downloadBtn = document.getElementById('downloadBtn');
const rawFileInput = document.getElementById('rawFileInput');
const rawJsonInput = document.getElementById('rawJsonInput');
const convertBtn = document.getElementById('convertBtn');

let isRecording = false;
let sessionData = null;

const updateUI = (recording, count) => {
    isRecording = recording;
    if (isRecording) {
        statusDiv.innerText = `Status: Recording... (${count || 0} events)`;
        statusDiv.classList.add('recording');
        toggleBtn.innerText = "Stop Recording";
        exportSection.style.display = 'none';
    } else {
        statusDiv.innerText = "Status: Idle";
        statusDiv.classList.remove('recording');
        toggleBtn.innerText = "Start Recording";
        exportSection.style.display = 'block';
    }
};

const pollStatus = () => {
     chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
         if (response) {
            const count = response.session ? response.session.pages.reduce((acc, p) => acc + p.visits.reduce((acc2, v) => acc2 + v.interactions.length, 0), 0) : 0;
            updateUI(response.isRecording, count);
            sessionData = response.session;
         }
     });
};

toggleBtn.addEventListener('click', () => {
    const type = isRecording ? 'STOP_RECORDING' : 'START_RECORDING';
    chrome.runtime.sendMessage({ type }, (response) => {
        pollStatus();
        if (type === 'STOP_RECORDING' && response.session) {
             sessionData = response.session;
        }
    });
});

downloadBtn.addEventListener('click', () => {
    const exportFromSession = (raw) => {
        downloadJson(raw, 'recording.raw.json');
        chrome.runtime.sendMessage({ type: 'BUILD_FLOWMAP', rawRecording: raw }, (res) => {
            if (!res || !res.ok) {
                console.error('BUILD_FLOWMAP failed', res);
                return;
            }
            downloadJson(res.flowmap, 'recording.flowmap.json');
        });
    };

    // If sessionData is null, fetch it one last time.
    if (!sessionData) {
        chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
            if (response && response.session) exportFromSession(response.session);
        });
        return;
    }
    exportFromSession(sessionData);
});

const downloadJson = (data, filename) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type : 'application/json'});
    const url = URL.createObjectURL(blob);
    // Use chrome.downloads API if available/permitted, else anchor click
    chrome.downloads.download({
        url: url,
        filename: filename,
        saveAs: true
    }, (downloadId) => {
        if (chrome.runtime.lastError) {
             console.error(chrome.runtime.lastError);
             // Fallback
             const a = document.createElement('a');
             a.href = url;
             a.download = filename;
             a.click();
        }
    });
};

const suggestFlowmapFilename = (rawFilename) => {
    if (!rawFilename) return 'recording.flowmap.json';
    if (rawFilename.toLowerCase().endsWith('.json')) {
        return rawFilename.slice(0, -5) + '.flowmap.json';
    }
    return rawFilename + '.flowmap.json';
};

convertBtn.addEventListener('click', () => {
    const file = rawFileInput && rawFileInput.files ? rawFileInput.files[0] : null;
    const pasted = rawJsonInput ? rawJsonInput.value : '';

    const buildAndDownload = (raw, filename) => {
        chrome.runtime.sendMessage({ type: 'BUILD_FLOWMAP', rawRecording: raw }, (res) => {
            if (!res || !res.ok) {
                console.error('BUILD_FLOWMAP failed', res);
                return;
            }
            downloadJson(res.flowmap, filename || 'recording.flowmap.json');
        });
    };

    if (file) {
        const reader = new FileReader();
        reader.onload = () => {
            try {
                const raw = JSON.parse(String(reader.result || ''));
                buildAndDownload(raw, suggestFlowmapFilename(file.name));
            } catch (err) {
                console.error('Invalid JSON file', err);
            }
        };
        reader.readAsText(file);
        return;
    }

    if (pasted && pasted.trim()) {
        try {
            buildAndDownload(JSON.parse(pasted), 'recording.flowmap.json');
        } catch (err) {
            console.error('Invalid pasted JSON', err);
        }
    }
});

chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'UPDATE_COUNT') {
        if (isRecording) {
             statusDiv.innerText = `Status: Recording... (${message.count} events)`;
        }
    }
});

// Init
pollStatus();
