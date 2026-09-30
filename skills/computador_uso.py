import time
from pathlib import Path

import pyautogui


# ============================================================
# CONFIGURAÇÃO
# ============================================================

PASTA_SCREENSHOTS = Path(
    r"C:\Duque\screenshots"
)

PASTA_SCREENSHOTS.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# CONFIGURAÇÃO DE SEGURANÇA
# ============================================================

# Se o mouse for movido para o canto superior esquerdo,
# o PyAutoGUI interrompe uma ação em andamento.
pyautogui.FAILSAFE = True

# Pequena pausa entre ações.
pyautogui.PAUSE = 0.15


# ============================================================
# TELA
# ============================================================

def capturar_tela(
    nome: str = "tela"
) -> str:

    """
    Captura a tela inteira e salva uma imagem.
    """

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    caminho = (
        PASTA_SCREENSHOTS
        / f"{nome}_{timestamp}.png"
    )

    try:

        imagem = pyautogui.screenshot()

        imagem.save(caminho)

        return (
            f"Screenshot capturada com sucesso.\n"
            f"Arquivo: {caminho}"
        )

    except Exception as erro:

        return (
            f"Erro ao capturar a tela: {erro}"
        )


# ============================================================
# TAMANHO DA TELA
# ============================================================

def tamanho_tela() -> str:

    """
    Retorna a resolução atual da tela.
    """

    try:

        largura, altura = (
            pyautogui.size()
        )

        return (
            f"Tela: {largura}x{altura}"
        )

    except Exception as erro:

        return (
            f"Erro ao obter tamanho da tela: {erro}"
        )


# ============================================================
# POSIÇÃO DO MOUSE
# ============================================================

def posicao_mouse() -> str:

    """
    Retorna a posição atual do mouse.
    """

    try:

        x, y = pyautogui.position()

        return (
            f"Mouse: X={x}, Y={y}"
        )

    except Exception as erro:

        return (
            f"Erro ao obter posição do mouse: {erro}"
        )


# ============================================================
# MOVER MOUSE
# ============================================================

def mover_mouse(
    x: int,
    y: int,
    duracao: float = 0.2
) -> str:

    """
    Move o mouse para uma coordenada específica.
    """

    try:

        pyautogui.moveTo(
            x,
            y,
            duration=duracao
        )

        return (
            f"Mouse movido para X={x}, Y={y}."
        )

    except Exception as erro:

        return (
            f"Erro ao mover mouse: {erro}"
        )


# ============================================================
# CLIQUE
# ============================================================

def clicar(
    x: int,
    y: int,
    botao: str = "left"
) -> str:

    """
    Move até uma coordenada e clica.
    """

    try:

        if botao not in [
            "left",
            "right",
            "middle"
        ]:

            return (
                "Botão inválido. "
                "Use left, right ou middle."
            )

        pyautogui.click(
            x=x,
            y=y,
            button=botao
        )

        return (
            f"Clique {botao} realizado "
            f"em X={x}, Y={y}."
        )

    except Exception as erro:

        return (
            f"Erro ao clicar: {erro}"
        )


# ============================================================
# DUPLO CLIQUE
# ============================================================

def duplo_clique(
    x: int,
    y: int
) -> str:

    """
    Realiza um duplo clique.
    """

    try:

        pyautogui.doubleClick(
            x=x,
            y=y,
            interval=0.1
        )

        return (
            f"Duplo clique realizado "
            f"em X={x}, Y={y}."
        )

    except Exception as erro:

        return (
            f"Erro no duplo clique: {erro}"
        )


# ============================================================
# CLIQUE DIREITO
# ============================================================

def clique_direito(
    x: int,
    y: int
) -> str:

    """
    Realiza clique direito.
    """

    try:

        pyautogui.rightClick(
            x=x,
            y=y
        )

        return (
            f"Clique direito realizado "
            f"em X={x}, Y={y}."
        )

    except Exception as erro:

        return (
            f"Erro no clique direito: {erro}"
        )


# ============================================================
# DIGITAR
# ============================================================

def digitar(
    texto: str,
    intervalo: float = 0.01
) -> str:

    """
    Digita texto no elemento atualmente focado.
    """

    try:

        pyautogui.write(
            texto,
            interval=intervalo
        )

        return (
            "Texto digitado com sucesso."
        )

    except Exception as erro:

        return (
            f"Erro ao digitar: {erro}"
        )


# ============================================================
# COLAR TEXTO
# ============================================================

def colar_texto(
    texto: str
) -> str:

    """
    Coloca texto na área de transferência
    e usa CTRL+V.

    Isso é mais confiável para textos grandes
    ou caracteres especiais.
    """

    try:

        import pyperclip

        pyperclip.copy(
            texto
        )

        pyautogui.hotkey(
            "ctrl",
            "v"
        )

        return (
            "Texto colado com sucesso."
        )

    except Exception as erro:

        return (
            f"Erro ao colar texto: {erro}"
        )


# ============================================================
# PRESSIONAR TECLA
# ============================================================

def pressionar_tecla(
    tecla: str
) -> str:

    """
    Pressiona uma tecla.
    """

    try:

        pyautogui.press(
            tecla
        )

        return (
            f"Tecla '{tecla}' pressionada."
        )

    except Exception as erro:

        return (
            f"Erro ao pressionar tecla: {erro}"
        )


# ============================================================
# ATALHO DE TECLADO
# ============================================================

def atalho(
    *teclas: str
) -> str:

    """
    Pressiona uma combinação de teclas.

    Exemplo:
        atalho("ctrl", "l")
    """

    try:

        pyautogui.hotkey(
            *teclas
        )

        return (
            f"Atalho executado: "
            f"{' + '.join(teclas)}"
        )

    except Exception as erro:

        return (
            f"Erro ao executar atalho: {erro}"
        )


# ============================================================
# SCROLL
# ============================================================

def rolar(
    quantidade: int
) -> str:

    """
    Rola a página/janela ativa.

    Positivo = para cima
    Negativo = para baixo
    """

    try:

        pyautogui.scroll(
            quantidade
        )

        return (
            f"Scroll realizado: {quantidade}."
        )

    except Exception as erro:

        return (
            f"Erro ao rolar: {erro}"
        )


# ============================================================
# ARRASTAR MOUSE
# ============================================================

def arrastar(
    x: int,
    y: int,
    duracao: float = 0.5,
    botao: str = "left"
) -> str:

    """
    Arrasta o mouse até a coordenada indicada.
    """

    try:

        pyautogui.dragTo(
            x,
            y,
            duration=duracao,
            button=botao
        )

        return (
            f"Mouse arrastado para "
            f"X={x}, Y={y}."
        )

    except Exception as erro:

        return (
            f"Erro ao arrastar mouse: {erro}"
        )


# ============================================================
# ESPERAR
# ============================================================

def esperar(
    segundos: float
) -> str:

    """
    Aguarda alguns segundos.
    """

    try:

        time.sleep(
            segundos
        )

        return (
            f"Aguardei {segundos} segundos."
        )

    except Exception as erro:

        return (
            f"Erro durante espera: {erro}"
        )


# ============================================================
# TESTE COMPLETO
# ============================================================

def teste_computador() -> str:

    """
    Executa um teste seguro:

    1. identifica tela
    2. identifica mouse
    3. captura screenshot

    Não clica nem digita.
    """

    resultado = []

    resultado.append(
        tamanho_tela()
    )

    resultado.append(
        posicao_mouse()
    )

    resultado.append(
        capturar_tela(
            "teste"
        )
    )

    return "\n".join(
        resultado
    )


# ============================================================
# EXECUÇÃO DIRETA
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("DUQUE - TESTE COMPUTER USE")
    print("=" * 60)
    print()

    print(
        teste_computador()
    )

    print()