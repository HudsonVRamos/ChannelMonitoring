# Implementation Plan: Audio & Subtitle Monitoring via UI

## Overview

Implementação do módulo de monitoramento de áudio e legendas que interage com a UI do player SKY+ via Playwright, valida mudanças via Shaka Player API, coleta telemetria de áudio via Web Audio API, monitora cues de legenda via TextTrack API e gera relatórios consolidados por canal.

Módulo localizado em `src/audio_subtitle_monitor/` com testes em `tests/test_audio_subtitle_monitor/`.

## Tasks

- [x] 1. Estrutura do módulo e data models
  - [x] 1.1 Criar estrutura de diretórios e módulo base
    - Criar `src/audio_subtitle_monitor/__init__.py` com exports públicos
    - Criar `src/audio_subtitle_monitor/config.py` com a dataclass `AudioSubtitleConfig` contendo todos os parâmetros configuráveis (timeouts, thresholds, channels, output_dir)
    - Criar `tests/test_audio_subtitle_monitor/__init__.py` e `tests/test_audio_subtitle_monitor/conftest.py` com fixtures compartilhadas (mock page, mock capability_map, mock interaction_manager)
    - _Requirements: 8.1, 9.1_

  - [x] 1.2 Implementar data models e enums
    - Criar `src/audio_subtitle_monitor/models.py` com todas as dataclasses: `TrackTestStatus` (Enum), `OverallStatus` (Enum), `TrackOption`, `ValidationResult`, `AudioSample`, `AudioTelemetryResult`, `CueResult`, `TrackTestResult`, `ChannelTestReport`, `ConsolidatedReport`
    - Usar `@dataclass` com type hints completos (Python 3.10+)
    - Incluir serialização JSON nos reports (`dataclasses_json` ou método `to_dict`)
    - _Requirements: 7.1, 7.4, 3.3_

  - [x] 1.3 Escrever property tests para os data models
    - **Property 10: Report Serialization Completeness** — Verificar que para qualquer `ChannelTestReport` válido, a serialização JSON contém todas as chaves obrigatórias
    - **Property 11: Report Filename Format** — Verificar que para qualquer channel_id e timestamp, o filename segue o padrão `audio_subtitle_report_{channel_id}_{timestamp}.json`
    - **Validates: Requirements 7.1, 7.3, 7.4**

- [x] 2. Implementar SettingsDialogManager
  - [x] 2.1 Implementar abertura e fechamento do Settings Dialog
    - Criar `src/audio_subtitle_monitor/settings_dialog_manager.py`
    - Implementar `open_dialog()`: hover no player para exibir controles + clique no Settings_Icon + aguardar dialog visível (5s timeout)
    - Implementar `close_dialog()`: pressionar Escape ou clicar fora do dialog
    - Implementar `ensure_dialog_open()`: verificar visibilidade e reabrir se necessário
    - Implementar `_show_player_controls()`: mover cursor sobre o player
    - Implementar `_find_settings_icon()`: localizar via estratégia do CapabilityMap (semantic_dom, visual_fallback, ou heurísticas)
    - Implementar retry: fechar dialog, aguardar 2s, reabrir 1x antes de classificar como FAIL
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 6.1, 6.4, 6.5, 8.1, 8.2, 8.3, 8.4_

  - [x] 2.2 Implementar descoberta de opções de áudio e legendas
    - Implementar `discover_audio_options()`: coletar itens da seção "IDIOMA ALTERNATIVO", identificar opção selecionada
    - Implementar `discover_subtitle_options()`: coletar itens da seção "LEGENDAS", identificar opção selecionada
    - Implementar `select_option(section, option_text)`: clicar em opção dentro de uma seção
    - Implementar `get_selected_option(section)`: retornar texto da opção ativa
    - Gerenciar estado do dialog: detectar se fecha automaticamente após seleção e reabrir quando necessário
    - _Requirements: 1.3, 2.1, 2.2, 4.1, 4.2, 6.2, 6.3_

  - [x] 2.3 Escrever property tests para SettingsDialogManager
    - **Property 1: Option Discovery Completeness and Selection** — Para qualquer DOM com N opções e uma selecionada, a função retorna N `TrackOption` com exatamente uma `is_selected=True`
    - **Property 6: Subtitle "Desativadas" Filtering** — Para qualquer lista contendo "Desativadas", a iteração exclui esses itens corretamente
    - **Validates: Requirements 2.1, 2.2, 4.1, 4.2, 5.1**

  - [x] 2.4 Escrever unit tests para SettingsDialogManager
    - Testar abertura/fechamento do dialog com mock Playwright
    - Testar hover para exibir controles
    - Testar retry após dialog congelado
    - Testar quando Settings_Icon não é encontrado
    - Testar dialog que fecha automaticamente após seleção
    - Testar dialog que permanece aberto após seleção
    - _Requirements: 1.1, 1.2, 1.4, 6.1, 6.2, 6.3, 6.4_

- [x] 3. Implementar AudioMonitor
  - [x] 3.1 Implementar validação de track switch e telemetria de áudio
    - Criar `src/audio_subtitle_monitor/audio_monitor.py`
    - Implementar `validate_track_switch(expected_language, timeout_s)`: consultar `window.player.getAudioTracks()` via `page.evaluate()` e verificar track ativo
    - Implementar `get_active_tracks()`: consultar Shaka API
    - Implementar `_init_audio_context()`: inicializar Web Audio API AudioContext no browser
    - Implementar `_collect_single_sample()`: coletar amostra RMS/peak via Web Audio API
    - Implementar `collect_telemetry(duration_s, sample_interval_s)`: coletar amostras durante janela de 30s, calcular agregações (rms_avg, rms_min, rms_max, audio_present_ratio, silence_duration)
    - Implementar `classify_result(telemetry)`: PASS se audio_present_ratio >= 0.80, FAIL caso contrário
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 10.1_

  - [x] 3.2 Escrever property tests para AudioMonitor
    - **Property 3: Track Switch Validation** — Para qualquer language e resposta da API, validate_track_switch retorna success=True sse existe track com language correspondente marcado como active
    - **Property 4: Audio Telemetry Aggregation** — Para qualquer lista não-vazia de amostras RMS (floats entre 0.0 e 1.0), a agregação produz média, min, max e ratio corretos
    - **Property 5: Audio Result Classification** — Para qualquer AudioTelemetryResult, classificação retorna PASS se ratio >= 0.80 e FAIL se ratio < 0.80
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 10.1**

  - [x] 3.3 Escrever unit tests para AudioMonitor
    - Testar validate_track_switch com track encontrado/não encontrado
    - Testar collect_telemetry com amostras mockadas
    - Testar classify_result com boundary cases (exatamente 80%, 79%, 81%)
    - Testar cenário onde AudioContext não inicializa
    - Testar canal com apenas 1 track de áudio
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 4. Implementar SubtitleMonitor
  - [x] 4.1 Implementar validação de track switch e monitoramento de cues
    - Criar `src/audio_subtitle_monitor/subtitle_monitor.py`
    - Implementar `validate_track_switch(expected_language, timeout_s)`: consultar `window.player.getTextTracks()` via `page.evaluate()` e verificar track ativo
    - Implementar `get_active_tracks()`: consultar Shaka API para text tracks
    - Implementar `wait_for_active_cue(timeout_s, poll_interval_s)`: polling de activeCues na track ativa durante até 15s, retornar CueResult com cue_text truncado a 50 chars
    - Filtrar tracks "Desativadas" da lista de iteração
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 10.2_

  - [x] 4.2 Escrever property tests para SubtitleMonitor
    - **Property 3: Track Switch Validation** (legendas) — Mesma lógica do áudio aplicada a getTextTracks()
    - **Property 7: Cue Evidence Formatting** — Para qualquer cue detectada, evidence contém cue_text <= 50 chars, track_name correto, e time_to_first_cue_ms >= 0
    - **Validates: Requirements 5.2, 5.4, 10.2**

  - [x] 4.3 Escrever unit tests para SubtitleMonitor
    - Testar validate_track_switch com track encontrado/não encontrado
    - Testar wait_for_active_cue com cue encontrada rapidamente
    - Testar wait_for_active_cue com timeout (sem cues em 15s)
    - Testar truncamento de cue_text > 50 caracteres
    - Testar cue com texto vazio
    - Testar lista de legendas onde todas são "Desativadas"
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 5. Checkpoint - Verificar componentes individuais
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implementar ReportGenerator
  - [x] 6.1 Implementar geração de relatórios por canal e consolidado
    - Criar `src/audio_subtitle_monitor/report_generator.py`
    - Implementar `create_channel_report(channel_url, audio_results, subtitle_results, duration_ms)`: criar ChannelTestReport com overall_status calculado
    - Implementar `_calculate_overall_status(results)`: PASS se todos PASS, FAIL se todos FAIL/TIMEOUT, PARTIAL se misto
    - Implementar `create_consolidated_report(channel_reports)`: criar ConsolidatedReport com contadores (pass, partial, fail)
    - Implementar `save_channel_report(report)`: serializar JSON e salvar no output_dir com formato `audio_subtitle_report_{channel_id}_{timestamp}.json`
    - Garantir formatação filesystem-safe do timestamp no nome do arquivo
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 9.4_

  - [x] 6.2 Escrever property tests para ReportGenerator
    - **Property 9: Overall Status Calculation** — Para qualquer lista de TrackTestResults, overall_status é PASS quando todos PASS, FAIL quando todos FAIL/TIMEOUT, PARTIAL em casos mistos
    - **Property 12: Consolidated Report Aggregation** — Para qualquer lista de ChannelTestReports, total_channels = len(lista), channels_pass/partial/fail contam corretamente
    - **Validates: Requirements 7.2, 9.4**

  - [x] 6.3 Escrever unit tests para ReportGenerator
    - Testar cálculo de overall_status com combinações: todos PASS, todos FAIL, misto PASS+FAIL, misto PASS+TIMEOUT
    - Testar serialização JSON contém todas as chaves obrigatórias
    - Testar geração de filename com channel_id contendo caracteres especiais
    - Testar save_channel_report cria arquivo no diretório correto
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 7. Implementar AudioSubtitleOrchestrator
  - [x] 7.1 Implementar orquestração multi-canal
    - Criar `src/audio_subtitle_monitor/orchestrator.py`
    - Implementar `__init__()`: receber page, capability_map, config; instanciar SettingsDialogManager, AudioMonitor, SubtitleMonitor, ReportGenerator
    - Implementar `run(channels)`: iterar sequencialmente pela lista de canais, executar run_channel para cada, coletar resultados e gerar ConsolidatedReport
    - Implementar `_navigate_to_channel(url)`: navegar e aguardar DOM carregado
    - Implementar `_wait_for_playback(timeout_s)`: polling de currentTime avançando até 30s
    - Tratamento de erro: se canal falha com exceção inesperada, registrar erro e avançar para próximo canal
    - _Requirements: 9.1, 9.2, 9.3, 9.5_

  - [x] 7.2 Implementar fluxo de Monitoring_Session por canal
    - Implementar `run_channel(channel_url)`: fluxo completo de um canal
    - Sequência: navegar → aguardar playback → abrir dialog → descobrir opções áudio → descobrir opções legenda → testar cada audio track (selecionar via UI + validar API + coletar telemetria 30s) → testar cada subtitle track (selecionar via UI + validar API + aguardar cue 15s) → restaurar tracks iniciais → fechar dialog → gerar ChannelTestReport
    - Registrar api_state_before e api_state_after para cada track switch
    - Validar opções descobertas contra Shaka API (cross-validation)
    - Restaurar tracks iniciais ao final da sessão
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.7, 4.1, 4.2, 4.3, 5.1, 5.7, 6.5, 8.5, 10.1, 10.2, 10.3, 10.4_

  - [x] 7.3 Escrever property tests para AudioSubtitleOrchestrator
    - **Property 2: UI vs API Cross-Validation** — Para qualquer par (UI options, API tracks), a validação classifica corretamente consistência ou mismatch
    - **Property 8: Track Restoration** — Para qualquer track inicial e sequência de seleções, a restauração final aponta para o track original
    - **Property 13: Error Resilience — Channel Continuation** — Para qualquer lista de canais onde um canal levanta exceção, os canais subsequentes ainda são executados e o relatório final contém entradas para todos
    - **Property 14: API State Recording** — Para qualquer track switch, o resultado contém api_state_before e api_state_after não-nulos
    - **Validates: Requirements 2.3, 3.7, 5.7, 9.5, 10.3, 10.4**

  - [x] 7.4 Escrever unit tests para AudioSubtitleOrchestrator
    - Testar fluxo completo de um canal com mocks
    - Testar sequência de 3 canais com 1 falha no meio (continuidade)
    - Testar canal com playback timeout — skip correto
    - Testar restauração de tracks iniciais
    - Testar integração com CapabilityMap
    - _Requirements: 9.1, 9.2, 9.3, 9.5_

- [x] 8. Checkpoint - Verificar integração dos componentes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Integração final e wiring
  - [x] 9.1 Criar entry point e integração com Player Discovery
    - Atualizar `src/audio_subtitle_monitor/__init__.py` com exports públicos
    - Criar `src/audio_subtitle_monitor/main.py` com função `run_audio_subtitle_monitoring(page, capability_map, channels, config)` como entry point principal
    - Integrar logging estruturado via StructuredLogger existente em todas as operações
    - Registrar todas as interações (cliques, verificações, tempos) como eventos no log para correlação com EventProbe do Player Discovery
    - _Requirements: 8.1, 8.5, 9.1_

  - [x] 9.2 Escrever integration tests do fluxo completo
    - Testar fluxo end-to-end com Playwright mockado (page.evaluate retornando dados realistas)
    - Testar cenário com Settings Dialog que fecha automaticamente após seleção
    - Testar cenário com Settings Dialog que permanece aberto
    - Testar geração de relatório JSON final com todos os campos
    - _Requirements: 7.1, 6.2, 6.3, 9.1_

- [x] 10. Checkpoint final - Verificar sistema completo
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas com `*` são opcionais e podem ser puladas para MVP mais rápido
- Cada task referencia requirements específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Property tests validam propriedades universais de corretude definidas no design
- Unit tests validam exemplos específicos e edge cases
- O módulo reutiliza CapabilityMap e InteractionManager do Player Discovery existente
- Execução sequencial por canal evita race conditions com o player
- Todos os timeouts são configuráveis via AudioSubtitleConfig

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1"] },
    { "id": 3, "tasks": ["2.3", "2.4", "3.2", "3.3", "4.2", "4.3", "6.1"] },
    { "id": 4, "tasks": ["6.2", "6.3", "7.1"] },
    { "id": 5, "tasks": ["7.2"] },
    { "id": 6, "tasks": ["7.3", "7.4"] },
    { "id": 7, "tasks": ["9.1"] },
    { "id": 8, "tasks": ["9.2"] }
  ]
}
```
