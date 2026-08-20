"""Verifica se o Widevine CDM está disponível no ambiente."""
import subprocess
import os
import sys


def main():
    print("=== Diagnóstico Widevine CDM ===")
    print()

    # Procurar arquivos Widevine
    result = subprocess.run(
        ["find", "/", "-name", "*idevine*", "-type", "f"],
        capture_output=True, text=True, timeout=10
    )
    widevine_files = result.stdout.strip()
    if widevine_files:
        print("Arquivos Widevine encontrados:")
        for f in widevine_files.split("\n"):
            print(f"  {f}")
    else:
        print("NENHUM arquivo Widevine encontrado!")

    print()

    # Procurar o binário do Chrome
    result2 = subprocess.run(
        ["find", "/root/.cache/ms-playwright", "-name", "chrome", "-type", "f"],
        capture_output=True, text=True, timeout=10
    )
    chrome_bin = result2.stdout.strip()
    if chrome_bin:
        print(f"Chrome binary: {chrome_bin}")
    else:
        print("Chrome binary: NAO ENCONTRADO")

    print()

    # Verificar versao do Playwright
    try:
        import playwright
        print(f"Playwright version: {getattr(playwright, '__version__', 'unknown')}")
    except ImportError:
        print("Playwright: NAO INSTALADO")

    # Verificar se o Chrome suporta Widevine
    if chrome_bin:
        chrome_path = chrome_bin.split("\n")[0]
        result3 = subprocess.run(
            [chrome_path, "--headless", "--no-sandbox", "--dump-dom",
             "chrome://components/"],
            capture_output=True, text=True, timeout=15
        )
        if "widevine" in result3.stdout.lower() or "Widevine" in result3.stdout:
            print("Chrome components: Widevine DETECTADO")
        else:
            print("Chrome components: Widevine NAO detectado nos componentes")
            print(f"  stdout length: {len(result3.stdout)}")
            if result3.stderr:
                print(f"  stderr: {result3.stderr[:200]}")


if __name__ == "__main__":
    main()
