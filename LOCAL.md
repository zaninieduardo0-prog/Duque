# TELEX 100% local (sem OpenAI, sem créditos)

Tudo roda no seu PC: **ouvido** (Vosk) → **cérebro** (regras + Ollama) → **voz** (Piper ou voz do Windows).

## Ligar o modo local (uma vez)

1. Dê duplo clique em `preparar_local.bat`. Ele baixa a voz (Piper + pt-BR, ~80 MB),
   instala o Ollama (winget) e baixa o modelo `qwen2.5:3b` (~2 GB).
   Se ele pedir, feche e abra o arquivo de novo depois de instalar o Ollama.
2. Feche o Duque e abra pelo `iniciar_duque.bat`.
3. Diga "TELEX" (ou já com o pedido: "TELEX, que horas são?").

Sem rodar o `preparar_local.bat`, já funciona com a voz do Windows ("Microsoft Maria"),
mas sem o cérebro de modelo (só as regras locais: abrir apps, YouTube, notas, volume...).

## Variáveis (opcionais, `setx NOME valor` e reabrir o Duque)

| Variável | Valores | Para quê |
|---|---|---|
| `DUQUE_VOICE` | `auto` (padrão), `local`, `openai` | auto = OpenAI só se houver chave **e** créditos; senão local |
| `DUQUE_BRAIN` | `auto` (padrão), `local`, `openai` | auto = Ollama se estiver no ar, OpenAI de reserva |
| `DUQUE_LOCAL_MODEL` | `qwen2.5:3b` (padrão), `qwen2.5:1.5b`... | modelo do Ollama |
| `DUQUE_TTS` | `auto`, `piper`, `sapi` | motor de voz |
| `DUQUE_PIPER_VOICE` | nome do arquivo em `duque_data/vozes` | qual voz do Piper usar |
| `DUQUE_SAPI_VOICE` | parte do nome, ex. `Maria` | voz do Windows |
| `DUQUE_STT` | `vosk` (padrão), `whisper` | ouvido (Whisper exige `pip install faster-whisper`) |
| `DUQUE_WAKE_MAX_GAIN` | `6` (padrão) | ganho máximo para microfone baixo |

## Trocar a voz

- Vozes prontas: `.venv\Scripts\python.exe -m voice.local_tts --baixar faber` (também `cadu`, `jeff`, `edresson`).
- Ouvir: `.venv\Scripts\python.exe -m voice.local_tts --testar`
- **Voz diferente de todas:** qualquer voz `.onnx` do Piper (com o `.onnx.json` ao lado) colocada em
  `duque_data/vozes/` vira uma voz do TELEX. Dá para treinar a sua própria voz com o Piper
  (gravações suas ou de uma voz que você tenha direito de usar) e só copiar o arquivo para lá.

## Limites conhecidos (PC com 6 GB de RAM, sem placa de vídeo)

- O modelo de 3B pensa em alguns segundos por resposta. Se estiver pesado, use `qwen2.5:1.5b`.
- Na conversa local o TELEX não é interrompido no meio da fala (ele não distingue a própria voz no
  microfone). Peça "para" depois que ele terminar, ou use o HUD.
- O ouvido Vosk erra mais que o da OpenAI com frases longas ou barulho.

## Voz do Fish Audio (opcional)

O Fish só é usado se existir a chave. Sem `FISH_API_KEY`, nada é enviado para fora e o TELEX fica 100% local.

```powershell
setx FISH_API_KEY "sua-chave"          # fish.audio → conta → API Keys
setx FISH_VOICE_ID "id-da-voz"         # opcional: o ID (reference_id) da voz escolhida/clonada
```

Reabra o Duque. Por padrão usa a faixa gratuita (`FISH_MODEL=s2.1-pro-free`). Se o Fish recusar
(chave inválida, sem saldo, sem rede), o TELEX cancela e fala com a voz local (Piper/Windows) sem travar,
e só tenta o Fish de novo depois de 5 minutos. Para desligar o Fish: `setx DUQUE_TTS piper`.

## Estilo da voz (grave, calma, firme)

`DUQUE_VOICE_STYLE`: `firme` (padrão: calma, grave, fala um pouco mais devagar e com pausas marcadas),
`grave` (ainda mais grave e lento) ou `padrao` (a voz como o Piper entrega).
Ajuste fino: `DUQUE_VOICE_PITCH` (semitons; `-3` mais grave, `0` normal) e `DUQUE_VOICE_SPEED`
(`0.9` mais devagar, `1.0` normal). Ouvir os três estilos em sequência:

```powershell
.\.venv\Scripts\python.exe -m voice.local_tts --amostras
```

Palavra pronunciada errada? Crie `duque_data/pronuncia.txt` com linhas `palavra=como falar`
(ex.: `Embralan=embralã`).
