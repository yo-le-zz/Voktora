"""
Voktora — icon_catalog.py
Données pures (sans Qt) sur les icônes : catalogue du sélecteur, correspondance emoji → icône,
détection des emojis dans un texte.

Les icônes viennent de la police Material Design Icons (assets/icons). Une icône est désignée par
un identifiant de la forme « mdi:nom » (ex. « mdi:rocket-launch »). Les champs « emoji » déjà
enregistrés (projets, catégories, statuts) restent valides : un emoji est converti en icône à
l'affichage grâce à EMOJI_TO_ICON, sans toucher aux données de l'utilisateur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PREFIX = "mdi:"
FALLBACK_ICON = "mdi:tag-outline"     # emoji sans équivalent connu


@dataclass(frozen=True)
class IconEntry:
    id: str          # « mdi:… »
    label: str       # nom affiché (français)
    keywords: str    # mots-clés de recherche, minuscules, sans accents


def _e(name: str, label: str, keywords: str = "") -> IconEntry:
    return IconEntry(PREFIX + name, label, f"{label} {keywords}".lower())


# Catégorie -> icônes. Les catégories reprennent celles de l'ancien sélecteur d'emoji.
CATEGORIES: dict[str, list[IconEntry]] = {
    "Projets & Tech": [
        _e("package-variant-closed", "Paquet", "boite projet colis"),
        _e("target", "Cible", "objectif but"),
        _e("rocket-launch", "Fusée", "lancement rapide"),
        _e("flash", "Éclair", "rapide energie"),
        _e("fire", "Feu", "populaire chaud"),
        _e("diamond-stone", "Diamant", "precieux qualite"),
        _e("star-four-points", "Étincelle", "etoile favori important"),
        _e("palette", "Palette", "design creatif couleur"),
        _e("tools", "Outils", "bricolage maintenance"),
        _e("bookshelf", "Bibliothèque", "livres documentation"),
        _e("microscope", "Microscope", "science recherche laboratoire"),
        _e("gamepad-variant", "Manette", "jeu gaming"),
        _e("web", "Web", "internet reseau site"),
        _e("cellphone", "Mobile", "telephone app smartphone"),
        _e("laptop", "Portable", "ordinateur dev"),
        _e("keyboard", "Clavier", "code saisie"),
        _e("monitor", "Écran", "bureau ordinateur"),
        _e("chart-bar", "Graphique", "stats donnees histogramme"),
        _e("chart-line", "Croissance", "progres statistiques courbe"),
        _e("folder-multiple", "Dossiers", "classement"),
        _e("folder", "Dossier", "fichiers"),
        _e("bug", "Bug", "debogage insecte"),
        _e("flask", "Fiole", "test experimentation chimie"),
        _e("puzzle", "Puzzle", "module plugin extension"),
        _e("code-braces", "Code", "accolades programmation"),
        _e("console", "Terminal", "console ligne de commande shell"),
        _e("git", "Git", "versions depot"),
        _e("github", "GitHub", "depot"),
        _e("database", "Base de données", "sql stockage"),
        _e("server", "Serveur", "backend hebergement"),
        _e("cloud", "Nuage", "cloud en ligne"),
        _e("robot", "Robot", "ia bot automatisation"),
        _e("api", "API", "interface service"),
        _e("cube-outline", "Cube", "3d module objet"),
        _e("application", "Application", "fenetre logiciel"),
        _e("language-python", "Python", "langage"),
        _e("language-javascript", "JavaScript", "langage js web"),
        _e("language-typescript", "TypeScript", "langage ts"),
        _e("language-rust", "Rust", "langage"),
        _e("language-cpp", "C++", "langage"),
        _e("language-java", "Java", "langage"),
        _e("language-go", "Go", "langage golang"),
        _e("language-html5", "HTML", "langage web"),
        _e("docker", "Docker", "conteneur"),
        _e("minecraft", "Minecraft", "jeu mod"),
        _e("chat", "Discussion", "discord bot messagerie"),
        _e("brain", "Cerveau", "intelligence idee"),
        _e("rocket", "Fusée (pleine)", "lancement"),
    ],
    "Sécurité": [
        _e("shield-lock", "Chiffré", "securise chiffre protege"),
        _e("lock", "Verrou", "verrouille prive cadenas"),
        _e("lock-open-variant", "Déverrouillé", "ouvert"),
        _e("key-variant", "Clé", "acces"),
        _e("shield-check", "Bouclier", "protection securite"),
        _e("cog", "Engrenage", "config parametres reglages"),
        _e("wrench", "Clé à molette", "outil reparation"),
        _e("hammer", "Marteau", "construction build"),
        _e("fingerprint", "Empreinte", "identite biometrie"),
        _e("eye", "Œil", "visible surveiller"),
    ],
    "Statuts": [
        _e("check-circle", "Validé", "termine ok fini"),
        _e("close-circle", "Échec", "erreur annule abandonne"),
        _e("timer-sand", "En cours", "attente sablier"),
        _e("alert", "Attention", "avertissement"),
        _e("hard-hat", "Travaux", "en construction chantier"),
        _e("circle", "Pastille", "rond couleur actif"),
        _e("pause-circle", "Pause", "suspendu"),
        _e("stop-circle", "Stop", "bloque arret"),
        _e("star", "Favori", "important etoile"),
        _e("flag-checkered", "Arrivée", "termine fin drapeau"),
        _e("new-box", "Nouveau", "recent debut"),
        _e("sync", "Synchronisation", "actualiser en cours"),
        _e("progress-wrench", "À améliorer", "maintenance"),
        _e("archive", "Archive", "ancien range"),
    ],
    "Réactions": [
        _e("emoticon-happy", "Content", "sourire heureux"),
        _e("emoticon-cool", "Cool", "stylé lunettes"),
        _e("head-question", "Réflexion", "pensif question"),
        _e("emoticon-neutral", "Neutre", "soulage"),
        _e("sleep", "Endormi", "pause inactif"),
        _e("party-popper", "Fête", "celebration"),
        _e("thumb-up", "Pouce levé", "ok approuve"),
        _e("thumb-down", "Pouce baissé", "refuse"),
        _e("lightbulb-on", "Idée", "ampoule astuce"),
        _e("heart", "Cœur", "favori aime"),
    ],
    "Nature & divers": [
        _e("sprout", "Pousse", "debut nouveau plante"),
        _e("tree", "Arbre", "croissance"),
        _e("looks", "Arc-en-ciel", "couleurs"),
        _e("white-balance-sunny", "Soleil", "jour"),
        _e("weather-night", "Lune", "nuit"),
        _e("alarm", "Réveil", "horloge temps rappel"),
        _e("calendar", "Calendrier", "date planning"),
        _e("email", "Courriel", "email message"),
        _e("bell", "Cloche", "notification alerte"),
        _e("trophy", "Trophée", "recompense"),
        _e("music", "Musique", "audio son"),
        _e("movie", "Film", "video"),
        _e("camera", "Photo", "image appareil"),
        _e("book-open-page-variant", "Livre", "lecture doc"),
        _e("home", "Maison", "accueil"),
        _e("airplane", "Avion", "voyage"),
    ],
}


def all_entries() -> list[IconEntry]:
    return [entry for entries in CATEGORIES.values() for entry in entries]


def entry_for(icon_id: str) -> IconEntry | None:
    return next((e for e in all_entries() if e.id == icon_id), None)


# ──────────────────────────────────────────────
# EMOJI → ICÔNE
# ──────────────────────────────────────────────

EMOJI_TO_ICON: dict[str, str] = {
    # projets & tech
    "📦": "package-variant-closed", "🎯": "target", "🚀": "rocket-launch", "⚡": "flash", "🔥": "fire",
    "💎": "diamond-stone", "🌟": "star-four-points", "🎨": "palette", "🛠": "tools", "📚": "bookshelf",
    "🔬": "microscope", "🎮": "gamepad-variant", "🌐": "web", "📱": "cellphone", "💻": "laptop",
    "⌨": "keyboard", "🖥": "monitor", "📊": "chart-bar", "📈": "chart-line", "🗂": "folder-multiple",
    "📁": "folder", "💽": "harddisk", "📂": "folder-open", "🐛": "bug", "🧪": "flask", "🧩": "puzzle", "🐙": "github",
    "🤖": "robot", "🧠": "brain", "🐳": "docker", "🐍": "language-python", "🦀": "language-rust",
    # sécurité
    "🔐": "shield-lock", "🔒": "lock", "🔓": "lock-open-variant", "🔑": "key-variant", "🛡": "shield-check",
    "⚙": "cog", "🔧": "wrench", "🔨": "hammer",
    # statuts
    "✅": "check-circle", "✔": "check", "❌": "close-circle", "✕": "close", "✖": "close", "⏳": "timer-sand",
    "⚠": "alert", "🚧": "hard-hat", "🟢": "circle", "🟡": "circle", "🔴": "circle", "🔵": "circle",
    "⭐": "star", "🏁": "flag-checkered", "🆕": "new-box", "🔄": "sync", "⟳": "refresh", "🗃": "archive",
    # réactions
    "😀": "emoticon-happy", "😎": "emoticon-cool", "🤔": "head-question", "😅": "emoticon-neutral",
    "😴": "sleep", "🥳": "party-popper", "👍": "thumb-up", "👎": "thumb-down", "💡": "lightbulb-on",
    "❤": "heart",
    # nature & divers
    "🌱": "sprout", "🌳": "tree", "🌈": "looks", "☀": "white-balance-sunny", "🌙": "weather-night",
    "⏰": "alarm", "📅": "calendar", "✉": "email", "🔔": "bell", "🏆": "trophy", "🎵": "music",
    "🎬": "movie", "📷": "camera", "🏠": "home", "✈": "airplane",
    # actions d'interface
    "📥": "tray-arrow-down", "📤": "tray-arrow-up", "⬇": "download", "⬆": "upload", "🔍": "magnify",
    "🔎": "magnify", "📝": "note-edit", "📋": "clipboard-text", "🗑": "delete", "💾": "content-save",
    "▶": "play", "⏸": "pause", "⏹": "stop", "➕": "plus", "➖": "minus", "🔗": "link-variant",
    "🏢": "domain", "👤": "account", "👥": "account-group", "🍴": "source-fork", "📌": "pin",
    "🔃": "sync", "🔁": "repeat", "📸": "camera", "🧱": "wall", "🪝": "hook", "🧹": "broom",
    "📦️": "package-variant-closed", "🔖": "bookmark", "🏷": "tag", "💬": "message-text", "ℹ": "information",
    "❓": "help-circle", "❗": "alert-circle", "🌍": "earth", "🖱": "cursor-default-click", "🖋": "pen",
    "✏": "pencil", "📄": "file-document", "📃": "file-document", "💼": "briefcase", "🧭": "compass",
    "📡": "satellite-variant", "🔌": "power-plug", "🔋": "battery", "🧰": "toolbox", "⚡️": "flash",
    "🛑": "stop-circle", "⛔": "cancel", "🚫": "cancel", "✨": "shimmer", "🎉": "party-popper",
    "🔥️": "fire", "💥": "alert-decagram", "📢": "bullhorn", "🕒": "clock-outline", "⏱": "timer-outline",
    "📜": "script-text", "🗒": "note-text", "📎": "paperclip", "🔀": "source-branch", "🌿": "source-branch",
    "🧬": "dna", "🎛": "tune", "🖼": "image", "🔊": "volume-high", "🔇": "volume-off", "🌑": "moon-waning-crescent",
    "🌞": "white-balance-sunny", "🌲": "pine-tree", "🐧": "linux", "🪟": "microsoft-windows",
}


def emoji_to_icon_id(emoji: str) -> str | None:
    """Icône (« mdi:… ») correspondant à un emoji, ou None s'il n'est pas connu."""
    key = emoji.replace("️", "").strip()
    name = EMOJI_TO_ICON.get(key) or EMOJI_TO_ICON.get(key[:1])
    return PREFIX + name if name else None


# ──────────────────────────────────────────────
# DÉTECTION DES EMOJIS
# ──────────────────────────────────────────────
# Volontairement SANS les flèches (→ ← ↔ …), les symboles mathématiques ni les formes géométriques
# (■ ●) : ils sont du texte ou des pastilles de couleur, pas des emojis, et la plupart des polices
# les affichent correctement.
_EMOJI_CHAR = (
    "[\U0001F000-\U0001FAFF"      # pictogrammes, symboles, émoticônes, drapeaux
    "⌀-⏿"               # techniques (⏳ ⏰ ⌨ ⏱)
    "☀-➿"               # divers (☀ ⚙ ⚠ ✅ ✔ ✕ ❌ ❤ ➕)
    "⟳"                      # ⟳
    "⬀-⯿"               # flèches/symboles divers (⬇ ⭐)
    "ℹ]"                     # ℹ
)
_CLUSTER = rf"{_EMOJI_CHAR}(?:[️‍\U0001F3FB-\U0001F3FF]|{_EMOJI_CHAR})*"
EMOJI_RE = re.compile(_CLUSTER)
_LEADING_RE = re.compile(rf"^(\s*)({_CLUSTER})\s*")
_WITH_SPACES_RE = re.compile(rf"{_CLUSTER}[ \t]*")


def contains_emoji(text: str) -> bool:
    return EMOJI_RE.search(text) is not None


def is_icon_id(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX) and len(value) > len(PREFIX)


def split_leading_emoji(text: str) -> tuple[str, str]:
    """("🚀", "Lancer") pour « 🚀  Lancer » ; ("", texte) s'il n'y a pas d'emoji en tête."""
    match = _LEADING_RE.match(text)
    if not match:
        return "", text
    return match.group(2), text[match.end():]


def strip_emoji(text: str) -> str:
    """Retire tous les emojis d'un texte, avec les espaces qui les suivent."""
    if not contains_emoji(text):
        return text
    return _WITH_SPACES_RE.sub("", text).strip(" \t")
