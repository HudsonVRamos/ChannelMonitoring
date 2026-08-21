"""Entry point principal do módulo Audio & Subtitle Monitor.

Fornece a função run_audio_subtitle_monitoring como ponto de entrada
único para executar o monitoramento de áudio e legendas em múltiplos
canais via interação com a UI do player SKY+.

Integra logging estruturado via StructuredLogger para correlação
com o EventProbe do Player Discovery.

Requirements: 8.1, 8.5, 9.1
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.structured_logger import StructuredLogger

from .config import AudioSubtitleConfig
from .models import ConsolidatedReport
from .orchestrator import AudioSubtitleOrchestrator
from .report_generator import ReportGenerator

if TYPE_CHECKING:
    from playwright.async_api import Page

    from src.player_discovery.models.capability_map import CapabilityMap

# Logger estruturado para correlação com EventProbe do Player Discovery
_structured_logger = StructuredLogger(min_level="DEBUG")

STAGE_ID = "audio_subtitle_monitor"


async def run_audio_subtitle_monitoring(
    page: Page,
    capability_map: CapabilityMap,
    channels: list[str] | None = None,
    config: AudioSubtitleConfig | None = None,
) -> ConsolidatedReport:
    """Executa monitoramento completo de áudio e legendas em múltiplos canais.

    Entry point principal do módulo. Cria o orchestrator e executa
    o fluxo completo de testes de áudio e legendas, registrando
    todas as interações como eventos no log estruturado para
    correlação com o EventProbe do Player Discovery.

    Args:
        page: Instância do Playwright Page para interação com o browser.
        capability_map: CapabilityMap com estratégias de interação
            descobertas pelo Player Discovery.
        channels: Lista de URLs dos canais a serem testados.
            Se None, usa os canais do config.
        config: Configuração do módulo. Se None, cria config
            com defaults e carrega do ambiente.

    Returns:
        ConsolidatedReport com resultados de todos os canais testados.

    Req 8.1: Consultar CapabilityMap para interaction_strategy.
    Req 8.5: Registrar todas as interações como eventos no log.
    Req 9.1: Iterar pela lista de canais executando Monitoring_Session.
    """
    start_time = time.time()

    # Configuração padrão se não fornecida
    if config is None:
        config = AudioSubtitleConfig.from_env()

    # Registrar início no log estruturado (Req 8.5)
    _structured_logger.info(
        STAGE_ID,
        "Monitoramento de áudio e legendas iniciado.",
        config=config.to_dict(),
    )

    # Usar channels do argumento ou da config
    target_channels = channels or config.channels
    if not target_channels:
        _structured_logger.warning(
            STAGE_ID,
            "Nenhum canal configurado para monitoramento.",
        )
        # Retornar report vazio
        rg = ReportGenerator(config.output_dir)
        return rg.create_consolidated_report([])

    _structured_logger.info(
        STAGE_ID,
        "Iniciando Audio & Subtitle Monitor.",
        total_channels=len(target_channels),
        channels=target_channels,
    )

    # Registrar consulta ao CapabilityMap (Req 8.1, 8.5)
    _structured_logger.info(
        STAGE_ID,
        "Consultando CapabilityMap para interaction_strategy.",
        capability_map_available=capability_map is not None,
    )

    # Criar orchestrator e executar
    orchestrator = AudioSubtitleOrchestrator(
        page=page,
        capability_map=capability_map,
        config=config,
    )

    consolidated = await orchestrator.run(target_channels)

    # Registrar conclusão no log estruturado (Req 8.5)
    duration_ms = int((time.time() - start_time) * 1000)
    _structured_logger.info(
        STAGE_ID,
        "Audio & Subtitle Monitor finalizado.",
        total_channels=consolidated.total_channels,
        channels_pass=consolidated.channels_pass,
        channels_partial=consolidated.channels_partial,
        channels_fail=consolidated.channels_fail,
        total_duration_ms=duration_ms,
    )

    return consolidated
