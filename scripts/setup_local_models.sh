#!/usr/bin/env bash
# Script de bootstrap para instalação opcional de ferramentas locais (pyttsx3, vosk)
# NÃO baixa modelos pesados automaticamente.

set -euo pipefail

echo "Instalando dependências Python opcionais (pyttsx3, vosk, soundfile)..."
python -m pip install --upgrade pip
python -m pip install pyttsx3 || true
python -m pip install vosk soundfile || true

echo
cat <<'EOF'
Próximo passos (manuais):
- Para VOSK: baixe um modelo em https://alphacephei.com/vosk/models e defina DUQUE_VOSK_MODEL_PATH para o diretório do modelo.
- Para LLMs: obtenha pesos compatíveis (gpt4all/llama) e configure DUQUE_LOCAL_MODEL_PATH.
- Para GitHub PRs: exporte GH_TOKEN com permissões repo.
EOF

exit 0
