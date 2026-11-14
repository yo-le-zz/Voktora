// Generators (JavaScript) — UUID, lorem ipsum, horodatages et couleurs aléatoires, copiés dans le presse-papiers.
const gen = require("./lib/gen.js");

voktora.options.addInt("paragraphs", "Paragraphes de lorem ipsum", 3, 1, 20);

function put(text, label) {
  voktora.setClipboardText(text);
  voktora.notify(label + " copié : " + (text.length > 60 ? text.slice(0, 57) + "…" : text));
}

voktora.addMenuAction("Outils/Générer", "UUID v4", () => put(gen.uuid4(), "UUID"));
voktora.addMenuAction("Outils/Générer", "Lorem ipsum", () => put(gen.lorem(voktora.options.get("paragraphs")), "Lorem ipsum"));
voktora.addMenuAction("Outils/Générer", "Horodatage ISO 8601", () => put(gen.timestamps().iso, "Horodatage"));
voktora.addMenuAction("Outils/Générer", "Horodatage Unix (secondes)", () => put(String(gen.timestamps().unix), "Horodatage Unix"));
voktora.addMenuAction("Outils/Générer", "Couleur hexadécimale", () => put(gen.hexColor(), "Couleur"));
voktora.addPaletteCommand("Générer un UUID", () => put(gen.uuid4(), "UUID"));
