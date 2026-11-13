"""Modèle de données : symboles, relations (avec CERTITUDE), problèmes. Tout est sérialisable en JSON."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CERTAIN, PROBABLE, UNKNOWN = "certain", "probable", "inconnu"
CERTAINTIES = (CERTAIN, PROBABLE, UNKNOWN)
RANK = {CERTAIN: 2, PROBABLE: 1, UNKNOWN: 0}

# kinds de symboles
DIR, FILE, MODULE, CLASS, FUNCTION, METHOD = "dir", "file", "module", "class", "function", "method"
STRUCT, ENUM, TRAIT, IMPL, MACRO, CRATE, EXTERNAL, UNKNOWN_NODE = (
    "struct", "enum", "trait", "impl", "macro", "crate", "external", "unknown")
CALLABLE_KINDS = {FUNCTION, METHOD, MACRO}
TYPE_KINDS = {CLASS, STRUCT, ENUM, TRAIT}

# kinds de relations
IMPORTS, CALLS, INHERITS, IMPLEMENTS, DEFINES, FFI, REFERENCES, DECORATES, USES = (
    "imports", "calls", "inherits", "implements", "defines", "ffi", "references", "decorates", "uses")


@dataclass
class Symbol:
    id: str
    kind: str
    name: str
    file: str = ""
    line: int = 0
    end_line: int = 0
    lang: str = ""
    parent: str = ""
    signature: str = ""
    params: list = field(default_factory=list)       # [{"name","annotation","default","kind"}]
    returns: str = ""
    decorators: list = field(default_factory=list)
    doc: str = ""
    complexity: int = 0
    meta: dict = field(default_factory=dict)         # visibilité, local_types, attr_types, pyo3…

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Symbol:
        return Symbol(**d)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    certainty: str = CERTAIN
    line: int = 0
    file: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Edge:
        return Edge(**d)


@dataclass
class Issue:
    file: str
    line: int
    severity: str          # info | warn | error
    code: str
    title: str
    explain: str = ""
    hint: str = ""
    symbol: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Issue:
        return Issue(**d)


@dataclass
class RawRef:
    """Référence brute relevée par un analyseur, résolue plus tard par le lieur (linker)."""
    src: str            # id du symbole appelant (ou <module>)
    expr: str           # « self.helper », « mod.func », « Foo »
    kind: str           # call | ref | inherits | implements | decorates | import
    line: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> RawRef:
        return RawRef(**d)


@dataclass
class FileResult:
    path: str
    lang: str
    digest: str = ""
    loc: int = 0
    symbols: list[Symbol] = field(default_factory=list)
    refs: list[RawRef] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)   # {"module","names":[[name,alias]],"alias","level","line"}
    issues: list[Issue] = field(default_factory=list)
    blocks: list[list] = field(default_factory=list)    # [[hash, first_line, last_line]] pour les duplications
    info: dict = field(default_factory=dict)            # points d'entrée, pyo3, extern "C"…

    def to_dict(self) -> dict:
        return {"path": self.path, "lang": self.lang, "digest": self.digest, "loc": self.loc,
                "symbols": [s.to_dict() for s in self.symbols], "refs": [r.to_dict() for r in self.refs],
                "imports": self.imports, "issues": [i.to_dict() for i in self.issues], "blocks": self.blocks,
                "info": self.info}

    @staticmethod
    def from_dict(d: dict) -> FileResult:
        return FileResult(path=d["path"], lang=d["lang"], digest=d.get("digest", ""), loc=d.get("loc", 0),
                          symbols=[Symbol.from_dict(s) for s in d.get("symbols", [])],
                          refs=[RawRef.from_dict(r) for r in d.get("refs", [])], imports=d.get("imports", []),
                          issues=[Issue.from_dict(i) for i in d.get("issues", [])], blocks=d.get("blocks", []),
                          info=d.get("info", {}))


def better(a: str, b: str) -> str:
    return a if RANK[a] >= RANK[b] else b


def sym_id(path: str, qualname: str) -> str:
    return f"{path}::{qualname}"
