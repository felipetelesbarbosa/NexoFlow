"""Seleciona o segmento antes de carregar a configuração do armazenamento."""

import argparse
import os


def run(argv=None, *, input_fn=input):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--perfil", choices=("FARMA", "PET"))
    parser.add_argument("operation", nargs="?", choices=("configurar", "status"))
    args = parser.parse_args(argv)
    from run_noturno_console import choose

    profile = args.perfil or os.environ.get("NEXOFLOW_PERFIL")
    if not profile:
        print("NexoFlow — armazenamento\n[1] FarmaLíder\n[2] Pets Líder")
        profile = choose({"1": "FARMA", "2": "PET"}, "Segmento: ", input_fn)
    if profile not in ("FARMA", "PET"):
        raise ValueError("Perfil inválido.")
    os.environ["NEXOFLOW_PERFIL"] = profile
    operation = args.operation
    if not operation:
        print(
            "[1] Autorizar Google e configurar continuações\n[2] Consultar capacidade\n[0] Sair"
        )
        operation = choose(
            {"1": "configurar", "2": "status", "0": None}, "Escolha: ", input_fn
        )
    if operation is None:
        return 0
    from run_sheets_continuation import run as storage_run

    return storage_run([operation])


if __name__ == "__main__":
    try:
        result = run()
    except (RuntimeError, OSError, ValueError) as error:
        print(f"[ERRO] {error}")
        result = 1
    print(f"Código de saída: {result}")
    try:
        input("Pressione ENTER para fechar...")
    except EOFError:
        pass
    raise SystemExit(result)
