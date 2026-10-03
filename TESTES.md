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

## 4D. Rotinas, WhatsApp e resumo do dia

| # | Ação | Esperado |
|---|------|----------|
| 4D.1 | `modo trabalho` | Abre VS Code, Spotify e GitHub (rotina pronta) |
| 4D.2 | `crie a rotina noite: abre o youtube, diminua o volume` e depois `modo noite` | Salva e roda as duas ações |
| 4D.3 | `minhas rotinas` / painel MEMÓRIA | Lista trabalho, estudo, jogo e as suas |
| 4D.4 | `salve o contato <nome> <DDD + número>` | Confirma o contato |
| 4D.5 | `manda uma mensagem pro <nome> no whatsapp dizendo que vou atrasar` | WhatsApp abre na conversa com o texto pronto; **só envia se você apertar Enter** |
| 4D.6 | `manda mensagem: teste` (sem contato) | WhatsApp abre para você escolher o contato |
| 4D.7 | `resumo do dia` | Quantos pedidos, o que falhou e a agenda de amanhã |
| 4D.8 | Deixe o Duque ligado às 21:30 | Ele fala o resumo do dia sozinho (mude com `setx DUQUE_DAILY_SUMMARY "22:00"` ou desligue com `"0"`) |

## 4E. Audição com portão, "Duque, stop", Chrome e interface nova

| # | Ação | Esperado |
|---|------|----------|
| 4E.1 | Abrir o Duque | HUD azul novo (cérebro de partículas), no **seu** perfil do Chrome, sem tela de escolher conta |
| 4E.2 | Diga `Hey Jarvis` e, em seguida, `abra o WhatsApp` | Abre **uma vez** (app ou WhatsApp Web no seu Chrome) e não fica tentando de novo |
| 4E.3 | Converse com alguém perto do microfone, sem dizer "Duque" | O Duque **não responde** (no log: `[GATE] ignore`) |
| 4E.4 | Diga `Duque, que horas são?` | Responde (no log: `[GATE] respond`) |
| 4E.5 | Peça algo longo (`Duque, me explica como funciona um motor`) e no meio diga `Duque, stop` | Para de falar na hora |
| 4E.6 | No meio de uma explicação, diga só `Duque` | Para e fica esperando seu pedido |
| 4E.7 | Fique 1 minuto sem chamar | Volta ao standby; só `Hey Jarvis` (ou digitar) abre de novo |
| 4E.8 | Digite `stop` (ou aperte Esc) enquanto ele fala | Para na hora |
| 4E.9 | Clique no ícone do YouTube/WhatsApp à esquerda | Abre no seu Chrome |
| 4E.10 | `.\.venv\Scripts\python.exe diagnostico.py` | Linha `[OK] Chrome: perfil 'Profile X'` |

Ajustes opcionais (PowerShell, depois reinicie o Duque):
`setx DUQUE_CHROME_PROFILE "Profile 1"` (outro perfil) · `setx DUQUE_VOICE_IDLE 120` (tempo até voltar ao standby, em segundos) · `setx DUQUE_VAD_INTERRUPT 1` (qualquer som volta a interromper).

## 4F. TELEX: ativação "Bom dia, TELEX", repouso e pausa de emergência

> Antes: rode o `preparar_duque.bat` uma vez (instala o reconhecedor local e baixa o
> modelo de português, ~50 MB). O diagnóstico deve mostrar
> `[OK] ativação Bom dia, TELEX: ...; nome como telex`.

| # | Ação | Esperado |
|---|------|----------|
| 4F.1 | Abrir o TELEX | Logo **TELEX** no canto superior esquerdo, meio apagado; nas respostas, o nome é TELEX |
| 4F.2 | Diga `Bom dia, TELEX` (ou `Boa tarde`/`Boa noite`) | Logo acende; ele responde com uma saudação curta; no log: `[WAKE] ouvi "bom dia telex" -> wake` |
| 4F.3 | Logo depois, sem dizer o nome: `abre o bloco de notas` | Abre (o primeiro pedido vale sem o nome) |
| 4F.4 | `Telex, que horas são?` / `Telex, stop` no meio de uma fala | Responde / para na hora |
| 4F.5 | Diga `Repousar, Telex` | Volta ao standby **na hora**, sem despedida; logo apaga |
| 4F.6 | Diga `Hey Jarvis` | Também acorda (desligue com `setx DUQUE_HEY_JARVIS "0"`) |
| 4F.7 | Fale "bom dia" para alguém, sem "Telex" | **Não** acorda |
| 4F.8 | Mande algo demorado (ex.: um pedido à Forja) e olhe o painel **Tarefas** (canto inferior direito) | Mostra o objetivo, a etapa atual, o tempo correndo e a barrinha de etapas, sem abrir janela de CMD |
| 4F.9 | Com a Forja trabalhando, clique **Pausa de emergência** (ou F9) | Tudo para; aparece o quadro vermelho com o que estava rodando e a etapa onde parou; a voz fecha |
| 4F.10 | Em pausa, digite `que horas são?` | Ele avisa que está em pausa e não executa nada |
| 4F.11 | Em pausa, diga `Bom dia, TELEX` | Não acorda; só `Retomar, TELEX` funciona |
| 4F.12 | Clique **Retomar** (ou diga `Retomar, TELEX`, ou digite `retomar`) | Fala "Retomando. Estava parado: ..." e a Forja continua **da mesma etapa** |
| 4F.13 | Pause, feche o TELEX e abra de novo | Volta em pausa e conta o que foi interrompido pelo reinício |
| 4F.14 | Digite `Telex, pausa tudo` | Mesmo efeito do botão |

## 4G. Pedidos em várias etapas, voz natural e HUD limpo

| # | Ação | Esperado |
|---|------|----------|
| 4G.1 | `.\preparar_duque.bat` | Linha `[OK] ativação Bom dia, TELEX: ...` (pode dizer "modo livre" se o modelo não conhecer a palavra telex) |
| 4G.2 | Diga `Bom dia, TELEX` | Acorda e responde |
| 4G.3 | `abra o youtube e reproduza Numb do Linkin Park` | Abre o **vídeo** e começa a tocar (não fica só na lista de resultados) |
| 4G.4 | `toque lofi no youtube` | Mesmo comportamento |
| 4G.5 | `abra o bloco de notas e escreva um poema sobre o mar` | Bloco de Notas abre **com o poema escrito**; arquivo em Documentos\TELEX |
| 4G.6 | `abra o bloco de notas e escreva: comprar pão, leite e café` | Abre com esse texto exato |
| 4G.7 | `abra o spotify, aumente o volume e anote que o teste passou` | Faz as três coisas, em ordem, e responde dizendo cada uma |
| 4G.8 | Converse por voz | Fala solta e no ritmo de conversa, sem pausas entre frases e sem picotes; voz nova **cedar** (dá para trocar no painel MEMÓRIA → Voz) |
| 4G.9 | Digite uma pergunta (resposta pelo HUD) | Começa a falar bem mais rápido que antes (áudio em streaming) |
| 4G.10 | Olhe o HUD com conversa, Spotify e Forja ao mesmo tempo | Nada fica um em cima do outro; coluna da direita empilhada (avisos → conversa → tarefas) |

## 4H. Logo, letras e reconexão

| # | Ação | Esperado |
|---|------|----------|
| 4H.1 | Abrir o TELEX | Logo do TELEX (o emblema enviado pelo Du) no canto; letras do meio menores; nada sobreposto, nem com a janela do Chrome menor |
| 4H.2 | Com o TELEX aberto, feche só o servidor (ou espere um reinício) e digite algo | Aparece "TELEX reiniciando — sua mensagem será enviada assim que ele voltar"; quando ele volta, a mensagem é enviada e respondida |
| 4H.3 | Depois de uma atualização | O HUD se recarrega sozinho com a versão nova |
| 4H.4 | Se o TELEX cair | `Get-Content .\duque.log -Tail 80` mostra uma linha `[QUEDA]` com o motivo; mande para o Claude |

## 4I. Um nome só, ouvido aberto, YouTube e WhatsApp completo

| # | Ação | Esperado |
|---|------|----------|
| 4I.1 | Diga `Duque, que horas são?` ou `Hey Jarvis` | **Não** responde (só TELEX chama) |
| 4I.2 | Diga `Boa tarde, TELEX` e, logo depois, **sem o nome**: `abre o youtube` | Responde a saudação e abre o YouTube; no log: `[GATE] saudação respondida; ouvindo sem precisar do nome` |
| 4I.3 | Durante a saudação, olhe o log | A própria voz do TELEX aparece como `ignore (eco...)` e o ouvido continua aberto |
| 4I.4 | `abre o youtube` (com o Chrome já aberto) | Abre como **aba** no Chrome aberto e diz "Abri youtube"; se não aparecer, ele avisa |
| 4I.5 | `abra o whatsapp, procure pelo Otávio que trabalha comigo na Embralan, e encaminhe a mensagem Teste do TELEX` | Abre o WhatsApp, busca Otávio, escolhe o certo, **confere o nome no topo da conversa**, cola o texto, envia e diz "Mensagem enviada para ..." |
| 4I.6 | Mesmo pedido com um nome que não existe | Diz que não achou a conversa certa e **não escreve nada** |
| 4I.7 | `procura a Maria no whatsapp e escreve: oi` | Deixa escrito **sem enviar** |

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
