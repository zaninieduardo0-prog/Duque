import time
import pyautogui

from skills.computador_uso import (
    posicao_mouse,
    mover_mouse,
    clicar,
    capturar_tela,
)


print()
print("=" * 60)
print("DUQUE - TESTE DE CLIQUE")
print("=" * 60)
print()

# ------------------------------------------------------------
# 1. Descobrir resolução
# ------------------------------------------------------------

largura, altura = pyautogui.size()

print(f"Tela detectada: {largura}x{altura}")
print()

# ------------------------------------------------------------
# 2. Capturar tela antes da ação
# ------------------------------------------------------------

print("Capturando tela antes do clique...")

print(
    capturar_tela("antes_clique")
)

print()

# ------------------------------------------------------------
# 3. Mostrar posição atual
# ------------------------------------------------------------

print(
    posicao_mouse()
)

print()

# ------------------------------------------------------------
# 4. DEFINIR COORDENADA DO CLIQUE
# ------------------------------------------------------------
#
# IMPORTANTE:
# Vamos clicar aproximadamente no centro da tela.
#
# NÃO é um botão específico ainda.
# É apenas um teste para verificar se o controle
# de coordenadas e clique está funcionando.
#

x = largura // 2
y = altura // 2

print(
    f"Coordenada escolhida: X={x}, Y={y}"
)

print()

# ------------------------------------------------------------
# 5. Mover mouse
# ------------------------------------------------------------

print("Movendo mouse...")

print(
    mover_mouse(
        x,
        y,
        duracao=0.5
    )
)

time.sleep(1)

# ------------------------------------------------------------
# 6. CLIQUE
# ------------------------------------------------------------

print()
print("Realizando clique...")

print(
    clicar(
        x,
        y
    )
)

time.sleep(1)

# ------------------------------------------------------------
# 7. Verificar posição
# ------------------------------------------------------------

print()
print(
    posicao_mouse()
)

# ------------------------------------------------------------
# 8. Capturar tela depois
# ------------------------------------------------------------

print()
print("Capturando tela depois do clique...")

print(
    capturar_tela("depois_clique")
)

print()
print("=" * 60)
print("TESTE CONCLUÍDO")
print("=" * 60)
print()