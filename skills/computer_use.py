import time
import pyautogui

from skills.visao import olhar_tela_lote
from skills.computador_uso import mover_mouse, clicar


# ============================================================
# DUQUE - COMPUTER USE
# VISÃO EM LOTE
# ============================================================

CONFIANCA_MINIMA = 70
TEMPO_ANTES_CLIQUE = 0.25
TEMPO_ENTRE_ACOES = 0.15


# ============================================================
# LOCALIZAR UM ELEMENTO
# ============================================================

def localizar(objetivo):

    resultado = olhar_tela_lote(
        [objetivo]
    )

    dados = (
        resultado
        .get("elementos", {})
        .get(objetivo)
    )

    if not dados:

        return {
            "encontrado": False,
            "x": None,
            "y": None,
            "confianca": 0,
            "resposta": "Elemento não retornado pela visão."
        }

    x = dados.get("x")
    y = dados.get("y")
    confianca = dados.get(
        "confianca",
        0
    )

    if not dados.get("encontrado", False):

        return {
            "encontrado": False,
            "x": x,
            "y": y,
            "confianca": confianca,
            "resposta": (
                f"Elemento '{objetivo}' não encontrado."
            )
        }

    largura, altura = pyautogui.size()

    if not (
        isinstance(x, int)
        and isinstance(y, int)
        and 0 <= x < largura
        and 0 <= y < altura
    ):

        return {
            "encontrado": False,
            "x": x,
            "y": y,
            "confianca": confianca,
            "resposta": (
                f"Coordenadas inválidas: "
                f"X={x}, Y={y}."
            )
        }

    if confianca < CONFIANCA_MINIMA:

        return {
            "encontrado": False,
            "x": x,
            "y": y,
            "confianca": confianca,
            "resposta": (
                f"Confiança insuficiente: "
                f"{confianca}%."
            )
        }

    return {
        "encontrado": True,
        "x": x,
        "y": y,
        "confianca": confianca,
        "resposta": (
            f"Elemento localizado: "
            f"{objetivo}"
        )
    }


# ============================================================
# LOCALIZAR VÁRIOS ELEMENTOS
# ============================================================

def localizar_varios(elementos):

    resultado = olhar_tela_lote(
        elementos
    )

    encontrados = {}

    dados_elementos = resultado.get(
        "elementos",
        {}
    )

    for elemento in elementos:

        dados = dados_elementos.get(
            elemento
        )

        if not dados:
            continue

        x = dados.get("x")
        y = dados.get("y")
        confianca = dados.get(
            "confianca",
            0
        )

        if not dados.get(
            "encontrado",
            False
        ):
            continue

        if confianca < CONFIANCA_MINIMA:
            continue

        if not isinstance(x, int):
            continue

        if not isinstance(y, int):
            continue

        largura, altura = pyautogui.size()

        if not (
            0 <= x < largura
            and
            0 <= y < altura
        ):
            continue

        encontrados[elemento] = {
            "x": x,
            "y": y,
            "confianca": confianca
        }

    return encontrados


# ============================================================
# CLICAR EM ELEMENTO
# ============================================================

def clicar_elemento(objetivo):

    resultado = localizar(
        objetivo
    )

    if not resultado["encontrado"]:

        return (
            "Não consegui localizar "
            "o elemento com segurança.\n"
            f"Confiança: "
            f"{resultado['confianca']}%\n"
            f"{resultado['resposta']}"
        )

    x = resultado["x"]
    y = resultado["y"]

    print()
    print("=" * 60)
    print("ELEMENTO LOCALIZADO")
    print("=" * 60)

    print(
        f"Alvo: {objetivo}"
    )

    print(
        f"X: {x}"
    )

    print(
        f"Y: {y}"
    )

    print(
        f"Confiança: "
        f"{resultado['confianca']}%"
    )

    mover_mouse(
        x,
        y
    )

    time.sleep(
        TEMPO_ANTES_CLIQUE
    )

    clicar(
        x,
        y
    )

    return (
        f"Clique realizado com sucesso.\n"
        f"Elemento: {objetivo}\n"
        f"X={x}, Y={y}\n"
        f"Confiança={resultado['confianca']}%"
    )


# ============================================================
# SEQUÊNCIA RÁPIDA
# ============================================================

def executar_sequencia(acoes):

    if not acoes:

        return (
            "Nenhuma ação foi informada."
        )

    # --------------------------------------------------------
    # Primeiro: descobrir todos os elementos clicáveis
    # --------------------------------------------------------

    elementos = []

    for acao in acoes:

        tipo = acao.get(
            "acao",
            ""
        )

        alvo = acao.get(
            "alvo"
        )

        if tipo == "clicar" and alvo:

            if alvo not in elementos:
                elementos.append(
                    alvo
                )

    coordenadas = {}

    if elementos:

        print()
        print("=" * 60)
        print("VISÃO EM LOTE")
        print("=" * 60)

        print(
            f"Localizando {len(elementos)} elementos "
            "em uma única análise..."
        )

        coordenadas = localizar_varios(
            elementos
        )

    resultados = []

    # --------------------------------------------------------
    # Executar ações
    # --------------------------------------------------------

    for indice, acao in enumerate(
        acoes,
        start=1
    ):

        tipo = acao.get(
            "acao",
            ""
        )

        alvo = acao.get(
            "alvo"
        )

        print()
        print(
            f"[AÇÃO {indice}/{len(acoes)}]"
        )

        print(
            f"Tipo: {tipo}"
        )

        print(
            f"Alvo: {alvo}"
        )

        # ----------------------------------------------------
        # CLIQUE
        # ----------------------------------------------------

        if tipo == "clicar":

            dados = coordenadas.get(
                alvo
            )

            if not dados:

                resultados.append(
                    f"Falha: '{alvo}' não foi "
                    "localizado com confiança suficiente."
                )

                continue

            x = dados["x"]
            y = dados["y"]

            print(
                f"Coordenadas: X={x}, Y={y}"
            )

            print(
                f"Confiança: "
                f"{dados['confianca']}%"
            )

            mover_mouse(
                x,
                y
            )

            time.sleep(
                TEMPO_ANTES_CLIQUE
            )

            clicar(
                x,
                y
            )

            resultados.append(
                f"Clique realizado: {alvo}"
            )

            time.sleep(
                TEMPO_ENTRE_ACOES
            )

        # ----------------------------------------------------
        # ESCREVER
        # ----------------------------------------------------

        elif tipo == "escrever":

            texto = acao.get(
                "texto",
                ""
            )

            pyautogui.write(
                texto,
                interval=0.01
            )

            resultados.append(
                f"Texto digitado: {texto}"
            )

            time.sleep(
                TEMPO_ENTRE_ACOES
            )

        # ----------------------------------------------------
        # TECLA
        # ----------------------------------------------------

        elif tipo == "pressionar":

            tecla = acao.get(
                "tecla"
            )

            if not tecla:

                resultados.append(
                    "Falha: tecla não informada."
                )

                continue

            pyautogui.press(
                tecla
            )

            resultados.append(
                f"Tecla pressionada: {tecla}"
            )

            time.sleep(
                TEMPO_ENTRE_ACOES
            )

        else:

            resultados.append(
                f"Ação desconhecida: {tipo}"
            )

    return "\n".join(
        resultados
    )


# ============================================================
# DIGITAR
# ============================================================

def escrever_texto(texto):

    pyautogui.write(
        texto,
        interval=0.02
    )

    return (
        f"Texto digitado: {texto}"
    )


# ============================================================
# PRESSIONAR TECLA
# ============================================================

def pressionar(tecla):

    pyautogui.press(
        tecla
    )

    return (
        f"Tecla pressionada: {tecla}"
    )


# ============================================================
# VERIFICAR TELA
# ============================================================

def verificar_tela(objetivo):

    resultado = localizar(
        objetivo
    )

    if resultado["encontrado"]:

        return (
            f"Verificação positiva.\n"
            f"Elemento: {objetivo}\n"
            f"X={resultado['x']}, "
            f"Y={resultado['y']}\n"
            f"Confiança="
            f"{resultado['confianca']}%"
        )

    return (
        f"Verificação negativa.\n"
        f"O elemento '{objetivo}' "
        "não foi localizado."
    )


# ============================================================
# TESTE
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("DUQUE - COMPUTER USE")
    print("=" * 60)
    print()

    print(
        "Teste de visão em lote."
    )

    entrada = input(
        "Elementos separados por vírgula:\n> "
    )

    elementos = [
        x.strip()
        for x in entrada.split(",")
        if x.strip()
    ]

    print()

    resultado = localizar_varios(
        elementos
    )

    print()
    print("=" * 60)
    print("RESULTADO")
    print("=" * 60)
    print()

    for nome, dados in resultado.items():

        print(
            f"{nome}: "
            f"X={dados['x']} "
            f"Y={dados['y']} "
            f"Confiança={dados['confianca']}%"
        )

    print()