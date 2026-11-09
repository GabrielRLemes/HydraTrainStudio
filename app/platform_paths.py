from pathlib import Path
import os

WINDOWS=os.name=="nt"
VENV_PY=Path("Scripts/python.exe" if WINDOWS else "bin/python")
