# Comandos para rodar no PC (PowerShell)

Copie e cole **um bloco por vez**, na ordem. Onde estiver `<...>`, troque pelo
seu valor (sem os sinais `<` `>`).

---

## Passo 1 — Entrar na pasta do Duque

```powershell
cd "<CAMINHO DA PASTA DO DUQUE>"
```

> Não lembra onde está? Abra a pasta no Explorer, clique na barra de endereço,
> copie o caminho e cole entre as aspas.

Confira se é a pasta certa (deve listar `duque.py`, `servidor.py`, `Duque.vbs`):

```powershell
dir duque.py, servidor.py, Duque.vbs
```

## Passo 2 — Fechar o Duque, se estiver aberto

```powershell
Get-Process pythonw, python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$((Get-Location).Path)*" } | Stop-Process
```

## Passo 3 — Backup dos bancos antigos (eles saem do GitHub)

```powershell
New-Item -ItemType Directory -Force "$HOME\Documents\Duque-backup" | Out-Null
Copy-Item .\duque_memoria.db, .\duque_imoveis.db "$HOME\Documents\Duque-backup\" -ErrorAction SilentlyContinue
dir "$HOME\Documents\Duque-backup"
```

## Passo 4 — Ver se a pasta é um repositório Git

```powershell
git status
```

- Mostrou **"On branch main"** → vá para o **Passo 5A**.
- Mostrou **"not a git repository"** → vá para o **Passo 5B**.
- Mostrou arquivos em vermelho em **"Changes not staged"** → rode primeiro:

```powershell
git stash push -m "minhas alteracoes antes da atualizacao"
```

## Passo 5A — Atualizar (pasta já é Git)

Se você **já fez o merge do PR #8 no site do GitHub**:

```powershell
git checkout main
git pull origin main
```

Se **ainda não fez o merge** (faz o merge daqui mesmo, sem abrir o site):

```powershell
git checkout main
git pull origin main
git fetch origin duque/proxima-versao
git merge --no-ff origin/duque/proxima-versao -m "Merge da próxima versão do Duque (PR #8)"
git push origin main
```

> O PR #8 (e o #7) fecham sozinhos no GitHub depois do `git push`.
>
> Se o `git push` abrir uma janela de login do GitHub, entre com a conta
> **zaninieduardo0-prog**. O Windows guarda a credencial, e é ela que a Forja
> usa depois para enviar as melhorias (a Forja nunca abre janela de login
> sozinha).

## Passo 5B — Pasta não é Git (instalação nova ao lado da antiga)

```powershell
cd ..
git clone https://github.com/zaninieduardo0-prog/Duque.git Duque-novo
cd Duque-novo
git fetch origin duque/proxima-versao
git merge --no-ff origin/duque/proxima-versao -m "Merge da próxima versão do Duque (PR #8)"
git push origin main
```

> A partir daqui, use a pasta **Duque-novo**. A antiga fica intacta como backup.

## Passo 6 — Chaves (variáveis de ambiente)

Só rode as que ainda não existem. **Nunca** coloque as chaves em arquivos do projeto.

```powershell
setx OPENAI_API_KEY "<sua chave da OpenAI>"
setx ANTHROPIC_API_KEY "<sua chave da Anthropic, começa com sk-ant->"
setx DUQUE_CITY "Piracicaba"
```

Opcional — horário do resumo do dia falado (padrão 21:30; `"0"` desliga):

```powershell
setx DUQUE_DAILY_SUMMARY "21:30"
```

Opcional (a Forja abrir PRs sozinha): crie em
GitHub → Settings → Developer settings → Fine-grained tokens, só para o
repositório **Duque**, com *Contents: Read and write* e
*Pull requests: Read and write*.

```powershell
setx DUQUE_GITHUB_TOKEN "<seu token github_pat_...>"
```

**Feche o PowerShell e abra de novo** (o `setx` só vale em janelas novas) e
volte para a pasta (Passo 1).

Conferir se ficaram salvas (mostra só se existe, não a chave):

```powershell
"OPENAI: $([bool]$env:OPENAI_API_KEY)  ANTHROPIC: $([bool]$env:ANTHROPIC_API_KEY)  GITHUB: $([bool]$env:DUQUE_GITHUB_TOKEN)"
```

## Passo 7 — Preparar e diagnosticar

```powershell
.\preparar_duque.bat
```

Tudo `[OK]` ou `[AVISO]` → siga. Algum `[FALHA]` → mande print para o Claude.

Microfone errado? O diagnóstico lista os microfones com número. Para escolher
(um número só: a conversa usa o mesmo microfone da ativação):

```powershell
setx DUQUE_WAKE_MIC "<número>"
```

## Passo 8 — Iniciar o Duque

```powershell
wscript .\Duque.vbs
```

Depois siga o **TESTES.md**.

---

## Comandos úteis no dia a dia

Ver o log do Duque (últimas 60 linhas):

```powershell
Get-Content .\duque.log -Tail 60
```

Ver o log do supervisor (reinícios, atualizações, rollback):

```powershell
Get-Content .\duque_data\supervisor.log -Tail 40
```

Diagnóstico completo com testes:

```powershell
.\.venv\Scripts\python.exe diagnostico.py --testes
```

Atualizar manualmente (quando não estiver usando a Forja):

```powershell
git pull origin main
.\.venv\Scripts\python.exe -m pip install -e .
```

Andamento da Forja no navegador: <http://127.0.0.1:5000/api/forja>

## Autoteste da voz (quando ele "às vezes não ouve")

Feche o TELEX antes (o microfone não pode estar em uso) e rode:

```powershell
cd C:\Users\zanin\Duque
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process
.\.venv\Scripts\python.exe -m voice.selftest
```

Fale "Bom dia, TELEX" enquanto a barra aparece. Ele mostra o nível do microfone
e o que entendeu, e grava em `duque.log`. Me mande esse resultado: com ele eu
descubro se é microfone mudo, microfone errado, volume baixo ou reconhecimento.

Trocar o microfone, se o diagnóstico apontar outro número:

```powershell
setx DUQUE_WAKE_MIC "<número>"
```

## Iniciar junto com o Windows (sem interface, só voz)

Dê dois cliques **uma vez** em `iniciar_com_windows.bat`. A partir daí o TELEX
liga junto com o Windows só com a voz; a interface abre sozinha quando você
disser "Bom dia, TELEX". Para desfazer: `parar_inicio_windows.bat`.

## Desligar o TELEX

Pela voz: "Telex, desligar". Pelo HUD: botão **Desligar** (dois cliques).
Pelo PowerShell (se a interface sumiu):

```powershell
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process
```

Interface fechada mas TELEX ligado: abra `http://127.0.0.1:5000` no Chrome.

## Emergência — voltar para a versão anterior

```powershell
git log --oneline -8
```

Copie o código (7 letras) da versão que funcionava e:

```powershell
git reset --hard <código>
```

> Isso só mexe no código do Duque. Memória e configurações (`duque_data/`)
> continuam.

---

## Aplicar uma atualização nova do Claude (branch `duque/ajustes-N`)

> Sempre comece pelo `cd C:\Users\zanin\Duque`. Se aparecer
> `fatal: not a git repository`, o PowerShell está fora da pasta do TELEX.

Troque `N` pelo número que o Claude informar (a última foi **13**). Um bloco por vez:

```powershell
cd C:\Users\zanin\Duque
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process
git fetch origin
git merge origin/duque/ajustes-13 -m "Ajustes 13"
git push origin main
.\preparar_duque.bat
wscript .\Duque.vbs
```

> O `preparar_duque.bat` só é obrigatório quando a atualização traz pacote novo
> (a 13 inclui da 7 em diante; a 7 baixa de novo o modelo do "Bom dia, TELEX"). Ele termina com o
> diagnóstico; aperte uma tecla para fechar.

Opcionais do TELEX (depois feche e abra):

```powershell
setx DUQUE_LOCAL_WAKE "0"
setx DUQUE_TTS_SPEED "1.12"
setx DUQUE_LISTEN_SECONDS "8"
setx DUQUE_OPERATOR "1"
```

`DUQUE_LISTEN_SECONDS`: quanto tempo ele fica ouvindo depois de "Telex".
`DUQUE_AFTER_GREETING` (5): espera depois da saudação. `DUQUE_MEDIA_VOLUME` (30): volume ao tocar
música/vídeo (`"0"` não mexe).
`DUQUE_OPERATOR`: `"0"` desliga o operador autônomo (pedidos sem ferramenta pronta).

`DUQUE_TTS_SPEED` é a velocidade da fala do HUD (1.0 normal, 1.2 mais rápida).

Desde a 9 o "Hey Jarvis" já vem desligado (um nome só: TELEX). Ele só volta
sozinho como reserva se o modelo do "Bom dia, TELEX" não carregar. Os textos que o TELEX escreve no
Bloco de Notas ficam em `Documentos\TELEX` (mude com `setx DUQUE_NOTES_DIR "<pasta>"`).

Opcionais da audição e do Chrome (depois feche e abra o Duque):

```powershell
setx DUQUE_CHROME_PROFILE "zaninieduardo0"
setx DUQUE_VOICE_IDLE "60"
setx DUQUE_VAD_INTERRUPT "0"
```
