Guia rápido: executar Duque com modelo local

Objetivo
Este documento explica como configurar o Duque para usar um modelo local (gpt4all ou llama-cpp-python) em vez da API OpenAI.

Pré-requisitos
- Python 3.10+
- Dependências opcionais:
  - gpt4all (pip install gpt4all)
  - llama-cpp-python (pip install llama-cpp-python) e um arquivo de modelo local compatível
- Hardware adequado para o modelo escolhido (CPU ou GPU conforme o backend)

Configuração
1. Escolha um backend e instale o pacote Python correspondente.
   - Para gpt4all: pip install gpt4all
   - Para llama: pip install llama-cpp-python

2. Defina variáveis de ambiente:
   - DUQUE_LOCAL_MODEL=1
   - DUQUE_LOCAL_BACKEND=gpt4all   # ou 'llama'
   - DUQUE_LOCAL_MODEL_PATH=/caminho/para/o/modelo  # necessário para llama e recomendado para gpt4all
   - DUQUE_ALLOW_SELF_MODIFICATION=0 # por padrão, alterações requerem aprovação humana
   - DUQUE_API_TOKEN=seu_token_opcional # protege endpoints sensíveis

Execução
- Teste se o backend está acessível:
  python scripts/check_local_model.py

- Inicie o servidor do Duque (exemplo):
  DUQUE_LOCAL_MODEL=1 python servidor.py

Instalação rápida de ferramentas locais (opcional):
1. Execute scripts/setup_local_models.sh para instalar pyttsx3 e vosk (não baixa modelos automaticamente).
2. Para VOSK, baixe um modelo grande e defina DUQUE_VOSK_MODEL_PATH apontando para o diretório do modelo.
3. Para TTS local, pyttsx3 usa backends do SO (SAPI5 no Windows; espeak/pulseaudio no Linux).

Observações de segurança
- A funcionalidade de auto-modificação do Duque permite que o agente sugira e aplique mudanças no workspace. Por padrão, o sistema requer revisão/aprovação humana antes de aplicar mudanças automatizadas.
- Não exponha o servidor em redes públicas sem controles de acesso.

Licença e modelos
- Verifique licenças dos modelos que você baixar. Alguns modelos têm restrições de uso.

Se algo falhar, veja as mensagens de erro retornadas por scripts/check_local_model.py e ajuste dependências e caminhos.
