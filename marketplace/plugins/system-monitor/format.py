"""Mise en forme (pur Python)."""


def bar(percent, width: int = 20) -> str:
    p = 0.0 if percent is None else max(0.0, min(100.0, float(percent)))
    filled = round(width * p / 100)
    return "█" * filled + "░" * (width - filled) + f" {p:.0f} %"


def summary(data, cpu=True, ram=True, load=False) -> str:
    parts = []
    if cpu:
        parts.append(f"CPU {data['cpu_percent'] or 0:.0f} %")
    if ram:
        parts.append(f"RAM {data['memory']['percent']:.0f} %")
    if load:
        parts.append("charge " + str(data["load"][0]))
    return " · ".join(parts) or "—"
