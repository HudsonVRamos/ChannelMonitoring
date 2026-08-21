"""Entry point CLI do Unified Channel Monitor.

Ponto de entrada principal que carrega a configuração, lança o browser
Playwright com persistent context, cria o orquestrador unificado e
executa rotação única ou contínua conforme a flag --continuous.

Uso:
    PYTHONPATH=. python -m src.unified_channel_monitor.run
    PYTHONPATH=. python -m src.unified_channel_monitor.run --continuous

Requirements: 1.1, 1.2, 1.3, 1.5, 1.6
"""

from __future__ import annotations

import asyncio
import logging
import sys

from playwright.async_api import async_playwright

from src.unified_channel_monitor.config import UnifiedMonitorConfig
from src.unified_channel_monitor.orchestrator import UnifiedOrchestrator

logger = logging.getLogger(__name__)


def _setup_logging(log_level: str) -> None:
    """Configura logging estruturado para stdout.

    Args:
        log_level: Nível de logging (DEBUG, INFO, WARNING, ERROR).
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format=(
            '{"timestamp":"%(asctime)s",'
            '"level":"%(levelname)s",'
            '"logger":"%(name)s",'
            '"message":"%(message)s"}'
        ),
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


async def main() -> None:
    """Função principal async do Unified Channel Monitor.

    Fluxo:
    1. Carrega configuração via env vars
    2. Parseia flag --continuous de sys.argv
    3. Valida que há canais configurados
    4. Configura logging estruturado
    5. Lança Playwright persistent context
    6. Cria UnifiedOrchestrator
    7. Registra signal handlers (SIGINT)
    8. Executa rotação única ou contínua
    9. Fecha browser e sai com exit code apropriado
    """
    # 1. Carregar configuração
    config = UnifiedMonitorConfig.from_env()

    # 2. Override --continuous flag via CLI
    if "--continuous" in sys.argv:
        config.continuous = True

    # 3. Configurar logging
    _setup_logging(config.log_level)

    # 4. Validar canais configurados
    if not config.channels:
        logger.error(
            "Nenhum canal configurado. Defina "
            "UNIFIED_MONITOR_CHANNELS "
            "com URLs separadas por vírgula."
        )
        sys.exit(1)

    logger.info(
        "Unified Channel Monitor iniciando",
        extra={
            "channels_count": len(config.channels),
            "continuous": config.continuous,
            "chrome_profile_dir": config.chrome_profile_dir,
            "output_dir": config.output_dir,
        },
    )

    # 5. Lançar Playwright persistent context com Google Chrome real
    # (necessário para Widevine DRM — Chromium bundled não tem CDM)
    chrome_profile = config.chrome_profile_dir or "/data/chrome-profile"
    try:
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

            # Obter ou criar página
            page = (
                browser.pages[0]
                if browser.pages
                else await browser.new_page()
            )

            logger.info(
                "Google Chrome lançado com Widevine CDM",
                extra={
                    "chrome_profile_dir": chrome_profile,
                    "executable": "/usr/bin/google-chrome",
                    "pages_count": len(browser.pages),
                },
            )

            # 6. Criar orquestrador
            orchestrator = UnifiedOrchestrator(
                page=page,
                config=config,
                browser_context=browser,
            )

            # 7. Registrar signal handlers
            orchestrator.register_signal_handlers()

            # 8. Executar rotação
            if config.continuous:
                exit_code = await orchestrator.run_continuous(
                    config.channels
                )
            else:
                await orchestrator.run_single_rotation(
                    config.channels
                )
                exit_code = orchestrator.exit_code

            logger.info(
                "Unified Channel Monitor finalizado",
                extra={"exit_code": exit_code},
            )

    except Exception as exc:
        logger.error(
            "Falha ao lançar browser Playwright: %s",
            exc,
            extra={"error": str(exc)},
            exc_info=True,
        )
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
