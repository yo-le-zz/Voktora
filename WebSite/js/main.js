/* Voktora — comportements communs : thème, onglets, copie, apparitions, frappe.
   Le contenu essentiel reste lisible sans ce script. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.add("js");

  function store(key, val) {
    try { if (val === undefined) return localStorage.getItem(key); localStorage.setItem(key, val); } catch (e) { /* stockage indisponible */ }
    return null;
  }

  /* ---------- Thème clair / sombre ---------- */
  function effectiveTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  var SUN = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg>';
  var themeBtn = doc.getElementById("theme-toggle");
  function paintThemeBtn() {
    if (!themeBtn) return;
    var dark = effectiveTheme() === "dark";
    themeBtn.innerHTML = dark ? SUN : MOON;
    themeBtn.setAttribute("aria-label", dark ? "Passer au thème clair" : "Passer au thème sombre");
    themeBtn.title = themeBtn.getAttribute("aria-label");
  }
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = effectiveTheme() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      store("voktora-theme", next);
      paintThemeBtn();
    });
    paintThemeBtn();
  }

  /* ---------- Onglets ARIA (avec indicateur glissant) ---------- */
  function initTabs(box) {
    var list = box.querySelector(":scope > .tabs");
    if (!list) return null;
    var tabs = Array.prototype.slice.call(list.querySelectorAll(':scope > [role="tab"]'));
    var panels = tabs.map(function (t) { return doc.getElementById(t.getAttribute("aria-controls")); });
    var ind = null;
    if (!list.classList.contains("sub-tabs")) {
      ind = doc.createElement("span"); ind.className = "tab-ind"; ind.setAttribute("aria-hidden", "true");
      list.appendChild(ind);
    }
    function moveInd() {
      var sel = tabs.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0];
      if (!ind || !sel) return;
      ind.style.width = sel.offsetWidth + "px";
      ind.style.transform = "translateX(" + sel.offsetLeft + "px)";
    }
    function select(tab, focus, animate) {
      tabs.forEach(function (t, i) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        if (panels[i]) {
          panels[i].hidden = !on;
          if (on && animate && !reduce) {
            panels[i].classList.remove("in-anim"); void panels[i].offsetWidth; panels[i].classList.add("in-anim");
          }
        }
      });
      if (focus) tab.focus();
      moveInd();
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { select(tab, false, true); });
      tab.addEventListener("keydown", function (e) {
        var n = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") n = tabs[(i + 1) % tabs.length];
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = tabs[(i - 1 + tabs.length) % tabs.length];
        else if (e.key === "Home") n = tabs[0];
        else if (e.key === "End") n = tabs[tabs.length - 1];
        if (n) { e.preventDefault(); select(n, true, true); }
      });
    });
    window.addEventListener("resize", moveInd);
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(moveInd);
    var initial = tabs.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0] || tabs[0];
    select(initial, false, false);
    return { select: select, tabs: tabs };
  }
  var groups = {};
  Array.prototype.forEach.call(doc.querySelectorAll("[data-tabs]"), function (box) {
    var g = initTabs(box);
    if (g) groups[box.dataset.tabs] = g;
  });

  /* Détection de l'OS : onglet principal des méthodes d'installation */
  var osGroup = groups.os;
  if (osGroup) {
    var ua = navigator.userAgent || "", plat = navigator.platform || "";
    var os = /Win/i.test(plat) || /Windows/i.test(ua) ? "windows" : /Mac/i.test(plat) && !/iPhone|iPad/i.test(ua) ? "macos" : /Linux|X11|CrOS/i.test(plat + ua) && !/Android/i.test(ua) ? "linux" : "sources";
    var target = osGroup.tabs.filter(function (t) { return t.dataset.os === os; })[0];
    if (target) osGroup.select(target, false, false);
    var note = doc.getElementById("os-detected");
    if (note) note.textContent = os === "windows" ? "Windows détecté." : os === "macos" ? "macOS détecté." : os === "linux" ? "Linux détecté." : "Aucun paquet pour ce système : installation depuis les sources.";
  }

  /* ---------- Bouton Copier ---------- */
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (ok, ko) {
      var ta = doc.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;opacity:0;top:0";
      doc.body.appendChild(ta); ta.select();
      try { doc.execCommand("copy") ? ok() : ko(); } catch (e) { ko(e); } finally { doc.body.removeChild(ta); }
    });
  }
  Array.prototype.forEach.call(doc.querySelectorAll(".term"), function (term) {
    var bar = term.querySelector(".term-bar"), code = term.querySelector("pre code");
    if (!bar || !code || bar.querySelector(".copy")) return;
    var b = doc.createElement("button");
    b.type = "button"; b.className = "copy"; b.textContent = "Copier";
    b.setAttribute("aria-label", "Copier les commandes");
    var timer;
    b.addEventListener("click", function () {
      var text = code.dataset.copy || code.textContent;
      copyText(text.replace(/\s+$/, "")).then(function () {
        b.textContent = "Copié"; b.classList.add("done");
      }, function () {
        b.textContent = "Échec";
      }).then(function () {
        clearTimeout(timer);
        timer = setTimeout(function () { b.textContent = "Copier"; b.classList.remove("done"); }, 1600);
      });
    });
    bar.appendChild(b);
  });

  /* ---------- Apparition au défilement ---------- */
  var reveals = Array.prototype.slice.call(doc.querySelectorAll(".reveal"));
  if (reveals.length) {
    if (!("IntersectionObserver" in window) || reduce) {
      reveals.forEach(function (el) { el.classList.add("in"); });
    } else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
        });
      }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
      reveals.forEach(function (el, i) {
        if (!el.style.getPropertyValue("--d")) el.style.setProperty("--d", (i % 4) * 0.05 + "s");
        io.observe(el);
      });
    }
  }

  /* ---------- Frappe de la commande à l'arrivée (une seule fois, non bloquante) ---------- */
  var typed = Array.prototype.slice.call(doc.querySelectorAll("[data-type]")).filter(function (t) { return t.offsetParent !== null; })[0];
  if (typed && !reduce && "IntersectionObserver" in window) {
    var code = typed.querySelector("pre code");
    var full = code.innerHTML, plain = code.textContent;
    var done = false;
    var tio = new IntersectionObserver(function (entries) {
      if (done || !entries[0].isIntersecting) return;
      done = true; tio.disconnect();
      var pre = code.parentNode;
      pre.style.minHeight = pre.offsetHeight + "px";
      var cur = '<span class="cursor" aria-hidden="true"></span>';
      var i = 0, step = Math.max(2, Math.ceil(plain.length / 70));
      (function tick() {
        i = Math.min(plain.length, i + step);
        var text = plain.slice(0, i).replace(/&/g, "&amp;").replace(/</g, "&lt;");
        if (i < plain.length) { code.innerHTML = text + cur; setTimeout(tick, 16); }
        else { code.innerHTML = full; pre.style.minHeight = ""; }
      })();
    }, { threshold: 0.6 });
    tio.observe(typed);
  }
})();
