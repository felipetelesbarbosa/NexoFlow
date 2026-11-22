"""Reservas privadas da aplicação Weni e Recompra no Windows FARMA."""

import hashlib
import json
import os
from dataclasses import dataclass
from uuid import UUID

from project_paths import ROOT

MANIFESTO = ROOT / "credentials" / "farma-reservas.json"
AMBIENTE_SHA = "NEXOFLOW_RESERVAS_FARMA_SHA256"


@dataclass(frozen=True)
class Reservas:
    sha256: str = ""
    contatos: frozenset[str] = frozenset()

    def protege(self, uid: str) -> bool:
        return uid.strip().lower() in self.contatos

    def conferir_revisao(self, revisao):
        if revisao.get("reservas_farma_sha256", "") != self.sha256:
            raise RuntimeError("Reservas FARMA mudaram. Gere nova simulação.")

    def registrar(self, revisao):
        if self.sha256:
            revisao["reservas_farma_sha256"] = self.sha256


def carregar(segmento: str) -> Reservas:
    if segmento != "FARMA":
        return Reservas()
    try:
        conteudo = MANIFESTO.read_bytes()
    except FileNotFoundError:
        reservas = Reservas()
    else:
        try:
            dados = json.loads(conteudo.decode("utf-8-sig"))
            if (
                set(dados) != {"segmento", "adiar_exclusoes", "contatos_recompra"}
                or dados["segmento"] != "FARMA"
                or dados["adiar_exclusoes"] is not True
                or not isinstance(dados["contatos_recompra"], list)
            ):
                raise ValueError
            ids = dados["contatos_recompra"]
            if any(not isinstance(uid, str) or str(UUID(uid)) != uid for uid in ids):
                raise ValueError
            if len(set(ids)) != len(ids):
                raise ValueError
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("Manifesto de reservas FARMA inválido.") from exc
        reservas = Reservas(hashlib.sha256(conteudo).hexdigest(), frozenset(ids))
    esperado = os.environ.get(AMBIENTE_SHA)
    if esperado is not None and esperado != reservas.sha256:
        raise RuntimeError("Arquivo de reservas FARMA mudou desde o início do Noturno.")
    return reservas


def conferir(quantidade: int) -> Reservas:
    from runtime_profile import segment

    reservas = carregar(segment())
    if not reservas.sha256 or quantidade != len(reservas.contatos):
        raise RuntimeError(
            "Confira o perfil FARMA, o arquivo de reservas e a quantidade de contatos."
        )
    print(
        f"Reservas FARMA: {quantidade} contatos; exclusões adiadas; SHA-256 {reservas.sha256}"
    )
    return reservas


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Conferir reservas locais sem acessar APIs."
    )
    parser.add_argument("--esperados", type=int, required=True)
    try:
        conferir(parser.parse_args().esperados)
    except (OSError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")
