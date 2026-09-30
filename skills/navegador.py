from playwright.sync_api import sync_playwright


def executar_navegador(
    url: str,
    acao: str,
    alvo: str = "",
    valor: str = ""
) -> str:

    p = sync_playwright().start()

    try:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print(f"\nAbrindo: {url}")

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        page.wait_for_timeout(2000)

        if acao in ["abrir", "ler"]:
            return ler_pagina(page)

        if acao == "clicar":

            elemento = page.get_by_text(
                alvo,
                exact=False
            ).first

            elemento.wait_for(
                state="visible",
                timeout=10000
            )

            elemento.click()

            page.wait_for_timeout(2000)

            return ler_pagina(page)

        if acao == "preencher":

            page.locator(alvo).fill(valor)

            return (
                f"Campo '{alvo}' preenchido "
                f"com sucesso."
            )

        if acao == "enter":

            page.keyboard.press("Enter")

            page.wait_for_timeout(2000)

            return ler_pagina(page)

        return f"Ação desconhecida: {acao}"

    except Exception as erro:

        return f"Erro no navegador: {erro}"

    finally:

        try:
            browser.close()
        except:
            pass

        p.stop()


def ler_pagina(page) -> str:

    titulo = page.title()
    url_atual = page.url

    texto = page.locator("body").inner_text()

    texto = texto[:20000]

    resultado = (
        f"TÍTULO:\n"
        f"{titulo}\n\n"
        f"URL:\n"
        f"{url_atual}\n\n"
        f"CONTEÚDO:\n"
        f"{texto}"
    )

    print("\n" + "=" * 60)
    print("PÁGINA LIDA")
    print("=" * 60)

    print(resultado)

    return resultado