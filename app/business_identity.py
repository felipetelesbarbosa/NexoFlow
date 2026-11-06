"""Validação matemática de CPF, sem configuração de segmento ou transporte."""

from __future__ import annotations


def cpf_checksum_valid(cpf: str) -> bool:
    if len(cpf) != 11 or not cpf.isascii() or not cpf.isdecimal() or cpf == cpf[0] * 11:
        return False

    def digit(base: str, factor: int) -> str:
        total = sum(
            int(n) * weight
            for n, weight in zip(base, range(factor, 1, -1), strict=False)
        )
        result = (total * 10) % 11
        return "0" if result == 10 else str(result)

    return cpf[9] == digit(cpf[:9], 10) and cpf[10] == digit(cpf[:10], 11)
