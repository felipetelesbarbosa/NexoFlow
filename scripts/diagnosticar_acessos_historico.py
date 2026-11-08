"""Auditoria somente leitura das quatro guardas de acesso do histórico 1.5.27.

Executar com o Python da instalação; não substitui módulos nem reconcilia planos.
A saída usa apenas metadados técnicos e não contém e-mails ou valores de pedidos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

# Preenchido com os blobs oficiais da release 1.5.27, normalizados para LF.
INSTALLED_HASHES = {
    "google_sheets.py": "6841e8a179fd7d435e88f062c56117106a2df521cbafad51c2ac5f94f40b42b5",
    "history_sheets_transport.py": "72f5db379333f560e141c848d63db3437291611fac539bc54d91c9a3c6abb456",
    "sheets_provisioning.py": "05fa3f5e8e03a2e5d10fa018423cdf00e12a49374f3c025bc679625f58468e1b",
    "sheets_partitions.py": "b28ad57b991f6cfbd6c5bd913f8b39815b8151983521826a4d15037d9f8b24ed",
    "sheets_continuation.py": "2b2119dc5a22f91ce484d177fbaa26220433d398195be015f8445367c7f9aca5",
}


class DiagnosticError(ValueError):
    """Código literal emitido pelo próprio auditor; sem texto de respostas."""


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def error_summary(exc):
    return {
        "codigo": str(exc) if isinstance(exc, DiagnosticError) else None,
        "tipo": type(exc).__name__,
        "http": getattr(getattr(exc, "response", None), "status_code", None),
    }


def permissions(values):
    return sorted(
        (
            p["type"],
            p["role"],
            p["emailAddress"].casefold(),
            p.get("expirationTime", ""),
        )
        for p in values
    )


def parent_summary(expected, service, owner):
    actual = owner.get("parents")
    valid = (
        isinstance(expected, list)
        and len(expected) == 1
        and isinstance(actual, list)
        and len(actual) == 1
        and actual == expected
        and owner.get("capabilities", {}).get("canEdit") is True
        and not owner.get("trashed")
    )
    return {
        "ids_aprovados_oauth": expected,
        "ids_visiveis_servico": service.get("parents", []),
        "ids_visiveis_oauth": actual,
        "esperados_oauth": len(expected) if isinstance(expected, list) else None,
        "visiveis_servico": len(service.get("parents", [])),
        "visiveis_oauth": len(actual) if isinstance(actual, list) else 0,
        "oauth_confere": valid if expected is not None else None,
        "comparacao_cruzada_1_5_27_confere": sorted(service.get("parents", []))
        == expected
        if expected is not None
        else None,
        "visoes_diferentes_com_oauth_confirmado": bool(
            valid and sorted(service.get("parents", [])) != expected
        ),
    }


def inspect_access(remote, metadata, review, states, manifest):
    """Coleta todas as comparações, sem parar no primeiro bloqueio."""
    manager = remote.manager
    if remote.context() != review["context"] or remote.context() != metadata["context"]:
        raise DiagnosticError("DESTINOS_DIVERGENTES")
    provider = manager.provider_factory()
    manager.provider = provider

    # Proteção adicional: o diagnóstico não pode gravar no Drive/Sheets.
    def guard(fn):
        def get_only(method, *args, **kwargs):
            if str(method).upper() not in ("GET", "HEAD"):
                raise DiagnosticError("DIAGNOSTICO_BLOQUEOU_ESCRITA_REMOTA")
            return fn(method, *args, **kwargs)

        return get_only

    provider.before_write = lambda: (_ for _ in ()).throw(
        DiagnosticError("DIAGNOSTICO_BLOQUEOU_ESCRITA_REMOTA")
    )
    for session in {id(s): s for s in (provider.source, provider.owner)}.values():
        session.request = guard(session.request)
    remote.store.client.http_client.request = guard(
        remote.store.client.http_client.request
    )
    observed_manifest = remote.manifest()
    result = dict(
        coletado_em=datetime.now(UTC).isoformat(),
        formato="historico_acessos_diagnostico_v1",
        somente_leitura=True,
        segmento=review["segment"],
        revisao=review["revision"],
        manifesto_confere=observed_manifest == manifest,
        estados_lotes=states,
        origens=[],
        arquivos=[],
        intencoes=[],
        autoriza_aplicacao=False,
        lotes_previstos=review["batches"],
        lotes_observados=sum(states.values()),
        partes_preparadas=[],
    )
    proofs = {}
    for role, book in metadata["roots"].items():
        item = dict(papel=role, arquivo=book)
        try:
            proof = provider.prepare_intent(
                book,
                "0" * 32,
                hub=metadata["roots"]["dashboard"],
                segment=review["segment"],
                role=role,
                number=1,
            )
            proofs[role] = proof
            expected = metadata.get("permissions", {}).get(role)
            current = dict(
                parents=sorted(proof["parents"]),
                permissions=sorted(
                    proof["permissions"], key=lambda p: (p["type"], p["emailAddress"])
                ),
            )
            item.update(
                prova_existente=expected is not None,
                pasta_oauth_confere=current["parents"] == expected["parents"]
                if expected
                else None,
                permissoes_literais_conferem=current["permissions"]
                == expected["permissions"]
                if expected
                else None,
                permissoes_semanticas_conferem=permissions(current["permissions"])
                == permissions(expected["permissions"])
                if expected
                else None,
                quantidade_acessos=len(current["permissions"]),
            )
        except Exception as exc:
            item["falha_leitura"] = error_summary(exc)
        result["origens"].append(item)
    files = {book: role for role, book in metadata["roots"].items()}
    files.update({book: info["role"] for book, info in manager.index.files.items()})
    layouts = {}
    for book, role in files.items():
        item = dict(
            arquivo=book,
            papel=role,
            tipo="original" if book in metadata["books"] else "continuacao_nova",
        )
        try:
            physical = manager._book(book)
            layout = physical.fetch_sheet_metadata()
            remote._origin(layout, role)
            layouts[book] = layout
            item["marcador_origem_confere"] = True
            service = remote._drive(book)
            owner = provider._get(
                provider.owner,
                f"/files/{book}",
                params={"fields": "id,mimeType,parents,trashed,capabilities(canEdit)"},
            )
            expected = metadata.get("permissions", {}).get(role, {}).get("parents")
            item.update(
                edicao_servico=service.get("capabilities", {}).get("canEdit") is True,
                excluido_servico=bool(service.get("trashed")),
                identidade_oauth_confere=owner.get("id") == book,
                edicao_oauth=owner.get("capabilities", {}).get("canEdit") is True,
                pastas=parent_summary(expected, service, owner),
            )
            if item["tipo"] == "continuacao_nova":
                try:
                    proof = metadata.get("permissions", {}).get(role)
                    if proof is None:
                        raise DiagnosticError("PROVA_ORIGINAL_DE_PERMISSOES_AUSENTE")
                    provider.verify_private_access(book, proof)
                    item["compartilhamento_privado_confere"] = True
                except Exception as exc:
                    item["compartilhamento_privado_confere"] = False
                    item["falha_compartilhamento"] = error_summary(exc)
            if book in metadata["access_proofs"]:
                item["pasta_servico_confere_baseline_servico"] = (
                    sorted(service.get("parents", []))
                    == metadata["access_proofs"][book]
                )
        except Exception as exc:
            item["falha_leitura"] = error_summary(exc)
        result["arquivos"].append(item)
    from order_history_sheets import SCHEMAS
    from sheets_partitions import _empty_creation_values

    originals = {(p["book"], p["sheet"]) for p in metadata["parts"]}
    candidates = {
        (part.book_id, part.sheet_id): part.title
        for part in manager.index.parts.values()
        if part.title in SCHEMAS and (part.book_id, part.sheet_id) not in originals
    }
    for planned in review["capacity"]["creations"]:
        for sheet in layouts.get(planned["book"], {}).get("sheets", []):
            props = sheet["properties"]
            if (
                props["title"] == planned["title"]
                and (planned["book"], props["sheetId"]) not in originals
            ):
                candidates[planned["book"], props["sheetId"]] = planned["title"]
    for (book, sheet), title in candidates.items():
        item = dict(arquivo=book, aba_id=sheet, tabela=title)
        try:
            if book not in layouts:
                raise DiagnosticError("ORIGEM_NAO_CONFIRMADA_PARA_LER_CABECALHO")
            ws = manager._book(book).get_worksheet_by_id(sheet)
            headers = SCHEMAS[title]
            item.update(
                titulo_confere=ws.title == title,
                grade_cabecalho_minima=ws.row_count == 1
                and ws.col_count == len(headers),
            )
            # Não ler fatos ou grades grandes. Para este incidente, as novas
            # partes devem conter somente uma linha de cabeçalho.
            if item["titulo_confere"] and item["grade_cabecalho_minima"]:
                values = ws.get(
                    f"A1:{manager.store_column(len(headers))}1",
                    value_render_option="FORMULA",
                )
                item.update(
                    cabecalho_exato=values == [headers],
                    cabecalho_vazio=_empty_creation_values(values),
                )
                manager._check_creation_structure(
                    manager._book(book), ws, single_sheet=book not in metadata["books"]
                )
                item["estrutura_nativa_confere"] = True
        except Exception as exc:
            item["falha_leitura_ou_estrutura"] = error_summary(exc)
        result["partes_preparadas"].append(item)
    for intent in manager.index.intents.values():
        item = dict(
            tabela=intent.get("table"),
            parte=intent.get("part"),
            arquivo=intent.get("file_id"),
        )
        try:
            if intent.get("segment") != review["segment"] or intent.get(
                "source"
            ) != metadata["roots"].get(intent.get("role")):
                raise DiagnosticError("INTENCAO_FORA_DO_CONTEXTO")
            current = proofs[intent["role"]]
            item.update(
                pasta_origem_oauth_confere=current["parents"] == intent["parents"],
                permissoes_origem_conferem=permissions(current["permissions"])
                == permissions(intent["permissions"]),
            )
        except Exception as exc:
            item["falha_leitura"] = error_summary(exc)
        result["intencoes"].append(item)
    result["manifesto_estavel_durante_diagnostico"] = (
        remote.manifest() == observed_manifest
    )
    return result


def validate_installation(root):
    if (root / "VERSION").read_text(encoding="utf-8-sig").strip() != "1.5.27":
        raise DiagnosticError("DIAGNOSTICO_EXIGE_INSTALACAO_1_5_27")
    for name, expected in INSTALLED_HASHES.items():
        data = (root / "app" / name).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() != expected:
            raise DiagnosticError("MODULOS_INSTALADOS_DIVERGEM_DA_RELEASE")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instalacao", type=Path, required=True)
    parser.add_argument("--perfil", choices=("FARMA", "PET"), required=True)
    parser.add_argument("--revisao", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    args = parser.parse_args(argv)
    stage = "instalacao"
    try:
        root = args.instalacao.resolve(strict=True)
        validate_installation(root)
        selected = os.environ.get("NEXOFLOW_PERFIL")
        if selected and selected != args.perfil:
            raise DiagnosticError("PERFIL_DIVERGENTE_DA_SESSAO")
        os.environ["NEXOFLOW_PERFIL"] = args.perfil
        sys.path.insert(0, str(root / "app"))
        from google_sheets import GoogleSheetsStore
        from history_sheets_transport import SheetsTransport
        from order_history import digest
        from project_paths import ROOT, load_private_settings
        from proxy_config import configure_proxy
        from runtime_profile import scoped_path

        if ROOT.resolve() != root:
            raise DiagnosticError("RAIZ_INSTALADA_DIVERGENTE")
        private = (root / scoped_path("logs/privado")).resolve(strict=True)
        plan = args.revisao.resolve(strict=True)
        output = args.saida.resolve()
        if (
            not plan.is_relative_to(private)
            or not output.is_relative_to(private)
            or output.suffix.lower() != ".json"
            or output.is_relative_to(private / "historico_publicacoes")
        ):
            raise DiagnosticError("CAMINHO_FORA_DA_PASTA_PRIVADA_DO_PERFIL")
        if output.exists():
            raise DiagnosticError("RELATORIO_JA_EXISTE_NAO_SERA_SOBRESCRITO")
        review = json.loads(plan.read_text(encoding="utf-8-sig"))
        original = dict(review)
        checksum = original.pop("digest", None)
        if (
            review.get("format") != "historico_publicacao_v2"
            or review.get("segment") != args.perfil
            or checksum != digest(original)
        ):
            raise DiagnosticError("REVISAO_INVALIDA")
        stage = "journal_somente_leitura"
        journal = Path(review["journal"]).resolve(strict=True)
        if (
            not journal.is_relative_to(private / "historico_publicacoes")
            or output == journal
            or output == plan
        ):
            raise DiagnosticError("JOURNAL_OU_SAIDA_FORA_DO_ESCOPO")
        if any(Path(str(journal) + suffix).exists() for suffix in ("-wal", "-journal")):
            raise DiagnosticError("JOURNAL_ATIVO_ENCERRE_AS_ROTINAS")
        before = sha256(journal)
        with closing(sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise DiagnosticError("JOURNAL_INTEGRIDADE_INVALIDA")

            def meta(key):
                row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
                return json.loads(row[0]) if row else None

            if meta("review") != review:
                raise DiagnosticError("REVISAO_DIVERGE_DO_JOURNAL")
            metadata, manifest = meta("metadata"), meta("manifest")
            if digest(metadata) != review["metadata_signature"]:
                raise DiagnosticError("METADADOS_DIVERGEM_DA_REVISAO")
            local_status = {
                key: meta(key)
                if type(meta(key)) in (bool, type(None))
                else "INCOMPATIVEL"
                for key in ("started", "finished")
            }
            local_status["manifesto_pendente"] = meta("manifest_pending") is not None
            local_status["backups_de_lote"] = len(
                list(journal.parent.glob("lote_*.json"))
            )
            receipt = meta("code_reconciliation")
            sig = receipt.get("to_signature") if isinstance(receipt, dict) else None
            local_status["recibo_codigo_presente"] = isinstance(receipt, dict)
            local_status["assinatura_destino_recibo"] = (
                sig
                if isinstance(sig, str)
                and len(sig) == 64
                and set(sig) <= set("0123456789abcdef")
                else None
            )
            states = {
                str(state): count
                for state, count in db.execute(
                    "SELECT state,count(*) FROM batches GROUP BY state"
                )
            }
        stage = "metadados_google_somente_leitura"
        configure_proxy()
        store = GoogleSheetsStore.open_native_readonly(
            load_private_settings().GOOGLE_SPREADSHEET_ID
        )
        try:
            result = inspect_access(
                SheetsTransport(store), metadata, review, states, manifest
            )
        finally:
            store.close()
        after = sha256(journal)
        result.update(
            journal_inalterado=before == after,
            journal_sha256=after,
            estado_local=local_status,
        )
        if before != after:
            raise DiagnosticError("JOURNAL_ALTERADO_POR_OUTRO_PROCESSO")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(
            "[DIAGNÓSTICO] Coleta concluída; não autoriza aplicação. Nenhum plano foi reconciliado ou aplicado."
        )
        for item in result["arquivos"]:
            if item["tipo"] == "continuacao_nova" and item.get("pastas", {}).get(
                "visoes_diferentes_com_oauth_confirmado"
            ):
                print(
                    f"[EVIDÊNCIA] {item['papel']} / {item['arquivo']}: pasta confirmada por OAuth; visão de serviço difere."
                )
        print(f"Relatório sanitizado: {output}")
        return 0
    except Exception as exc:
        print(
            json.dumps(
                dict(
                    erro="DIAGNOSTICO_NAO_CONCLUIDO", etapa=stage, **error_summary(exc)
                ),
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
