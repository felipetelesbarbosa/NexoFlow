"""Verificação de recibo compartilhada pelo Windows e pelo Hub."""


def ready_receipt_matches(receipt, *, revision, manifest_hash, version=None):
    if not isinstance(receipt, dict):
        return False
    actual_version = receipt.get("version")
    return (
        receipt.get("state") == "READY"
        and receipt.get("revision") == revision
        and receipt.get("manifest_hash") == manifest_hash
        and type(actual_version) is int
        and actual_version > 0
        and (version is None or (type(version) is int and actual_version == version))
    )
