# Voktora — Templates de projets

Lors de la création d'une instance, choisissez un template pour générer automatiquement la structure du projet.

---

## Templates disponibles

### 🐍 Python
```
mon_projet/
├── src/
│   ├── __init__.py
│   └── main.py
├── tests/
│   ├── __init__.py
│   └── test_main.py
├── .gitignore
├── README.md
└── pyproject.toml
```
Post-création : `uv venv`, `git init`, commit initial.

---

### ⚡ C++
```
mon_projet/
├── src/
│   └── main.cpp
├── include/
├── CMakeLists.txt
├── .gitignore
└── README.md
```
Post-création : `git init`, commit initial.

---

### 🌐 Web App
```
mon_projet/
├── index.html
├── style.css
├── main.js
├── .gitignore
└── README.md
```
Post-création : `git init`, commit initial.

---

### 🤖 Discord Bot (Python)
```
mon_projet/
├── bot.py
├── .env               ← DISCORD_TOKEN=...
├── .env.example
├── requirements.txt   ← discord.py, python-dotenv
├── .gitignore         ← .env exclue automatiquement
└── README.md
```
Post-création : `uv venv`, `git init`, commit initial.

---

### 🧱 Minecraft Mod (Fabric/Java)
```
mon_projet/
├── src/main/java/mod/
│   └── Main.java
├── src/main/resources/
│   └── fabric.mod.json
├── build.gradle
├── .gitignore
└── README.md
```
Post-création : `git init`, commit initial.

---

### 📄 Vide
```
mon_projet/
├── README.md
└── .gitignore
```
Post-création : `git init`, commit initial.

---

## Variables de template

Dans les fichiers générés, les variables suivantes sont remplacées :

| Variable | Valeur |
|----------|--------|
| `{name}` | Nom du projet |
| `{name_lower}` | Nom en minuscules, underscores |

---

## Ajouter un template personnalisé

Modifiez `BUILTIN_TEMPLATES` dans `src/templates.py` :

```python
"mon_template": {
    "label": "🚀  Mon Template",
    "desc":  "Description courte",
    "files": {
        "src/main.py":  "# {name}\nif __name__ == '__main__':\n    pass\n",
        "README.md":    "# {name}\n",
        ".gitignore":   "__pycache__/\n",
    },
    "post_cmds": ["git init", "git add .", 'git commit -m "init: {name}"'],
},
```
