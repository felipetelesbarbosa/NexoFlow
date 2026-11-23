"""Consulta a Hostinger e grava localmente apenas o inventário exibido na Central."""

import argparse
import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .infrastructure import (
    MAX_SNAPSHOT_BYTES,
    SNAPSHOT_NAME,
    Infrastructure,
    ProviderMetrics,
)

API = "https://developers.hostinger.com/api"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
METRICS = {
    "cpu": ("cpu_usage", "%"),
    "ram": ("ram_usage", "bytes"),
    "disco": ("disk_space", "bytes"),
    "entrada": ("incoming_traffic", "bytes"),
    "saida": ("outgoing_traffic", "bytes"),
    "uptime": ("uptime", "seconds"),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(token, path, params=None):
    url = API + path + ("?" + urlencode(params) if params else "")
    request = Request(
        url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}
    )
    with build_opener(NoRedirect()).open(request, timeout=12) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("RESPOSTA_HOSPEDAGEM_MUITO_GRANDE")
    return json.loads(raw)


def entries(response):
    return response if isinstance(response, list) else response["data"]


def metric_series(response, now):
    interval_start = now - timedelta(hours=24)
    series = {}
    for name, (field, unit) in METRICS.items():
        metric = response.get(field)
        if not isinstance(metric, dict) or metric.get("unit") != unit:
            series[name] = []
            continue
        usage = metric.get("usage")
        points = []
        if not isinstance(usage, dict):
            series[name] = points
            continue
        for epoch, number in usage.items():
            instant = datetime.fromtimestamp(int(epoch), tz=UTC)
            if interval_start <= instant <= now and number is not None:
                if name == "cpu" and not 0 <= number <= 100:
                    continue
                points.append((instant, number))
        series[name] = sorted(points)[-192:]
    return ProviderMetrics.model_validate(series)


def collect(get, vm_id, now):
    vm_path = f"/vps/v1/virtual-machines/{vm_id}"
    vm = get(vm_path)
    if vm["id"] != vm_id:
        raise ValueError("VPS_DIVERGENTE")

    def optional(path, params=None):
        try:
            return get(path, params)
        except HTTPError as error:
            if error.code not in (401, 403, 404):
                raise
            # A credencial pode ter acesso a VPS e não ter acesso a faturamento.
            return None

    data_centers = optional("/vps/v1/data-centers")
    location = (
        next(
            (x for x in entries(data_centers) if x["id"] == vm.get("data_center_id")),
            {},
        )
        if data_centers is not None
        else {}
    )
    subscriptions = optional("/billing/v1/subscriptions")
    billing = (
        next(
            (x for x in entries(subscriptions) if x["id"] == vm.get("subscription_id")),
            {},
        )
        if subscriptions is not None
        else {}
    )
    backups = optional(vm_path + "/backups", {"page": 1})
    backup = (
        max(
            (row["created_at"] for row in entries(backups) if row.get("created_at")),
            default=None,
        )
        if backups is not None
        else None
    )
    metrics = optional(
        vm_path + "/metrics",
        {
            "date_from": (now - timedelta(hours=24)).isoformat(timespec="seconds"),
            "date_to": now.isoformat(timespec="seconds"),
        },
    )
    state = vm.get("state")

    def bytes_from_mib(field):
        value = vm.get(field)
        return value * 1024**2 if type(value) is int else None

    return Infrastructure(
        coletado_em=now,
        hostname=vm["hostname"],
        sistema=(vm.get("template") or {}).get("name"),
        estado=state
        if state in ("running", "stopped", "starting", "stopping")
        else "unknown",
        cidade=location.get("city"),
        pais=str(location["location"]).upper() if location.get("location") else None,
        ipv4=next((row["address"] for row in vm.get("ipv4") or []), None),
        plano=vm.get("plan"),
        nucleos=vm.get("cpus"),
        ram_bytes=bytes_from_mib("memory"),
        disco_bytes=bytes_from_mib("disk"),
        banda_bytes=bytes_from_mib("bandwidth"),
        validade=billing.get("expires_at"),
        renovacao_automatica=billing.get("is_auto_renewed"),
        ultimo_backup_provedor=backup,
        metricas=metric_series(metrics, now) if metrics is not None else None,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vps", required=True, type=int)
    parser.add_argument("--diretorio", required=True, type=Path)
    args = parser.parse_args()
    token = os.environ.get("HOSTINGER_API_TOKEN", "").strip()
    if args.vps < 1 or not re.fullmatch(r"[a-zA-Z0-9._~-]{16,512}", token):
        raise SystemExit("VPS_OU_CREDENCIAL_INVALIDA")
    try:
        now = datetime.now(UTC)
        snapshot = collect(
            lambda path, params=None: get_json(token, path, params), args.vps, now
        )
        payload = snapshot.model_dump_json().encode()
        if len(payload) > MAX_SNAPSHOT_BYTES:
            raise ValueError
        with tempfile.NamedTemporaryFile(dir=args.diretorio, delete=False) as temporary:
            path = Path(temporary.name)
            try:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
                path.chmod(0o644)
                path.replace(args.diretorio / SNAPSHOT_NAME)
            finally:
                path.unlink(missing_ok=True)
    except Exception:
        raise SystemExit("COLETA_VPS_FALHOU") from None
    print("Coleta da VPS atualizada.")


if __name__ == "__main__":
    main()
