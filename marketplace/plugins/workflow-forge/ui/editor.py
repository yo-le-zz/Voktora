"""Éditeur visuel de blocs (QGraphicsScene) : blocs déplaçables, ports, liens par glisser-déposer, zoom ; conçu pour 200+ blocs fluides."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from ..core import blocks

W, H = 176, 58
PORT_R = 6
COLORS = {"Flux": "#4f6bed", "Données": "#2e9e6b", "Système": "#c7561e", "Scripts": "#9b59b6", "Réseau": "#3b82a0", "Projet": "#b5651d"}


class PortItem(QGraphicsEllipseItem):
    def __init__(self, node: NodeItem, name: str, is_output: bool):
        super().__init__(-PORT_R, -PORT_R, 2 * PORT_R, 2 * PORT_R, node)
        self.node, self.name, self.is_output = node, name, is_output
        self.setBrush(QBrush(QColor("#ffffff")))
        self.setPen(QPen(QColor("#333"), 1.2))
        self.setZValue(2)
        self.setToolTip(f"port « {name} »" if is_output else "entrée")
        self.setAcceptedMouseButtons(Qt.LeftButton if is_output else Qt.NoButton)
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, ev):  # noqa: N802
        self.scene().begin_link(self)
        ev.accept()

    def mouseMoveEvent(self, ev):  # noqa: N802
        self.scene().drag_link(ev.scenePos())

    def mouseReleaseEvent(self, ev):  # noqa: N802
        self.scene().end_link(ev.scenePos())


class NodeItem(QGraphicsRectItem):
    def __init__(self, data: dict):
        super().__init__(0, 0, W, H)
        self.data = data
        self.edges: list[EdgeItem] = []
        b = blocks.REGISTRY.get(data["type"])
        color = QColor(COLORS.get(b.category if b else "", "#7a7f8a"))
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(150), 1.2))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.setPos(float(data.get("x", 0)), float(data.get("y", 0)))
        self.title = QGraphicsSimpleTextItem(self)
        self.sub = QGraphicsSimpleTextItem(self)
        self.refresh_text()
        self.inport = PortItem(self, "in", False) if data["type"] != "start" else None
        if self.inport:
            self.inport.setPos(0, H / 2)
        self.outports: dict[str, PortItem] = {}
        ports = b.ports if b else ()
        for i, name in enumerate(ports):
            p = PortItem(self, name, True)
            p.setPos(W, H * (i + 1) / (len(ports) + 1))
            self.outports[name] = p
            if len(ports) > 1:
                t = QGraphicsSimpleTextItem(name, self)
                t.setBrush(QBrush(Qt.white))
                f = QFont()
                f.setPointSize(7)
                t.setFont(f)
                t.setPos(W - 8 - t.boundingRect().width(), H * (i + 1) / (len(ports) + 1) - 7)
        self.setToolTip(f"{data['id']} — {b.title if b else data['type']}\n{b.doc if b else ''}")

    def refresh_text(self) -> None:
        b = blocks.REGISTRY.get(self.data["type"])
        for item, text, size in ((self.title, str(self.data.get("label") or self.data["id"])[:22], 9), (self.sub, b.title if b else "?", 8)):
            item.setText(text)
            item.setBrush(QBrush(Qt.white))
            f = QFont()
            f.setPointSize(size)
            f.setBold(item is self.title)
            item.setFont(f)
        self.title.setPos(12, 8)
        self.sub.setPos(12, 30)

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.data["x"], self.data["y"] = round(value.x()), round(value.y())
            for e in self.edges:
                e.update_path()
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 9, 9)
        painter.setBrush(self.brush())
        painter.setPen(QPen(QColor("#ffb300"), 3) if self.isSelected() else self.pen())
        painter.drawPath(path)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, src: NodeItem, port: str, dst: NodeItem, data: dict):
        super().__init__()
        self.src, self.port, self.dst, self.data = src, port, dst, data
        self.setPen(QPen(QColor("#6b7088"), 2))
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        src.edges.append(self)
        dst.edges.append(self)
        self.update_path()

    def update_path(self) -> None:
        sp = self.src.outports.get(self.port)
        a = sp.scenePos() if sp else self.src.scenePos() + QPointF(W, H / 2)
        b = self.dst.inport.scenePos() if self.dst.inport else self.dst.scenePos()
        path = QPainterPath(a)
        dx = max(abs(b.x() - a.x()) / 2, 40)
        path.cubicTo(a + QPointF(dx, 0), b - QPointF(dx, 0), b)
        self.setPath(path)

    def detach(self) -> None:
        for n in (self.src, self.dst):
            if self in n.edges:
                n.edges.remove(self)


class FlowScene(QGraphicsScene):
    changed_model = Signal()
    node_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        self.wf: dict = {"nodes": [], "edges": []}
        self.items_by_id: dict[str, NodeItem] = {}
        self.link_src: PortItem | None = None
        self.link_line: QGraphicsPathItem | None = None
        self.status: dict[str, str] = {}
        self.selectionChanged.connect(self._sel)

    def load(self, wf: dict) -> None:
        self.clear()
        self.wf, self.items_by_id, self.link_line, self.link_src = wf, {}, None, None
        for n in wf["nodes"]:
            self._add_item(n)
        for e in wf["edges"]:
            self._add_edge(e)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-200, -200, 400, 400))

    def _add_item(self, data: dict) -> NodeItem:
        it = NodeItem(data)
        self.addItem(it)
        self.items_by_id[data["id"]] = it
        return it

    def _add_edge(self, data: dict) -> EdgeItem | None:
        s, d = self.items_by_id.get(data["src"]), self.items_by_id.get(data["dst"])
        if not s or not d:
            return None
        e = EdgeItem(s, data.get("port", "out"), d, data)
        self.addItem(e)
        return e

    def new_id(self, type_: str) -> str:
        n = 1
        while f"{type_}{n}" in self.items_by_id:
            n += 1
        return f"{type_}{n}"

    def add_node(self, type_: str, pos: QPointF) -> NodeItem:
        data = {"id": self.new_id(type_), "type": type_, "label": blocks.REGISTRY[type_].title, "params": blocks.defaults(type_), "options": {},
                "x": round(pos.x()), "y": round(pos.y())}
        self.wf["nodes"].append(data)
        it = self._add_item(data)
        self.changed_model.emit()
        return it

    def connect_nodes(self, src: str, port: str, dst: str) -> bool:
        if src == dst or dst not in self.items_by_id or self.items_by_id[dst].inport is None:
            return False
        if any(e["src"] == src and e.get("port", "out") == port and e["dst"] == dst for e in self.wf["edges"]):
            return False
        data = {"src": src, "port": port, "dst": dst}
        self.wf["edges"].append(data)
        self._add_edge(data)
        self.changed_model.emit()
        return True

    def remove_selected(self) -> None:
        for it in list(self.selectedItems()):
            if isinstance(it, EdgeItem):
                self._drop_edge(it)
            elif isinstance(it, NodeItem) and it.data["type"] != "start":
                for e in list(it.edges):
                    self._drop_edge(e)
                self.wf["nodes"].remove(it.data)
                self.items_by_id.pop(it.data["id"], None)
                self.removeItem(it)
        self.changed_model.emit()

    def _drop_edge(self, e: EdgeItem) -> None:
        e.detach()
        if e.data in self.wf["edges"]:
            self.wf["edges"].remove(e.data)
        if e.scene():
            self.removeItem(e)

    def mark(self, node_id: str, status: str) -> None:
        it = self.items_by_id.get(node_id)
        if it:
            it.setPen(QPen(QColor({"running": "#ffb300", "ok": "#2e9e6b", "failed": "#d63031", "error-handled": "#e17055", "error-ignored": "#e17055"}.get(status, "#333")), 3))
            it.update()

    def clear_marks(self) -> None:
        for it in self.items_by_id.values():
            b = blocks.REGISTRY.get(it.data["type"])
            it.setPen(QPen(QColor(COLORS.get(b.category if b else "", "#7a7f8a")).darker(150), 1.2))

    # -- liaison par glisser-déposer ------------------------------------------------------------------
    def begin_link(self, port: PortItem) -> None:
        self.link_src = port
        self.link_line = QGraphicsPathItem()
        self.link_line.setPen(QPen(QColor("#ffb300"), 2, Qt.DashLine))
        self.addItem(self.link_line)
        self.drag_link(port.scenePos())

    def drag_link(self, pos: QPointF) -> None:
        if self.link_line and self.link_src:
            a = self.link_src.scenePos()
            p = QPainterPath(a)
            p.cubicTo(a + QPointF(50, 0), pos - QPointF(50, 0), pos)
            self.link_line.setPath(p)

    def end_link(self, pos: QPointF) -> None:
        src = self.link_src
        if self.link_line:
            self.removeItem(self.link_line)
        self.link_line, self.link_src = None, None
        if not src:
            return
        it = self.itemAt(pos, self.views()[0].transform()) if self.views() else None
        while it is not None and not isinstance(it, NodeItem):
            it = it.parentItem()
        if it is not None:
            self.connect_nodes(src.node.data["id"], src.name, it.data["id"])

    def _sel(self) -> None:
        sel = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        self.node_selected.emit(sel[0].data["id"] if len(sel) == 1 else "")


class FlowView(QGraphicsView):
    def __init__(self, scene: FlowScene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(0, 0, 0, 0)))

    def wheelEvent(self, ev):  # noqa: N802
        k = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        self.scale(k, k)

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.scene().remove_selected()
        else:
            super().keyPressEvent(ev)

    def fit(self) -> None:
        r = self.scene().itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)


