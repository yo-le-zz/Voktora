"""Modèle : requêtes, collections, environnements (JSON simple, versionné)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
BODY_TYPES = ("none", "json", "text", "xml", "form", "multipart")
AUTH_TYPES = ("none", "basic", "bearer", "apikey", "oauth2")


@dataclass
class Request:
    name: str = "Nouvelle requête"
    method: str = "GET"
    url: str = ""
    headers: list = field(default_factory=list)        # [{"key","value","enabled"}]
    params: list = field(default_factory=list)
    body_type: str = "none"
    body: str = ""                                      # json/text/xml : texte ; form/multipart : voir body_fields
    body_fields: list = field(default_factory=list)     # [{"key","value","file"?}]
    auth: dict = field(default_factory=lambda: {"type": "none"})
    pre_script: dict = field(default_factory=lambda: {"lang": "python", "code": ""})
    post_script: dict = field(default_factory=lambda: {"lang": "python", "code": ""})
    extract: list = field(default_factory=list)         # chaînage : [{"var","source","expr"}]
    tests: list = field(default_factory=list)           # [{"kind","expr","op","value"}]
    timeout: float = 30.0
    follow_redirects: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Request:
        return Request(**{k: v for k, v in d.items() if k in Request.__dataclass_fields__})


@dataclass
class Collection:
    name: str
    requests: list = field(default_factory=list)       # liste de Request.to_dict()
    variables: dict = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return {"schema": 1, "name": self.name, "description": self.description, "variables": self.variables, "requests": self.requests}

    @staticmethod
    def from_dict(d: dict) -> Collection:
        return Collection(d.get("name", "Collection"), [Request.from_dict(r).to_dict() for r in d.get("requests", [])],
                          dict(d.get("variables", {})), d.get("description", ""))


def kv(items: list, only_enabled: bool = True) -> list[tuple[str, str]]:
    return [(i["key"], str(i.get("value", ""))) for i in items if i.get("key") and (i.get("enabled", True) or not only_enabled)]
