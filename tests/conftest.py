"""
PYTEST ENVIRONMENT SETUP
------------------------
The built-in tmp_path fixture asks pytest to scan and clean a shared Temp
directory. On some Windows machines that directory is inaccessible. This
project fixture creates a unique folder directly under tests/ instead.
"""

import os
import uuid
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_path() -> Path:
    """Return an isolated folder without pytest temporary-directory scanning."""
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / "tests" / f".test_tmp_{os.getpid()}_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
