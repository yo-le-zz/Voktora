// JSON Clipboard (JavaScript) — formate, minifie, trie et valide le JSON du presse-papiers.
const j = require("./lib/jsonfmt.js");

function run(label, fn) {
  const text = voktora.clipboardText();
  if (!text || !text.trim()) { voktora.notify("Le presse-papiers est vide."); return; }
  try {
    voktora.setClipboardText(fn(text));
    voktora.notify(label + " — résultat copié");
  } catch (e) {
    voktora.notify(e.message);
  }
}

voktora.options.addChoice("indent", "Indentation", ["2", "4", "tab"], "2");
const indent = () => { const v = voktora.options.get("indent"); return v === "tab" ? "tab" : Number(v); };

voktora.addMenuAction("Outils/JSON", "Formater", () => run("Formaté", (t) => j.format(t, indent())));
voktora.addMenuAction("Outils/JSON", "Minifier", () => run("Minifié", (t) => j.minify(t)));
voktora.addMenuAction("Outils/JSON", "Trier les clés", () => run("Clés triées", (t) => j.sorted(t, indent())));
voktora.addMenuAction("Outils/JSON", "Valider / résumer", () => {
  voktora.showMarkdown("JSON", "**" + j.summary(voktora.clipboardText()) + "**");
});
voktora.addPaletteCommand("JSON : formater le presse-papiers", () => run("Formaté", (t) => j.format(t, indent())));
