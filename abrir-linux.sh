#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
venv="$PWD/componentes/interface"
python3 -c 'import sys,tkinter; assert sys.version_info >= (3,11), "Python 3.11+ necessário"' || { echo "Instale Python 3.11+, tkinter e venv da sua distribuição."; exit 1; }
if [[ ! -x "$venv/bin/python" ]]; then python3 -m venv "$venv"; fi
if [[ ! -f "$venv/.interface-pronta" ]]; then
  "$venv/bin/python" -m pip install 'uv==0.12.9' 'av==17.1.0' 'numpy==2.5.4' 'pillow==13.0.0' 'requests==2.34.2' 'psutil>=7,<8' 'nvidia-ml-py==13.595.45' 'pyyaml>=6,<7' 'keyring>=25,<26' 'SecretStorage>=3.3,<4'
  touch "$venv/.interface-pronta"
fi
exec "$venv/bin/python" -B app/inicio.py
