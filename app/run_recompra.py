"""Rotina incremental de recompra, sempre com revisão antes dos POSTs."""

import argparse
import json
import logging
from pathlib import Path
from uuid import uuid4

from requests import RequestException


def build_parser():
    from config import FARMALIDER_MAX_WORKERS

    parser = argparse.ArgumentParser(
        description="NexoFlow 1.0 — Recompra FarmaLíder D+25"
    )
    parser.add_argument(
        "--perfil",
        choices=("FARMA", "PET"),
        default="FARMA",
        help="organização e regras da Recompra (FARMA D+25 ou PET D+30)",
    )
    parser.add_argument(
        "--cleanup-cancelled",
        action="store_true",
        help="revisa/aplica somente remoções de cancelados do grupo",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="interrompe o fluxo se houver consultas de pedido incompletas",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-only",
        action="store_true",
        help="audita campos, grupos, campanha e fluxo; somente GET",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="consulta clientes e propõe alterações sem gravar na Weni",
    )
    mode.add_argument(
        "--apply", action="store_true", help="revalida e aplica o snapshot revisado"
    )
    mode.add_argument(
        "--check-review",
        action="store_true",
        help="confere integridade e dia da revisão local, sem acessar APIs",
    )
    mode.add_argument(
        "--diagnose-state",
        action="store_true",
        help="resume estado, pendências e auditoria sem acessar APIs nem gravar arquivos",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="auditoria de toda a base; mesmas regras do incremental, sem retroativos",
    )
    parser.add_argument("--contact", help="UUID Weni para auditoria de um contato")
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, FARMALIDER_MAX_WORKERS + 1),
        default=FARMALIDER_MAX_WORKERS,
        help="consultas FarmaLíder simultâneas no dry-run; mantém o limitador global da API",
    )
    parser.add_argument("--review-out", type=Path, default=None)
    parser.add_argument(
        "--require-review", type=Path, help="snapshot que foi revisado antes do apply"
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    from recompra_profiles import profile_for, profile_settings

    profile = profile_for(args.perfil)
    state_path = profile.directory / "recompra_state.json"
    audit_path = profile.directory / "recompra_audit.jsonl"
    if args.review_out is None:
        args.review_out = profile.directory / (
            "recompra_cancelados_review.json"
            if args.cleanup_cancelled
            else "recompra_review.json"
        )
    if (args.apply or args.check_review) and not args.require_review:
        parser.error("--apply e --check-review exigem --require-review.")
    from recompra import (
        REVIEW_EXPIRED_EXIT_CODE,
        ReviewExpiredError,
        diagnose_state,
        ensure_review_current,
        finalize_review,
        now_local,
        read_review,
        safe_error_frames,
    )

    if args.diagnose_state:
        try:
            print(
                json.dumps(
                    diagnose_state(state_path, audit_path), ensure_ascii=False, indent=2
                )
            )
            return 0
        except (RuntimeError, OSError, ValueError) as exc:
            print("[ERRO] " + str(exc))
            return 1
    review = None
    if args.apply or args.check_review:
        try:
            if args.cleanup_cancelled:
                from recompra_cleanup import read_cleanup_review

                review = read_cleanup_review(args.require_review, args.perfil)
            else:
                review = read_review(args.require_review)
                if review["structure"].get("segment", "FARMA") != args.perfil:
                    raise RuntimeError("A revisão pertence a outro perfil.")
            ensure_review_current(review, now_local())
        except ReviewExpiredError as exc:
            print("[REVISÃO EXPIRADA] " + str(exc))
            return REVIEW_EXPIRED_EXIT_CODE
        except Exception as exc:
            print(
                "[ERRO] "
                + (
                    str(exc)
                    if isinstance(exc, RuntimeError)
                    else "Não foi possível validar a revisão. Gere um novo dry-run."
                )
            )
            return 1
        if args.check_review:
            print(
                "[OK] Integridade e dia da revisão conferidos: " + review["day"] + "."
            )
            return 0
    from proxy_config import configure_proxy

    configure_proxy()
    from logging_config import configure_logging

    configure_logging(profile.directory / "nexoflow_recompra.log")
    import secrets_config as secrets
    from recompra import (
        STATE,
        apply_review,
        build_plans,
        inspect_structure,
        load_state,
        make_review,
        now_local,
        read_review,
        write_review,
    )
    from weni_client import WeniClient
    from weni_update import _open_farmalider

    weni = None
    farm = None
    try:
        settings = profile_settings(secrets, args.perfil)
        if not settings.get("WENI_API_TOKEN"):
            raise RuntimeError("Token Weni não configurado.")
        # Uma resposta perdida de POST não autoriza repetir inclusão nem
        # atravessar a virada do dia em uma tentativa interna do cliente.
        weni = WeniClient(str(settings["WENI_API_TOKEN"]), retry_mutations=False)
        if args.cleanup_cancelled:
            from recompra_cleanup import inspect_cleanup_structure

            structure = {**inspect_cleanup_structure(weni, args.perfil), "errors": []}
        else:
            structure = (
                inspect_structure(weni)
                if args.perfil == "FARMA"
                else inspect_structure(weni, segment="PET")
            )
        for error in structure["errors"]:
            print("[PENDÊNCIA] " + error)
        print(
            f"[INFO] Perfil {args.perfil}: diagnóstico somente leitura de grupo, campos e regras D+{profile.days}."
        )
        if args.check_only:
            return 1 if structure["errors"] else 0
        if structure["errors"]:
            return 1
        if args.perfil == "FARMA" and not getattr(secrets, "PERFIS", None):
            farm = _open_farmalider()
        else:
            from farmalider_client import FarmaliderClient
            from recompra_profiles import PetRecompraClient

            if not settings.get("FARMALIDER_API_ENABLED", True) or not settings.get(
                "FARMALIDER_API_TOKEN"
            ):
                raise RuntimeError("API de pedidos não configurada para este perfil.")
            client_class = (
                PetRecompraClient if args.perfil == "PET" else FarmaliderClient
            )
            farm = client_class(
                str(settings["FARMALIDER_API_TOKEN"]),
                use_hml=bool(settings.get("FARMALIDER_USE_HML", False)),
            )
        if farm is None:
            raise RuntimeError(
                "FarmaLíder precisa estar disponível para confirmar a compra."
            )
        if args.cleanup_cancelled:
            from recompra_cleanup import (
                apply_cleanup_review,
                make_cleanup_review,
                write_cleanup_review,
            )

            if args.apply:
                result = apply_cleanup_review(
                    review, weni, farm, state_path=state_path, audit_path=audit_path
                )
                partial = bool(
                    result.get("conflitos") or result.get("consultas_pendentes")
                )
                print(
                    ("[AVISO] " if partial else "[OK] ")
                    + "Limpeza de cancelados: "
                    + str(result)
                )
                return 3 if partial else 0
            cleanup_review = make_cleanup_review(weni, farm, args.perfil)
            write_cleanup_review(cleanup_review, args.review_out)
            print(
                "[OK] Simulação sem gravações. Revise "
                + str(args.review_out.with_suffix(".txt"))
            )
            return 0
        if (
            args.perfil == "PET"
            and args.apply
            and settings.get("RECOMPRA_ENABLED") is not True
        ):
            raise RuntimeError(
                'Ative RECOMPRA_ENABLED em PERFIS["PET"] após configurar o fluxo e o evento D+30.'
            )
        if args.apply:
            pending_report = (
                args.require_review.parent
                / "privado"
                / (args.require_review.stem + "_" + uuid4().hex + "_aplicacao.json")
            )
            result = apply_review(
                review,
                weni,
                farm,
                pending_report_path=pending_report,
                **(
                    {"state_path": state_path, "audit_path": audit_path}
                    if args.perfil == "PET"
                    else {}
                ),
            )
            partial = bool(result.get("conflitos") or result.get("consultas_pendentes"))
            print(
                (
                    "[AVISO] Recompra aplicada com pendências: "
                    if partial
                    else "[OK] Recompra: "
                )
                + str(result)
            )
            print("[INFO] Relatório desta aplicação: " + str(pending_report))
            if partial:
                print(
                    "[INFO] Alterações confirmadas preservadas. Gere uma nova revisão para "
                    "revalidar as pendências; não reaplique a revisão antiga."
                )
            return 3 if partial else 0
        state = load_state(state_path if args.perfil == "PET" else STATE)
        now = now_local()
        if args.contact:
            contact = weni.get_contact(uuid=args.contact)
            if not contact:
                raise RuntimeError("Contato não localizado.")
            contacts = [contact]
        else:
            # O relógio e a API FarmaLíder podem mudar sem modified_on na Weni.
            # Uma varredura de contatos é necessária para detectar D+26, novas
            # compras e recusas em todos os membros, mesmo no incremental.
            contacts = weni.iter_contacts()
        pagination = {}
        plans = build_plans(
            contacts,
            farm,
            structure,
            state,
            now=now,
            workers=args.workers,
            pagination_stats=pagination,
        )
        review = make_review(plans, structure, now=now, state=state)
        review["pagination"] = pagination
        # Os planos usam o relógio capturado antes da varredura. Não publicar
        # esses planos sob a data nova se a geração atravessou a meia-noite.
        ensure_review_current(review, now_local())
        finalize_review(review, now_local())
        write_review(review, args.review_out)
        ensure_review_current(review, now_local())
        from recompra_review_audit import incomplete_query_summary

        incomplete = incomplete_query_summary(plans)
        if incomplete["contatos"]:
            logging.warning(
                "Recompra: consultas incompletas em %s contato(s); motivos da consulta=%s; "
                "decisões finais=%s. Detalhes na revisão privada: %s.",
                incomplete["contatos"],
                incomplete["motivos_consulta"],
                incomplete["decisoes"],
                args.review_out,
            )
        if args.require_complete and incomplete["contatos"]:
            print(
                "[AVISO] Recompra com consultas incompletas. O fluxo completo foi interrompido antes da aplicação."
            )
            return 3
        print(
            "[OK] Dry-run concluído; nenhuma gravação na Weni. Revise "
            + str(args.review_out.with_suffix(".txt"))
        )
        print(
            f"[INFO] {profile.brand}: grupo de 0 a {profile.days} dias. Envio exclusivamente pela campanha Weni D+{profile.days}."
        )
        return 1 if structure["errors"] else 0
    except ReviewExpiredError as exc:
        logging.warning("Recompra: %s", exc)
        print("[REVISÃO EXPIRADA] " + str(exc))
        return REVIEW_EXPIRED_EXIT_CODE if exc.allow_refresh else 1
    except Exception as exc:
        logging.error(
            "Recompra falhou: tipo=%s; errno=%s; winerror=%s; origem=%s.",
            type(exc).__name__,
            getattr(exc, "errno", None),
            getattr(exc, "winerror", None),
            " > ".join(safe_error_frames(exc)),
        )
        print(
            "[ERRO] "
            + (
                "Falha ao acessar um arquivo local da Recompra "
                f"({type(exc).__name__}, errno={getattr(exc, 'errno', None)}, "
                f"winerror={getattr(exc, 'winerror', None)}). "
                "Verifique as permissões da pasta logs e se há bloqueio por outro processo "
                "ou antivírus. Preserve o estado e a auditoria; gere uma nova revisão "
                "antes de retomar."
                if isinstance(exc, OSError) and not isinstance(exc, RequestException)
                else str(exc)
                if isinstance(exc, (RuntimeError, ValueError))
                else "Falha de API. Consulte o diagnóstico seguro."
            )
        )
        return 1
    finally:
        if farm:
            farm.close()
        if weni:
            weni.close()


if __name__ == "__main__":
    raise SystemExit(main())
