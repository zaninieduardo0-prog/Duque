Execução local do Duque

Modo rápido (ambiente virtual):

1. Criar e ativar venv
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate     # Windows

2. Instalar dependências
   pip install -e .

3. Rodar servidor (texto)
   python servidor.py

Com modelo local (opcional):

- Instale gpt4all ou llama-cpp-python conforme preferir.
- Defina variáveis de ambiente:
  DUQUE_LOCAL_MODEL=1
  DUQUE_LOCAL_BACKEND=gpt4all
  DUQUE_LOCAL_MODEL_PATH=/caminho/para/modelo

- Teste backends:
  python scripts/check_local_model.py

- Inicie com:
  DUQUE_LOCAL_MODEL=1 python servidor.py

Acesso à interface:
- Abra http://127.0.0.1:5000/ para a HUD principal
- Abra http://127.0.0.1:5000/editor.html para o editor de workspace

Segurança e revisão
- Por padrão, auto-modificação pode estar habilitada. Ajuste DUQUE_ALLOW_SELF_MODIFICATION=0 para desabilitar.
 - Por padrão, auto-aplicação NÃO é feita automaticamente. Use DUQUE_ALLOW_SELF_MODIFICATION=1 para permitir merges automáticos feitos pelo Duque (alto risco).

Voz e STT local
- Para TTS offline (pyttsx3): instale com scripts/setup_local_models.sh e valide com scripts/check_local_model.py. No Windows, pyttsx3 usa SAPI5.
- Para STT (VOSK): baixe um modelo VOSK e defina DUQUE_VOSK_MODEL_PATH para o diretório do modelo; use scripts/setup_local_models.sh para instalar requisitos.

Criação de PR automatizada
- Para criar PRs remotamente, exporte GH_TOKEN com permissões repo; o endpoint /api/workspace/propose_change aceita create_pr=true para tentar push+PR.
 - Para criar PRs remotamente, exporte GH_TOKEN com permissões repo; o endpoint /api/workspace/propose_change aceita create_pr=true para tentar push+PR. Se a CLI 'gh' estiver instalada, o Duque usará ela prioritariamente para criar PRs.

Gravação e STT via navegador
- A interface agora permite gravar áudio diretamente do navegador e enviar para /api/stt.
- O servidor tentará VOSK primeiro; se falhar, usa um fallback via scripts/whisper_infer.py se disponível.


