# Forja — o Duque desenvolvendo a si mesmo

A Forja é o caminho seguro para o Duque alterar o próprio código. A cópia em
execução **nunca** é editada diretamente pelo agente.

```
pedido
  └─> cópia isolada (git worktree em duque_data/forja/work, branch duque/forja-*)
        └─> agente programador (lê, procura, edita, roda checks)
              └─> verificação independente: compilação + testes + ruff
                    ├─ falhou → nova rodada com o erro real (até 3)
                    └─ passou → commit + push do branch + PR
                          └─> CI no GitHub (Windows)
                                ├─ falhou → nova rodada com as anotações do CI
                                └─ passou → fast-forward no main
                                      └─> atualização da instalação ao vivo
                                            ├─ validação local falhou → volta à versão anterior
                                            └─ reinício pelo supervisor
                                                  └─ não respondeu em /status → rollback automático
```

## Freios que o agente não pode tirar sozinho

Alterações nestes arquivos nunca entram automaticamente; o PR fica aberto
esperando aprovação humana:

- `core/security.py`, `forge/`, `.github/`, `duque_supervisor.py`,
  `Duque.vbs`, `iniciar_duque.bat`, `pyproject.toml`
- qualquer remoção de arquivo de teste

Além disso: a verificação é feita pelo código da Forja, não pela palavra do
modelo; o merge é sempre fast-forward (nunca força); a atualização ao vivo
nunca descarta alterações locais suas.

## Configuração (variáveis de ambiente no Windows)

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | cérebro programador (Claude). Sem ela, usa `OPENAI_API_KEY`; sem nenhuma, a Forja fica desligada |
| `DUQUE_DEV_MODEL` | modelo do programador (padrão `claude-sonnet-5-5`) |
| `DUQUE_GITHUB_TOKEN` | token *fine-grained* só do repositório Duque, com **Contents: read/write** e **Pull requests: read/write**. Sem ele, o branch é enviado com suas credenciais do Git, mas o PR não é aberto |
| `DUQUE_FORGE_AUTO_MERGE` | `1` (padrão) aplica sozinho quando o CI passa; `0` sempre espera aprovação |
| `DUQUE_FORGE_REQUIRE_CI` | `1` (padrão) só aplica com CI verde |
| `DUQUE_FORGE_MAX_ROUNDS` / `DUQUE_FORGE_MAX_STEPS` | limites de rodadas e de ações por rodada |

Nunca coloque chaves no código nem em arquivos versionados.

## Supervisor

`duque_supervisor.py` roda o `duque.py` como processo filho. Quando a Forja
aplica uma atualização, o Duque sai com código 75, o supervisor reinicia e
deixa a versão nova em observação por 90 s. Se ela não responder em
`http://127.0.0.1:5000/status`, ele volta para o commit anterior. Quedas
repetidas (5 em 10 min) fazem o supervisor parar em vez de ficar em loop.
Log em `duque_data/supervisor.log`; estado em `duque_data/update_state.json`.

## Como usar

- Por texto (HUD ou `POST /api/comando`): "Duque, melhore seu código para ...",
  "coloque na Forja ...", "corrija o projeto ...". O Duque responde na hora e
  trabalha em segundo plano. A voz (Realtime) ainda não tem acesso às
  ferramentas do agente; quando tiver, o mesmo pedido falado vai funcionar.
- O agente autônomo também pode chamar a ferramenta `forge_improve` sozinho.
- HTTP: `GET /api/forja` (andamento e histórico) e
  `POST /api/forja {"objetivo": "..."}`.
- O `Duque.vbs` inicia pelo supervisor, então as atualizações reiniciam o Duque
  sozinhas.

A edição direta do código em execução fica desligada por padrão
(`DUQUE_ALLOW_SELF_MODIFICATION=0`) e commits na instalação ao vivo pedem
confirmação: o caminho de auto-desenvolvimento é a Forja.
