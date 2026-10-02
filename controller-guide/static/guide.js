// Controller Guide: search filter, print buttons, ?only=<slug> for print documents.
(function () {
  "use strict";

  // Home Assistant serves /local with a 31-day cache. Printed QR codes can't
  // carry a version, so pages ask for version.txt (uncached) on load, when
  // shown again (back/forward cache, tab switch) and every 10 minutes while
  // visible, and reload with the new ?v= when a newer build is deployed.
  var mine = document.body.getAttribute("data-version");
  function checkVersion() {
    if (!mine || location.protocol.indexOf("http") !== 0 || !window.fetch) return;
    fetch(document.body.getAttribute("data-root") + "version.txt?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (latest) {
        latest = latest.trim();
        if (!latest || latest === mine) return;
        var u = new URL(location.href);
        var key = "guide-reload-" + latest;
        if (u.searchParams.get("v") === latest) {
          // Asked for the new build but still got the old page: retry once
          // with a unique query, then give up rather than loop.
          try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, "1"); } catch (e) { return; }
          u.searchParams.set("r", String(Date.now()));
        }
        u.searchParams.set("v", latest);
        location.replace(u.toString());
      })
      .catch(function () {});
  }
  checkVersion();
  window.addEventListener("pageshow", function (e) { if (e.persisted) checkVersion(); });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) checkVersion(); });
  setInterval(function () { if (!document.hidden) checkVersion(); }, 10 * 60 * 1000);

  document.querySelectorAll("[data-print]").forEach(function (btn) {
    btn.addEventListener("click", function () { window.print(); });
  });

  // ?only=slug or ?only=slug1,slug2 prints just those controllers.
  var only = new URLSearchParams(location.search).get("only");
  if (only) {
    var wanted = only.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    var sheets = Array.prototype.slice.call(document.querySelectorAll(".print-sheet"));
    if (sheets.length) {
      // Multi-up sheets: keep the wanted slots and repack them from the first sheet on.
      var per = sheets[0].classList.contains("two-up") ? 2 : 10;
      var slots = Array.prototype.slice.call(document.querySelectorAll(".print-sheet > .slot, .print-sheet > .cell"))
        .filter(function (s) { var el = s.querySelector("[data-slug]"); return el && wanted.indexOf(el.getAttribute("data-slug")) !== -1; });
      if (slots.length) {
        sheets.forEach(function (sh) { sh.querySelectorAll(".slot, .cell").forEach(function (x) { x.remove(); }); });
        slots.forEach(function (slot, i) {
          var sh = sheets[Math.floor(i / per)];
          var crops = sh.querySelector(".crops");
          slot.className = slot.className.replace(/slot-\d/, "slot-" + ((i % per) + 1));
          sh.insertBefore(slot, crops);
        });
        sheets.forEach(function (sh) { if (!sh.querySelector(".slot, .cell")) sh.remove(); });
      }
    } else {
      var pages = document.querySelectorAll("[data-slug]");
      var shown = 0;
      pages.forEach(function (p) {
        var match = wanted.indexOf(p.getAttribute("data-slug")) !== -1;
        p.hidden = !match;
        if (match) shown++;
      });
      if (!shown) pages.forEach(function (p) { p.hidden = false; });
    }
    var note = document.querySelector("[data-only-note]");
    if (note) note.hidden = false;
  }

  var cut = document.querySelector("[data-cutlines]");
  if (cut) cut.addEventListener("change", function () { document.body.classList.toggle("cutlines", cut.checked); });

  var q = document.getElementById("q");
  if (q) {
    var entries = Array.prototype.slice.call(document.querySelectorAll(".entry[data-search]"));
    var empty = document.getElementById("no-results");
    q.addEventListener("input", function () {
      var terms = q.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      var visible = 0;
      entries.forEach(function (e) {
        var hay = e.getAttribute("data-search");
        var hit = terms.every(function (t) { return hay.indexOf(t) !== -1; });
        e.hidden = !hit;
        if (hit) visible++;
      });
      document.querySelectorAll(".floor").forEach(function (f) {
        var any = f.querySelector(".entry[data-search]:not([hidden])");
        if (f.querySelector(".entry[data-search]")) f.hidden = !any;
      });
      if (empty) empty.hidden = visible !== 0;
    });
  }
})();
