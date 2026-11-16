/* Liste des plugins : chargée depuis data/plugins.json, recherche + filtres côté client. */
(function () {
  "use strict";
  var doc = document;
  var grid = doc.getElementById("plugin-grid");
  if (!grid) return;
  var status = doc.getElementById("plugin-status");
  var search = doc.getElementById("plugin-search");
  var langBox = doc.getElementById("lang-chips");
  var tagBox = doc.getElementById("tag-chips");
  var state = { q: "", lang: "", tag: "" };
  var all = [];
  var LANG = { python: "Python", js: "JavaScript", rust: "Rust" };

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function norm(s) { return String(s).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }

  function chips(box, values, key, label) {
    box.textContent = "";
    [""].concat(values).forEach(function (v) {
      var b = el("button", "tag", v ? (label ? label(v) : v) : "Tous");
      b.type = "button";
      b.setAttribute("aria-pressed", String(state[key] === v));
      if (state[key] === v) b.classList.add("on");
      b.addEventListener("click", function () { state[key] = v; paint(); });
      box.appendChild(b);
    });
  }

  function paint() {
    var q = norm(state.q.trim());
    var list = all.filter(function (p) {
      if (state.lang && p.lang !== state.lang) return false;
      if (state.tag && p.tags.indexOf(state.tag) < 0) return false;
      if (!q) return true;
      return norm([p.id, p.name, p.description, p.tags.join(" ")].join(" ")).indexOf(q) >= 0;
    });
    grid.textContent = "";
    list.forEach(function (p) {
      var c = el("article", "card");
      c.appendChild(el("h3", "", p.name));
      c.appendChild(el("p", "", p.description));
      var meta = el("div", "meta");
      meta.appendChild(el("span", "tag lang", LANG[p.lang] || p.lang));
      p.tags.forEach(function (t) { meta.appendChild(el("span", "tag", t)); });
      meta.appendChild(el("span", "tag", "v" + p.version));
      c.appendChild(meta);
      grid.appendChild(c);
    });
    status.textContent = list.length ? list.length + " plugin" + (list.length > 1 ? "s" : "") + " sur " + all.length : "Aucun plugin ne correspond.";
    chips(langBox, uniq(all.map(function (p) { return p.lang; })), "lang", function (v) { return LANG[v] || v; });
    var flat = [].concat.apply([], all.map(function (p) { return p.tags; }));
    chips(tagBox, uniq(flat).filter(function (t) { return flat.filter(function (x) { return x === t; }).length > 1 || state.tag === t; }), "tag");
  }
  function uniq(a) { return a.filter(function (v, i) { return a.indexOf(v) === i; }).sort(); }

  fetch("data/plugins.json").then(function (r) {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }).then(function (d) {
    all = d.plugins || [];
    Array.prototype.forEach.call(doc.querySelectorAll("[data-count]"), function (n) {
      var k = n.dataset.count;
      var v = k === "plugins" ? d.count : d.shops && d.shops[k];
      if (v !== undefined) n.textContent = v;
    });
    var fb = doc.getElementById("plugin-fallback");
    if (fb) fb.hidden = true;
    if (search) search.addEventListener("input", function () { state.q = search.value; paint(); });
    paint();
  }).catch(function () {
    status.textContent = "Impossible de charger la liste. Elle est consultable dans le dépôt : marketplace/index.json.";
  });
})();
