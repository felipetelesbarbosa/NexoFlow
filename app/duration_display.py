"""Durações legíveis só na apresentação; métricas persistidas continuam numéricas."""

from __future__ import annotations

import math
import re


def duration(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "indisponível"
    if seconds < 60:
        return f"{seconds:.1f}s"
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return (f"{hours}h " if hours else "") + f"{minutes}min {secs}s"


def humanize(message: str) -> str:
    # Somente tokens com unidade explícita, nunca IDs, centavos ou JSON.
    return re.sub(
        r"(?<![\w.:-])(\d+(?:\.\d+)?)\s?s\b",
        lambda m: duration(float(m[1])) if float(m[1]) >= 60 else m[0],
        message,
    )
