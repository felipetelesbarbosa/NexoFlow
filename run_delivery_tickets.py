"""NexoFlow 1.0: pedidos de clientes de atendimentos marcados no Weni Chats."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Reconcilia as tags Pedido e Pedido finalizado do Weni Chats com a FarmaLíder."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="consulta todo o histórico encerrado e gera revisão, sem gravar nas integrações",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="aplica o snapshot revisado na Weni e no Google Sheets",
    )
    parser.add_argument(
        "--review-out", type=Path, default=Path("logs/delivery_review.json")
    )
    parser.add_argument(
        "--require-review", type=Path, help="snapshot Delivery previamente revisado"
    )
    parser.add_argument(
        "--planilhas",
        action="store_true",
        help="usa Conversas_Delivery.xlsx e Contatos_Delivery.xlsx, sem token do Chats",
    )
    parser.add_argument(
        "--import-dir",
        type=Path,
        default=Path("importacoes"),
        help="pasta dos dois exports XLSX",
    )
    parser.add_argument(
        "--target",
        choices=["weni", "analytics", "both"],
        help="destino da carga; fica congelado no relatório de revisão",
    )
    args = parser.parse_args()
    if args.apply and args.require_review is None:
        parser.error("--apply exige --require-review com o snapshot revisado.")
    if os.name == "nt":
        from proxy_config import configure_proxy

        configure_proxy()
    import secrets_config as secrets
    from delivery_tickets import (
        apply_delivery_review,
        reconcile_tickets,
        select_tickets,
        write_delivery_review,
    )
    from google_sheets import GoogleSheetsStore
    from logging_config import configure_logging
    from weni_chats_client import WeniChatsClient
    from weni_client import WeniClient
    from weni_update import _open_farmalider

    configure_logging(Path("logs/nexoflow_delivery.log"))
    weni, chats, farm = None, None, None
    try:
        if not getattr(secrets, "WENI_API_TOKEN", ""):
            raise RuntimeError("Token da Weni não configurado.")
        imported = None
        cutoff = datetime.now(UTC)
        if args.dry_run and args.planilhas:
            from delivery_spreadsheets import read_delivery_spreadsheets

            imported = read_delivery_spreadsheets(args.import_dir, cutoff=cutoff)
        elif args.dry_run:
            # Validate Chats configuration before listing the entire Weni base or querying FarmaLíder.
            chats = WeniChatsClient(
                str(getattr(secrets, "WENI_CHATS_API_BASE_URL", "")),
                str(getattr(secrets, "WENI_CHATS_API_TOKEN", "")),
            )
        weni = WeniClient(secrets.WENI_API_TOKEN)
        if args.apply:
            spreadsheet_id = str(getattr(secrets, "GOOGLE_SPREADSHEET_ID", ""))

            def store_factory():
                if not spreadsheet_id:
                    raise RuntimeError("ID da planilha Google não configurado.")
                return GoogleSheetsStore(spreadsheet_id)

            result = apply_delivery_review(
                args.require_review,
                weni,
                store_factory=store_factory,
                target=args.target,
            )
            print("[OK] Reconciliação aplicada:", result)
            return 3 if result["conflicts"] else 0
        farm = _open_farmalider()
        if farm is None:
            raise RuntimeError(
                "FarmaLíder deve estar configurada para confirmar os pedidos."
            )
        if imported is not None:
            from delivery_spreadsheets import validate_current_contacts

            tickets, _, import_report = imported
            contacts = weni.list_contacts() if tickets else []
            tickets, contacts, rejected = validate_current_contacts(
                tickets,
                contacts,
                refresh_contact=lambda uid: weni.get_contact(uuid=uid),
            )
            import_report["current_contact_rejections"] = rejected
            logging.info(
                "Delivery planilhas: %s; exclusões atuais=%s.",
                import_report["summary"],
                rejected,
            )
        else:
            rooms = chats.list_closed_rooms(cutoff=cutoff)
            tickets, rejected = select_tickets(rooms, cutoff=cutoff)
            contacts = weni.list_contacts() if tickets else []
        logging.info(
            "Delivery: tickets selecionados=%s; exclusões por motivo=%s.",
            len(tickets),
            rejected,
        )
        available = {item.get("key") for item in weni.list_fields()}
        plans, delivery = reconcile_tickets(
            tickets,
            contacts,
            farm,
            captured_at=cutoff.isoformat(),
            available_fields=available,
            order_id_field=""
            if imported is not None
            else str(getattr(secrets, "WENI_CHATS_ORDER_ID_FIELD", "")),
        )
        delivery["selection_rejections"] = rejected
        delivery["target"] = args.target or "both"
        if imported is not None:
            delivery["spreadsheet_import"] = import_report
        write_delivery_review(plans, delivery, args.review_out)
        print(f"[OK] Revisão gerada em {args.review_out.with_suffix('.txt')}.")
        print(
            f"Tickets: {len(tickets)} | clientes: {len(plans)} | pedidos únicos: {len(delivery['orders'])}."
        )
        print(
            "[INFO] Nenhuma gravação na Weni ou no Google Sheets. Revise o relatório antes de aplicar."
        )
        print(
            "[INFO] Sem ID de pedido no ticket, a existência de pedido do cliente não comprova atribuição ao atendimento."
        )
        return 0
    except Exception as exc:
        # SDK errors can contain private/authenticated URLs; never print the original exception text.
        from delivery_spreadsheets import DeliverySpreadsheetError
        from weni_chats_client import WeniChatsError
        from weni_client import WeniError
        from weni_update import PlanAuditError

        if isinstance(
            exc, (WeniChatsError, DeliverySpreadsheetError, WeniError, PlanAuditError)
        ):
            logging.error("%s", exc)
        else:
            logging.error(
                "Reconciliação Delivery interrompida (%s). Confira as configurações e o relatório privado; uma aplicação parcial deve ser retomada com o mesmo snapshot.",
                type(exc).__name__,
            )
        return 1
    finally:
        for client in (weni, chats, farm):
            if client is not None:
                client.close()


if __name__ == "__main__":
    raise SystemExit(main())
