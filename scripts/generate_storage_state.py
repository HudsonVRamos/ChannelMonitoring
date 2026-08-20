"""Script para gerar storageState da plataforma SKY+ e enviar ao S3.

Fluxo:
1. Abre browser Chromium com interface gráfica
2. Navega para a página de login da SKY+
3. Aguarda você fazer login manualmente
4. Após login, navega para um canal ao vivo (para capturar cookies DRM)
5. Exporta storageState.json com todos os cookies e localStorage
6. Valida o arquivo gerado
7. Faz upload para o S3

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

# Adicionar raiz do projeto ao path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Configurações
SKY_LOGIN_URL = "https://www.skymais.com.br/acessar"
S3_BUCKET = "widevine-poc-artifacts-us-east-1-761018874615"
S3_KEY = "storage_state/state.json"
AWS_REGION = "us-east-1"
OUTPUT_FILE = "storageState.json"


def print_header():
    """Imprime cabeçalho do script."""
    print()
    print("=" * 60)
    print("  Gerador de StorageState — SKY+ / Widevine PoC")
    print("=" * 60)
    print()
    print("  Este script vai:")
    print("  1. Abrir um browser Chromium")
    print("  2. Navegar para a SKY+")
    print("  3. Aguardar você fazer login")
    print("  4. Exportar cookies e sessão")
    print("  5. Fazer upload para o S3")
    print()
    print("=" * 60)
    print()


def validate_storage_state(path: str) -> bool:
    """Valida se o storageState gerado é válido.

    Verifica:
    - Arquivo existe e tamanho > 0
    - JSON válido
    - Contém array 'cookies' com ao menos um cookie

    Returns:
        True se válido.
    """
    if not os.path.exists(path):
        print(f"  ✗ Arquivo não encontrado: {path}")
        return False

    size = os.path.getsize(path)
    if size == 0:
        print(f"  ✗ Arquivo vazio (0 bytes)")
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON inválido: {e}")
        return False

    cookies = data.get("cookies", [])
    if not isinstance(cookies, list) or len(cookies) == 0:
        print(f"  ✗ Nenhum cookie encontrado no storageState")
        return False

    print(f"  ✓ Arquivo válido: {size} bytes, {len(cookies)} cookies")

    # Mostrar domínios dos cookies capturados
    domains = set(c.get("domain", "") for c in cookies)
    for domain in sorted(domains):
        count = sum(1 for c in cookies if c.get("domain") == domain)
        print(f"    • {domain} ({count} cookies)")

    return True


def upload_to_s3(local_path: str) -> bool:
    """Faz upload do storageState para o S3.

    Returns:
        True se upload bem-sucedido.
    """
    try:
        import boto3

        print(f"\n  Uploading para s3://{S3_BUCKET}/{S3_KEY} ...")

        s3_client = boto3.client("s3", region_name=AWS_REGION)
        s3_client.upload_file(local_path, S3_BUCKET, S3_KEY)

        print(f"  ✓ Upload concluído!")
        print(f"    Bucket: {S3_BUCKET}")
        print(f"    Key: {S3_KEY}")
        print(f"    Region: {AWS_REGION}")
        return True

    except ImportError:
        print("  ✗ boto3 não instalado. Instale com: pip install boto3")
        print(f"  → Upload manual: aws s3 cp {local_path} s3://{S3_BUCKET}/{S3_KEY} --region {AWS_REGION}")
        return False
    except Exception as e:
        print(f"  ✗ Falha no upload: {e}")
        print(f"  → Upload manual: aws s3 cp {local_path} s3://{S3_BUCKET}/{S3_KEY} --region {AWS_REGION}")
        return False


async def generate_storage_state():
    """Fluxo principal: abre browser, aguarda login, exporta sessão."""
    from playwright.async_api import async_playwright

    print("  Abrindo browser Chrome do sistema (evita detecção de bot)...")
    print()

    async with async_playwright() as p:
        # Usar Chrome do sistema ao invés do Chromium do Playwright
        # Isso evita detecção de bot/captcha
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",  # Usa o Chrome instalado no sistema
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            no_viewport=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        # Navegar para a SKY+
        print(f"  Navegando para {SKY_LOGIN_URL} ...")
        await page.goto(SKY_LOGIN_URL, wait_until="domcontentloaded")

        print()
        print("  ┌─────────────────────────────────────────────────┐")
        print("  │                                                   │")
        print("  │   Faça LOGIN na plataforma SKY+ no browser.      │")
        print("  │                                                   │")
        print("  │   Após logar, NAVEGUE até um CANAL AO VIVO       │")
        print("  │   para garantir que os cookies de DRM sejam       │")
        print("  │   capturados.                                     │")
        print("  │                                                   │")
        print("  │   Quando estiver pronto, volte aqui e             │")
        print("  │   pressione ENTER.                                │")
        print("  │                                                   │")
        print("  └─────────────────────────────────────────────────┘")
        print()

        # Aguardar usuário fazer login
        input("  → Pressione ENTER quando estiver logado e num canal ao vivo... ")

        # Verificar URL atual
        current_url = page.url
        print(f"\n  URL atual: {current_url}")

        # Exportar storageState
        print(f"  Exportando storageState para {OUTPUT_FILE} ...")
        await context.storage_state(path=OUTPUT_FILE)

        # Fechar browser
        await browser.close()

    print(f"  ✓ Browser fechado.")
    print()


def main():
    """Entry point do script."""
    print_header()

    # Verificar se Playwright está instalado
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  ✗ Playwright não instalado.")
        print("    Execute:")
        print("      pip install playwright")
        print("      playwright install chromium")
        sys.exit(1)

    # Executar geração do storageState
    asyncio.run(generate_storage_state())

    # Validar arquivo gerado
    print("  Validando storageState...")
    if not validate_storage_state(OUTPUT_FILE):
        print("\n  ✗ StorageState inválido. Tente novamente.")
        sys.exit(1)

    # Perguntar se quer fazer upload para S3
    print()
    upload = input("  Fazer upload para S3? [S/n]: ").strip().lower()

    if upload in ("", "s", "sim", "y", "yes"):
        upload_to_s3(OUTPUT_FILE)
    else:
        print(f"\n  Upload pulado. Arquivo salvo em: {OUTPUT_FILE}")
        print(f"  Para upload manual:")
        print(f"    aws s3 cp {OUTPUT_FILE} s3://{S3_BUCKET}/{S3_KEY} --region {AWS_REGION}")

    print()
    print("=" * 60)
    print("  Pronto! Agora pode executar a PoC:")
    print(f"  aws codebuild start-build --project-name widevine-poc --region {AWS_REGION}")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
