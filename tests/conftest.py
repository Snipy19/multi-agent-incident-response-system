"""
PYTEST ENVIRONMENT SETUP
------------------------
Use a fresh temporary root inside the project workspace. Some Windows
installations restrict or lock the default user Temp directory, which can
prevent pytest's tmp_path fixture from creating or cleaning test databases.
"""

import os
import tempfile
from pathlib import Path


_project_root = Path(__file__).resolve().parents[1]
_runtime_root = _project_root / ".pytest_runtime"
_runtime_root.mkdir(exist_ok=True)

# pytest consults tempfile.gettempdir() when it creates the tmp_path factory.
# Setting both the environment and Python's cached temp directory keeps this
# behavior consistent across Windows and Python versions.
os.environ["TEMP"] = str(_runtime_root)
os.environ["TMP"] = str(_runtime_root)
tempfile.tempdir = str(_runtime_root)
