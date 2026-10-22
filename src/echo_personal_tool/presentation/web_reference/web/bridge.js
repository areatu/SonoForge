"use strict";

window.bridge = {
    _backend: null,
    _ready: false,
    _readyCallbacks: [],
    _initPromise: null,

    init() {
        if (this._initPromise) return this._initPromise;
        if (typeof QWebChannel === "undefined") {
            console.warn("QWebChannel not available");
            this._ready = true;
            this._initPromise = Promise.resolve();
            return this._initPromise;
        }
        this._initPromise = new Promise(function (resolve) {
            try {
                new QWebChannel(qt.webChannelTransport, function (channel) {
                    window.bridge._backend = channel.objects.backend;
                    window.bridge._ready = true;
                    window.bridge._readyCallbacks.forEach(function (cb) { cb(); });
                    window.bridge._readyCallbacks = [];
                    resolve();
                });
            } catch (e) {
                console.error("QWebChannel init failed:", e);
                window.bridge._ready = true;
                resolve();
            }
        });
        return this._initPromise;
    },

    whenReady() {
        if (this._ready) return Promise.resolve();
        return new Promise(function (resolve) { window.bridge._readyCallbacks.push(resolve); });
    },

    _call(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        var self = this;
        return this.whenReady().then(function () {
            if (!self._backend) return { error: "Bridge not connected" };
            return new Promise(function (resolve) {
                var cb = function (raw) {
                    try { resolve(JSON.parse(raw)); }
                    catch (e) { resolve({ error: "Invalid JSON" }); }
                };
                try {
                    var callArgs = args.concat([cb]);
                    self._backend[method].apply(self._backend, callArgs);
                } catch (e) {
                    resolve({ error: "Call failed: " + e.message });
                }
            });
        });
    },

    getTopics: function () { return this._call("get_topics"); },
    getTopicDetail: function (slug) { return this._call("get_topic_detail", slug); },
    getPathology: function (t, p) { return this._call("get_pathology", t, p); },
    search: function (q) { return this._call("search", q); },
    updateParam: function (t, p, id, field, value) { return this._call("update_param", t, p, id, field, value); },
    updateGradation: function (t, p, id, grad, male, female) { return this._call("update_gradation", t, p, id, grad, male, female); },
    reloadStore: function () { return this._call("reload_store"); },
    getUiStrings: function () { return this._call("get_ui_strings"); },
};

// Wait for qt to be available, then initialize. Retries are bounded so we don't
// spin forever when QWebChannel never appears — the Python side has its own
// 5s fallback timer that detects the failure.
var _initAttempts = 0;
function tryInit() {
    if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
        window.bridge.init();
        return;
    }
    _initAttempts++;
    if (_initAttempts <= 100) {
        setTimeout(tryInit, 50);
    } else if (_initAttempts === 101) {
        console.warn("QWebChannel did not become available; bridge offline");
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(tryInit, 0); });
} else {
    setTimeout(tryInit, 0);
}
