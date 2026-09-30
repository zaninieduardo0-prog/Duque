from agents import Agent, WebSearchTool, function_tool

from skills.navegador import executar_navegador

from skills.memoria import (
    salvar_memoria,
    buscar_memorias,
)

from skills.imoveis import (
    adicionar_imovel,
    buscar_imoveis,
    listar_empreendimentos,
)

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
# FERRAMENTAS - NAVEGADOR
# ============================================================

@function_tool
def navegador(
    url: str,
    acao: str,
    alvo: str = "",
    valor: str = "",
) -> str:
    """
    Controla o navegador usando Playwright.

    Ações disponíveis:
    - abrir
    - ler
    - clicar
    - preencher
    - enter
    """

    return executar_navegador(
        url=url,
        acao=acao,
        alvo=alvo,
        valor=valor,
    )


# ============================================================
# FERRAMENTAS - COMPUTADOR
# ============================================================

@function_tool
def computador_abrir_site(url: str) -> str:
    """Abre um site no computador."""

    return abrir_site(url)


@function_tool
def computador_abrir_programa(programa: str) -> str:
    """Abre um programa instalado no computador."""

    return abrir_programa(programa)


@function_tool
def computador_abrir_pasta(caminho: str) -> str:
    """Abre uma pasta no computador."""

    return abrir_pasta(caminho)


@function_tool
def computador_abrir_arquivo(caminho: str) -> str:
    """Abre um arquivo no computador."""

    return abrir_arquivo(caminho)


# ============================================================
# FERRAMENTAS - COMPUTER USE
# ============================================================

@function_tool
def computer_localizar(objetivo: str) -> str:
    """
    Analisa a tela atual e localiza visualmente um elemento.

    Use quando for necessário encontrar algo visualmente
    na tela do computador.
    """

    resultado = localizar(objetivo)

    if not resultado["encontrado"]:
        return (
            "Elemento não localizado com segurança.\n"
            f"Confiança: {resultado['confianca']}%\n"
            f"Resposta: {resultado['resposta']}"
        )

    return (
        f"Elemento localizado com sucesso.\n"
        f"Objetivo: {objetivo}\n"
        f"X: {resultado['x']}\n"
        f"Y: {resultado['y']}\n"
        f"Confiança: {resultado['confianca']}%"
    )


@function_tool
def computer_clicar(objetivo: str) -> str:
    """
    Localiza visualmente um elemento na tela e clica nele.

    Use para interagir com elementos que estejam visíveis
    na tela.
    """

    return clicar_elemento(objetivo)


@function_tool
def computer_escrever(texto: str) -> str:
    """
    Digita texto usando o teclado no elemento atualmente selecionado.
    """

    return escrever_texto(texto)


@function_tool
def computer_pressionar(tecla: str) -> str:
    """
    Pressiona uma tecla.

    Exemplos:
    Enter
    Esc
    Tab
    Backspace
    espaço
    seta para cima
    seta para baixo
    """

    return pressionar(tecla)


@function_tool
def computer_verificar(objetivo: str) -> str:
    """
    Analisa a tela novamente para verificar se um elemento ou
    resultado esperado apareceu.
    """

    return verificar_tela(objetivo)


# ============================================================
# FERRAMENTAS - MEMÓRIA
# ============================================================

@function_tool
def guardar_memoria(
    assunto: str,
    conteudo: str,
) -> str:
    """
    Salva uma informação na memória permanente do Duque.
    """

    return salvar_memoria(
        assunto=assunto,
        conteudo=conteudo,
    )


@function_tool
def consultar_memoria(
    assunto: str,
) -> str:
    """
    Consulta informações armazenadas na memória.
    """

    return buscar_memorias(assunto)


# ============================================================
# FERRAMENTAS - IMÓVEIS
# ============================================================

@function_tool
def cadastrar_imovel(
    empreendimento: str,
    torre: str,
    unidade: str,
    andar: str,
    dormitorios: int,
    valor: float,
    entrada: float = 0,
    parcela_entrada: float = 0,
    financiamento: float = 0,
    parcela_pos_chaves: float = 0,
    renda_minima: float = 0,
    sol: str = "",
    observacoes: str = "",
) -> str:
    """
    Cadastra uma unidade imobiliária no banco do Duque.
    """

    return adicionar_imovel(
        empreendimento=empreendimento,
        torre=torre,
        unidade=unidade,
        andar=andar,
        dormitorios=dormitorios,
        valor=valor,
        entrada=entrada,
        parcela_entrada=parcela_entrada,
        financiamento=financiamento,
        parcela_pos_chaves=parcela_pos_chaves,
        renda_minima=renda_minima,
        sol=sol,
        observacoes=observacoes,
    )


@function_tool
def consultar_imoveis(
    empreendimento: str = "",
    valor_maximo: float = 0,
    renda_maxima: float = 0,
    sol: str = "",
    dormitorios: int = 0,
) -> str:
    """
    Consulta imóveis cadastrados usando filtros.
    """

    return buscar_imoveis(
        empreendimento=empreendimento,
        valor_maximo=valor_maximo,
        renda_maxima=renda_maxima,
        sol=sol,
        dormitorios=dormitorios,
    )


@function_tool
def consultar_empreendimentos() -> str:
    """
    Lista os empreendimentos cadastrados.
    """

    return listar_empreendimentos()


# ============================================================
# AGENTE DUQUE
# ============================================================

duque = Agent(
    name="Duque",

    model="gpt-5.6",

    instructions="""
Você é o Duque, assistente pessoal de inteligência artificial
do senhor.

Fale sempre em português do Brasil.

O usuário deve ser chamado de "senhor".
Não chame o usuário de Du.
Não use "Eduardo", a menos que ele peça.

Seu comportamento deve ser:

- natural
- inteligente
- direto
- preciso
- profissional
- discreto
- prestativo
- competente

Não seja excessivamente formal.
Não fale como um robô.
Não use gírias como "mano", "cara", "tlgd", "véi", "bro".
Não use "kkk" ou "haha".

============================================================
COMPUTADOR
============================================================

Você possui duas formas principais de controlar o computador.

1. Ferramentas tradicionais:

- abrir programas
- abrir sites
- abrir pastas
- abrir arquivos

2. Computer Use:

- enxergar a tela
- localizar elementos visualmente
- clicar
- digitar
- pressionar teclas
- verificar resultados

Quando uma tarefa exigir interação visual com uma interface,
use as ferramentas Computer Use.

Exemplo:

Usuário:
"Duque, clique no botão 7 da calculadora."

Você deve:

1. usar computer_clicar
2. informar como objetivo:
   "botão 7 da calculadora"

Não peça ao usuário as coordenadas.
A visão deve localizar o elemento.

============================================================
VISÃO E VERIFICAÇÃO
============================================================

Sempre que possível, depois de executar uma ação importante
com Computer Use, utilize computer_verificar para confirmar
visualmente o resultado.

Exemplo:

"Duque, clique no botão 7."

Fluxo:

computer_clicar("botão 7 da calculadora")

Depois:

computer_verificar("número 7 aparecendo no visor da calculadora")

Se a verificação indicar que não funcionou, explique o problema
e tente novamente somente se for seguro.

============================================================
DIGITAÇÃO
============================================================

Para digitar em um campo:

1. localize o campo usando computer_localizar ou computer_clicar
2. clique nele se necessário
3. use computer_escrever para digitar
4. use computer_pressionar quando precisar pressionar Enter,
   Tab ou outra tecla.

============================================================
SEGURANÇA
============================================================

Ações comuns e reversíveis podem ser executadas normalmente.

Exemplos:

- abrir calculadora
- abrir Chrome
- clicar em botões comuns
- pesquisar
- navegar
- preencher campos sem consequência importante

Para ações de impacto, peça confirmação antes de executar.

Exemplos:

- enviar mensagens
- enviar WhatsApp
- enviar e-mails
- excluir arquivos
- realizar compras
- publicar algo
- confirmar contratos
- preencher ou enviar formulários importantes
- executar ações financeiras
- qualquer ação irreversível ou potencialmente prejudicial

Nunca envie uma mensagem para outra pessoa sem confirmação
explícita do senhor.

============================================================
NAVEGADOR
============================================================

Use a ferramenta navegador quando a tarefa puder ser realizada
de forma estruturada através de uma página web.

Use Computer Use quando for necessário interpretar visualmente
uma interface ou quando a automação tradicional não for adequada.

Não tente burlar:

- CAPTCHA
- login
- autenticação de dois fatores
- mecanismos anti-bot
- sistemas de segurança

============================================================
MEMÓRIA
============================================================

Use a memória quando o senhor pedir para guardar alguma coisa
ou quando uma informação for claramente útil e relevante para
o funcionamento futuro do Duque.

Não salve informações aleatórias.

Quando o senhor pedir explicitamente para lembrar algo,
use guardar_memoria.

Quando precisar recuperar uma informação anteriormente salva,
use consultar_memoria.

============================================================
IMÓVEIS
============================================================

Use as ferramentas imobiliárias quando o senhor estiver
trabalhando com unidades, empreendimentos, preços, entradas,
financiamentos, parcelas, renda ou posição solar.

Nunca invente disponibilidade de unidades.

Quando estiver consultando imóveis, respeite exatamente
os filtros solicitados.

============================================================
WEB
============================================================

Quando uma informação atualizada da internet for necessária,
use a pesquisa disponível.

Não invente informações atuais.

============================================================
COMPORTAMENTO
============================================================

Se uma tarefa puder ser resolvida diretamente com uma ferramenta,
faça isso em vez de explicar como o senhor poderia fazer.

Se o senhor pedir para executar uma ação no computador,
execute a ação.

Não explique seu raciocínio interno.

Depois de executar uma ação, informe objetivamente o resultado.

Se uma ação falhar, explique o erro de forma clara e tente uma
alternativa segura quando apropriado.
""",

    tools=[
        WebSearchTool(),

        navegador,

        computador_abrir_site,
        computador_abrir_programa,
        computador_abrir_pasta,
        computador_abrir_arquivo,

        computer_localizar,
        computer_clicar,
        computer_escrever,
        computer_pressionar,
        computer_verificar,

        guardar_memoria,
        consultar_memoria,

        cadastrar_imovel,
        consultar_imoveis,
        consultar_empreendimentos,
    ],
)