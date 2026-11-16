/* Journal des versions : chargé depuis data/changelog.json. */
(function () {
  "use strict";
  var doc = document;
  var box = doc.getElementById("releases");
  if (!box) return;
  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  /* Mise en forme minimale et sûre : `code` et **gras** (texte échappé via les nœuds DOM). */
  function inline(parent, text) {
    var re = /`([^`]+)`|\*\*([^*]+)\*\*/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(doc.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) parent.appendChild(el("code", "", m[1]));
      else parent.appendChild(el("strong", "", m[2]));
      last = re.lastIndex;
    }
    if (last < text.length) parent.appendChild(doc.createTextNode(text.slice(last)));
  }
  function render(v, open) {
    var art = el("article", "release reveal");
    var h = el("h2", "", "Voktora " + v.version);
    if (v.date) { var t = el("time", "", v.date); t.setAttribute("datetime", v.date); h.appendChild(t); }
    art.appendChild(h);
    var body = art;
    if (!open) {
      body = el("details");
      body.appendChild(el("summary", "", "Afficher les changements"));
      art.appendChild(body);
    }
    v.sections.forEach(function (s) {
      if (s.title) body.appendChild(el("h3", "", s.title));
      var ul = el("ul");
      s.items.forEach(function (it) { var li = el("li"); inline(li, it); ul.appendChild(li); });
      body.appendChild(ul);
    });
    return art;
  }
  fetch("data/changelog.json").then(function (r) {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }).then(function (d) {
    box.textContent = "";
    (d.versions || []).forEach(function (v, i) {
      var a = render(v, i === 0);
      a.classList.add("in");
      box.appendChild(a);
    });
  }).catch(function () {
    box.textContent = "Impossible de charger le journal. Il est consultable dans CHANGELOG.md sur GitHub.";
  });
})();
