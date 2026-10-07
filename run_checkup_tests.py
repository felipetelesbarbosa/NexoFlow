from __future__ import annotations

import logging
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    # O check-up deve mostrar somente o que importa. Logs/warnings esperados
    # dos mocks ficam silenciosos; falhas e tracebacks do unittest continuam
    # visíveis normalmente pelo TextTestRunner.
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")

    # Synthetic HTTP500 fixtures must never appear as real customer failures.
    with tempfile.TemporaryDirectory(prefix="nexoflow_checkup_") as directory:
        with patch("private_diagnostics.private_diagnostic_directory", return_value=Path(directory)):
            suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
            result = unittest.TextTestRunner(verbosity=0).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
