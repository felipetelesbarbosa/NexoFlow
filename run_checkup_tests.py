from __future__ import annotations

import logging
import sys
import unittest
import warnings


def main() -> int:
    # O check-up deve mostrar somente o que importa. Logs/warnings esperados
    # dos mocks ficam silenciosos; falhas e tracebacks do unittest continuam
    # visíveis normalmente pelo TextTestRunner.
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")

    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
