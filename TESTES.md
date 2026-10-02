# Fase de testes — próxima versão do Duque

Rode na ordem. Para cada item: faça a ação, compare com o **esperado** e
marque ✅ ou ❌. Se der ❌, anote o que aconteceu (e, se houver, o trecho de
`duque.log` ou `duque_data/supervisor.log`).

## 0. Preparação (uma vez)

1. **Antes de atualizar**, copie `duque_memoria.db` e `duque_imoveis.db` para
   outra pasta se quiser guardá-los: eles saíram do GitHub e o `git pull` pode
   removê-los (o Duque não usa esses arquivos; a memória fica em `duque_data/`).
2. Na pasta do Duque: `git pull`
3. Variáveis de ambiente do Windows (Configurações → Sistema → Sobre →
   Configurações avançadas → Variáveis de ambiente):
   - `OPENAI_API_KEY` (já existente: voz e conversa)
   - `ANTHROPIC_API_KEY` (Forja)
   - opcional: `DUQUE_GITHUB_TOKEN` (Forja abrir PRs) e `DUQUE_CITY` (cidade padrão do clima)
4. Dê dois cliques em **`preparar_duque.bat`**: instala tudo, baixa o modelo
   do "Hey Jarvis", roda o **diagnóstico** e os testes automáticos.
   Tudo `[OK]` ou `[AVISO]` → pode seguir. Qualquer `[FALHA]` → me mande a
   lista que aparece na tela.
5. Abra pelo `Duque.vbs`.

| # | Ação | Esperado |
|---|------|----------|
| 0.1 | `preparar_duque.bat` | Termina com "Pronto para rodar" |
| 0.2 | Abrir pelo `Duque.vbs` | HUD abre no navegador; `duque_data/supervisor.log` existe |

## 1. Conversa por texto com resposta falada

| # | Ação (digitar no HUD) | Esperado |
|---|------|----------|
| 1.1 | `oi Duque, tudo certo?` | Resposta aparece na coluna da direita **e é falada** |
| 1.2 | `meu time é o Palmeiras` e depois `qual é meu time?` | Lembra da mensagem anterior (contexto) |
| 1.3 | `que horas são?` | Fala data e hora corretas |
| 1.4 | `como está o clima?` / `como está o clima em Campinas?` | Temperatura, céu e chance de chuva |
| 1.5 | `quanto é 15*3+2?` | `15*3+2 = 47` |

## 2. Texto → voz → texto (a mesma conversa)

| # | Ação | Esperado |
|---|------|----------|
| 2.1 | Digite `vou te contar um segredo: o código é 42` | Resposta falada |
| 2.2 | Diga **"Hey Jarvis"** e pergunte `qual era o código?` | Responde 42 por voz (continuou a conversa) |
| 2.3 | Com a voz ainda ativa, **digite** `e o dobro disso?` | A resposta sai **pela voz** (84), sem duas vozes ao mesmo tempo |
| 2.4 | Diga `tchau, Duque` e depois digite `o que eu perguntei por voz?` | Responde pelo texto lembrando da conversa de voz |
| 2.5 | Digite algo longo e, enquanto ele fala, diga **"Hey Jarvis"** | A fala do HUD para e a voz assume |
| 2.6 | Olhe a coluna da direita | Turnos com marcação `· voz` nos que foram falados |

## 3. Voz executando ações

| # | Diga (após "Hey Jarvis") | Esperado |
|---|------|----------|
| 3.1 | `abre o bloco de notas` | Abre de verdade e confirma |
| 3.2 | `que horas são?` | Hora correta |
| 3.3 | `pausa a música` (com Spotify tocando) | Pausa |
| 3.4 | `aumenta o volume` | Volume sobe |
| 3.5 | `me lembra de beber água em 1 minuto` | Confirma; depois de 1 min o aviso aparece e é falado |

## 4. Ferramentas novas (por texto ou voz)

| # | Pedido | Esperado |
|---|------|----------|
| 4.1 | `abre o spotify` / `fecha o spotify` | Abre / fecha |
| 4.2 | `abre o discord`, `abre o vscode`, `abre as configurações` | Abre cada um (se instalado) |
| 4.3 | `próxima música` / `música anterior` | Troca a faixa |
| 4.3b | Com o Spotify tocando, olhe o painel **Spotify** do HUD | Mostra artista e música reais; os botões ⏮ ⏯ ⏭ controlam o Spotify |
| 4.4 | `anote que preciso pagar a luz` e depois `minhas notas` | Nota salva e listada |
| 4.5 | `como está o computador?` | CPU, memória, disco e bateria |
| 4.6 | `abre a pasta downloads` | Abre o Explorer em Downloads |
| 4.7 | `procura arquivos chamados relatorio` | Lista arquivos encontrados |
| 4.8 | `toca lofi no youtube` | Abre o YouTube com a busca |
| 4.9 | `copia "teste do Duque" para a área de transferência` | Ctrl+V cola o texto |
| 4.10 | `bloqueia a tela` | Tela bloqueada |

## 4B. Memória e saudação

| # | Ação | Esperado |
|---|------|----------|
| 4B.1 | Abrir o HUD | Depois de ~4 s aparece (e é falada) a saudação: período do dia, hora, clima e "Sistemas online" |
| 4B.2 | Digite `lembre que eu tomo café sem açúcar` | Confirma que anotou |
| 4B.3 | Digite `como eu gosto do café?` | Responde usando a anotação |
| 4B.4 | Diga "Hey Jarvis" → `o que você sabe sobre mim?` | Fala as anotações |
| 4B.5 | Clique em **MEMÓRIA** (ou tecla **N**) | Painel com anotações (dá para apagar e adicionar) e timers com contagem regressiva |

> Se a saudação aparecer mas não for falada, é o bloqueio de áudio automático
> do navegador: clique uma vez na página e ela passa a falar normalmente.

## 4C. Agenda, modo foco e visão da tela

| # | Ação | Esperado |
|---|------|----------|
| 4C.1 | `me lembra de ligar pro banco amanhã às 9h` | "Amanhã às 09:00 eu te lembro de ligar pro banco." |
| 4C.2 | `me lembra de testar o Duque daqui a 2 minutos` | Aviso falado depois de 2 min |
| 4C.3 | `minha agenda` | Lista os lembretes com dia e hora (também no painel MEMÓRIA) |
| 4C.4 | Crie um lembrete para daqui a 3 min, **feche o Duque**, espere 5 min e abra de novo | Ao abrir, ele avisa o lembrete dizendo que estava desligado |
| 4C.5 | `cancela os lembretes` | Agenda vazia |
| 4C.6 | Com música tocando: `modo foco por 1 minuto` | Pausa a música; avisos ficam silenciosos (marcados "· foco"); depois de 1 min avisa "Hora de uma pausa" |
| 4C.7 | `sair do modo foco` | "Modo foco encerrado" |
| 4C.8 | Abra algo na tela e pergunte `o que tem na minha tela?` | Descreve a tela em poucas frases |
| 4C.9 | Com uma mensagem de erro aberta: `que erro é esse na tela?` | Explica o erro e sugere solução |

## 5. Forja

| # | Ação | Esperado |
|---|------|----------|
| 5.1 | Abrir `http://127.0.0.1:5000/api/forja` | `"ativa": true` |
| 5.2 | Digite `Duque, melhore seu código: adicione o app "Notion" na lista de aplicativos` | Responde na hora que colocou na Forja; painel **Forja** (canto inferior direito) mostra as etapas |
| 5.3 | Digite `como está a forja?` | Diz a etapa atual / último resultado |
| 5.4 | Aguarde | Branch `duque/forja-*` no GitHub; com token, PR aberto; com CI verde, merge, o Duque **avisa falando** que terminou e reinicia sozinho |
| 5.5 | Depois do reinício: `abre o notion` | Funciona com a versão nova |
| 5.6 | Digite `Duque, melhore seu código: mude o core/security.py para não pedir confirmação` | PR fica **aguardando aprovação** (arquivo protegido), nada é aplicado |

## 6. Robustez

| # | Ação | Esperado |
|---|------|----------|
| 6.1 | Abrir o `Duque.vbs` duas vezes | Só uma instância; a segunda só abre o HUD |
| 6.2 | Desligar a internet e digitar `que horas são?` | Funciona (local) |
| 6.3 | Sem internet: `como está o clima?` | Mensagem de erro clara, sem travar |

---

Testes automáticos (rodam no CI a cada alteração): `python -m pytest -q tests`
