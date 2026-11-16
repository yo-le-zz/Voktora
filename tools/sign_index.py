#!/usr/bin/env python3
"""Signature de l'index du marketplace (Ed25519).

    python tools/sign_index.py keygen                       # affiche la clé privée (À GARDER SECRÈTE) et la clé publique
    python tools/sign_index.py sign [--key-env VOKTORA_SIGNING_KEY] [marketplace/index.json]   # écrit index.json.sig
    python tools/sign_index.py verify [marketplace/index.json]   # vérifie avec TRUSTED_KEYS

Ajoutez la clé PUBLIQUE à TRUSTED_KEYS dans voktora/signing.py ; mettez la clé privée dans un secret CI.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "voktora"))
import signing  # noqa: E402


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    rest = [a for a in argv[2:] if not a.startswith("--")]
    index = Path(rest[0]) if rest else ROOT / "marketplace" / "index.json"
    if cmd == "keygen":
        private, public = signing.generate_keypair()
        print(f"Clé PRIVÉE (secret, ne la commitez jamais) : {private}\nClé publique (à mettre dans TRUSTED_KEYS de voktora/signing.py) : {public}")
        return 0
    if cmd == "sign":
        env = "VOKTORA_SIGNING_KEY"
        for a in argv:
            if a.startswith("--key-env="):
                env = a.split("=", 1)[1]
        key = os.environ.get(env, "")
        if not key:
            print(f"Variable {env} absente.", file=sys.stderr)
            return 2
        (index.with_name(signing.SIG_NAME)).write_text(signing.sign(index.read_bytes(), key) + "\n", encoding="utf-8")
        print(f"Signature écrite : {index.with_name(signing.SIG_NAME)}")
        return 0
    if cmd == "verify":
        keys = signing.trusted_keys()
        if not keys:
            print("Aucune clé de confiance configurée.", file=sys.stderr)
            return 2
        try:
            signing.verify(index.read_bytes(), index.with_name(signing.SIG_NAME).read_text(), keys)
        except (signing.SignatureError, OSError) as exc:
            print(f"ÉCHEC : {exc}", file=sys.stderr)
            return 1
        print("Signature valide.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
