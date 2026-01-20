const toggleBtn = document.getElementById('toggleBtn');
const statusDiv = document.getElementById('status');
const exportSection = document.getElementById('export-section');
const downloadBtn = document.getElementById('downloadBtn');

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
    // If sessionData is null, try fetching it one last time
    if (!sessionData) {
        chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
            if (response && response.session) {
                downloadData(response.session);
            }
        });
    } else {
        downloadData(sessionData);
    }
});

const downloadData = (data) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type : 'application/json'});
    const url = URL.createObjectURL(blob);
    // Use chrome.downloads API if available/permitted, else anchor click
    chrome.downloads.download({
        url: url,
        filename: 'recording.json',
        saveAs: true
    }, (downloadId) => {
        if (chrome.runtime.lastError) {
             console.error(chrome.runtime.lastError);
             // Fallback
             const a = document.createElement('a');
             a.href = url;
             a.download = 'recording.json';
             a.click();
        }
    });
};

chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'UPDATE_COUNT') {
        if (isRecording) {
             statusDiv.innerText = `Status: Recording... (${message.count} events)`;
        }
    }
});

// Init
pollStatus();
