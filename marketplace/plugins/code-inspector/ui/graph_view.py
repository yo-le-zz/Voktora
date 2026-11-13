"""Vue graphique interactive : QGraphicsScene alimentée par une vue + sa mise en page (zoom, glisser, clic, recherche)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from ..exporters.common import KIND_COLORS, LANG_COLORS, short
from ..services import layout as layout_mod

STYLES = {"certain": (Qt.SolidLine, 1.8), "probable": (Qt.DashLine, 1.5), "inconnu": (Qt.DotLine, 1.3)}


class NodeItem(QGraphicsRectItem):
    def __init__(self, node: dict, x: float, y: float, w: float, h: float):
        super().__init__(0, 0, w, h)
        self.node = node
        self.setPos(x, y)
        n = node
        color = LANG_COLORS.get(n.get("lang", ""), "") if n["kind"] in ("file", "dir") else ""
        self.base = QColor(color or KIND_COLORS.get(n["kind"], "#4f6bed"))
        self.setBrush(QBrush(self.base))
        self.setPen(QPen(QColor(0, 0, 0, 60)))
        self.setToolTip(f"{n['id']}\n{n.get('sub', '')}")
        self.setCursor(Qt.PointingHandCursor)
        t = QGraphicsSimpleTextItem(short(n["label"], 24), self)
        t.setBrush(QBrush(Qt.white))
        t.setPos((w - t.boundingRect().width()) / 2, 6 if n.get("sub") else h / 2 - 9)
        if n.get("sub"):
            s = QGraphicsSimpleTextItem(short(n["sub"], 30), self)
            s.setBrush(QBrush(QColor(255, 255, 255, 215)))
            f = s.font()
            f.setPointSize(max(f.pointSize() - 2, 6))
            s.setFont(f)
            s.setPos((w - s.boundingRect().width()) / 2, h - 22)

    def highlight(self, on: bool) -> None:
        self.setPen(QPen(QColor("#ffb300"), 3) if on else QPen(QColor(0, 0, 0, 60)))


class GraphView(QGraphicsView):
    node_clicked = Signal(str)
    node_activated = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.items_by_id: dict[str, NodeItem] = {}
        self.edge_items: list[tuple[QGraphicsPathItem, dict]] = []

    def show_view(self, view: dict, min_certainty: str = "inconnu") -> None:
        sc = self.scene()
        sc.clear()
        self.items_by_id, self.edge_items = {}, []
        if not view["nodes"]:
            t = sc.addSimpleText("Rien à afficher pour cette vue.")
            self.fitInView(t, Qt.KeepAspectRatio)
            return
        lay = layout_mod.layout(view)
        pos, nw, nh = lay["pos"], lay["node_w"], lay["node_h"]
        for e in view["edges"]:
            if e["src"] not in pos or e["dst"] not in pos or e["src"] == e["dst"]:
                continue
            (x1, y1), (x2, y2) = pos[e["src"]], pos[e["dst"]]
            down = y2 > y1
            a = QPointF(x1 + nw / 2, y1 + (nh if down else 0))
            b = QPointF(x2 + nw / 2, y2 + (0 if down else nh))
            path = QPainterPath(a)
            my = (a.y() + b.y()) / 2
            path.cubicTo(QPointF(a.x(), my), QPointF(b.x(), my), b)
            item = QGraphicsPathItem(path)
            style, width = STYLES.get(e["certainty"], STYLES["inconnu"])
            pen = QPen(QColor("#c7561e" if e["kind"] == "ffi" else "#7a7f95"), width, style)
            item.setPen(pen)
            item.setZValue(-1)
            item.setToolTip(f"{e['kind']} — {e['certainty']}" + (f" ×{e['count']}" if e.get("count", 1) > 1 else ""))
            sc.addItem(item)
            self.edge_items.append((item, e))
        for n in view["nodes"]:
            if n["id"] in pos:
                x, y = pos[n["id"]]
                it = NodeItem(n, x, y, nw, nh)
                sc.addItem(it)
                self.items_by_id[n["id"]] = it
        sc.setSceneRect(sc.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.set_min_certainty(min_certainty)
        self.fitInView(sc.sceneRect(), Qt.KeepAspectRatio)

    def set_min_certainty(self, level: str) -> None:
        from ..core.model import RANK
        for item, e in self.edge_items:
            item.setVisible(RANK[e["certainty"]] >= RANK[level])

    def highlight(self, text: str) -> int:
        t = text.lower().strip()
        hits = 0
        for nid, it in self.items_by_id.items():
            on = bool(t) and (t in nid.lower() or t in it.node["label"].lower())
            it.highlight(on)
            hits += on
        return hits

    def wheelEvent(self, ev):  # noqa: N802
        k = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        self.scale(k, k)

    def _node_at(self, pos):
        it = self.itemAt(pos)
        while it is not None and not isinstance(it, NodeItem):
            it = it.parentItem()
        return it

    def mouseReleaseEvent(self, ev):  # noqa: N802
        super().mouseReleaseEvent(ev)
        it = self._node_at(ev.position().toPoint())
        if it is not None and ev.button() == Qt.LeftButton:
            self.node_clicked.emit(it.node["id"])

    def mouseDoubleClickEvent(self, ev):  # noqa: N802
        it = self._node_at(ev.position().toPoint())
        if it is not None:
            self.node_activated.emit(it.node["id"])
        else:
            super().mouseDoubleClickEvent(ev)
