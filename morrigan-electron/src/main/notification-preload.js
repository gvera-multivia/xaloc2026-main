const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronNotify', {
    onData: (callback) => {
        ipcRenderer.on('notification:data', (_event, data) => callback(data))
    },
    close: () => {
        ipcRenderer.send('notification:close')
    }
})
