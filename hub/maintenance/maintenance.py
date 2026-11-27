"""Fixed, least-privilege host maintenance target for the n8n bridge.

Only a root-owned install/config supplies paths. Request payloads carry an
opaque id and one of two fixed actions; no user-supplied commands or paths.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath

ROOT = Path("/srv/nexoflow/manutencao/limpeza")
CONFIG = Path("/etc/nexoflow/storage-maintenance.json")
REQUEST = ROOT / "requests" / "request.json"
STATUS = ROOT / "status"
STATE = ROOT / "state"
AUDIT = ROOT / "audit"
ACTIONS = {"limpeza", "monitorar"}
AGE = 30 * 86400
# A 29-day safety floor tolerates scheduling at a fixed hour; n8n invokes every 30 days.
MIN_CLEAN_INTERVAL = 29 * 86400
DAILY_TAGS = {frozenset({"nexoflow-diario"}), frozenset({"nexoflow-diario", "nexoflow-policy-v1"})}
RELEASE_ROOTS = (Path("/srv/nexoflow/central-hml/releases"), Path("/srv/nexoflow/hub-hml/releases"))
CLONE_PREFIXES = (
    (Path("/tmp"), "nexo-reader-hml."),
    (Path("/var/tmp"), "nf-meta-cobertura."),
    (Path("/var/tmp"), "nexoflow-qa14-limited-"),
    (Path("/var/tmp"), "nexoflow-qa14-"),
)
LOCKS = ("/run/lock/nexoflow-backup.lock", "/srv/nexoflow/central-hml/consumo-005.lock")


def now() -> int:
    return int(time.time())


def write_json(path: Path, value: dict, mode: int = 0o600) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    tmp.chmod(mode)
    tmp.replace(path)


def validate_request(raw: bytes) -> dict:
    if len(raw) > 160:
        raise ValueError("request_size")
    obj = json.loads(raw)
    if not isinstance(obj, dict) or set(obj) != {"id", "acao"}:
        raise ValueError("request_shape")
    if not isinstance(obj["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", obj["id"]):
        raise ValueError("request_id")
    if obj["acao"] not in ACTIONS:
        raise ValueError("request_action")
    return obj


def receive_request() -> dict:
    try:
        fd = os.open(REQUEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        # Consume an invalid marker without following a symlink.
        REQUEST.unlink(missing_ok=True)
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 10001 or info.st_nlink != 1 or info.st_size > 160:
            raise ValueError("request_file")
        obj = validate_request(os.read(fd, 161))
    finally:
        os.close(fd)
        # Unlink the fixed marker only; never follow links or payload paths.
        REQUEST.unlink(missing_ok=True)
    return obj


def command(args, *, env=None, timeout=120, log=None):
    if log is None:
        return subprocess.run(args, env=env, timeout=timeout, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    with log.open("ab") as f:
        subprocess.run(args, env=env, timeout=timeout, check=True, stdout=f, stderr=f)
    return b""


def disk_usage() -> dict:
    d = shutil.disk_usage("/")
    return {"total_bytes": d.total, "usado_bytes": d.used, "livre_bytes": d.free}


def cost_estimate(bytes_standard: int) -> dict:
    gb = bytes_standard / 1_000_000_000
    excess = max(0, math.ceil(gb - 10))
    return {
        "franquia_standard_gb_mes": 10,
        "standard_gb_atual": round(gb, 3),
        "estimativa_excedente_usd_mes_se_constante": round(excess * 0.015, 3),
        "nivel": "alerta" if gb > 10 else "atencao" if gb >= 8 else "normal",
    }


def config() -> dict:
    s = CONFIG.stat()
    if CONFIG.is_symlink() or s.st_uid != 0 or s.st_mode & 0o077:
        raise ValueError("private_config")
    c = json.loads(CONFIG.read_text())
    if not re.fullmatch(r"https://[a-f0-9]{32}\.r2\.cloudflarestorage\.com", c["endpoint"]):
        raise ValueError("endpoint")
    if c["bucket"] != "nexoflow-backups":
        raise ValueError("bucket")
    if c["credentials_file"] != "/srv/nexoflow/configuracoes/r2_s3_credentials" or c["password_file"] != "/srv/nexoflow/configuracoes/restic_password":
        raise ValueError("private_config_paths")
    return c


def r2_env(c: dict) -> dict:
    return {
        **os.environ,
        "AWS_SHARED_CREDENTIALS_FILE": c["credentials_file"],
        "AWS_DEFAULT_REGION": "auto",
        "RESTIC_PASSWORD_FILE": c["password_file"],
        "RESTIC_REPOSITORY": "s3:" + c["endpoint"] + "/" + c["bucket"] + "/vps",
    }


def measure_r2(c: dict) -> dict:
    import boto3
    from botocore.config import Config
    # S3 keys are read exclusively from the private existing Restic credential.
    old = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
    os.environ["AWS_SHARED_CREDENTIALS_FILE"] = c["credentials_file"]
    try:
        client = boto3.session.Session().client(
            "s3", endpoint_url=c["endpoint"], region_name="auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=8, read_timeout=30, retries={"max_attempts": 3}),
        )
        totals: dict[str, int] = {}
        objects = pages = 0
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=c["bucket"], PaginationConfig={"PageSize": 1000}):
            pages += 1
            if pages > 1000:
                raise ValueError("pagination_bound")
            for obj in page.get("Contents", []):
                key = obj.get("StorageClass", "STANDARD").upper()
                totals[key] = totals.get(key, 0) + int(obj["Size"])
                objects += 1
        standard = totals.get("STANDARD", 0)
        result = {"bucket": c["bucket"], "objetos": objects, "bytes": sum(totals.values()),
                  "classes_bytes": totals, "paginas": pages, **cost_estimate(standard)}
        if set(totals) - {"STANDARD"}:
            result["nivel"] = "revisao_classe_armazenamento"
        return result
    finally:
        if old is None:
            os.environ.pop("AWS_SHARED_CREDENTIALS_FILE", None)
        else:
            os.environ["AWS_SHARED_CREDENTIALS_FILE"] = old


def approved_retention_ids(snapshots: list, plan: list) -> tuple[list[str], set[str]]:
    """Validate the dry run against the complete snapshot inventory, fail closed."""
    items = {s["id"]: s for s in snapshots}
    if len(items) != len(snapshots) or not all(re.fullmatch(r"[a-f0-9]{64}", i) for i in items):
        raise ValueError("snapshot_inventory")
    daily = {i for i, s in items.items() if frozenset(s.get("tags") or []) in DAILY_TAGS}
    protected = set(items) - daily
    if len(daily) < 2:
        raise ValueError("daily_backup_minimum")
    latest = max(daily, key=lambda i: items[i]["time"])
    protected.add(latest)
    removals = set()
    for group in plan:
        keep = {s["id"] for s in (group.get("keep") or [])}
        remove = {s["id"] for s in (group.get("remove") or [])}
        if remove and (not keep or keep & remove or not remove <= daily or remove & protected):
            raise ValueError("unsafe_retention_plan")
        if not (keep | remove) <= set(items):
            raise ValueError("unknown_snapshot")
        removals |= remove
    if len(daily - removals) < 2:
        raise ValueError("daily_backup_minimum")
    return sorted(removals), protected


def retain_r2(c: dict, audit: Path) -> dict:
    env = r2_env(c)
    # Require a recent successful normal backup before forgetting anything.
    stamp = Path("/var/lib/nexoflow/backup-last-success")
    if not stamp.is_file() or now() - int(stamp.read_text().strip()) > 72 * 3600:
        return {"estado": "adiada", "motivo": "backup_recente_nao_confirmado", "removidos": 0}
    before = json.loads(command(["restic", "snapshots", "--json"], env=env))
    plan = json.loads(command(["restic", "forget", "--dry-run", "--json", "--tag", "nexoflow-diario",
                               "--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "3",
                               "--group-by", "host,tags"], env=env, timeout=180))
    ids, protected = approved_retention_ids(before, plan)
    write_json(audit / "retencao-plano.json", {"remover": ids, "protegidos": sorted(protected),
                                               "politica": "7/4/3"})
    if not ids:
        return {"estado": "concluida", "removidos": 0, "snapshots_posteriores": len(before)}
    command(["restic", "check"], env=env, timeout=600, log=audit / "restic-check-antes.log")
    current = json.loads(command(["restic", "snapshots", "--json"], env=env))
    if {s["id"] for s in current} != {s["id"] for s in before}:
        raise ValueError("snapshot_inventory_changed")
    # Only the exact previously verified IDs. No generic bucket deletion.
    command(["restic", "forget", *ids], env=env, timeout=180, log=audit / "restic-forget.log")
    after_forget = json.loads(command(["restic", "snapshots", "--json"], env=env))
    remaining = {s["id"] for s in after_forget}
    if not protected <= remaining or remaining != {s["id"] for s in before} - set(ids):
        raise ValueError("unexpected_retention_result")
    command(["restic", "prune"], env=env, timeout=1800, log=audit / "restic-prune.log")
    command(["restic", "check"], env=env, timeout=600, log=audit / "restic-check-depois.log")
    after = json.loads(command(["restic", "snapshots", "--json"], env=env))
    if {s["id"] for s in after} != remaining:
        raise ValueError("unexpected_post_prune_inventory")
    return {"estado": "concluida", "removidos": len(ids), "snapshots_posteriores": len(after),
            "protegidos": len(protected), "integridade": "ok"}


def hash_stream(f) -> bytes:
    h = hashlib.sha256()
    for block in iter(lambda: f.read(1024 * 1024), b""):
        h.update(block)
    return h.digest()


def archive_matches(a: Path, release: Path) -> bool:
    """Every archive member must match extracted source bytes, not just its name."""
    try:
        count = 0
        with tarfile.open(a, "r:gz") as tf:
            for item in tf:
                parts = PurePosixPath(item.name).parts
                if not parts or item.name.startswith("/") or ".." in parts:
                    return False
                if len(parts) == 1:
                    if not item.isdir():
                        return False
                    continue
                p = release.joinpath(*parts[1:])
                if item.isdir():
                    if not p.is_dir() or p.is_symlink():
                        return False
                elif item.isfile():
                    if not p.is_file() or p.is_symlink() or p.stat().st_size != item.size:
                        return False
                    with p.open("rb") as f, tf.extractfile(item) as z:
                        if hash_stream(f) != hash_stream(z):
                            return False
                    count += 1
                elif item.issym():
                    if not p.is_symlink() or os.readlink(p) != item.linkname:
                        return False
                else:
                    return False
        return count > 0
    except (OSError, ValueError, tarfile.TarError):
        return False


def no_open_files(p: Path, recursive: bool = False) -> bool:
    args = ["lsof", "-t"] + (["+D", str(p)] if recursive else [str(p)])
    r = subprocess.run(args, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode == 1 and not r.stdout and not r.stderr


def docker_references() -> list[Path]:
    ids = command(["docker", "ps", "-aq"]).decode().split()
    if not ids:
        return []
    refs = []
    for c in json.loads(command(["docker", "inspect", *ids])):
        refs.extend(Path(m["Source"]) for m in c.get("Mounts", []) if m.get("Source"))
        labels = c.get("Config", {}).get("Labels") or {}
        refs.extend(Path(p) for k in ("com.docker.compose.project.working_dir", "com.docker.compose.project.config_files")
                    for p in (labels.get(k) or "").split(",") if p.startswith("/"))
    return refs


def related_path(p: Path, refs: list[Path]) -> bool:
    return any(p == r or p in r.parents or r in p.parents for r in refs)


def safe_local_cleanup(audit: Path) -> dict:
    refs = docker_references()
    volumes_before = command(["docker", "volume", "ls", "-q"]).splitlines()
    running_before = command(["docker", "ps", "--format", "{{.Names}}"]).splitlines()
    before = disk_usage()
    details = {"arquivos_tar": 0, "bytes_tar": 0, "clones": 0, "bytes_clones": 0}
    for root in RELEASE_ROOTS:
        if not root.is_dir() or root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o022:
            continue
        for a in root.glob("*.tar.gz"):
            if not re.fullmatch(r"[a-f0-9]{40}\.tar\.gz", a.name):
                continue
            release = root / a.name[:-7]
            s = a.lstat()
            if a.is_symlink() or not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_nlink != 1 or now() - s.st_mtime < AGE:
                continue
            # Mount references to the tarball itself are unsafe; extracted sources are preserved.
            if any(a == r or r in a.parents for r in refs) or not release.is_dir() or release.is_symlink() or not no_open_files(a):
                continue
            if not archive_matches(a, release):
                continue
            fresh = a.lstat()
            if (s.st_ino, s.st_dev, s.st_size, s.st_mtime_ns) != (fresh.st_ino, fresh.st_dev, fresh.st_size, fresh.st_mtime_ns):
                continue
            a.unlink()
            details["arquivos_tar"] += 1
            details["bytes_tar"] += s.st_blocks * 512

    # Only known root-owned private temp clone directories, never generic /tmp.
    seen = set()
    for root, prefix in CLONE_PREFIXES:
        for base in root.glob(prefix + "*"):
            if base in seen:
                continue
            seen.add(base)
            if not re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9]{6,16}", base.name):
                continue
            src = base / "src"
            try:
                s = base.lstat()
                if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o077 or now() - s.st_mtime < AGE:
                    continue
                if (not src.is_dir() or src.is_symlink() or src.resolve() != src
                    or src.stat().st_uid != 0 or src.stat().st_mode & 0o022
                    or not (src / ".git").is_dir() or (src / ".git").is_symlink()
                    or (src / ".git").stat().st_uid != 0):
                    continue
                if related_path(base, refs) or not no_open_files(src, True):
                    continue
                git = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(src)]
                if command(git + ["status", "--porcelain", "--untracked-files=all"]).strip():
                    continue
                if command(git + ["ls-files", "--others", "--ignored", "--exclude-standard"]).strip():
                    continue
                if command(git + ["rev-list", "--count", "HEAD", "--not", "--remotes"]).strip() != b"0":
                    continue
                mount_points = command(["findmnt", "-rn", "-o", "TARGET"]).decode().splitlines()
                if any(Path(p) == src or src in Path(p).parents for p in mount_points):
                    continue
                size = int(command(["du", "-sx", "-B1", str(src)]).split()[0])
                command(["rm", "-rf", "--one-file-system", "--", str(src)], timeout=120)
                if src.exists():
                    raise ValueError("clone_removal_incomplete")
                details["clones"] += 1
                details["bytes_clones"] += size
            except (OSError, subprocess.SubprocessError, ValueError):
                continue
    # Package archives and inactive, regenerable, >30-day build cache only.
    command(["apt-get", "clean"], timeout=120, log=audit / "apt-clean.log")
    command(["docker", "builder", "prune", "--all", "--force", "--filter", "until=720h"],
            timeout=600, log=audit / "build-cache-clean.log")
    if sorted(command(["docker", "volume", "ls", "-q"]).splitlines()) != sorted(volumes_before):
        raise ValueError("volume_inventory_changed")
    if sorted(command(["docker", "ps", "--format", "{{.Names}}"]).splitlines()) != sorted(running_before):
        raise ValueError("running_inventory_changed")
    after = disk_usage()
    return {**details, "antes": before, "depois": after,
            "bytes_liberados_observados": before["usado_bytes"] - after["usado_bytes"],
            "volumes_e_servicos_preservados": True}


@contextlib.contextmanager
def locks():
    with contextlib.ExitStack() as stack:
        for p in LOCKS:
            f = stack.enter_context(open(p, "a+"))
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main() -> int:
    os.umask(0o077)
    request = receive_request()
    action = request["acao"]
    status_file = STATUS / (action + ".json")
    result = {**request, "estado": "em_andamento", "inicio_epoch": now()}
    write_json(status_file, result, 0o644)
    audit = AUDIT / request["id"]
    audit.mkdir(mode=0o700)
    try:
        c = config()
        if action == "monitorar":
            result.update({"r2": measure_r2(c), "vps": disk_usage(), "estado": "concluida"})
        else:
            stamp = STATE / "last-cleanup"
            if stamp.is_file() and now() - int(stamp.read_text().strip()) < MIN_CLEAN_INTERVAL:
                result.update(estado="adiada", motivo="janela_minima_29_dias")
            else:
                with locks():
                    result["vps"] = safe_local_cleanup(audit)
                    result["r2_antes"] = measure_r2(c)
                    result["retencao"] = retain_r2(c, audit)
                    result["r2_depois"] = measure_r2(c)
                    if result["retencao"]["estado"] == "concluida":
                        stamp.write_text(str(now()) + "\n")
                        result["estado"] = "concluida"
                    else:
                        result["estado"] = "adiada"
    except BlockingIOError:
        result.update(estado="adiada", motivo="backup_ou_implantacao_em_andamento")
    except Exception as e:
        # Do not leak request bodies, S3 keys, credentials, or exception messages.
        result.update(estado="falhou", classe_erro=type(e).__name__)
        # Preserve private stderr and stage logs; safe summary goes to n8n only.
    result["fim_epoch"] = now()
    write_json(status_file, result, 0o644)
    write_json(audit / "resultado.json", result)
    print(json.dumps({"acao": action, "estado": result["estado"], "id": request["id"]}), flush=True)
    return 1 if result["estado"] == "falhou" else 0


if __name__ == "__main__":
    raise SystemExit(main())
