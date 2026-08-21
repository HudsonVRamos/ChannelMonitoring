"""Script para gerar storageState da plataforma SKY+ e enviar ao S3.

Usa persistent context com perfil do Chrome para herdar sessão existente
e evitar detecção de bot/captcha.

Uso:
    python scripts/generate_storage_state.py

Pré-requisitos:
    pip install playwright boto3
    playwright install chromium
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurações
SKY_LOGIN_URL = "https://www.skymais.com.br/acessar"
SKY_CHANNEL_URL = "https://www.skymais.com.br/player/live/CH0100000000124"
S3_BUCKET = "widevine-poc-artifacts-us-east-1-761018874615"
S3_KEY = "storage_state/state.json"
AWS_REGION = "us-east-1"
OUTPUT_FILE = "storageState.json"


def print_header():
    print()
    print("=" * 60)
    print("  Gerador de StorageState — SKY+ / Widevine PoC")
    print("=" * 60)
    print()
    print("  IMPORTANTE: Feche TODAS as janelas do Chrome antes")
    print("  de executar este script!")
    print()
    print("  O script vai abrir o Chrome usando seu perfil real")
    print("  (com sessão já logada), navegar até o canal e")
    print("  exportar os cookies.")
    print()
    print("=" * 60)
    print()


def validate_storage_state(path: str) -> bool:
    if not os.path.exists(path):
        print(f"  ✗ Arquivo não encontrado: {path}")
        return False

    size = os.path.getsize(path)
    if size == 0:
        print(f"  ✗ Arquivo vazio")
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON inválido: {e}")
        return False

    cookies = data.get("cookies", [])
    origins = data.get("origins", [])

    print(f"  ✓ Arquivo válido: {size} bytes")
    print(f"    Cookies: {len(cookies)}")
    print(f"    Origins (localStorage): {len(origins)}")

    # Verificar se tem dados de skymais
    sky_cookies = [c for c in cookies if "skymais" in c.get("domain", "")]
    print(f"    Cookies skymais: {len(sky_cookies)}")

    # Verificar localStorage
    for origin in origins:
        if "skymais" in origin.get("origin", ""):
            ls = origin.get("localStorage", [])
            print(f"    localStorage skymais: {len(ls)} entries")
            # Procurar tokens
            for item in ls:
                name = item.get("name", "")
                if any(k in name.lower() for k in ["token", "auth", "session", "user"]):
                    value_preview = item.get("value", "")[:50]
                    print(f"      → {name}: {value_preview}...")

    return len(cookies) > 0 or len(origins) > 0


def upload_to_s3(local_path: str) -> bool:
    try:
        import boto3
        print(f"\n  Uploading para s3://{S3_BUCKET}/{S3_KEY} ...")
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        s3_client.upload_file(local_path, S3_BUCKET, S3_KEY)
        print(f"  ✓ Upload concluído!")
        return True
    except Exception as e:
        print(f"  ✗ Falha no upload: {e}")
        print(f"  → Manual: aws s3 cp {local_path} s3://{S3_BUCKET}/{S3_KEY} --region {AWS_REGION}")
        return False


def get_chrome_user_data_dir() -> str:
    """Retorna o diretório de perfil padrão do Chrome no Windows."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    chrome_dir = os.path.join(local_app_data, "Google", "Chrome", "User Data")
    if os.path.exists(chrome_dir):
        return chrome_dir
    # Fallback
    home = os.path.expanduser("~")
    return os.path.join(home, "AppData", "Local", "Google", "Chrome", "User Data")


async def generate_storage_state():
    """Abre Chrome com perfil real, navega e exporta storageState."""
    from playwright.async_api import async_playwright

    user_data_dir = get_chrome_user_data_dir()
    print(f"  Chrome profile: {user_data_dir}")

    if not os.path.exists(user_data_dir):
        print(f"  ✗ Perfil do Chrome não encontrado!")
        print(f"    Esperado em: {user_data_dir}")
        print()
        print("  Alternativa: faça login no Chrome normal primeiro,")
        print("  depois rode este script.")
        return False

    print(f"  ✓ Perfil do Chrome encontrado")
    print()
    print("  FECHE O CHROME AGORA se estiver aberto!")
    print()
    input("  Pressione ENTER quando o Chrome estiver fechado... ")
    print()

    async with async_playwright() as p:
        # Usar persistent context com o perfil do Chrome
        # Isso herda todos os cookies e localStorage da sessão existente
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="chrome",
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1920, "height": 1080},
            no_viewport=True,
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Navegar direto para o canal (já deve estar logado)
        print(f"  Navegando para {SKY_CHANNEL_URL} ...")
        await page.goto(SKY_CHANNEL_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        current_url = page.url
        print(f"  URL atual: {current_url}")

        # Verificar se está na tela de login
        if "acessar" in current_url.lower() or "login" in current_url.lower():
            print()
            print("  ⚠ Você foi redirecionado para login!")
            print("  Faça login agora no browser que abriu.")
            print("  Depois navegue até um canal ao vivo.")
            print()
            input("  Pressione ENTER quando estiver logado e no canal... ")
            await page.wait_for_timeout(2000)

        # Exportar storageState
        print(f"  Exportando storageState para {OUTPUT_FILE} ...")
        await context.storage_state(path=OUTPUT_FILE)

        # Fechar
        await context.close()

    print(f"  ✓ StorageState exportado!")
    return True


def main():
    print_header()

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  ✗ Playwright não instalado: pip install playwright")
        sys.exit(1)

    success = asyncio.run(generate_storage_state())
    if not success:
        sys.exit(1)

    print()
    print("  Validando storageState...")
    if not validate_storage_state(OUTPUT_FILE):
        print("\n  ✗ StorageState inválido.")
        sys.exit(1)

    print()
    upload = input("  Fazer upload para S3? [S/n]: ").strip().lower()
    if upload in ("", "s", "sim", "y", "yes"):
        upload_to_s3(OUTPUT_FILE)
    else:
        print(f"\n  Arquivo salvo em: {OUTPUT_FILE}")

    print()
    print("=" * 60)
    print("  Pronto!")
    print("=" * 60)


if __name__ == "__main__":
    main()
