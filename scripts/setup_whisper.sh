#!/usr/bin/env bash
# Script de orientação para instalar Whisper e dependências (não baixa modelos automaticamente)

set -euo pipefail

echo "Instalando dependências para Whisper (opcional)"
python -m pip install --upgrade pip
python -m pip install -U openai-whisper || true

cat <<'EOF'
Observações:
- Whisper e modelos podem ser grandes. Este script apenas instala a ferramenta; você deve baixar modelos localmente quando necessário.
- Alternativamente, use ferramentas leve como vosk para STT offline.
EOF

exit 0
