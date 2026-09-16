from playwright.sync_api import sync_playwright

p = sync_playwright().start()

browser = p.chromium.launch(headless=False)
page = browser.new_page()

page.goto("https://www.google.com/search?q=teste+apartamentos+Piracicaba")

page.wait_for_timeout(5000)

print("\n" + "=" * 60)
print("TÍTULO DA PÁGINA")
print("=" * 60)
print(page.title())

print("\n" + "=" * 60)
print("URL ATUAL")
print("=" * 60)
print(page.url)

print("\n" + "=" * 60)
print("TEXTO DA PÁGINA")
print("=" * 60)

texto = page.locator("body").inner_text()

print(texto[:15000])

input("\nPressione ENTER para fechar...")

browser.close()
p.stop()