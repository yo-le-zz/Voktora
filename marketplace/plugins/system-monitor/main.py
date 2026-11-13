"""System Monitor — état système dans la barre d'état + panneau détaillé."""

from PySide6.QtWidgets import QLabel, QPlainTextEdit

from .format import bar, summary


def on_load(api):
    o = api.options
    plus = api.plugin("api-plus")
    o.group("Barre d'état")
    o.add_bool("show_cpu", "Afficher le processeur", default=True)
    o.add_bool("show_ram", "Afficher la mémoire", default=True)
    o.add_bool("show_load", "Afficher la charge", default=False)
    o.group("Rafraîchissement")
    o.add_float("interval", "Intervalle (secondes)", default=2.0, min=0.5, max=60.0)
    o.group("Alertes")
    o.add_int("warn_cpu", "Alerte processeur (%)", default=95, min=50, max=100)
    o.add_int("warn_ram", "Alerte mémoire (%)", default=92, min=50, max=100)
    o.add_bool("alerts", "Prévenir en cas de dépassement", default=True)

    labels, details, state = [], [], {"alerted": False}

    def refresh():
        data = api.system_info()
        text = summary(data, o.get("show_cpu"), o.get("show_ram"), o.get("show_load"))
        for label in labels:
            label.setText(text)
        for box in details:
            box.setPlainText(detail_text(data, plus))
        hot = (data["cpu_percent"] or 0) >= o.get("warn_cpu") or data["memory"]["percent"] >= o.get("warn_ram")
        if hot and o.get("alerts") and not state["alerted"]:
            api.notify("Système très chargé : " + text)
        state["alerted"] = hot

    def status_factory(ctx):
        label = QLabel("…")
        labels.append(label)
        return label

    def dock_factory(ctx):
        box = QPlainTextEdit()
        box.setReadOnly(True)
        details.append(box)
        return box

    api.add_status_widget(status_factory)
    api.add_dock("Moniteur système", dock_factory, area="bottom", icon="mdi:chart-line")
    api.every(o.get("interval"), refresh)
    o.on_change(lambda key, value: key == "interval" and api.warn("L'intervalle s'applique au prochain rechargement."))


def detail_text(data, plus):
    mem = data["memory"]
    lines = [f"Processeur : {bar(data['cpu_percent'])} ({data['cpu_count']} cœurs)",
             f"Mémoire    : {bar(mem['percent'])}  {plus.fmt_bytes(mem['used'])} / {plus.fmt_bytes(mem['total'])}",
             "Charge     : " + " ".join(str(x) for x in data["load"]), ""]
    for disk in data["disks"]:
        lines.append(f"Disque {disk.get('path', '?')} : {bar(disk.get('percent', 0))}")
    return "\n".join(lines)
