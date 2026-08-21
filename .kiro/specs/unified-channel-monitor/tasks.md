# Implementation Plan: Unified Channel Monitor

## Overview

Implementação do módulo `unified_channel_monitor` que consolida player_discovery e audio_subtitle_monitor em um orquestrador unificado. A implementação segue uma abordagem bottom-up: data models e config primeiro, depois componentes individuais, e por último a orquestração e CLI. Testes de propriedade validam invariantes em cada camada.

## Tasks

- [x] 1. Configuração do projeto e data models
  - [x] 1.1 Criar estrutura de diretórios e módulo base
    - Criar `src/unified_channel_monitor/__init__.py`
    - Criar `tests/unified_channel_monitor/__init__.py` e `conftest.py` com fixtures compartilhados (mock Page, mock CapabilityMap)
    - _Requirements: 1.1_

  - [x] 1.2 Implementar data models (`src/unified_channel_monitor/models.py`)
    - Implementar dataclasses: `TelemetrySample`, `TelemetrySummary`, `FreezeEvent`, `DeferredEscalation`, `EscalationResult`, `AudioTrackResult`, `SubtitleTrackResult`, `UnifiedChannelReport`, `ConsolidatedReport`, `ChannelSessionStatus` (Enum)
    - Incluir type hints completos e defaults onde aplicável
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.6_

  - [x] 1.3 Implementar `UnifiedMonitorConfig` (`src/unified_channel_monitor/config.py`)
    - Implementar dataclass com todos os parâmetros configuráveis e defaults
    - Implementar `from_env()` com parsing de env vars com prefixo `UNIFIED_MONITOR_`
    - Tratar valores inválidos (non-numeric) retornando default e logando warning
    - Parsing de `UNIFIED_MONITOR_CHANNELS` como lista de URLs comma-separated com trim e remoção de entradas vazias
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 1.4_

  - [x] 1.4 Escrever property test para parsing de configuração (Property 1)
    - **Property 1: Configuration parsing round-trip**
    - **Validates: Requirements 1.4, 10.1, 10.3**

  - [x] 1.5 Escrever property test para robustez de configuração (Property 2)
    - **Property 2: Configuration robustness against invalid values**
    - **Validates: Requirements 10.4**

- [x] 2. Checkpoint - Verificar que config e models estão corretos
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implementar VideoTelemetryCollector
  - [x] 3.1 Implementar `VideoTelemetryCollector` (`src/unified_channel_monitor/video_telemetry.py`)
    - Implementar `start(page, interval_s)` que cria asyncio.Task coletando samples via `page.evaluate()`
    - Implementar `stop()` que cancela a task e retorna `TelemetrySummary`
    - Implementar detecção de freeze: 3 amostras consecutivas com `total_frames_decoded` sem avanço → `FreezeEvent`
    - Implementar `annotate_current_sample(context)` para correlacionar switches com amostras
    - Implementar `get_deferred_escalations()` para retornar escalações pendentes
    - Implementar cálculo de `TelemetrySummary` com average FPS, buffer, health classification
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 3.2 Escrever property test para detecção de freeze (Property 5)
    - **Property 5: Freeze detection on consecutive non-advancing samples**
    - **Validates: Requirements 4.4**

  - [x] 3.3 Escrever property test para anotação de telemetria (Property 11)
    - **Property 11: Telemetry annotation correlates freeze with track switch**
    - **Validates: Requirements 4.5, 8.5**

- [x] 4. Implementar AudioTrackTester e SubtitleTrackTester
  - [x] 4.1 Implementar `AudioTrackTester` (`src/unified_channel_monitor/audio_tester.py`)
    - Wrapper sobre `AudioMonitor` e `SettingsDialogManager` existentes
    - Implementar `test_all_tracks()` que descobre tracks via Settings Dialog, seleciona cada um, valida switch via Shaka API, coleta RMS telemetry
    - Integrar com `VideoTelemetryCollector.annotate_current_sample()` durante switches
    - Marcar track como FAIL com reason "switch_timeout" se validação exceder timeout
    - Restaurar track original ao final
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 4.2 Implementar `SubtitleTrackTester` (`src/unified_channel_monitor/subtitle_tester.py`)
    - Wrapper sobre `SubtitleMonitor` e `SettingsDialogManager` existentes
    - Implementar `test_all_tracks()` que descobre tracks, seleciona cada um, valida switch, monitora cues
    - Marcar track como FAIL com reason "no_cue_received" se cue não aparecer dentro do timeout
    - Marcar ALL tracks como SKIP com reason "dialog_unavailable" se Settings Dialog falhar ao abrir
    - Restaurar configuração inicial ao final
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 4.3 Escrever property test para status de falha de tracks (Property 6)
    - **Property 6: Track test failure produces correct status and reason**
    - **Validates: Requirements 5.5, 6.4**

  - [x] 4.4 Escrever property test para dialog unavailable (Property 7)
    - **Property 7: Dialog unavailable marks all tracks as SKIP**
    - **Validates: Requirements 6.6**

- [x] 5. Checkpoint - Verificar componentes de coleta e teste
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implementar EscalationManager
  - [x] 6.1 Implementar `EscalationManager` (`src/unified_channel_monitor/escalation.py`)
    - Implementar `defer_escalation(trigger)` que enfileira para processamento posterior
    - Implementar `process_deferred()` que executa frame capture + OpenCV + Bedrock para cada trigger pendente
    - Implementar `escalate_immediate(trigger)` para quando não há testes de track ativos
    - Garantir que escalações deferidas NÃO executam DOM interactions durante track tests
    - Anotar escalações com contexto de track switch quando aplicável
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 6.2 Escrever property test para deferimento de escalação (Property 10)
    - **Property 10: Escalation is deferred during track testing**
    - **Validates: Requirements 7.3, 7.4, 7.5**

- [x] 7. Implementar ReportGenerator
  - [x] 7.1 Implementar `UnifiedReportGenerator` (`src/unified_channel_monitor/report_generator.py`)
    - Implementar `create_channel_report()` que agrega video summary + audio results + subtitle results + escalations
    - Implementar `create_consolidated_report()` que agrega channel reports com contagens por status
    - Implementar `persist_report()` que serializa para JSON e salva no output directory com filename timestamped
    - Gerar `session_id` (UUID) por Channel Session para correlação
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 7.2 Escrever property test para completude do relatório (Property 8)
    - **Property 8: Unified report completeness**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

  - [x] 7.3 Escrever property test para agregação consolidada (Property 9)
    - **Property 9: Consolidated report aggregation is correct**
    - **Validates: Requirements 8.6**

- [x] 8. Checkpoint - Verificar escalation e report generation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implementar UnifiedOrchestrator
  - [x] 9.1 Implementar `UnifiedOrchestrator` (`src/unified_channel_monitor/orchestrator.py`)
    - Implementar `run_single_rotation(channels)` com sequência: navigate → wait playback → discovery (if needed) → start telemetry → test audio → verify playback → test subtitles → stop telemetry → process escalations → generate report
    - Implementar reuso de CapabilityMap: discovery executa apenas na primeira vez ou após invalidação
    - Implementar invalidação de CapabilityMap após N falhas consecutivas (configurável)
    - Implementar fail-forward: exceção em um canal → status ERROR/UNREACHABLE → próximo canal
    - Implementar playback recovery entre audio e subtitle tests
    - Implementar `run_continuous(channels)` para modo loop
    - Implementar structured logging com `session_id` em todas as fases
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 9.1, 9.2, 9.3, 9.4, 9.5, 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 9.2 Escrever property test para processamento sequencial com resiliência (Property 3)
    - **Property 3: Sequential processing with error resilience**
    - **Validates: Requirements 2.1, 2.3, 2.4**

  - [x] 9.3 Escrever property test para discovery única (Property 4)
    - **Property 4: Discovery executes once while CapabilityMap is valid**
    - **Validates: Requirements 3.2, 3.3**

- [x] 10. Implementar Graceful Shutdown
  - [x] 10.1 Implementar shutdown graceful no `UnifiedOrchestrator`
    - Registrar handler para SIGINT via `asyncio.get_event_loop().add_signal_handler()`
    - Setar flag `_shutting_down = True` ao receber sinal
    - Verificar flag entre Channel Sessions e parar loop
    - Dar timeout de 10s para sessão em andamento completar
    - Persistir partial `ConsolidatedReport` com resultados coletados até o momento
    - Gerar partial `UnifiedChannelReport` para canal interrompido com dados parciais
    - Fechar browser context do Playwright corretamente
    - Exit code 0 (clean shutdown) vs 1 (error)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 10.2 Escrever property test para preservação de dados no shutdown (Property 12)
    - **Property 12: Shutdown preserves all collected data**
    - **Validates: Requirements 12.2, 12.4**

- [x] 11. Implementar CLI Entry Point
  - [x] 11.1 Implementar CLI (`src/unified_channel_monitor/run.py`)
    - Implementar `main()` async que carrega config, lança Playwright persistent context, cria orquestrador
    - Parsear `--continuous` de `sys.argv`
    - Registrar signal handler
    - Executar `run_single_rotation()` ou `run_continuous()` conforme flag
    - Implementar `if __name__ == "__main__"` com `asyncio.run(main())`
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6_

- [x] 12. Integração final e wiring
  - [x] 12.1 Wiring completo e integration tests
    - Verificar que todos os componentes estão importados corretamente no `__init__.py`
    - Criar integration test com mock Page que executa rotação de 2-3 canais (mocks para navigate, evaluate, click)
    - Verificar que JSON report é gerado corretamente no diretório de output
    - Validar sequência de fases no orchestrator via mocks
    - _Requirements: 9.1, 8.7, 2.1_

- [x] 13. Final checkpoint - Verificar tudo integrado
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requirements específicos para rastreabilidade
- Checkpoints garantem validação incremental entre fases
- Property tests validam propriedades universais de corretude (Hypothesis com `@settings(max_examples=100)`)
- Unit tests validam exemplos específicos e edge cases
- Os componentes existentes (`DiscoveryEngine`, `VideoProbe`, `AudioMonitor`, `SubtitleMonitor`, `SettingsDialogManager`, `FrameCapturer`, `OpenCVAnalyzer`, `BedrockClient`) são reutilizados via composição
- O projeto já utiliza Hypothesis (diretório `.hypothesis/` presente) — não é necessário instalar

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3", "4.4", "6.1", "7.1"] },
    { "id": 5, "tasks": ["6.2", "7.2", "7.3"] },
    { "id": 6, "tasks": ["9.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 8, "tasks": ["10.2", "11.1"] },
    { "id": 9, "tasks": ["12.1"] }
  ]
}
```
