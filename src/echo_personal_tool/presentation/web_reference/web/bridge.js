"use strict";

window.bridge = {
    _backend: null,
    _ready: false,
    _readyCallbacks: [],

    init() {
        if (typeof QWebChannel === "undefined") {
            console.warn("QWebChannel not available");
            this._ready = true;
            return Promise.resolve();
        }
        return new Promise(function (resolve) {
            new QWebChannel(qt.webChannelTransport, function (channel) {
                window.bridge._backend = channel.objects.backend;
                window.bridge._ready = true;
                window.bridge._readyCallbacks.forEach(function (cb) { cb(); });
                window.bridge._readyCallbacks = [];
                resolve();
            });
        });
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
                if (args.length === 0) self._backend[method](cb);
                else if (args.length === 1) self._backend[method](args[0], cb);
                else if (args.length === 2) self._backend[method](args[0], args[1], cb);
            });
        });
    },

    getTopics: function () { return this._call("get_topics"); },
    getTopicDetail: function (slug) { return this._call("get_topic_detail", slug); },
    getPathology: function (t, p) { return this._call("get_pathology", t, p); },
    search: function (q) { return this._call("search", q); },
};

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { window.bridge.init(); });
} else {
    window.bridge.init();
}
