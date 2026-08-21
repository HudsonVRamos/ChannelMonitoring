# Requirements Document

## Introduction

O módulo Unified Channel Monitor consolida os dois módulos independentes — Player Discovery (monitoramento de vídeo) e Audio/Subtitle Monitor (testes de áudio/legendas) — em um único processo orquestrador. Para cada canal, o sistema executa discovery, coleta telemetria de vídeo de forma contínua em background, e simultaneamente testa tracks de áudio e legendas, produzindo um relatório unificado que cobre saúde do vídeo, funcionalidade de áudio e funcionalidade de legendas. O objetivo é rodar como um único comando na EC2, eliminando a necessidade de executar dois processos separados.

## Glossary

- **Unified_Orchestrator**: Processo principal que coordena discovery, monitoramento de vídeo e testes de áudio/legendas para cada canal em sequência
- **Video_Telemetry_Collector**: Componente responsável por coletar métricas de vídeo (currentTime, frames, FPS, freeze, black screen, buffer) em intervalos regulares durante toda a sessão de um canal
- **Audio_Track_Tester**: Componente que interage com a UI do player para selecionar e validar cada track de áudio disponível via Shaka API e Web Audio API
- **Subtitle_Track_Tester**: Componente que interage com a UI do player para selecionar e validar cada track de legenda disponível via TextTrack API
- **CapabilityMap**: Estrutura JSON produzida pelo DiscoveryEngine contendo as capabilities detectadas do player e estratégias de interação
- **Unified_Report**: Relatório JSON consolidado por canal contendo saúde de vídeo, resultados de áudio e resultados de legendas
- **Channel_Session**: Período completo de monitoramento de um canal, desde navegação até geração do relatório
- **Settings_Dialog**: Painel de configurações do player SKY+ que contém opções de áudio (IDIOMA ALTERNATIVO) e legendas (LEGENDAS)
- **Escalation_Pipeline**: Pipeline determinístico de escalação de anomalias: HEALTHY → SUSPECT → OpenCV → Bedrock
- **Telemetry_Sample**: Uma amostra individual de métricas coletada pelo Video_Telemetry_Collector em um instante específico
- **Health_Score**: Pontuação calculada a partir das Telemetry_Samples que classifica o estado do canal
- **Playwright_Page**: Instância única do Playwright Page compartilhada por todos os componentes durante uma Channel_Session

## Requirements

### Requirement 1: Single Entry Point

**User Story:** As a operations engineer, I want to run a single command on the EC2 to monitor all channels, so that I don't need to manage two separate processes.

#### Acceptance Criteria

1. THE Unified_Orchestrator SHALL expose a CLI entry point executable via `PYTHONPATH=. python -m src.unified_channel_monitor.run`
2. WHEN the `--continuous` flag is provided, THE Unified_Orchestrator SHALL execute channel rotations in a loop until interrupted by the user
3. WHEN no flag is provided, THE Unified_Orchestrator SHALL execute a single rotation through all configured channels and exit
4. THE Unified_Orchestrator SHALL accept channel configuration via the environment variable `UNIFIED_MONITOR_CHANNELS` as a comma-separated list of URLs
5. THE Unified_Orchestrator SHALL use a single Playwright persistent browser context with the Chrome profile at the path specified by `CHROME_PROFILE_DIR`
6. IF the browser fails to launch, THEN THE Unified_Orchestrator SHALL log the error with structured logging and exit with a non-zero exit code

### Requirement 2: Sequential Channel Rotation

**User Story:** As a operations engineer, I want channels to be processed one at a time, so that there are no race conditions from concurrent browser interactions.

#### Acceptance Criteria

1. THE Unified_Orchestrator SHALL process channels sequentially, completing one Channel_Session before starting the next
2. WHEN navigating to a new channel, THE Unified_Orchestrator SHALL wait for the `<video>` element to be present and playback to begin within 30 seconds
3. IF navigation to a channel times out, THEN THE Unified_Orchestrator SHALL log the failure, record the channel as UNREACHABLE in the Unified_Report, and proceed to the next channel
4. IF an unhandled exception occurs during a Channel_Session, THEN THE Unified_Orchestrator SHALL log the exception, record the channel as ERROR in the Unified_Report, and proceed to the next channel without terminating the process
5. THE Unified_Orchestrator SHALL share the same Playwright_Page instance across all Channel_Sessions within a rotation

### Requirement 3: Discovery Integration

**User Story:** As a developer, I want the CapabilityMap to be produced once and reused, so that subsequent channels don't repeat expensive discovery.

#### Acceptance Criteria

1. WHEN the first channel begins playback, THE Unified_Orchestrator SHALL execute the DiscoveryEngine to produce a CapabilityMap
2. WHILE the CapabilityMap is valid, THE Unified_Orchestrator SHALL reuse the existing CapabilityMap for subsequent channels without re-executing discovery
3. IF the number of consecutive channel failures exceeds the configured invalidation threshold, THEN THE Unified_Orchestrator SHALL invalidate the CapabilityMap and re-execute the DiscoveryEngine on the next channel
4. THE Unified_Orchestrator SHALL make the CapabilityMap available to both the Audio_Track_Tester and the Subtitle_Track_Tester for interaction strategy selection
5. WHEN re-discovery is triggered, THE Unified_Orchestrator SHALL log a structured event indicating the reason for invalidation

### Requirement 4: Continuous Video Telemetry

**User Story:** As a monitoring operator, I want video telemetry to be collected continuously during audio and subtitle tests, so that I can detect if track switching causes playback issues.

#### Acceptance Criteria

1. WHEN a Channel_Session starts playback, THE Video_Telemetry_Collector SHALL begin collecting Telemetry_Samples at the configured interval (default 2 seconds)
2. WHILE audio or subtitle tracks are being tested, THE Video_Telemetry_Collector SHALL continue collecting Telemetry_Samples without interruption
3. THE Video_Telemetry_Collector SHALL collect the following metrics per sample: currentTime, total frames decoded, frames dropped, estimated FPS, buffer ahead in seconds, and video readyState
4. WHEN the Video_Telemetry_Collector detects zero frame advancement for 3 consecutive samples, THE Video_Telemetry_Collector SHALL flag a freeze event with the timestamp
5. WHEN the Video_Telemetry_Collector detects a freeze or buffer underrun during an audio or subtitle track switch, THE Video_Telemetry_Collector SHALL annotate the Telemetry_Sample with the track switch context
6. THE Video_Telemetry_Collector SHALL stop collection only when the Channel_Session ends or the Unified_Orchestrator signals shutdown

### Requirement 5: Audio Track Testing

**User Story:** As a QA operator, I want each audio track to be tested during the monitoring session, so that I can verify all audio options are functional.

#### Acceptance Criteria

1. WHEN the Video_Telemetry_Collector is running, THE Audio_Track_Tester SHALL open the Settings_Dialog using the interaction strategy from the CapabilityMap
2. THE Audio_Track_Tester SHALL identify all available audio track options in the Settings_Dialog section "IDIOMA ALTERNATIVO"
3. WHEN an audio track is selected in the UI, THE Audio_Track_Tester SHALL validate the switch via the Shaka Player API `getAudioTracks()` within 5 seconds
4. WHEN an audio track switch is confirmed, THE Audio_Track_Tester SHALL collect RMS audio telemetry via Web Audio API for the configured window (default 30 seconds)
5. IF an audio track switch is not confirmed by the Shaka API within the timeout, THEN THE Audio_Track_Tester SHALL mark the track as FAIL with reason "switch_timeout"
6. WHEN all audio tracks have been tested, THE Audio_Track_Tester SHALL restore the original audio track

### Requirement 6: Subtitle Track Testing

**User Story:** As a QA operator, I want each subtitle track to be tested during the monitoring session, so that I can verify all subtitle options are functional.

#### Acceptance Criteria

1. WHEN audio track testing is complete, THE Subtitle_Track_Tester SHALL identify all available subtitle options in the Settings_Dialog section "LEGENDAS"
2. WHEN a subtitle track is selected in the UI, THE Subtitle_Track_Tester SHALL validate the switch via the Shaka Player API `getTextTracks()` within 5 seconds
3. WHEN a subtitle track switch is confirmed, THE Subtitle_Track_Tester SHALL monitor for at least one TextTrack cue to appear within the configured timeout (default 15 seconds)
4. IF no cue appears within the timeout, THEN THE Subtitle_Track_Tester SHALL mark the track as FAIL with reason "no_cue_received"
5. WHEN all subtitle tracks have been tested, THE Subtitle_Track_Tester SHALL restore the initial subtitle track configuration
6. IF the Settings_Dialog fails to open, THEN THE Subtitle_Track_Tester SHALL mark all subtitle tracks as SKIP with reason "dialog_unavailable"

### Requirement 7: Escalation Pipeline Integration

**User Story:** As a monitoring operator, I want anomalies detected during telemetry to be escalated through the existing pipeline, so that issues are diagnosed automatically.

#### Acceptance Criteria

1. WHEN the Video_Telemetry_Collector classifies a channel as SUSPECT based on Health_Score, THE Unified_Orchestrator SHALL capture frames and escalate to OpenCV analysis
2. WHEN OpenCV analysis confirms an anomaly, THE Unified_Orchestrator SHALL escalate to Bedrock for AI-powered diagnosis
3. WHILE audio or subtitle testing is in progress, THE Unified_Orchestrator SHALL defer escalation actions until the current track test completes to avoid UI interference
4. THE Unified_Orchestrator SHALL record all escalation results (OpenCV verdict, Bedrock diagnosis) in the Unified_Report for the channel
5. IF escalation is triggered during a track switch, THEN THE Unified_Orchestrator SHALL annotate the escalation with the active track switch context

### Requirement 8: Unified Report Generation

**User Story:** As a operations engineer, I want a single report per channel covering video, audio, and subtitles, so that I can assess channel health holistically.

#### Acceptance Criteria

1. WHEN a Channel_Session completes, THE Unified_Orchestrator SHALL generate a Unified_Report containing: video health summary, audio track test results, and subtitle track test results
2. THE Unified_Report SHALL include for video: total samples collected, freeze events detected, average buffer ahead, Health_Score classification, and escalation results if triggered
3. THE Unified_Report SHALL include for each audio track: track name, switch validation result, RMS telemetry summary (average RMS, percentage of samples with audio), and pass/fail status
4. THE Unified_Report SHALL include for each subtitle track: track name, switch validation result, cue received status, and pass/fail status
5. THE Unified_Report SHALL include video telemetry annotations that correlate freeze or buffer events with concurrent audio/subtitle track switches
6. WHEN all channels complete a rotation, THE Unified_Orchestrator SHALL generate a Consolidated_Report aggregating all channel Unified_Reports with overall pass/partial/fail counts
7. THE Unified_Orchestrator SHALL persist reports as JSON files in the configured output directory with timestamp-based filenames

### Requirement 9: Session Flow Coordination

**User Story:** As a developer, I want the session flow to be well-defined, so that video monitoring, audio testing, and subtitle testing cooperate without conflicts.

#### Acceptance Criteria

1. THE Unified_Orchestrator SHALL execute the following sequence per Channel_Session: navigate → wait for playback → run discovery (if needed) → start video telemetry → test audio tracks → test subtitle tracks → stop video telemetry → generate report
2. WHILE the Audio_Track_Tester or Subtitle_Track_Tester is interacting with the Settings_Dialog, THE Video_Telemetry_Collector SHALL collect telemetry using JavaScript evaluation only, without performing any DOM interactions
3. WHEN the Audio_Track_Tester finishes testing all audio tracks but before subtitle testing begins, THE Unified_Orchestrator SHALL verify video playback is still active
4. IF video playback has stopped between audio and subtitle testing, THEN THE Unified_Orchestrator SHALL attempt to recover playback before proceeding with subtitle tests
5. THE Unified_Orchestrator SHALL ensure the Settings_Dialog is closed and initial tracks are restored before ending the Channel_Session

### Requirement 10: Configuration

**User Story:** As a operations engineer, I want all parameters to be configurable via environment variables, so that I can tune the system without code changes.

#### Acceptance Criteria

1. THE Unified_Orchestrator SHALL load configuration from environment variables with the prefix `UNIFIED_MONITOR_`
2. THE Unified_Orchestrator SHALL provide sensible defaults for all configuration parameters derived from the existing Player Discovery and Audio/Subtitle Monitor defaults
3. THE Unified_Orchestrator SHALL expose the following configurable parameters: channels list, telemetry interval, observation period per channel, audio telemetry window, audio sample interval, subtitle cue timeout, track switch timeout, invalidation threshold, output directory, and log level
4. WHEN an environment variable contains an invalid value (non-numeric where number expected), THE Unified_Orchestrator SHALL ignore the invalid value, use the default, and log a warning

### Requirement 11: Structured Logging

**User Story:** As a developer, I want structured logs with correlation between video telemetry and track test events, so that I can debug issues across the unified session.

#### Acceptance Criteria

1. THE Unified_Orchestrator SHALL emit structured JSON log entries to stdout for all significant events
2. THE Unified_Orchestrator SHALL include a `session_id` field in all log entries within a Channel_Session to enable correlation
3. WHEN a track switch event occurs during active video telemetry, THE Unified_Orchestrator SHALL emit a log entry containing both the track switch details and the current video telemetry state
4. THE Unified_Orchestrator SHALL log the start and end of each phase (discovery, video telemetry, audio testing, subtitle testing) with duration in milliseconds
5. IF an error occurs, THEN THE Unified_Orchestrator SHALL log the error with full context including channel URL, current phase, and stack trace

### Requirement 12: Graceful Shutdown

**User Story:** As a operations engineer, I want the process to shut down cleanly when interrupted, so that partial results are saved and the browser is properly closed.

#### Acceptance Criteria

1. WHEN the user sends a SIGINT (Ctrl+C), THE Unified_Orchestrator SHALL stop accepting new Channel_Sessions and complete the current operation within 10 seconds
2. WHEN shutdown is initiated, THE Unified_Orchestrator SHALL persist any completed Unified_Reports collected so far as a partial Consolidated_Report
3. WHEN shutdown is initiated, THE Unified_Orchestrator SHALL close the Playwright browser context cleanly
4. IF the current Channel_Session is in progress during shutdown, THEN THE Unified_Orchestrator SHALL stop video telemetry collection and generate a partial Unified_Report for the interrupted channel
5. THE Unified_Orchestrator SHALL exit with code 0 after a clean shutdown and code 1 after an error shutdown
