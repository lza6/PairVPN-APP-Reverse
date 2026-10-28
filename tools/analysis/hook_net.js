// PairVPN 1.8.51 — 网络侦察 hook
// 目标: 抓出原生核心发起的所有 HTTP 请求、TCP 连接目标
setTimeout(function () {}, 0);

function log(tag, s) {
    console.log("[" + tag + "] " + s);
}

Java.perform(function () {
    try {
        var MyUtils = Java.use("com.pairvpn.MyUtils");
        MyUtils.getSslUrl.implementation = function (url) {
            log("HTTP", "GET " + url);
            var r = this.getSslUrl(url);
            try { log("HTTP-RESP", String(r).substring(0, 800)); } catch (e) {}
            return r;
        };
    } catch (e) { log("ERR", "MyUtils: " + e); }

    try {
        var Platform = Java.use("com.pairvpn.Platform");
        var m = Platform.getUrlResponse.overload("java.lang.String", "java.lang.String", "int");
        m.implementation = function (a, b, c) {
            log("URLREQ", "host=" + a + " url=" + b + " port=" + c);
            return m.call(this, a, b, c);
        };
    } catch (e) { log("ERR", "Platform: " + e); }

    // TCP 连接目标
    try {
        var Socket = Java.use("java.net.Socket");
        var ctor = Socket.$init.overload("java.lang.String", "int");
        ctor.implementation = function (h, p) {
            log("TCP", h + ":" + p);
            return ctor.call(this, h, p);
        };
    } catch (e) { log("ERR", "Socket: " + e); }

    // 裸 socket (native 自建) 看不到，但可监控 URL.openConnection
    try {
        var URL = Java.use("java.net.URL");
        var oc = URL.openConnection.overload();
        oc.implementation = function () {
            log("URLOBJ", this.toString());
            return oc.call(this);
        };
    } catch (e) { log("ERR", "URL: " + e); }

    // 原生库内的字符串活动
    try {
        var mods = Process.enumerateModules();
        var nat = mods.filter(function (m) { return m.name.indexOf("native-lib") >= 0; })[0];
        if (nat) log("MOD", nat.name + " base=" + nat.base + " size=" + nat.size);
    } catch (e) {}

    log("READY", "hooks installed");
});
