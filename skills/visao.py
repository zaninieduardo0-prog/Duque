import base64
import json
import re
import time
from pathlib import Path

import pyautogui
from openai import OpenAI


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MODELO_VISAO = "gpt-5.6-luna"

PASTA_SCREENSHOTS = Path(r"C:\Duque\screenshots")
PASTA_SCREENSHOTS.mkdir(parents=True, exist_ok=True)

client = OpenAI()


# ============================================================
# CAPTURAR TELA
# ============================================================

def capturar_tela_atual() -> Path:

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    caminho = (
        PASTA_SCREENSHOTS
        / f"visao_{timestamp}.png"
    )

    imagem = pyautogui.screenshot()
    imagem.save(caminho)

    return caminho


# ============================================================
# IMAGEM → DATA URL
# ============================================================

def imagem_data_url(caminho: str) -> str:

    arquivo = Path(caminho)

    if not arquivo.exists():
        raise FileNotFoundError(
            f"Imagem não encontrada: {caminho}"
        )

    dados = arquivo.read_bytes()

    base64_imagem = base64.b64encode(
        dados
    ).decode("utf-8")

    return (
        "data:image/png;base64,"
        + base64_imagem
    )


# ============================================================
# ANÁLISE INDIVIDUAL
# ============================================================

def analisar_tela(
    caminho: str,
    objetivo: str
) -> str:

    imagem = imagem_data_url(caminho)

    resposta = client.responses.create(

        model=MODELO_VISAO,

        input=[
            {
                "role": "user",

                "content": [

                    {
                        "type": "input_text",

                        "text": f"""
Você está analisando uma captura de tela
de um computador Windows.

A resolução da imagem é 1366x768.

Analise visualmente toda a imagem.

Objetivo:

{objetivo}

Diga se o elemento solicitado aparece
na tela.

Se aparecer:

1. identifique o elemento;
2. descreva brevemente onde ele está;
3. informe aproximadamente o centro
   do elemento em coordenadas X,Y.

As coordenadas começam no canto
superior esquerdo da imagem.

Não invente informações.

Se o elemento não estiver visível,
diga claramente que não está visível.

Responda em português.
"""
                    },

                    {
                        "type": "input_image",
                        "image_url": imagem
                    }

                ]
            }
        ]
    )

    return resposta.output_text


# ============================================================
# VISÃO NORMAL
# ============================================================

def olhar_tela(objetivo: str) -> str:

    print()
    print("Capturando a tela atual...")

    caminho = capturar_tela_atual()

    print(
        f"Screenshot: {caminho}"
    )

    print()
    print("Enviando imagem para o modelo...")

    resultado = analisar_tela(
        str(caminho),
        objetivo
    )

    return resultado


# ============================================================
# VISÃO EM LOTE
# ============================================================

def analisar_tela_lote(
    caminho: str,
    elementos: list
) -> dict:
    """
    Analisa uma única captura de tela e procura
    vários elementos de uma vez.

    Retorna:

    {
        "elementos": {
            "7": {
                "encontrado": true,
                "x": 100,
                "y": 200,
                "confianca": 95
            }
        }
    }
    """

    imagem = imagem_data_url(caminho)

    lista_elementos = "\n".join(
        f"- {elemento}"
        for elemento in elementos
    )

    prompt = f"""
Você é o sistema de visão computacional do Duque.

Está analisando uma captura de tela de um
computador Windows.

Resolução:
1366x768

Procure TODOS os elementos abaixo na imagem:

{lista_elementos}

Para cada elemento encontrado, informe:

- encontrado
- x
- y
- confiança

X e Y devem representar o centro aproximado
do elemento.

As coordenadas começam no canto superior
esquerdo da tela.

IMPORTANTE:

- Não invente elementos.
- Não invente coordenadas.
- Se não encontrar um elemento, marque encontrado
  como false.
- A confiança deve ser um número de 0 a 100.
- Analise a imagem inteira.

RESPONDA SOMENTE EM JSON VÁLIDO.

Formato obrigatório:

{{
    "elementos": {{
        "nome_do_elemento": {{
            "encontrado": true,
            "x": 100,
            "y": 200,
            "confianca": 95
        }}
    }}
}}
"""

    resposta = client.responses.create(

        model=MODELO_VISAO,

        input=[
            {
                "role": "user",

                "content": [

                    {
                        "type": "input_text",
                        "text": prompt
                    },

                    {
                        "type": "input_image",
                        "image_url": imagem
                    }

                ]
            }
        ]
    )

    texto = resposta.output_text.strip()

    # Remove possíveis blocos Markdown
    texto = re.sub(
        r"^```json\s*",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\s*```$",
        "",
        texto
    )

    try:

        dados = json.loads(texto)

    except json.JSONDecodeError:

        # Tenta encontrar o JSON dentro da resposta
        inicio = texto.find("{")
        fim = texto.rfind("}")

        if inicio == -1 or fim == -1:

            raise ValueError(
                "A visão não retornou JSON válido:\n"
                + texto
            )

        dados = json.loads(
            texto[inicio:fim + 1]
        )

    return dados


# ============================================================
# VISÃO EM LOTE — FUNÇÃO PRINCIPAL
# ============================================================

def olhar_tela_lote(elementos: list) -> dict:

    if not elementos:

        return {
            "elementos": {}
        }

    print()
    print("=" * 60)
    print("DUQUE - VISÃO EM LOTE")
    print("=" * 60)

    print()
    print("Elementos procurados:")

    for elemento in elementos:
        print(f"  • {elemento}")

    print()
    print("Capturando tela...")

    caminho = capturar_tela_atual()

    print(
        f"Screenshot: {caminho}"
    )

    print()
    print("Analisando todos os elementos em uma única chamada...")

    resultado = analisar_tela_lote(
        str(caminho),
        elementos
    )

    print()
    print("Resultado:")

    print(
        json.dumps(
            resultado,
            indent=4,
            ensure_ascii=False
        )
    )

    return resultado


# ============================================================
# TESTE
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("DUQUE - VISÃO COMPUTACIONAL")
    print("=" * 60)
    print()

    print(
        "Digite os elementos separados por vírgula."
    )

    entrada = input(
        "> "
    )

    elementos = [
        x.strip()
        for x in entrada.split(",")
        if x.strip()
    ]

    print()

    try:

        resultado = olhar_tela_lote(
            elementos
        )

        print()
        print("=" * 60)
        print("RESPOSTA")
        print("=" * 60)
        print()

        print(
            json.dumps(
                resultado,
                indent=4,
                ensure_ascii=False
            )
        )

    except Exception as erro:

        print()
        print("=" * 60)
        print("ERRO")
        print("=" * 60)
        print()

        print(
            repr(erro)
        )

    print()