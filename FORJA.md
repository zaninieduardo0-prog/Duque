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
- configuração de testes e do Python: `pytest.ini`, `setup.cfg`, `tox.ini`,
  `conftest.py` (em qualquer pasta), `sitecustomize.py`, `usercustomize.py`,
  `.gitignore`, `.gitattributes`
- qualquer remoção **ou alteração** de teste existente (testes novos são livres)

Mudanças em `.github/` nem chegam a ser enviadas: o branch fica só na
instalação local (`git branch --list "duque/forja-*"`), porque enviar já faria
o GitHub rodar o workflow alterado. As ferramentas do agente também recusam
qualquer caminho dentro de `.git`.

Além disso: a verificação é feita pelo código da Forja, não pela palavra do
modelo; os checks locais rodam sem as chaves de API e tokens do ambiente e com
`DUQUE_WORKSPACE_ROOT` apontando para a cópia isolada; com CI obrigatório,
pytest/ruff ausentes contam como falha; o merge é sempre fast-forward (nunca
força); o mesmo commit que já falhou no CI não é reenviado para nova espera; a
atualização ao vivo nunca descarta alterações locais suas, não reaplica uma
versão que já falhou e o rollback (da atualização ou do supervisor) é recusado
e registrado em `duque_data/update_state.json` se houver arquivos versionados
alterados.

Checks locais (`DUQUE_FORGE_CHECKS`, padrão `compile,imports,pytest,ruff`):
`imports` roda `python -c "import servidor; import duque_wake"` para pegar
dependência faltando que a compilação não vê.

## Configuração (variáveis de ambiente no Windows)

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | cérebro programador (Claude). Sem ela, usa `OPENAI_API_KEY`; sem nenhuma, a Forja fica desligada |
| `DUQUE_DEV_MODEL` | modelo do programador (padrão `claude-sonnet-5-5`) |
| `DUQUE_GITHUB_TOKEN` | token *fine-grained* só do repositório Duque, com **Contents: read/write**, **Pull requests: read/write** e **Checks: read** (sem esta, o CI aparece como "sem acesso" e a mudança fica esperando aprovação). Sem token, o branch é enviado com suas credenciais do Git (sem pedir senha na tela), mas o PR não é aberto e os checks só são lidos em repositório público |
| `DUQUE_FORGE_AUTO_MERGE` | `1` (padrão) aplica sozinho quando o CI passa; `0` sempre espera aprovação |
| `DUQUE_FORGE_REQUIRE_CI` | `1` (padrão) só aplica com CI verde |
| `DUQUE_FORGE_MAX_ROUNDS` / `DUQUE_FORGE_MAX_STEPS` | limites de rodadas e de ações por rodada |

Nunca coloque chaves no código nem em arquivos versionados.

## Supervisor

`duque_supervisor.py` roda o `duque.py` como processo filho. Quando a Forja
aplica uma atualização, o Duque sai com código 75, o supervisor reinicia e
deixa a versão nova em observação por 90 s (a observação só é marcada quando o
reinício vai mesmo acontecer, isto é, rodando sob o supervisor). Se ela não responder em
`http://127.0.0.1:5000/status`, ele volta para o commit anterior. Quedas
repetidas (5 em 10 min) fazem o supervisor parar em vez de ficar em loop.
Log em `duque_data/supervisor.log`; estado em `duque_data/update_state.json`.

## Estado atual

Os módulos da Forja, o adapter do Claude e o supervisor estão prontos e
testados (`tests/test_forge.py`, com git real e remoto local). O `Duque.vbs`
já inicia pelo supervisor. A Forja **ainda não está ligada ao `AgentLoop`**:
pedidos por voz/texto não disparam a Forja.

Enquanto isso, o `AgentLoop` em execução não altera o próprio Duque: as
ferramentas de workspace recusam escrever ou apagar o código-fonte do projeto
Duque (pacotes do Duque, `interface/`, `.github/`, scripts `.py` da raiz),
além de `.git` e arquivos `.env`, e as ferramentas de `git commit`, `pull` e
`push` não são oferecidas ao modelo. A Forja é o único caminho para o Duque
alterar o próprio código.
