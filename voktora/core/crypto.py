"""
Voktora — core.crypto
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from . import config_store, constants

# ──────────────────────────────────────────────
# CRYPTO (Whirlpool / SHA-512 + XOR)
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# CHIFFREMENT AES-256 via Fernet (AES-128-CBC + HMAC-SHA256)
# Dérivation : PBKDF2-HMAC-SHA256, 480 000 itérations, sel 32 octets aléatoires
#
# Chaque appel à token_encrypt() génère un nouveau sel → les ciphertexts sont
# différents pour le même plaintext+password, ce qui est correct et attendu.
# ──────────────────────────────────────────────────────────────────────────────

def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 → clé 32 octets → encodée base64url pour Fernet."""
    import hashlib as _hl
    raw = _hl.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        constants.PBKDF2_ITERATIONS,
        dklen=constants.AES_KEY_BYTES,
    )
    return base64.urlsafe_b64encode(raw)   # Fernet attend une clé base64url 32B


def token_encrypt(plaintext: str, password: str) -> str:
    """
    Chiffre `plaintext` avec AES-256 (Fernet) dérivé de `password`.
    Format du blob : base64url( salt[32] || fernet_token )
    """
    from cryptography.fernet import Fernet
    salt      = os.urandom(constants.SALT_BYTES)
    fkey      = _derive_fernet_key(password, salt)
    f         = Fernet(fkey)
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    # Préfixer avec le sel pour le stockage
    blob = base64.urlsafe_b64encode(salt + base64.urlsafe_b64decode(encrypted))
    return blob.decode("ascii")


def token_decrypt(ciphertext: str, password: str) -> str:
    """
    Déchiffre un blob produit par token_encrypt().
    Retourne "" si le mot de passe est faux ou le blob corrompu.
    """
    try:
        from cryptography.fernet import Fernet
        raw       = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        salt      = raw[:constants.SALT_BYTES]
        fernet_tk = base64.urlsafe_b64encode(raw[constants.SALT_BYTES:])
        fkey      = _derive_fernet_key(password, salt)
        f         = Fernet(fkey)
        return f.decrypt(fernet_tk).decode("utf-8")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# VAULT — Master Password + dérivation de clé unique par domaine
#
# Au premier lancement, l'utilisateur choisit UN mot de passe maître.
# On dérive un verifier (PBKDF2) stocké dans la config pour valider les
# saisies futures. On dérive aussi une clé AES-256 par "domaine"
# (github_token, ssh_key, api_key, env_secret…) via HKDF-like construction :
#   domain_key = PBKDF2(master_password, salt_domain, 480000)
# Ainsi compromettre un secret ne compromet pas les autres.
# ──────────────────────────────────────────────────────────────────────────────

_VAULT_MASTER_KEY: bytes | None = None   # clé en mémoire uniquement (session)

_VAULT_VERIFIER_ITER = 480_000
_VAULT_VERIFIER_LEN  = 64


def vault_is_initialized() -> bool:
    """True si un master password a déjà été créé."""
    cfg = config_store._load_config()
    return bool(cfg.get("vault", {}).get("verifier"))


def vault_init(master_password: str) -> None:
    """
    Initialise le vault avec le mot de passe maître.
    Calcule le verifier (PBKDF2) et le sel global. Ne stocke PAS le mot de passe.
    """
    global _VAULT_MASTER_KEY
    salt     = os.urandom(constants.SALT_BYTES)
    verifier = hashlib.pbkdf2_hmac(
        "sha256", master_password.encode(), salt,
        _VAULT_VERIFIER_ITER, dklen=_VAULT_VERIFIER_LEN,
    )
    cfg = config_store._load_config()
    cfg["vault"] = {
        "verifier": base64.b64encode(verifier).decode(),
        "salt":     base64.b64encode(salt).decode(),
    }
    config_store._save_config(cfg)
    # Dériver la clé maître en mémoire
    _VAULT_MASTER_KEY = _pbkdf2_raw(master_password, salt)


def vault_unlock(master_password: str) -> bool:
    """
    Vérifie le mot de passe et charge la clé maître en mémoire.
    Retourne True si correct.
    """
    global _VAULT_MASTER_KEY
    cfg  = config_store._load_config()
    info = cfg.get("vault", {})
    if not info.get("verifier") or not info.get("salt"):
        return False
    salt     = base64.b64decode(info["salt"])
    expected = base64.b64decode(info["verifier"])
    actual   = hashlib.pbkdf2_hmac(
        "sha256", master_password.encode(), salt,
        _VAULT_VERIFIER_ITER, dklen=_VAULT_VERIFIER_LEN,
    )
    if not hmac.compare_digest(expected, actual):
        return False
    _VAULT_MASTER_KEY = _pbkdf2_raw(master_password, salt)
    return True


def vault_is_unlocked() -> bool:
    return _VAULT_MASTER_KEY is not None


def vault_lock() -> None:
    global _VAULT_MASTER_KEY
    _VAULT_MASTER_KEY = None


def _pbkdf2_raw(password: str, salt: bytes) -> bytes:
    """Dérive 32 octets bruts pour usage interne."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, constants.PBKDF2_ITERATIONS, dklen=constants.AES_KEY_BYTES
    )


def _vault_domain_key(domain: str) -> bytes:
    """
    Dérive une clé Fernet spécifique à un domaine depuis la clé maître.
    Chaque domaine (github_token, ssh_key, api_key…) a sa propre clé.
    """
    if _VAULT_MASTER_KEY is None:
        raise RuntimeError("Vault verrouillé — appelez vault_unlock() d'abord.")
    cfg  = config_store._load_config()
    salt = base64.b64decode(cfg["vault"]["salt"])
    domain_salt = hashlib.sha256(salt + domain.encode()).digest()
    raw  = hashlib.pbkdf2_hmac(
        "sha256", _VAULT_MASTER_KEY, domain_salt, 1, dklen=constants.AES_KEY_BYTES
    )
    return base64.urlsafe_b64encode(raw)


def vault_encrypt(plaintext: str, domain: str) -> str:
    """Chiffre `plaintext` avec la clé dérivée pour `domain`."""
    from cryptography.fernet import Fernet
    key = _vault_domain_key(domain)
    return Fernet(key).encrypt(plaintext.encode()).decode()


def vault_decrypt(ciphertext: str, domain: str) -> str:
    """Déchiffre un secret du vault. Retourne "" si échoue."""
    try:
        from cryptography.fernet import Fernet
        key = _vault_domain_key(domain)
        return Fernet(key).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


def vault_store(key: str, value: str, domain: str = "general") -> None:
    """Stocke un secret chiffré dans la config sous vault.secrets.<key>."""
    cfg = config_store._load_config()
    cfg.setdefault("vault", {}).setdefault("secrets", {})[key] = {
        "domain":     domain,
        "ciphertext": vault_encrypt(value, domain),
    }
    config_store._save_config(cfg)


def vault_retrieve(key: str) -> str:
    """Récupère et déchiffre un secret du vault. Retourne "" si absent/verrouillé."""
    cfg    = config_store._load_config()
    entry  = cfg.get("vault", {}).get("secrets", {}).get(key)
    if not entry:
        return ""
    return vault_decrypt(entry["ciphertext"], entry.get("domain", "general"))


def vault_delete(key: str) -> None:
    cfg = config_store._load_config()
    cfg.get("vault", {}).get("secrets", {}).pop(key, None)
    config_store._save_config(cfg)


def vault_list_keys() -> list[str]:
    cfg = config_store._load_config()
    return list(cfg.get("vault", {}).get("secrets", {}).keys())


# ──────────────────────────────────────────────
