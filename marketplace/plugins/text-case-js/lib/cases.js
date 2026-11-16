// Conversions de casse et nettoyage de texte — fonctions pures, sans API Voktora (testables avec node).
"use strict";

function stripAccents(s) {
  if (typeof s.normalize === "function") return s.normalize("NFD").replace(/[̀-ͯ]/g, "");
  return s;
}

// « maCléHTTP_v2-test » -> ["ma", "clé", "HTTP", "v2", "test"]
function words(text) {
  return String(text)
    .replace(/([a-zà-ÿ0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-zà-ÿ])/g, "$1 $2")
    .split(/[^A-Za-z0-9À-ÿ]+/)
    .filter(Boolean);
}

const lower = (w) => w.toLowerCase();
const cap = (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();

const converters = {
  camel: (t) => words(t).map((w, i) => (i === 0 ? lower(w) : cap(w))).join(""),
  pascal: (t) => words(t).map(cap).join(""),
  snake: (t) => words(t).map(lower).join("_"),
  kebab: (t) => words(t).map(lower).join("-"),
  constant: (t) => words(t).map((w) => w.toUpperCase()).join("_"),
  title: (t) => words(t).map(cap).join(" "),
  sentence: (t) => { const w = words(t).map(lower).join(" "); return w.charAt(0).toUpperCase() + w.slice(1); },
  upper: (t) => String(t).toUpperCase(),
  lower: (t) => String(t).toLowerCase(),
  slug: (t) => words(stripAccents(String(t))).map(lower).join("-"),
};

function convert(kind, text) {
  if (!converters[kind]) throw new Error("conversion inconnue : " + kind);
  return converters[kind](text);
}

// Opérations ligne par ligne
const lineOps = {
  sort: (ls) => ls.slice().sort((a, b) => a.localeCompare(b)),
  sortReverse: (ls) => ls.slice().sort((a, b) => b.localeCompare(a)),
  unique: (ls) => { const seen = {}; return ls.filter((l) => (seen[l] ? false : (seen[l] = true))); },
  reverse: (ls) => ls.slice().reverse(),
  trim: (ls) => ls.map((l) => l.replace(/\s+$/, "")),
  dropEmpty: (ls) => ls.filter((l) => l.trim() !== ""),
  number: (ls) => ls.map((l, i) => String(i + 1) + ". " + l),
};

function applyLines(kind, text) {
  if (!lineOps[kind]) throw new Error("opération inconnue : " + kind);
  const trailing = /\n$/.test(text);
  const lines = String(text).replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n");
  return lineOps[kind](lines).join("\n") + (trailing ? "\n" : "");
}

function stats(text) {
  const t = String(text);
  return { chars: t.length, words: (t.match(/\S+/g) || []).length, lines: t === "" ? 0 : t.split(/\r?\n/).length };
}

module.exports = { words, convert, applyLines, stats, kinds: Object.keys(converters), lineKinds: Object.keys(lineOps) };
