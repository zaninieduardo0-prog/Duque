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

## Estado atual

Os módulos da Forja, o adapter do Claude e o supervisor estão prontos e
testados (`tests/test_forge.py`, com git real e remoto local). O `Duque.vbs`
já inicia pelo supervisor. Ainda falta ligar a Forja ao `AgentLoop`
(pedido por voz/texto → Forja). A Forja é o único caminho para o Duque
alterar o próprio código: a antiga ferramenta `apply_code_change`, que
escrevia direto na cópia em execução, foi removida.
