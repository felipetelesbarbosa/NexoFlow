"""Calendário e recusas puros, compartilhados sem carregar clientes/configuração."""

from datetime import timedelta

DAYS = {"FARMA": 25, "PET": 30}
REFUSALS = {
    "recusado",
    "nao",
    "negado",
    "inativo",
    "recusa",
    "opt-out",
    "opt out",
    "false",
    "0",
    "cancelado",
    "nao autorizado",
    "nao quero receber",
}


def refused_normalized(fields, segment):
    keys = (
        ("opt_in_marketing",)
        if segment == "PET"
        else ("marketing_opt_in", "opt_in_marketing")
    )
    return any(fields.get(key) in REFUSALS for key in keys)


def timing(purchase, now, days, delivery_hour=-1):
    event = purchase + timedelta(days=days)
    if isinstance(delivery_hour, int) and 0 <= delivery_hour <= 23:
        event = event.replace(hour=delivery_hour, minute=0, second=0, microsecond=0)
    age = (now.date() - purchase.date()).days
    return {
        "event_at": event.isoformat(),
        "due_today": age == days,
        "within_window": 0 <= age <= days,
        "scheduled_future": event > now,
    }
