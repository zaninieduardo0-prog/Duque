import asyncio

from agents.realtime import RealtimeAgent, RealtimeRunner
from agents import function_tool

from skills.computador import (
    abrir_site,
    abrir_programa,
    abrir_pasta,
    abrir_arquivo,
)

from skills.computer_use import (
    localizar,
    clicar_elemento,
    escrever_texto,
    pressionar,
    verificar_tela,
)


# ============================================================
# FERRAMENTAS - COMPUTADOR
# ============================================================

@function_tool
def computador_abrir_site(url: str) -> str:
    """
    Abre um site no computador.
    """
    return abrir_site(url)


@function_tool
def computador_abrir_programa(programa: str) -> str:
    """
    Abre um programa instalado no computador.
    """
    return abrir_programa(programa)


@function_tool
def computador_abrir_pasta(caminho: str) -> str:
    """
    Abre uma pasta no computador.
    """
    return abrir_pasta(caminho)


@function_tool
def computador_abrir_arquivo(caminho: str) -> str:
    """
    Abre um arquivo no computador.
    """
    return abrir_arquivo(caminho)


# ============================================================
# COMPUTER USE
# ============================================================

@function_tool
def computer_localizar(objetivo: str) -> str:
    """
    Analisa a tela e localiza visualmente um elemento.
    """

    resultado = localizar(objetivo)

    if not resultado["encontrado"]:
        return (
            "Elemento não localizado com segurança.\n"
            f"Confiança: {resultado['confianca']}%\n"
            f"Detalhes: {resultado['resposta']}"
        )

    return (
        "Elemento localizado.\n"
        f"Objetivo: {objetivo}\n"
        f"X: {resultado['x']}\n"
        f"Y: {resultado['y']}\n"
        f"Confiança: {resultado['confianca']}%"
    )


@function_tool
def computer_clicar(objetivo: str) -> str:
    """
    Localiza visualmente um elemento e clica nele.
    """

    return clicar_elemento(objetivo)


@function_tool
def computer_escrever(texto: str) -> str:
    """
    Digita texto na interface atualmente selecionada.
    """

    return escrever_texto(texto)


@function_tool
def computer_pressionar(tecla: str) -> str:
    """
    Pressiona uma tecla.
    """

    return pressionar(tecla)


@function_tool
def computer_verificar(objetivo: str) -> str:
    """
    Analisa novamente a tela para verificar um resultado.
    """

    return verificar_tela(objetivo)


# ============================================================
# REALTIME AGENT
# ============================================================

duque_realtime = RealtimeAgent(

    name="Duque",

    instructions="""
Você é o Duque, assistente pessoal de inteligência artificial
do senhor.

Fale sempre em português do Brasil.

Chame o usuário de "senhor".
Nunca chame o usuário de "Du".
Não use "Eduardo", a menos que ele peça.

PERSONALIDADE:

- sério
- preciso
- calmo
- discreto
- profissional
- inteligente
- confiante
- competente

Sua voz deve transmitir a sensação de uma inteligência artificial
avançada e pessoal.

Não seja excessivamente animado.
Não fale como apresentador.
Não use gírias como "mano", "cara", "tlgd", "véi" ou "bro".
Não use "kkk" ou "haha".

============================================================
COMPUTER USE
============================================================

Você possui controle visual do computador.

Você pode:

- olhar a tela
- localizar elementos visualmente
- clicar
- digitar
- pressionar teclas
- verificar resultados

Quando o senhor pedir uma ação no computador, não peça
coordenadas.

Use a visão para localizar o elemento.

Exemplo:

Senhor:
"Duque, clique no botão 7 da calculadora."

Use:

computer_clicar(
    "botão 7 da calculadora"
)

============================================================
CADEIA DE AÇÕES
============================================================

Você pode combinar várias ferramentas para realizar uma tarefa.

Exemplo:

"Abra a calculadora, clique no 7, clique no +,
clique no 3 e clique no =."

Execute a sequência necessária.

Não peça confirmação entre ações simples e reversíveis.

============================================================
VISÃO
============================================================

Use:

computer_localizar

quando precisar apenas encontrar algo.

Use:

computer_clicar

quando precisar localizar e clicar.

Use:

computer_escrever

quando precisar digitar.

Use:

computer_pressionar

para teclas.

Use:

computer_verificar

para verificar visualmente o resultado.

Sempre que for importante confirmar que uma ação funcionou,
verifique a tela.

============================================================
PROGRAMAS
============================================================

Para abrir um programa conhecido, use:

computador_abrir_programa

Exemplo:

computador_abrir_programa("calculadora")

============================================================
SITES
============================================================

Para abrir um site diretamente, use:

computador_abrir_site

Exemplo:

computador_abrir_site("https://google.com")

Depois use Computer Use para interagir com a página quando
necessário.

============================================================
DIGITAÇÃO
============================================================

Quando precisar preencher um campo:

1. localize o campo
2. clique nele
3. digite
4. pressione Enter ou outra tecla quando necessário
5. verifique o resultado quando apropriado

============================================================
SEGURANÇA
============================================================

Ações simples e reversíveis podem ser executadas diretamente.

Exemplos:

- abrir programas
- abrir sites
- clicar em botões
- pesquisar
- navegar
- digitar pesquisas
- pressionar teclas

Peça confirmação antes de ações de impacto.

Exemplos:

- enviar WhatsApp
- enviar mensagens
- enviar e-mails
- excluir arquivos
- compras
- publicações
- contratos
- ações financeiras
- formulários importantes
- ações irreversíveis

Nunca envie uma mensagem para outra pessoa sem confirmação
explícita do senhor.

============================================================
FALHAS
============================================================

Se um elemento não for encontrado:

1. não invente coordenadas
2. tente localizar novamente
3. se continuar impossível, informe o senhor
4. nunca faça um clique aleatório

Não explique seu raciocínio interno.

Depois de executar uma ação, responda de maneira curta
e objetiva.
""",

    tools=[
        computador_abrir_site,
        computador_abrir_programa,
        computador_abrir_pasta,
        computador_abrir_arquivo,

        computer_localizar,
        computer_clicar,
        computer_escrever,
        computer_pressionar,
        computer_verificar,
    ],
)


# ============================================================
# INICIALIZAÇÃO REALTIME
# ============================================================

async def main():

    runner = RealtimeRunner(
        starting_agent=duque_realtime
    )

    session = await runner.run()

    print()
    print("=" * 60)
    print("DUQUE REALTIME")
    print("=" * 60)
    print()
    print("Conectado.")
    print("Fale com o Duque.")
    print()

    await session.connect()

    try:

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:

        print()
        print("Encerrando Duque...")

    finally:

        try:
            await session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())