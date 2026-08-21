"""Runner do Player Discovery — executável via python -m src.player_discovery.run.

Uso:
    python -m src.player_discovery.run              # uma rotação
    python -m src.player_discovery.run --continuous  # loop contínuo

Fluxo:
1. Carrega configuração (env vars + defaults)
2. Inicia Playwright com Chrome real (perfil persistente)
3. Navega para o primeiro canal para iniciar sessão
4. Executa PlayerDiscoveryOrchestrator
5. Salva relatórios em JSON no output_dir
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from .config import PlayerDiscoveryConfig
from .main import PlayerDiscoveryOrchestrator


# Configuração de logging
def _setup_logging(level: str) -> None:
    """Configura logging para stdout."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


async def run_single(config: PlayerDiscoveryConfig, channels: list[str]) -> None:
    """Executa uma única rotação de monitoramento.

    Args:
        config: Configuração centralizada.
        channels: Lista de URLs de canais.
    """
    chrome_profile = os.environ.get("CHROME_PROFILE_DIR", "/data/chrome-profile")
    output_dir = os.environ.get("PLAYER_DISCOVERY_OUTPUT_DIR", "./output")

    async with async_playwright() as p:
        # Idêntico à PoC (poc_orchestrator.py) que funciona
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=chrome_profile,
            executable_path="/usr/bin/google-chrome",
            headless=False,
            timeout=300000,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--no-first-run",
                "--disable-popup-blocking",
            ],
            viewport=None,
            ignore_default_args=["--enable-automation"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        logging.info(
            "Chrome iniciado com perfil: %s", chrome_profile
        )

        try:
            # Criar orquestrador com configuração
            orchestrator = PlayerDiscoveryOrchestrator(
                page=page,
                config=config.to_dict(),
            )

            # Executar uma rotação completa
            logging.info(
                "Iniciando rotação de %d canais...", len(channels)
            )
            await orchestrator.start(page, channels)

            # Salvar relatórios
            _save_reports(orchestrator, output_dir)

            logging.info("Rotação concluída com sucesso.")

        except Exception as e:
            logging.error("Erro na execução: %s", str(e))
            raise
        finally:
            await orchestrator.stop()
            await browser.close()


async def run_continuous(config: PlayerDiscoveryConfig, channels: list[str]) -> None:
    """Executa rotações contínuas até Ctrl+C.

    Args:
        config: Configuração centralizada.
        channels: Lista de URLs de canais.
    """
    chrome_profile = os.environ.get("CHROME_PROFILE_DIR", "/data/chrome-profile")
    output_dir = os.environ.get("PLAYER_DISCOVERY_OUTPUT_DIR", "./output")

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=chrome_profile,
            executable_path="/usr/bin/google-chrome",
            headless=False,
            timeout=300000,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--no-first-run",
                "--disable-popup-blocking",
            ],
            viewport=None,
            ignore_default_args=["--enable-automation"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        logging.info(
            "Chrome iniciado (modo contínuo) com perfil: %s",
            chrome_profile,
        )

        orchestrator = PlayerDiscoveryOrchestrator(
            page=page,
            config=config.to_dict(),
        )

        try:
            logging.info(
                "Iniciando monitoramento contínuo de %d canais...",
                len(channels),
            )
            await orchestrator.run_continuous(page, channels)

        except KeyboardInterrupt:
            logging.info("Interrompido pelo usuário (Ctrl+C).")
        except Exception as e:
            logging.error("Erro fatal: %s", str(e))
            raise
        finally:
            await orchestrator.stop()
            _save_reports(orchestrator, output_dir)
            await browser.close()


async def run_setup(config: PlayerDiscoveryConfig, channels: list[str]) -> None:
    """Abre Chrome e aguarda login manual. Ctrl+C para fechar.

    Use este modo para autenticar no SKY+ pela primeira vez.
    O profile será salvo e reutilizado nas execuções seguintes.

    Args:
        config: Configuração centralizada.
        channels: Lista de URLs de canais (navega para o primeiro).
    """
    chrome_profile = os.environ.get("CHROME_PROFILE_DIR", "/data/chrome-profile")

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=chrome_profile,
            executable_path="/usr/bin/google-chrome",
            headless=False,
            timeout=300000,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--no-first-run",
                "--disable-popup-blocking",
            ],
            viewport=None,
            ignore_default_args=["--enable-automation"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        # Navegar para o canal para acionar login
        url = channels[0] if channels else "https://www.skymais.com.br"
        logging.info("Navegando para: %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        logging.info("")
        logging.info("=" * 60)
        logging.info("  MODO SETUP — Faça login no SKY+ manualmente")
        logging.info("  O Chrome vai ficar aberto até você dar Ctrl+C")
        logging.info("  Após logar, o profile será salvo automaticamente.")
        logging.info("=" * 60)
        logging.info("")

        # Ficar aberto indefinidamente até Ctrl+C
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logging.info("Setup finalizado. Profile salvo em: %s", chrome_profile)
        finally:
            await browser.close()


def _save_reports(orchestrator: PlayerDiscoveryOrchestrator, output_dir: str) -> None:
    """Salva relatórios em JSON no diretório de saída.

    Args:
        orchestrator: Instância do orquestrador com dados coletados.
        output_dir: Caminho do diretório de saída.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = Path(output_dir) / f"discovery_report_{timestamp}.json"

    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "capability_map": None,
        "status": "completed",
    }

    # Serializar CapabilityMap se disponível
    if orchestrator.capability_map is not None:
        report_data["capability_map"] = json.loads(
            orchestrator.capability_map.to_json()
        )

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    logging.info("Relatório salvo em: %s", report_path)


def main() -> None:
    """Entry point do runner."""
    # Carregar configuração de variáveis de ambiente
    config = PlayerDiscoveryConfig.from_env()

    # Log level
    log_level = os.environ.get("PLAYER_DISCOVERY_LOG_LEVEL", "INFO")
    _setup_logging(log_level)

    # Lista de canais (separados por vírgula)
    channels_str = os.environ.get(
        "PLAYER_DISCOVERY_CHANNELS",
        "https://www.skymais.com.br/player/live/CH0100000000124,"
        "https://www.skymais.com.br/player/live/CH0100000000092,"
        "https://www.skymais.com.br/player/live/CH0100000000093,"
        "https://www.skymais.com.br/player/live/CH0100000000094,"
        "https://www.skymais.com.br/player/live/CH0100000000096",
    )
    channels = [ch.strip() for ch in channels_str.split(",") if ch.strip()]

    if not channels:
        logging.error("Nenhum canal configurado. Defina PLAYER_DISCOVERY_CHANNELS.")
        sys.exit(1)

    logging.info("=" * 60)
    logging.info("  Player Discovery — Monitoramento SKY+")
    logging.info("=" * 60)
    logging.info("  Canais: %d", len(channels))
    for ch in channels:
        logging.info("    - %s", ch)
    logging.info("  Observação: %ss por canal", config.observation_period_s)
    logging.info("  Testes funcionais: a cada %d rotações", config.functional_test_interval)
    logging.info("=" * 60)

    # Modo de execução
    continuous = "--continuous" in sys.argv or "-c" in sys.argv
    setup_mode = "--setup" in sys.argv or "-s" in sys.argv

    try:
        if setup_mode:
            asyncio.run(run_setup(config, channels))
        elif continuous:
            asyncio.run(run_continuous(config, channels))
        else:
            asyncio.run(run_single(config, channels))
    except KeyboardInterrupt:
        logging.info("Interrompido pelo usuário.")
        sys.exit(0)
    except Exception as e:
        logging.error("Falha fatal: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
