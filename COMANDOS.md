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

Microfone errado? O diagnóstico lista os microfones com número. Para escolher:

```powershell
setx DUQUE_MIC "<número>"
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
