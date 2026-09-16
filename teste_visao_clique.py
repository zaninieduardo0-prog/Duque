import re
import time

from skills.visao import olhar_tela
from skills.computador_uso import (
    mover_mouse,
    clicar,
    capturar_tela,
)


def extrair_coordenadas(resposta):
    """
    Procura X e Y na resposta do modelo.
    Aceita formatos como:
        X=202, Y=413
        X: 202
        Y: 413
    """

    padrao_x = r"X\s*[:=]\s*(\d+)"
    padrao_y = r"Y\s*[:=]\s*(\d+)"

    resultado_x = re.search(
        padrao_x,
        resposta,
        re.IGNORECASE
    )

    resultado_y = re.search(
        padrao_y,
        resposta,
        re.IGNORECASE
    )

    if not resultado_x or not resultado_y:
        return None

    x = int(resultado_x.group(1))
    y = int(resultado_y.group(1))

    return x, y


def validar_coordenada(x, y):
    """
    Impede coordenadas fora da tela.
    """

    if not (0 <= x <= 1366):
        return False

    if not (0 <= y <= 768):
        return False

    return True


print()
print("=" * 60)
print("DUQUE - VISÃO + AÇÃO")
print("=" * 60)
print()

print(
    "Vou procurar a Calculadora na tela."
)

print()

resposta = olhar_tela(
    "Encontre a janela da Calculadora do Windows. "
    "Informe o centro aproximado dela usando X e Y."
)

print()
print("=" * 60)
print("VISÃO")
print("=" * 60)
print()
print(resposta)
print()

coordenadas = extrair_coordenadas(
    resposta
)

if coordenadas is None:

    print(
        "Não consegui extrair uma coordenada "
        "da resposta do modelo."
    )

    raise SystemExit


x, y = coordenadas

print(
    f"Coordenada identificada: X={x}, Y={y}"
)

if not validar_coordenada(x, y):

    print(
        "COORDENADA REJEITADA: "
        "está fora dos limites da tela."
    )

    raise SystemExit


print()
print(
    "Coordenada validada."
)

print()
print(
    "Movendo o mouse..."
)

print(
    mover_mouse(
        x,
        y,
        duracao=0.5
    )
)

time.sleep(1)

print()
print(
    "Posicionei o mouse."
)

print()
print(
    "Vou clicar em 2 segundos..."
)

time.sleep(2)

print(
    clicar(
        x,
        y
    )
)

time.sleep(1)

print()
print(
    "Capturando tela após o clique..."
)

print(
    capturar_tela(
        "apos_visao_clique"
    )
)

print()
print("=" * 60)
print("TESTE CONCLUÍDO")
print("=" * 60)
print()