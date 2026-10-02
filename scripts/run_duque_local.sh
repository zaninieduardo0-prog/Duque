#!/usr/bin/env bash
# Script simples para iniciar o servidor Duque com modelo local (Linux/macOS)
# Uso: DUQUE_LOCAL_BACKEND=gpt4all DUQUE_LOCAL_MODEL_PATH=/path/to/model ./scripts/run_duque_local.sh

set -euo pipefail

export DUQUE_LOCAL_MODEL=1

echo "Iniciando Duque com modelo local..."
python servidor.py
