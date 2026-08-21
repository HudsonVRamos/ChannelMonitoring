# Implementation Plan: Player Discovery

## Overview

Implementação do sistema Player Discovery que substitui seletores fixos por um mecanismo de descoberta dinâmica e semântica das capacidades do player SKY+. O sistema segue a filosofia "discovery uma vez, reutilização por todos os canais" com três níveis de interação (API → DOM semântico → Visual Fallback).

A implementação é incremental: primeiro os data models e interfaces, depois o Discovery Engine, seguido pelas Probes de telemetria, o ChannelMonitor com rotação multi-canal, e finalmente a integração completa com escalação determinística.

## Tasks

- [x] 1. Configurar estrutura do projeto e data models
  - [x] 1.1 Criar estrutura de diretórios e módulo base
    - Criar `src/player_discovery/` com `__init__.py`
    - Criar subpacotes: `discovery/`, `probes/`, `interaction/`, `monitoring/`, `models/`
    - Adicionar dependências ao `requirements.txt` se necessário (dataclasses-json para serialização)
    - _Requirements: 2.1, 2.4, 2.5_

  - [x] 1.2 Implementar data models e enums
    - Criar `src/player_discovery/models/enums.py` com InteractionLevel, CapabilityStatus, ChannelHealthStatus, FunctionalTestStatus, AudioStatus, BufferStatus
    - Criar `src/player_discovery/models/capability.py` com InteractionStrategy, Capability, PlayerInfo, CapabilityMapData
    - Criar `src/player_discovery/models/telemetry.py` com VideoTelemetry, AudioTelemetry, SubtitleTelemetry, BufferTelemetry, PlayerEvent
    - Criar `src/player_discovery/models/results.py` com InteractionResult, FunctionalTestResult, HealthScores, ChannelReport
    - _Requirements: 2.1, 5.1, 6.1, 7.1, 8.1, 9.2_

  - [x] 1.3 Implementar CapabilityMap com serialização JSON
    - Criar `src/player_discovery/models/capability_map.py` com classe CapabilityMap
    - Implementar `get_capability()`, `get_interaction_strategy()`, `is_valid()`, `invalidate()`
    - Implementar `to_json()` e `from_json()` para serialização/deserialização
    - Garantir que o Capability Map é o único ponto de acesso para interação com o player
    - _Requirements: 2.1, 2.4, 2.5, 3.3_

  - [x] 1.4 Write property test — Serialização round-trip do Capability Map
    - **Property 1: Serialização round-trip do Capability Map**
    - **Validates: Requirements 2.5**

  - [x] 1.5 Write property test — Estrutura mínima obrigatória do Capability Map
    - **Property 3: Capability Map contém estrutura mínima obrigatória**
    - **Validates: Requirements 1.7, 2.1**

  - [x] 1.6 Write property test — Classificação de confidence determinística
    - **Property 2: Classificação de confidence é determinística**
    - **Validates: Requirements 2.2, 2.3**

- [x] 2. Implementar Discovery Engine
  - [x] 2.1 Implementar análise de DOM semântico
    - Criar `src/player_discovery/discovery/dom_analyzer.py`
    - Implementar busca por role, aria-label, aria-haspopup, title, textContent, data-*, tabindex
    - Retornar lista de DOMEvidence sem utilizar seletores CSS fixos, IDs específicos ou classes CSS
    - _Requirements: 1.2, 1.5, 12.1_

  - [x] 2.2 Implementar análise de JavaScript APIs
    - Criar `src/player_discovery/discovery/js_analyzer.py`
    - Implementar investigação de objetos globais: player instance, library, version
    - Descobrir dinamicamente track APIs, quality APIs, audio APIs, subtitle APIs, event APIs
    - _Requirements: 1.3_

  - [x] 2.3 Implementar análise de Browser APIs
    - Criar `src/player_discovery/discovery/browser_api_analyzer.py`
    - Verificar HTMLMediaElement, TextTrackList, AudioTrackList, MediaCapabilities, Media Session, Performance APIs
    - _Requirements: 1.4_

  - [x] 2.4 Implementar análise de CSS (auxiliar)
    - Criar `src/player_discovery/discovery/css_analyzer.py`
    - Coletar evidência auxiliar: display, visibility, opacity, pointer-events, estados active/selected
    - CSS isolado nunca deve produzir alta confidence
    - _Requirements: 1.5_

  - [x] 2.5 Write property test — CSS isolado nunca produz alta confidence
    - **Property 4: CSS isolado nunca produz alta confidence**
    - **Validates: Requirements 1.5**

  - [x] 2.6 Implementar testes comportamentais
    - Criar `src/player_discovery/discovery/behavioral_tester.py`
    - Implementar teste comportamental seguro: interação controlada → observação → confirmação
    - Confirmar função antes de classificar capability como disponível com alta confidence
    - _Requirements: 1.6_

  - [x] 2.7 Implementar DiscoveryEngine principal
    - Criar `src/player_discovery/discovery/engine.py` com classe DiscoveryEngine
    - Implementar `discover()` que orquestra DOM + JS + Browser APIs + CSS + behavioral tests
    - Implementar `validate_map()` para validar Capability Map existente
    - Implementar `rediscover()` para re-execução completa
    - Implementar cache: rejeitar discovery se mapa válido em memória
    - Timeout de 60s no discovery, retry com backoff exponencial (max 3 tentativas)
    - _Requirements: 1.1, 1.6, 1.7, 3.2, 4.3, 4.5_

  - [x] 2.8 Write property test — Idempotência do cache
    - **Property 5: Idempotência do cache — discovery válido rejeita re-execução**
    - **Validates: Requirements 3.2**

- [x] 3. Checkpoint — Discovery Engine
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implementar InteractionManager e MutationObserver
  - [x] 4.1 Implementar InteractionManager com três níveis
    - Criar `src/player_discovery/interaction/manager.py` com classe InteractionManager
    - Implementar `execute()` com hierarquia: API (Nível 1) → DOM semântico (Nível 2) → Visual fallback (Nível 3)
    - Implementar `_execute_api()`, `_execute_semantic_dom()`, `_execute_visual_fallback()`
    - Rejeitar qualquer interação baseada em coordenadas fixas ou índice posicional
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 4.2 Write property test — Hierarquia de interação e fallback
    - **Property 19: Hierarquia de interação — strategies ordenadas e fallback correto**
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [x] 4.3 Write property test — Rejeição de coordenadas fixas
    - **Property 20: Rejeição de coordenadas fixas e índices posicionais**
    - **Validates: Requirements 12.4**

  - [x] 4.4 Implementar MutationObserverWatcher
    - Criar `src/player_discovery/discovery/mutation_watcher.py` com classe MutationObserverWatcher
    - Implementar `start()` com MutationObserver no browser via Playwright
    - Implementar debounce/coalescing para agrupar mutações em janela configurável
    - Classificar mudanças como estruturais (invalidam mapa) vs cosméticas (mantêm mapa)
    - Implementar callback `on_structural_change()` para notificar DiscoveryEngine
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 4.5 Write property test — Debounce de mutações
    - **Property 6: Debounce de mutações agrupa dentro da janela**
    - **Validates: Requirements 4.1**

  - [x] 4.6 Write property test — Classificação estrutural vs cosmética
    - **Property 7: Classificação de mudanças — estrutural vs cosmética**
    - **Validates: Requirements 4.3, 4.4**

- [x] 5. Implementar Probes de telemetria
  - [x] 5.1 Implementar VideoProbe
    - Criar `src/player_discovery/probes/video_probe.py` com classe VideoProbe
    - Implementar `collect()` via page.evaluate() a cada 2 segundos
    - Coletar: currentTime, duration, readyState, paused, playing, ended, seeking, playbackRate, networkState, buffered, videoWidth, videoHeight, error
    - Coletar getVideoPlaybackQuality(): totalVideoFrames, droppedVideoFrames, drop_rate, FPS
    - Detectar freeze: currentTime não avança por 5s com paused=false
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 5.2 Write property test — Classificação de freeze
    - **Property 8: Classificação de freeze por stalled currentTime**
    - **Validates: Requirements 5.5**

  - [x] 5.3 Write property test — Cálculo de drop_rate
    - **Property 9: Cálculo de drop_rate é correto**
    - **Validates: Requirements 5.2**

  - [x] 5.4 Implementar AudioProbe
    - Criar `src/player_discovery/probes/audio_probe.py` com classe AudioProbe
    - Implementar `collect()` via Web Audio API a cada 2 segundos: RMS, peak, silence_duration, muted
    - Implementar classificação: NO_AUDIO (RMS < 0.01 por 10s), AUDIO_LOW (RMS 0.01-0.05 por 10s)
    - Implementar `run_functional_test()` para mute/unmute e audio_selection
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 5.5 Write property test — Classificação de áudio por RMS
    - **Property 10: Classificação de status de áudio por RMS**
    - **Validates: Requirements 6.2, 6.3**

  - [x] 5.6 Implementar SubtitleProbe
    - Criar `src/player_discovery/probes/subtitle_probe.py` com classe SubtitleProbe
    - Implementar `collect()` via TextTrack API: tracks, language, label, kind, mode, activeCues
    - Implementar `run_functional_test()` para subtitle_selection
    - Classificar SUBTITLE_UNAVAILABLE quando nenhuma track encontrada
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 5.7 Implementar BufferProbe
    - Criar `src/player_discovery/probes/buffer_probe.py` com classe BufferProbe
    - Implementar `collect()` a cada 2 segundos: buffered_start, buffered_end, buffer_ahead
    - Registrar eventos waiting/stalled: waiting_count, waiting_total_ms, longest_wait_ms
    - Classificar BUFFER_LOW (buffer_ahead < 2s) e BUFFERING_FREQUENT (>3 waiting em 60s)
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 5.8 Write property test — Classificação de buffer
    - **Property 11: Classificação de status de buffer**
    - **Validates: Requirements 8.3, 8.4**

  - [x] 5.9 Write property test — Cálculo de métricas de waiting
    - **Property 12: Cálculo de métricas de waiting events**
    - **Validates: Requirements 8.2**

  - [x] 5.10 Implementar EventProbe
    - Criar `src/player_discovery/probes/event_probe.py` com classe EventProbe
    - Implementar `attach_listeners()` para todos os eventos HTMLMediaElement
    - Implementar `get_events()` e `clear_events()`
    - Manter janela de retenção de 5 minutos por canal
    - Registrar: event_type, timestamp ISO 8601, currentTime, dados adicionais
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 5.11 Write property test — Retenção de eventos na janela de 5 minutos
    - **Property 13: Retenção de eventos na janela de 5 minutos**
    - **Validates: Requirements 9.4**

  - [x] 5.12 Write property test — Campos obrigatórios de eventos
    - **Property 14: Registro de eventos contém campos obrigatórios**
    - **Validates: Requirements 9.2**

- [x] 6. Checkpoint — Probes de telemetria
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implementar ChannelMonitor e rotação multi-canal
  - [x] 7.1 Implementar HealthScoreCalculator
    - Criar `src/player_discovery/monitoring/health_score.py` com classe HealthScoreCalculator
    - Implementar `calculate_video_health()` com pesos: Playback 20%, Buffer 15%, Dropped Frames 15%, Freeze 10%, FPS 10%, Resolution 10%, DRM 20%
    - Implementar `calculate_audio_health()` com pesos: Audio present 40%, RMS 20%, Peak 10%, Silence 20%, Track 10%
    - Implementar `calculate_functional_health()` com pesos iguais 25% por capability
    - Scores bounded em [0, 100]
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 7.2 Write property test — Health Scores bounded e ponderados
    - **Property 21: Health Scores são bounded e seguem pesos definidos**
    - **Validates: Requirements 13.1, 13.2, 13.3**

  - [x] 7.3 Implementar ChannelMonitor com rotação
    - Criar `src/player_discovery/monitoring/channel_monitor.py` com classe ChannelMonitor
    - Implementar `start_rotation()` com lista de canais
    - Implementar `monitor_channel()` que ativa todas as probes durante período de observação
    - Consolidar resultados em ChannelReport por canal
    - Reutilizar mesmo Capability Map para todos os canais
    - _Requirements: 10.1, 10.2, 10.3, 3.1, 3.4_

  - [x] 7.4 Implementar lógica de invalidação por falhas consecutivas
    - Implementar acumulação de falhas por canal no ChannelMonitor
    - Invalidar Capability Map somente com N falhas consecutivas (threshold configurável, padrão: 3)
    - Falhas em canais não-consecutivos não acumulam
    - Ao invalidar, pausar rotação, executar re-discovery, retomar
    - _Requirements: 10.4, 4.3, 4.5_

  - [x] 7.5 Write property test — Threshold de invalidação por falhas consecutivas
    - **Property 15: Invalidação do Capability Map por threshold de falhas consecutivas**
    - **Validates: Requirements 10.4**

  - [x] 7.6 Implementar testes funcionais periódicos
    - Implementar `run_functional_tests()` no ChannelMonitor
    - Executar a cada N rotações (configurável, padrão: 5)
    - Ordem de execução: play/pause → mute/unmute → audio_selection → subtitle_selection
    - Sinalizar validação do Capability Map quando capability com confidence >= 0.9 falha
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 7.7 Write property test — Frequência de testes funcionais
    - **Property 16: Frequência de testes funcionais segue configuração**
    - **Validates: Requirements 11.1**

  - [x] 7.8 Write property test — Ordenação por impacto
    - **Property 17: Ordenação de testes funcionais por impacto**
    - **Validates: Requirements 11.2**

  - [x] 7.9 Write property test — Sinalização de alta confidence
    - **Property 18: Sinalização de validação quando capability de alta confidence falha**
    - **Validates: Requirements 11.4**

- [x] 8. Implementar pipeline de escalação determinística
  - [x] 8.1 Implementar lógica de escalação no ChannelMonitor
    - Implementar classificação: HEALTHY (sem captura adicional), SUSPECT (capturar frames + OpenCV), DEGRADED/CRITICAL (OpenCV + Bedrock)
    - Canal HEALTHY: capturar apenas 1 frame de validação por ciclo
    - Canal SUSPECT: capturar frames adicionais e acionar OpenCV
    - Acionar Bedrock somente se OpenCV confirma anomalia
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [x] 8.2 Write property test — Pipeline de escalação determinística
    - **Property 22: Pipeline de escalação determinística**
    - **Validates: Requirements 14.1, 14.2, 14.4**

  - [x] 8.3 Write property test — Canal HEALTHY limita captura
    - **Property 23: Canal HEALTHY limita captura a 1 frame por ciclo**
    - **Validates: Requirements 14.5**

- [x] 9. Checkpoint — ChannelMonitor e escalação
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integração final e wiring
  - [x] 10.1 Integrar todos os componentes no fluxo principal
    - Criar `src/player_discovery/main.py` como entry point
    - Orquestrar: DiscoveryEngine → CapabilityMap → MutationObserverWatcher → ChannelMonitor → Probes → HealthScore → Escalação
    - Conectar com módulos existentes: FrameCapturer, OpenCVAnalyzer, BedrockClient
    - Configurar logging estruturado via StructuredLogger existente
    - _Requirements: 1.1, 2.4, 3.1, 10.1, 14.1_

  - [x] 10.2 Implementar configuração centralizada
    - Criar `src/player_discovery/config.py` com dataclass de configuração
    - Parâmetros: discovery_timeout_s, telemetry_interval_s, observation_period_s, functional_test_interval, invalidation_threshold, debounce_window_ms, event_retention_s, buffer_low_threshold_s
    - Carregar de variáveis de ambiente ou defaults
    - _Requirements: 4.1, 8.4, 9.4, 10.4, 11.1_

  - [x] 10.3 Write integration tests
    - Testar fluxo completo: discovery → capabilities → rotação de 3 canais
    - Testar re-discovery acionado por MutationObserver
    - Testar escalação: telemetria suspeita → OpenCV → Bedrock
    - Testar functional tests com mock de Playwright Page
    - _Requirements: 1.1, 4.3, 10.1, 14.1_

- [x] 11. Final checkpoint — Integração completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Property tests validam propriedades universais de correção definidas no design
- Unit tests validam exemplos específicos e edge cases
- O projeto usa Hypothesis (já configurado em `requirements.txt`) para property-based testing
- Playwright é usado para automação de browser (já configurado)
- Linguagem de implementação: Python 3.10+ com type hints e dataclasses

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["1.4", "1.5", "1.6"] },
    { "id": 4, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 5, "tasks": ["2.5", "2.6"] },
    { "id": 6, "tasks": ["2.7"] },
    { "id": 7, "tasks": ["2.8"] },
    { "id": 8, "tasks": ["4.1", "4.4"] },
    { "id": 9, "tasks": ["4.2", "4.3", "4.5", "4.6"] },
    { "id": 10, "tasks": ["5.1", "5.4", "5.6", "5.7", "5.10"] },
    { "id": 11, "tasks": ["5.2", "5.3", "5.5", "5.8", "5.9", "5.11", "5.12"] },
    { "id": 12, "tasks": ["7.1"] },
    { "id": 13, "tasks": ["7.2", "7.3"] },
    { "id": 14, "tasks": ["7.4", "7.6"] },
    { "id": 15, "tasks": ["7.5", "7.7", "7.8", "7.9"] },
    { "id": 16, "tasks": ["8.1"] },
    { "id": 17, "tasks": ["8.2", "8.3"] },
    { "id": 18, "tasks": ["10.1", "10.2"] },
    { "id": 19, "tasks": ["10.3"] }
  ]
}
```
