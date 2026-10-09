"""Rotina incremental de recompra, sempre com revisão antes dos POSTs."""
import argparse
from collections import Counter
from pathlib import Path
import logging


def build_parser():
    parser = argparse.ArgumentParser(description="NexoFlow 1.0 — Recompra FarmaLíder D+25")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true', help='audita campos, grupos, campanha e fluxo; somente GET')
    mode.add_argument('--dry-run', action='store_true', help='consulta clientes e propõe alterações sem gravar na Weni')
    mode.add_argument('--apply', action='store_true', help='revalida e aplica o snapshot revisado')
    parser.add_argument('--full', action='store_true', help='auditoria de toda a base; mesmas regras do incremental, sem retroativos')
    parser.add_argument('--contact', help='UUID Weni para auditoria de um contato')
    parser.add_argument('--review-out', type=Path, default=Path('logs/recompra_review.json'))
    parser.add_argument('--require-review', type=Path, help='snapshot que foi revisado antes do apply')
    return parser


def main(argv=None):
    parser = build_parser(); args = parser.parse_args(argv)
    if args.apply and not args.require_review: parser.error('--apply exige --require-review após revisão humana.')
    from proxy_config import configure_proxy
    configure_proxy()
    from logging_config import configure_logging
    configure_logging(Path('logs/nexoflow_recompra.log'))
    import secrets_config as secrets
    from weni_client import WeniClient
    from weni_update import _open_farmalider
    from recompra import inspect_structure, now_local, load_state, STATE, propose, resolve_latest, make_review, write_review, read_review, apply_review
    from analytics import get_fields, cpf_query_priority
    weni = None; farm = None
    try:
        if not getattr(secrets, 'WENI_API_TOKEN', ''): raise RuntimeError('Token Weni não configurado.')
        weni = WeniClient(secrets.WENI_API_TOKEN)
        structure = inspect_structure(weni)
        for error in structure['errors']: print('[PENDÊNCIA] ' + error)
        print('[INFO] Diagnóstico somente leitura: grupo, evento +25 dias, campos, fluxo e fuso.')
        if args.check_only: return 1 if structure['errors'] else 0
        farm = _open_farmalider()
        if farm is None: raise RuntimeError('FarmaLíder precisa estar disponível para confirmar a compra.')
        if args.apply:
            result = apply_review(read_review(args.require_review), weni, farm)
            print('[OK] Recompra: ' + str(result)); return 3 if result.get('conflitos') else 0
        state = load_state(STATE)
        now = now_local(); cache = {}; plans = []
        if args.contact:
            contact = weni.get_contact(uuid=args.contact)
            if not contact: raise RuntimeError('Contato não localizado.')
            contacts = [contact]
        else:
            # O relógio e a API FarmaLíder podem mudar sem modified_on na Weni.
            # Uma varredura de contatos é necessária para detectar D+26, novas
            # compras e recusas em todos os membros, mesmo no incremental.
            contacts = weni.list_contacts()
        contacts.sort(key=lambda c: (cpf_query_priority(get_fields(c).get('cpf')), str(c.get('uuid'))))
        results = Counter()
        for index, contact in enumerate(contacts, 1):
            order, items = resolve_latest(contact, farm, now.isoformat(), cache, state["contacts"].get(contact["uuid"]))
            plan = propose(contact, order, items, structure, state['contacts'].get(contact['uuid']), now=now)
            plans.append(plan); results[plan['reason']] += 1
            if index % 100 == 0 or index == len(contacts): logging.info('Recompra: contatos=%s/%s; resultados=%s.', index, len(contacts), dict(results))
        review = make_review(plans, structure, now=now, state=state)
        write_review(review, args.review_out)
        print('[OK] Dry-run concluído; nenhuma gravação na Weni. Revise ' + str(args.review_out.with_suffix('.txt')))
        print('[INFO] Grupo: 0 a 25 dias. Envio: exclusivamente pela campanha Weni no D+25.')
        return 1 if structure['errors'] else 0
    except Exception as exc:
        logging.error('Recompra falhou: %s.', type(exc).__name__)
        print('[ERRO] ' + (str(exc) if isinstance(exc, (RuntimeError, ValueError)) else 'Falha de API. Consulte o diagnóstico seguro.'))
        return 1
    finally:
        if farm: farm.close()
        if weni: weni.close()


if __name__ == '__main__':
    raise SystemExit(main())
