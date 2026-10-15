/* First-party, cookie-free visit beacon. Sends: page view, time on page, UI events.
   No cookies; a random per-tab session id lives in sessionStorage and disappears when the tab closes. */
(function () {
  var sid;
  try { sid = sessionStorage.getItem("sid"); if (!sid) { sid = Math.random().toString(36).slice(2, 12) + Date.now().toString(36); sessionStorage.setItem("sid", sid); } }
  catch (e) { sid = "nostore-" + Math.random().toString(36).slice(2, 10); }
  window.__sid = sid;
  var t0 = Date.now(), maxScroll = 0, sentLeave = false;
  function utm() {
    var q = new URLSearchParams(location.search), o = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "src", "ref", "gclid", "fbclid"].forEach(function (k) { if (q.get(k)) o[k] = q.get(k); });
    return o;
  }
  function send(body) {
    body.sid = sid; body.path = location.pathname;
    var data = JSON.stringify(body);
    try { if (navigator.sendBeacon && navigator.sendBeacon("/api/e", new Blob([data], { type: "text/plain" }))) return; } catch (e) {}
    try { fetch("/api/e", { method: "POST", body: data, keepalive: true, headers: { "Content-Type": "text/plain" } }); } catch (e) {}
  }
  window.__track = function (name, extra) { var b = { t: "ev", name: String(name).slice(0, 60) }; if (extra) b.utm = extra; send(b); };
  var conn = navigator.connection && navigator.connection.effectiveType;
  send({ t: "pv", ref: document.referrer || "", title: document.title.slice(0, 120), lang: navigator.language || "",
         tz: (Intl.DateTimeFormat().resolvedOptions().timeZone || ""), sw: screen.width, sh: screen.height,
         vw: window.innerWidth, vh: window.innerHeight, dpr: window.devicePixelRatio || 1,
         touch: ("ontouchstart" in window), conn: conn || "", utm: utm() });
  window.addEventListener("scroll", function () {
    var h = document.documentElement.scrollHeight - window.innerHeight;
    if (h > 0) maxScroll = Math.max(maxScroll, Math.round(100 * window.scrollY / h));
  }, { passive: true });
  function leave() { if (sentLeave) return; sentLeave = true; send({ t: "leave", secs: Math.round((Date.now() - t0) / 1000), scroll: maxScroll }); }
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden") leave(); });
  window.addEventListener("pagehide", leave);
})();
