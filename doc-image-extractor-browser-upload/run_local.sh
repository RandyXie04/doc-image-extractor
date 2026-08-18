#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
exec python3 -m streamlit run app.py --server.address 127.0.0.1
