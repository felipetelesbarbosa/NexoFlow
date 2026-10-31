"""Cadastro reverso API → Weni: revisão, identidade única e criação sem consentimento inferido."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy

from analytics import get_fields, is_valid_cpf, normalize_cpf
from customer_observations import connect
from farmalider_customers import directory_for, matching_order_address
from runtime_profile import segment
from weni_client import WeniError


class CreationError(WeniError):
    """Motivo e etapa estáveis; diagnóstico sem CPF, telefone ou nome."""

    def __init__(self, message, *, code, stage, status_code=None, validation=None):
        super().__init__(message, status_code=status_code, validation=validation)
        self.code = code
        self.stage = stage


PREFIX = "novo-api:"
GUARD = "__new_api_customer"


def snapshot_digest(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    return "55" + digits if len(digits) in (10, 11) and len(set(digits)) > 1 else ""


def phone_lookup_keys(value):
    """Somente busca preventiva: a variação não comprova CPF nem autoriza fusão."""
    number = phone(value)
    if not number:
        return set()
    keys = {number}
    if re.fullmatch(r"55[1-9]\d9[6-9]\d{7}", number):
        keys.add(number[:4] + number[5:])
    elif re.fullmatch(r"55[1-9]\d[6-9]\d{7}", number):
        keys.add(number[:4] + "9" + number[4:])
    return keys


def contact_phones(contact):
    values = [
        str(u).split(":", 1)[-1]
        for u in contact.get("urns", [])
        if str(u).split(":", 1)[0] in ("tel", "whatsapp")
    ]
    values += [get_fields(contact).get(k) for k in ("telefone", "celular", "whatsapp")]
    return {p for value in values if (p := phone(value))}


class ContactIndex:
    def __init__(self, contacts):
        self.cpfs, self.phones = {}, {}
        for contact in contacts:
            self.add(contact)

    def add(self, contact):
        cpf = normalize_cpf(get_fields(contact).get("cpf"))
        if cpf:
            self.cpfs.setdefault(cpf, []).append(contact)
        for number in contact_phones(contact):
            for key in phone_lookup_keys(number):
                self.phones.setdefault(key, []).append(contact)

    def matches(self, cpf, number):
        candidates = list(self.cpfs.get(cpf, []))
        for key in phone_lookup_keys(number):
            candidates.extend(self.phones.get(key, []))
        unique = []
        for contact in candidates:
            if contact not in unique:
                unique.append(contact)
        return unique


def build_new_customer_plans(
    farm, contacts, *, captured_at, available_fields, quarter=None
):
    from product_scope import pharmacy_items
    from weni_update import PlanAuditError, _build_contact_plan, audit_plans

    directory = directory_for(farm)
    if directory is None:
        return [], {"BASE_INDISPONIVEL": 1}
    plans, reasons = [], Counter()
    index = ContactIndex(contacts)
    candidates = list(directory.by_id.values())
    cpf_counts = Counter(normalize_cpf(c["cpf"]) for c in candidates)
    phone_counts = Counter(
        key for c in candidates for key in phone_lookup_keys(c.get("celular"))
    )
    for customer in candidates:
        cid = str(customer["id"])
        if quarter is not None and int(cid) % 4 != quarter - 1:
            continue
        cpf, number = normalize_cpf(customer["cpf"]), phone(customer.get("celular"))
        matches = index.matches(cpf, number)
        if matches:
            if len(matches) != 1:
                reasons["IDENTIDADE_AMBIGUA"] += 1
            elif normalize_cpf(get_fields(matches[0]).get("cpf")) != cpf:
                stored = normalize_cpf(get_fields(matches[0]).get("cpf"))
                reasons[
                    "CONTATO_EXISTENTE_SEM_CPF"
                    if not stored or not stored.strip("0")
                    else "CONTATO_EXISTENTE_COM_CPF_DIVERGENTE"
                ] += 1
            continue
        if not is_valid_cpf(cpf):
            reasons["CPF_SEM_IDENTIDADE_WENI"] += 1
            continue
        if cpf_counts[cpf] != 1 or any(
            phone_counts[key] != 1 for key in phone_lookup_keys(number)
        ):
            reasons["IDENTIDADE_AMBIGUA"] += 1
            continue
        if cid not in directory.snapshots:
            reasons["PEDIDO_INCOMPLETO"] += 1
            continue
        snapshot = directory.snapshots[cid]
        scoped = [
            {
                "produto_nome": i.get("descricao"),
                "produto_codigo": i.get("codProduto"),
                "categoria": i.get("categoria"),
            }
            for i in snapshot["itens"]
        ]
        if not pharmacy_items(scoped):
            reasons["PEDIDO_FORA_DO_ESCOPO"] += 1
            continue
        urns = ["whatsapp:" + number] if number else []
        contact = {
            "uuid": PREFIX + segment() + ":" + cid,
            "name": str(customer.get("nome") or "").strip(),
            "fields": {"cpf": cpf},
            "urns": urns,
            "groups": [],
        }
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=farm,
            opt_out_group_name="",
            opt_out_group_uuid="",
            captured_at=captured_at,
            available_weni_fields=available_fields,
        )
        if not plan.order_validated:
            reasons["PEDIDO_NAO_VALIDADO"] += 1
            continue
        extra = {}
        if "email" in available_fields and customer.get("email"):
            extra["email"] = str(customer["email"]).strip()
        if "origem_contato" in available_fields:
            extra["origem_contato"] = "API FarmaLíder — " + segment()
        address_status, address = matching_order_address(customer, segment=segment())
        if (
            "endereco" in available_fields
            and address_status == "ENDERECO_CONFIRMADO"
            and address
        ):
            extra["endereco"] = ", ".join(
                str(address.get(key) or "").strip()
                for key in ("logradouro", "numero", "complemento")
                if str(address.get(key) or "").strip()
            )
        plan.fields["cpf"] = cpf
        plan.previous["cpf"] = None
        plan.guards[GUARD] = {
            "segment": segment(),
            "customer_id": cid,
            "name": contact["name"],
            "urns": urns,
            "extra_fields": extra,
            "source_sha256": snapshot_digest(directory.snapshots[cid]),
        }
        try:
            audit_plans([plan], opt_out_group_available=True)
        except PlanAuditError:
            reasons["CAMPOS_NAO_APROVADOS_PELA_AUDITORIA"] += 1
            continue
        plans.append(plan)
    return plans, dict(reasons)


def audit_creation(plan):
    data = plan.guards.get(GUARD)
    if not isinstance(data, dict) or data.get("segment") != segment():
        raise ValueError("Cadastro novo pertence a outro segmento.")
    if plan.contact_uuid != PREFIX + segment() + ":" + str(data.get("customer_id")):
        raise ValueError("Identificador do cadastro novo divergente.")
    if (
        not is_valid_cpf(plan.fields.get("cpf"))
        or plan.group_actions
        or not plan.order_validated
    ):
        raise ValueError(
            "Novo cadastro sem pedido/identidade válidos ou com inclusão em grupo."
        )
    if set(data.get("extra_fields", {})) - {"email", "origem_contato", "endereco"}:
        raise ValueError("Campo extra não autorizado no cadastro.")
    if any(key.startswith(("opt_in", "marketing_")) for key in plan.fields):
        raise ValueError("Novo cadastro não presume consentimento.")
    if any(u != "whatsapp:" + phone(u.split(":", 1)[-1]) for u in data.get("urns", [])):
        raise ValueError("Telefone inválido no cadastro.")


class CreationSession:
    def __init__(self, weni, farm):
        from farmalider_customers import prepare_customers

        self.weni = weni
        self.farm = farm
        prepare_customers(farm, None)
        weni._check_profile_org()
        self.contacts = ContactIndex(weni.list_contacts(after=None))

    def apply(self, plan):
        audit_creation(plan)
        data = plan.guards[GUARD]
        directory = directory_for(self.farm)
        fresh = (
            directory.snapshots.get(str(data["customer_id"]))
            if directory is not None
            else None
        )
        if fresh is None or snapshot_digest(fresh) != data.get("source_sha256"):
            raise CreationError(
                "Cadastro ou pedido mudou após a revisão; nova revisão necessária.",
                code="FONTE_ALTERADA_APOS_REVISAO",
                stage="revalidar_fonte",
            )
        number = phone((data.get("urns") or [""])[0].split(":")[-1])
        cpf = plan.fields["cpf"]
        if cpf != normalize_cpf(fresh["cliente"]["cpf"]) or number != phone(
            fresh["cliente"].get("celular")
        ):
            raise CreationError(
                "CPF ou telefone do novo cadastro diverge da fonte oficial.",
                code="IDENTIDADE_DIVERGENTE",
                stage="revalidar_identidade",
            )
        matches = self.contacts.matches(cpf, number)
        if number:
            for key in sorted(phone_lookup_keys(number)):
                latest = self.weni.get_contact(urn="whatsapp:" + key)
                if latest and latest not in matches:
                    matches.append(latest)
        if matches:
            # A variação de telefone evita duplicação; nunca substitui a prova de CPF.
            if (
                len(matches) != 1
                or normalize_cpf(get_fields(matches[0]).get("cpf")) != cpf
                or not matches[0].get("uuid")
            ):
                raise CreationError(
                    "Contato já existe por CPF/telefone; identidade exige reconciliação, sem novo POST.",
                    code="CONTATO_EXISTENTE_IDENTIDADE_NAO_CONFIRMADA",
                    stage="verificar_contato_existente",
                )
            return "already_exists", matches[0]["uuid"]
        with connect() as db:
            prior = db.execute(
                "SELECT status,uuid FROM creations WHERE id=?", (plan.contact_uuid,)
            ).fetchone()
            if prior:
                raise CreationError(
                    "Criação anterior já tentada; reconciliação pendente, sem novo POST.",
                    code="CRIACAO_ANTERIOR_INDETERMINADA",
                    stage="reconciliar_tentativa",
                )
            db.execute(
                "INSERT INTO creations(id,status) VALUES(?,?)",
                (plan.contact_uuid, "pending"),
            )
        try:
            response = self.weni.create_contact(
                name=data["name"],
                urns=data["urns"],
                fields={**plan.fields, **data["extra_fields"]},
            )
        except WeniError as exc:
            # Rejeição definitiva não criou cadastro: nova revisão pode tentar.
            # Timeout, rede e 5xx permanecem incertos e não repetem o POST.
            if exc.status_code in {400, 401, 403, 404, 422}:
                with connect() as db:
                    db.execute("DELETE FROM creations WHERE id=?", (plan.contact_uuid,))
            reason = str(exc.validation.get("reason") or "SEM_DETALHE")
            raise CreationError(
                "Weni recusou ou não confirmou a criação do contato.",
                code=f"WENI_HTTP_{exc.status_code}_{reason}"
                if exc.status_code
                else "WENI_RESULTADO_INDETERMINADO",
                stage="criar_contato",
                status_code=exc.status_code,
                validation=exc.validation,
            ) from None
        if (
            not isinstance(response, dict)
            or not response.get("uuid")
            or normalize_cpf(get_fields(response).get("cpf")) != cpf
        ):
            raise CreationError(
                "A criação não teve persistência confirmada; revalidar na próxima carga.",
                code="CRIACAO_NAO_CONFIRMADA",
                stage="confirmar_resposta",
            )
        from weni_update import _same_value

        expected = {**plan.fields, **data["extra_fields"]}
        if any(
            not _same_value(key, get_fields(response).get(key), value)
            for key, value in expected.items()
        ):
            raise CreationError(
                "A criação não confirmou todos os campos; reconciliação pendente.",
                code="CAMPOS_NAO_CONFIRMADOS",
                stage="confirmar_campos",
            )
        with connect() as db:
            db.execute(
                "UPDATE creations SET status=?,uuid=? WHERE id=?",
                ("confirmed", response["uuid"], plan.contact_uuid),
            )
        self.contacts.add(deepcopy(response))
        return "created", response["uuid"]
