#!/usr/bin/env python3
"""Script para autenticar no SKY+ e salvar sessão no Chrome profile.

Uso (na EC2, dentro do diretório do projeto):
    python3 scripts/setup_auth.py

O que faz:
1. Abre Chrome com o profile /data/chrome-profile
2. Navega para o SKY+ (página de login)
3. Espera você logar manualmente
4. Fica aberto até Ctrl+C
5. Ao fechar, os cookies ficam salvos no profile

Depois de rodar este script, o Player Discovery vai abrir já autenticado.
"""

import asyncio
import sys

from playwright.async_api import async_playwright


CHROME_PROFILE = "/data/chrome-profile"
SKY_URL = "https://www.skymais.com.br/player/live/CH0100000000124"


async def main():
    print("=" * 60)
    print("  Setup de Autenticação SKY+")
    print("=" * 60)
    print(f"  Profile: {CHROME_PROFILE}")
    print(f"  URL: {SKY_URL}")
    print("=" * 60)
    print()

    async with async_playwright() as p:
        print("[1/3] Abrindo Chrome...")
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
            executable_path="/usr/bin/google-chrome",
            headless=False,
            timeout=300000,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--disable-popup-blocking",
                "--window-size=1920,1080",
            ],
            viewport={"width": 1920, "height": 1080},
            ignore_default_args=["--enable-automation"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        print("[2/3] Navegando para SKY+...")
        await page.goto(SKY_URL, wait_until="domcontentloaded", timeout=30000)

        print("[3/3] Chrome aberto!")
        print()
        print("  >>> FAÇA LOGIN NO SKY+ MANUALMENTE <<<")
        print("  >>> Quando terminar, aperte Ctrl+C <<<")
        print()

        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        print()
        print("Salvando sessão e fechando Chrome...")
        await browser.close()
        print("Pronto! Profile salvo em:", CHROME_PROFILE)
        print("Agora rode: PYTHONPATH=. python3 -m src.player_discovery.run")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nFinalizado.")
        sys.exit(0)
