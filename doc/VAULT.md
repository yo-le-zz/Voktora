# Voktora — Vault & Sécurité

---

## Vue d'ensemble

Le vault Voktora stocke vos secrets sensibles chiffrés localement :

- Tokens GitHub (OAuth ou GitHub App)
- Clés SSH
- API keys (OpenAI, Discord, etc.)
- Variables `.env` sensibles
- Tout autre secret

**Chiffrement :** AES-256 via Fernet (`cryptography`)  
**Dérivation :** PBKDF2-HMAC-SHA256, 480 000 itérations, sel 32 octets  
**Par domaine :** chaque type de secret a sa propre clé dérivée

---

## Master Password

Au premier lancement, Voktora crée un **master password** :

1. Vous choisissez un mot de passe (≥ 8 caractères)
2. Un **verifier PBKDF2** est calculé et stocké (jamais le mot de passe lui-même)
3. La clé maître est gardée **en mémoire uniquement** pendant la session

Si vous oubliez le mot de passe maître, les secrets chiffrés sont **irrécupérables** (c'est voulu). Les données de projet (instances, intents, config) restent accessibles.

---

## Domaines

Chaque domaine a une clé AES-256 dérivée indépendante :

| Domaine | Usage |
|---------|-------|
| `github_token` | Token OAuth ou installation GitHub App |
| `ssh_key` | Clé privée SSH |
| `api_key` | Clés API tierces |
| `env_secret` | Variables `.env` sensibles |
| `general` | Tout autre secret |

Compromettre un domaine ne compromet **pas** les autres.

---

## Interface utilisateur

**Onglet Outils → Vault** dans le panneau projet :

- **Ajouter** : choisir clé, valeur, domaine, label
- **Afficher valeur** : déchiffrement à la demande
- **Supprimer** : suppression permanente

---

## API Python (pour plugins)

```python
import vault

# Stocker
vault.store("MY_API_KEY", "sk-abc123...", kind="api_key", label="OpenAI")

# Récupérer
key = vault.retrieve("MY_API_KEY")

# Lister
for entry in vault.list_entries():
    print(entry.key, entry.kind, entry.label)

# Supprimer
vault.delete("MY_API_KEY")

# Vérifier existence
if vault.exists("MY_API_KEY"):
    ...
```

---

## Stockage

Fichiers dans `~/.voktora/` :

- `voktora_config.json` → section `vault.secrets` : ciphertexts (chiffrés)
- `vault_meta.json` → métadonnées (clé, domaine, label, non chiffrées)

Le verifier et le sel global sont dans `voktora_config.json → vault.verifier / vault.salt`.
