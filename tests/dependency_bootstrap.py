"""Utilities for auto-installing lightweight test dependencies.

This module is intentionally imported from test `conftest.py` files so a plain
`pytest` run can bootstrap required packages (for example SQLAlchemy) in
minimal environments.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from typing import Iterable


_REQUIRED_PACKAGES: tuple[tuple[str, str], ...] = (
    ("sqlalchemy", "sqlalchemy>=2,<3"),
)


def _is_module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _install_requirement(requirement: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", requirement, "-q"])


def ensure_test_dependencies(required_packages: Iterable[tuple[str, str]] | None = None) -> None:
    """Install missing test dependencies unless explicitly disabled.

    Set `ONTOLOGY_AUTO_INSTALL_TEST_DEPS=0` to disable this behavior.
    """

    if os.environ.get("ONTOLOGY_AUTO_INSTALL_TEST_DEPS", "1") == "0":
        return

    for module_name, requirement in required_packages or _REQUIRED_PACKAGES:
        if not _is_module_available(module_name):
            _install_requirement(requirement)
