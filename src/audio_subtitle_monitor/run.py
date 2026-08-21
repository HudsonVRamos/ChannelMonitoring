"""Runner do Audio & Subtitle Monitor — executável via terminal.

Uso (na EC2 via RDP):
    cd ~/ChannelMonitoring
    PYTHONPATH=. python3 -m src.audio_subtitle_monitor.run

O que faz:
1. Abre Chrome com o perfil autenticado (sessão SKY+)
2. Roda o Player Discovery primeiro (para obter o CapabilityMap)
3. Executa o Audio & Subtitle Monitor em todos os canais
4. Mostra logs no terminal e salva relatório JSON

Você vai ver o Chrome abrindo, navegando entre canais, clicando
no menu de settings, trocando áudio/legendas — tudo visualmente.
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

from .config import AudioSubtitleConfig
from .main import run_audio_subtitle_monitoring


# Canais padrão
DEFAULT_CHANNELS = [
    "https://www.skymais.com.br/player/live/CH0100000000124",
    "https://www.skymais.com.br/player/live/CH0100000000092",
    "https://www.skymais.com.br/player/live/CH0100000000093",
    "https://www.skymais.com.br/player/live/CH0100000000094",
    "https://www.skymais.com.br/player/live/CH0100000000096",
]


def _setup_logging() -> None:
    """Configura logging colorido para stdout."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


async def run() -> None:
    """Executa o Audio & Subtitle Monitor com Chrome visual."""
    chrome_profile = os.environ.get(
        "CHROME_PROFILE_DIR", "/data/chrome-profile"
    )
    output_dir = os.environ.get(
        "AUDIO_SUBTITLE_OUTPUT_DIR", "./output/audio_subtitle"
    )

    # Carregar canais (env ou default)
    channels_str = os.environ.get("AUDIO_SUBTITLE_CHANNELS", "")
    if channels_str:
        channels = [ch.strip() for ch in channels_str.split(",") if ch.strip()]
    else:
        channels = DEFAULT_CHANNELS

    # Config
    config = AudioSubtitleConfig(
        channels=channels,
        output_dir=output_dir,
    )

    # Se foi passado --single-channel, usar apenas 1
    if "--single" in sys.argv or "-1" in sys.argv:
        channels = channels[:1]
        logging.info("Modo single-channel: testando apenas %s", channels[0])

    logging.info("=" * 60)
    logging.info("  Audio & Subtitle Monitor — SKY+")
    logging.info("=" * 60)
    logging.info("  Canais: %d", len(channels))
    for ch in channels:
        logging.info("    - %s", ch)
    logging.info("  Output: %s", output_dir)
    logging.info("  Telemetria áudio: %.0fs por track", config.audio_telemetry_window_s)
    logging.info("  Timeout cue legenda: %.0fs", config.subtitle_cue_timeout_s)
    logging.info("=" * 60)
    logging.info("")

    # Criar diretório de output
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # Abrir Chrome com perfil persistente (mesmo da PoC)
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
        logging.info("Chrome iniciado com perfil: %s", chrome_profile)

        try:
            # Criar CapabilityMap mock básico para uso inicial
            # (O módulo funciona com heurísticas se capability não for encontrada)
            from unittest.mock import MagicMock
            capability_map = MagicMock()
            capability_map.get_interaction_strategy.return_value = None
            capability_map.get_capability.return_value = None
            capability_map.is_valid.return_value = True

            logging.info(
                "Iniciando monitoramento (sem Player Discovery — "
                "usando heurísticas para localizar Settings Dialog)..."
            )
            logging.info("")

            # Executar
            consolidated = await run_audio_subtitle_monitoring(
                page=page,
                capability_map=capability_map,
                channels=channels,
                config=config,
            )

            # Mostrar resultado
            logging.info("")
            logging.info("=" * 60)
            logging.info("  RESULTADO FINAL")
            logging.info("=" * 60)
            logging.info(
                "  Total canais: %d", consolidated.total_channels
            )
            logging.info(
                "  ✅ PASS: %d", consolidated.channels_pass
            )
            logging.info(
                "  ⚠️  PARTIAL: %d", consolidated.channels_partial
            )
            logging.info(
                "  ❌ FAIL: %d", consolidated.channels_fail
            )
            logging.info(
                "  Duração total: %.1fs",
                consolidated.total_duration_ms / 1000,
            )
            logging.info("=" * 60)

            # Salvar relatório consolidado
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            report_path = Path(output_dir) / f"consolidated_{timestamp}.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(consolidated.to_dict(), f, indent=2, ensure_ascii=False)
            logging.info("Relatório salvo em: %s", report_path)

            # Detalhe por canal
            for report in consolidated.channel_reports:
                logging.info("")
                logging.info(
                    "  Canal %s: %s",
                    report.channel_id,
                    report.overall_status.value,
                )
                if report.audio_results:
                    for r in report.audio_results:
                        logging.info(
                            "    🔊 Áudio '%s': %s",
                            r.track_name,
                            r.status.value,
                        )
                if report.subtitle_results:
                    for r in report.subtitle_results:
                        logging.info(
                            "    💬 Legenda '%s': %s",
                            r.track_name,
                            r.status.value,
                        )
                if report.errors:
                    for e in report.errors:
                        logging.info("    ⚠️  Erro: %s", e)

        except KeyboardInterrupt:
            logging.info("Interrompido pelo usuário (Ctrl+C).")
        except Exception as e:
            logging.error("Erro fatal: %s", str(e), exc_info=True)
        finally:
            await browser.close()
            logging.info("Chrome fechado.")


def main() -> None:
    """Entry point."""
    _setup_logging()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.info("Interrompido.")
        sys.exit(0)


if __name__ == "__main__":
    main()
