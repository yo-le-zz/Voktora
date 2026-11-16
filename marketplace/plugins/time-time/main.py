
"""Time Time — plugin Voktora."""

from datetime import datetime

from PySide6.QtWidgets import QLabel
from PySide6.QtCore import QTimer


# Références aux widgets créés
_clock_labels = []


def on_load(api):
    """Initialisation du plugin."""

    api.add_status_widget(
        lambda ctx: create_clock(api)
    )

    api.add_menu_action(
        "Plugins/Time Time",
        "Switch on/off",
        lambda ctx: switch_status(api),
        icon="mdi:toggle-switch"
    )


def get_status(api):
    """Récupère l'état de l'horloge."""
    return api.settings.get("time-time.status", True)


def switch_status(api):
    """Active ou désactive l'affichage de l'horloge."""

    new_status = not get_status(api)
    api.settings.set("time-time.status", new_status)

    # Met à jour tous les widgets existants
    for label in _clock_labels:
        label.setVisible(new_status)


def create_clock(api):
    """Crée le widget de l'horloge."""

    label = QLabel()

    def update_time():
        label.setText(
            datetime.now().strftime("%H:%M:%S")
        )

    # Timer Qt : actualisation chaque seconde
    timer = QTimer(label)
    timer.timeout.connect(update_time)
    timer.start(1000)

    # Première actualisation immédiate
    update_time()

    # État initial
    label.setVisible(get_status(api))

    # Conserver une référence au widget
    _clock_labels.append(label)

    return label


def on_unload(api):
    """Nettoyage lors de la désactivation du plugin."""

    _clock_labels.clear()
