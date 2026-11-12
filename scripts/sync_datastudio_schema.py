"""Gera/confere o catálogo Apps Script usando o contrato Python e os tipos legados."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))
from ds_backend.contract import SCHEMA_HASH  # noqa: E402
from integrations.datastudio.read_catalog import READ_REGISTRY as REGISTRY  # noqa: E402


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    old = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "console.log(JSON.stringify(require('./connectors/continuacoes/Schemas.js')))",
            ],
            cwd=ROOT,
            text=True,
        )
    )
    public = {}
    for name, spec in REGISTRY.items():
        if not spec["public"]:
            continue
        dims = [
            f
            for f, kind in old.get(name, [])
            if kind.startswith("number") and kind != "number"
        ]
        columns = spec.get("read_columns", spec["columns"])
        public[name] = dict(
            spec,
            columns=columns,
            dimensions=dims,
            types={f: spec["types"][f] for f in columns},
        )
    abc = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "const fs=require('fs'),vm=require('vm'),c={};vm.createContext(c);vm.runInContext(fs.readFileSync('connectors/looker_abc/Code.js','utf8'),c);console.log(JSON.stringify(Object.fromEntries(['abc','resumo','juntos'].map(m=>[m,c.fieldSpecs_(m)]))))",
            ],
            cwd=ROOT,
            text=True,
        )
    )
    for mode, fields in abc.items():
        public["ABC_" + mode] = dict(
            columns=[f for f, _ in fields],
            types={
                f: "date" if k == "date" else "text" if k == "text" else "number"
                for f, k in fields
            },
            dimensions=[],
            period="periodo_inicio",
            abc_mode=mode,
            abc_kinds=dict(fields),
        )
    core = ROOT / "connectors/datastudio_api/AbcCore.js"
    original = (ROOT / "connectors/looker_abc/AbcCore.js").read_text(encoding="utf-8")
    if args.check:
        if core.read_text(encoding="utf-8") != original:
            raise SystemExit("Cálculo ABC diverge da referência oficial.")
    else:
        core.write_text(original, encoding="utf-8")
    content = (
        "/* Gerado pelo contrato; executar scripts/sync_datastudio_schema.py --check. */\nvar NexoDSSchemaHash="
        + json.dumps(SCHEMA_HASH)
        + ";\nvar NexoDSSchemas="
        + json.dumps(public, ensure_ascii=False, indent=2)
        + ';\nif(typeof module!=="undefined")module.exports={hash:NexoDSSchemaHash,tables:NexoDSSchemas};\n'
    )
    path = ROOT / "connectors/datastudio_api/Schemas.js"
    if args.check:
        if path.read_text(encoding="utf-8") != content:
            raise SystemExit("Catálogo Data Studio diverge do contrato.")
    else:
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    run()
