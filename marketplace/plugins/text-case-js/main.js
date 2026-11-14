// Text Case (JavaScript) — convertit le texte du presse-papiers : casse, lignes, statistiques.
const cases = require("./lib/cases.js");

const CASES = [
  ["camel", "camelCase"], ["pascal", "PascalCase"], ["snake", "snake_case"], ["kebab", "kebab-case"],
  ["constant", "CONSTANT_CASE"], ["title", "Title Case"], ["sentence", "Phrase"], ["slug", "slug-sans-accents"],
  ["upper", "MAJUSCULES"], ["lower", "minuscules"],
];
const LINES = [
  ["sort", "Trier A→Z"], ["sortReverse", "Trier Z→A"], ["unique", "Supprimer les doublons"], ["reverse", "Inverser l'ordre"],
  ["trim", "Retirer les espaces de fin"], ["dropEmpty", "Supprimer les lignes vides"], ["number", "Numéroter"],
];

function transform(fn, label) {
  const text = voktora.clipboardText();
  if (!text) { voktora.notify("Le presse-papiers est vide."); return; }
  try {
    voktora.setClipboardText(fn(text));
    voktora.notify(label + " — résultat copié");
  } catch (e) {
    voktora.notify("Échec : " + e.message);
  }
}

CASES.forEach(([kind, label]) => {
  const run = () => transform((t) => cases.convert(kind, t), label);
  voktora.addMenuAction("Outils/Texte (casse)", label, run);
});
LINES.forEach(([kind, label]) => {
  const run = () => transform((t) => cases.applyLines(kind, t), label);
  voktora.addMenuAction("Outils/Texte (lignes)", label, run);
});
voktora.addMenuAction("Outils/Texte (casse)", "Statistiques du presse-papiers", () => {
  const s = cases.stats(voktora.clipboardText());
  voktora.showMarkdown("Statistiques", "| Mesure | Valeur |\n|---|---:|\n| Caractères | " + s.chars + " |\n| Mots | " + s.words + " |\n| Lignes | " + s.lines + " |\n");
});
voktora.addPaletteCommand("Texte : convertir le presse-papiers…", () => {
  const labels = CASES.map((c) => c[1]).concat(LINES.map((c) => c[1]));
  const pick = voktora.askChoice("Texte", "Appliquer au presse-papiers :", labels);
  if (!pick) return;
  const i = labels.indexOf(pick);
  if (i < CASES.length) transform((t) => cases.convert(CASES[i][0], t), pick);
  else transform((t) => cases.applyLines(LINES[i - CASES.length][0], t), pick);
});
