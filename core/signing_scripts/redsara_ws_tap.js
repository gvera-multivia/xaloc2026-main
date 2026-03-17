(function() {
    if (window.__xaloc_ws_tap_installed) return;
    window.__xaloc_ws_tap_installed = true;
    var NativeWS = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        var ws = protocols ? new NativeWS(url, protocols) : new NativeWS(url);
        var wsUrl = String(url || "");
        try { console.log("[XALOC-WS-TAP] open " + wsUrl); } catch(e) {}

        var _send = ws.send.bind(ws);
        ws.send = function(data) {
            var txt = (data instanceof ArrayBuffer) ? ("[ArrayBuffer " + data.byteLength + "]") : String(data || "");
            var preview = txt.slice(0, 220).replace(/\s+/g, " ");
            try { console.log("[XALOC-WS-TAP] >> len=" + txt.length + " url=" + wsUrl + " data=" + preview); } catch(e) {}
            return _send(data);
        };

        ws.addEventListener("message", function(ev) {
            var txt = (ev.data instanceof ArrayBuffer) ? ("[ArrayBuffer " + ev.data.byteLength + "]") : String(ev.data || "");
            var preview = txt.slice(0, 220).replace(/\s+/g, " ");
            try { console.log("[XALOC-WS-TAP] << len=" + txt.length + " url=" + wsUrl + " data=" + preview); } catch(e) {}
        });
        ws.addEventListener("error", function() {
            try { console.log("[XALOC-WS-TAP] !! error url=" + wsUrl); } catch(e) {}
        });
        ws.addEventListener("close", function(ev) {
            try { console.log("[XALOC-WS-TAP] close url=" + wsUrl + " code=" + ev.code + " reason=" + (ev.reason || "")); } catch(e) {}
        });
        return ws;
    };
    window.WebSocket.prototype = NativeWS.prototype;
})();
