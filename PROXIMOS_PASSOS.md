# Onde paramos (03/10) e o que fazer a seguir

## ⚠️ Lembrete para o próximo teste: abastecer a OpenAI
A conta da OpenAI ficou **sem créditos** (`insufficient_quota`). Para testar com a API:
1. Adicione créditos em https://platform.openai.com/settings/organization/billing/
2. `.\usar_openai.bat` (deixa voz e cérebro pela OpenAI) e reabra o Duque pelo `iniciar_duque.bat`.
Sem créditos o TELEX cai sozinho para o modo local (se o Ollama estiver instalado) em vez de ficar mudo.

## Estado do projeto
- **Feito e enviado ao GitHub:** ativação "Bom dia, TELEX" com ganho automático de microfone; vários pedidos numa fala
  (separa em etapas, continua nas independentes, pula as que dependem de uma que falhou); modo 100% local
  (Ollama + Vosk + Piper/Windows) com a OpenAI de reserva; voz Piper **cadu** em estilo `firme`
  (grave, calma), ajustável; Fish Audio opcional (só com `FISH_API_KEY`; desligado).
- **Pendente (modo local):** instalar o Ollama (https://ollama.com/download → OllamaSetup.exe), rodar
  `.\preparar_local.bat` (baixa o modelo qwen2.5:3b, ~2 GB) e testar. PC: Ryzen 5 3500U, 5,9 GB RAM, sem placa
  de vídeo → se o modelo pesar, `setx DUQUE_LOCAL_MODEL qwen2.5:1.5b` e `ollama pull qwen2.5:1.5b`.
- **Voz:** cadu aprovada ("gostei do padrão"). Ajuste fino: `DUQUE_VOICE_PITCH`, `DUQUE_VOICE_SPEED`,
  `.\.venv\Scripts\python.exe -m voice.local_tts --amostras`.

## WhatsApp (contato + mensagem pela voz)
Já funciona: o TELEX acha a conversa (agenda salva ou busca no app), confere pela tela quando há OpenAI e envia.
Frases aceitas, entre outras: "manda uma mensagem pro João dizendo que vou atrasar", "manda um oi pra Maria no zap",
"envia no zap pra Maria oi tudo bem", "chama o João no whatsapp e fala que cheguei", "responde o João dizendo ok".
Para ele achar o contato sem erro, salve o número: "salve o contato João 19 99999-9999".
Sem visão (sem OpenAI) ele só deixa a mensagem pronta no WhatsApp para você apertar Enter.

## Se o "pensando" ficar lento
O `iniciar_duque.bat` agora sempre carrega as variáveis atuais do Windows. Se voltar a demorar, veja no `duque.log`
se aparece `[VOZ-LOCAL]` (modo local: modelo de 3B no CPU leva 30-70 s; use `.\usar_openai.bat`).

## Alternar de modo
| Quero | Rode |
|---|---|
| OpenAI (voz + cérebro pela API) | `.\usar_openai.bat` |
| Local (Ollama + Piper) | `.\usar_local.bat` |
Depois de qualquer troca: feche o Duque, abra um PowerShell novo e `.\iniciar_duque.bat`.

## Para testar amanhã (checklist)
1. `git pull`
2. Créditos na OpenAI → `.\usar_openai.bat` → reiniciar o Duque
3. "Bom dia, TELEX" → "abra o Chrome, pesquise o dólar e depois feche o Chrome"
4. Algo falhou? Mande as linhas do `duque.log` com `[WAKE]`, `[VOZ]`, `[GATE]`, `[VOZ-LOCAL]`, `[TTS]`.

Detalhes do modo local e das variáveis: `LOCAL.md`.
