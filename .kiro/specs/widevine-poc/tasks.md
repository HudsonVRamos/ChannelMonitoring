# Implementation Plan: Widevine PoC

## Overview

Plano de implementação da Proof of Concept para validação do Widevine DRM com Playwright em container Docker. A implementação segue a arquitetura definida no design, com módulos independentes orquestrados pelo `PoCOrchestrator`. A linguagem é Python 3.10+ com type hints, usando Playwright para automação do browser, OpenCV para análise visual, e boto3 para integração com Amazon Bedrock.

## Tasks

- [x] 1. Setup do projeto e infraestrutura base
  - [x] 1.1 Criar estrutura de diretórios e arquivos de configuração do projeto
    - Criar diretório `src/` com `__init__.py`
    - Criar diretório `tests/` com `__init__.py` e `conftest.py`
    - Criar diretório `output/` para relatórios e evidências
    - Criar `requirements.txt` com dependências: playwright, opencv-python-headless, numpy, boto3, hypothesis, pytest, pytest-asyncio
    - Criar `pytest.ini` com configuração para asyncio e hypothesis
    - _Requirements: 9.1, 9.4_

  - [x] 1.2 Implementar data models (`src/models.py`)
    - Implementar todas as dataclasses definidas no design: `VideoMetrics`, `AudioMetrics`, `SubtitleMetrics`, `PlayerMetrics`, `TelemetrySample`
    - Implementar enums: `ValidationStatus`, `GoNoGoDecision`, `FreezeClassification`, `BufferingClassification`, `DiagnosisStatus`
    - Implementar result classes: `ValidationResult`, `DRMResult`, `LuminanceResult`, `BlackScreenResult`, `FreezeResult`, `BufferingState`, `DiagnosisResult`
    - Implementar `PerformanceMetrics`, `PoCReport`, `LogEntry`
    - _Requirements: 3.4, 11.1_

  - [x] 1.3 Implementar configuração (`src/config.py`)
    - Implementar `PoCConfig` dataclass com todos os parâmetros definidos no design
    - Incluir valores padrão para timeouts, intervalos e thresholds
    - Suportar override via variáveis de ambiente
    - _Requirements: 4.3, 5.2, 6.2, 7.2, 8.5_

- [x] 2. Implementar Structured Logger
  - [x] 2.1 Implementar logger estruturado (`src/structured_logger.py`)
    - Implementar classe `StructuredLogger` com output em JSON para stdout
    - Implementar métodos `log`, `debug`, `info`, `warning`, `error`
    - Cada entrada DEVE conter: timestamp ISO 8601 com milissegundos, level, stage_id, message, data
    - Suportar configuração de nível mínimo via variável de ambiente `LOG_LEVEL`
    - Incluir stack_trace em logs de nível ERROR
    - _Requirements: 10.1, 10.9, 10.10, 10.11_

  - [x] 2.2 Write property test para formato de log estruturado
    - **Property 14: Formato de log estruturado**
    - **Validates: Requirements 10.1, 10.9, 10.10**

- [x] 3. Implementar Auth Manager
  - [x] 3.1 Implementar gerenciador de autenticação (`src/auth_manager.py`)
    - Implementar classe `AuthManager` com métodos para exportar e restaurar storageState
    - Implementar `validate_storage_state` para verificar arquivo válido (tamanho > 0, contém cookies)
    - Implementar `detect_session_expired` para detectar redirect para login ou HTTP 401/403
    - Implementar `restore_session` com timeout de 15 segundos
    - Registrar logs de cada ação (INFO para navegação, ERROR para sessão expirada)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 10.2_

  - [x] 3.2 Write property test para detecção de sessão expirada
    - **Property 1: Detecção de sessão expirada**
    - **Validates: Requirements 1.4**

- [x] 4. Implementar DRM Validator
  - [x] 4.1 Implementar validador DRM (`src/drm_validator.py`)
    - Implementar classe `DRMValidator` com timeout de 15 segundos
    - Implementar `validate_drm_initialization` para verificar criação de MediaKeys e license request
    - Implementar `wait_for_license` para aguardar obtenção de licença DRM
    - Implementar `capture_drm_error` para capturar erros específicos do CDM
    - Registrar logs de cada etapa do handshake DRM com tempos em milissegundos
    - _Requirements: 2.1, 2.4, 2.5, 10.3_

  - [x] 4.2 Write unit tests para DRM Validator
    - Testar cenários de sucesso e falha na inicialização do CDM
    - Testar timeout na obtenção de licença
    - Testar captura de erros DRM
    - _Requirements: 2.1, 2.4, 2.5_

- [x] 5. Implementar Telemetry Collector
  - [x] 5.1 Implementar coletor de telemetria (`src/telemetry_collector.py`)
    - Implementar classe `TelemetryCollector` com intervalo de 2 segundos
    - Implementar `collect_video_metrics` para coletar currentTime, readyState, paused, buffered_seconds
    - Implementar `collect_audio_metrics` via Web Audio API (retornar null se indisponível)
    - Implementar `collect_subtitle_metrics` para tracks_available, active_track, has_active_cues
    - Implementar `collect_sample` que produz `TelemetrySample` completo em JSON
    - Implementar `start_continuous_collection` para coleta contínua durante período configurável
    - Capturar erros do player em ≤500ms após evento de erro
    - Registrar logs DEBUG para cada amostra coletada
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 10.4_

  - [x] 5.2 Write property test para completude da estrutura de telemetria
    - **Property 3: Completude da estrutura de telemetria**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

  - [x] 5.3 Write property test para validação de progressão do currentTime
    - **Property 2: Validação de progressão do currentTime**
    - **Validates: Requirements 2.3**

- [x] 6. Implementar Frame Capturer
  - [x] 6.1 Implementar capturador de frames (`src/frame_capturer.py`)
    - Implementar classe `FrameCapturer` com intervalo padrão de 5 segundos (configurável 1-60s)
    - Implementar `capture_frame` para capturar screenshot PNG do viewport do player
    - Implementar `validate_frame_content` que calcula luminância média e verifica se excede 16/255
    - Implementar `capture_sequence` para captura sequencial com intervalo configurável
    - Rejeitar frames com resolução < 1280x720 ou tamanho > 5 MB
    - Descartar frames com tela preta (luminância ≤ 16) e registrar warning
    - Registrar logs INFO com timestamp, tamanho e resolução de cada frame capturado
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 10.5_

  - [x] 6.2 Write property test para validação de resolução e tamanho de frame
    - **Property 4: Validação de resolução e tamanho de frame**
    - **Validates: Requirements 4.2**

  - [x] 6.3 Write property test para validação de intervalo de captura
    - **Property 5: Validação de intervalo de captura**
    - **Validates: Requirements 4.3**

  - [x] 6.4 Write property test para classificação de luminância de frame
    - **Property 6: Classificação de luminância de frame**
    - **Validates: Requirements 4.4, 4.5**

- [x] 7. Checkpoint - Validar módulos base
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implementar OpenCV Analyzer
  - [x] 8.1 Implementar analisador OpenCV (`src/opencv_analyzer.py`)
    - Implementar classe `OpenCVAnalyzer` com thresholds configuráveis
    - Implementar `analyze_luminance` para calcular média de luminância, percentual de pixels pretos e variância
    - Implementar `detect_black_screen` com lógica: BLACK_SCREEN se luminância < 10 E pixels pretos > 95% E variância ≤ 50; cena escura legítima se variância > 50
    - Implementar `calculate_frame_similarity` usando SSIM entre dois frames
    - Implementar `detect_freeze` combinando similaridade visual + telemetria (currentTime diff)
    - Tratar frames inválidos retornando ANALYSIS_ERROR sem exceção
    - Tratar frames com dimensões diferentes sem classificar como freeze
    - Registrar logs INFO com métricas calculadas (luminância, percentual pixels pretos, SSIM)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 10.6_

  - [x] 8.2 Write property test para classificação de tela preta vs cena escura
    - **Property 7: Classificação de tela preta vs cena escura**
    - **Validates: Requirements 5.1, 5.2, 5.3**

  - [x] 8.3 Write property test para tratamento de frames inválidos
    - **Property 8: Tratamento de frames inválidos**
    - **Validates: Requirements 5.4, 6.4**

  - [x] 8.4 Write property test para classificação de freeze
    - **Property 9: Classificação de freeze**
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 9. Implementar Buffering Detector
  - [x] 9.1 Implementar detector de buffering (`src/buffering_detector.py`)
    - Implementar classe `BufferingDetector` com threshold padrão de 10 segundos
    - Implementar `update` que recebe `TelemetrySample` e atualiza estado
    - Implementar `is_persistent` para verificar se buffering excedeu threshold
    - Implementar `reset` para resetar estado quando player volta a reproduzir
    - Classificar como BUFFERING_PERSISTENT se waiting/stalled > threshold sem currentTime avançando
    - Classificar como BUFFERING_NORMAL se transição para playing ocorre dentro do threshold
    - Registrar estados inesperados em log WARNING sem interromper detecção
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 9.2 Write property test para classificação de buffering
    - **Property 10: Classificação de buffering**
    - **Validates: Requirements 7.1, 7.2, 7.3**

- [x] 10. Implementar Bedrock Client
  - [x] 10.1 Implementar cliente Bedrock (`src/bedrock_client.py`)
    - Implementar classe `BedrockClient` com timeout de 30 segundos e confidence threshold de 0.7
    - Implementar `diagnose_frame` com gate de pré-requisito (rejeitar se anomaly_confirmed=False)
    - Implementar `_invoke_haiku` para chamar Claude Haiku com frame base64
    - Implementar `_invoke_sonnet` para escalação quando confidence < threshold
    - Implementar `_parse_response` para validar JSON com campos: status, diagnosis, issues, description, confidence
    - Retornar UNKNOWN confidence=0.0 em caso de timeout, erro de API ou resposta inválida
    - Registrar logs INFO com modelo, tamanho do payload, tempo de resposta e status HTTP
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 10.7_

  - [x] 10.2 Write property test para parsing de resposta do Bedrock
    - **Property 11: Parsing de resposta do Bedrock**
    - **Validates: Requirements 8.2, 8.4**

  - [x] 10.3 Write property test para lógica de escalação Haiku → Sonnet
    - **Property 12: Lógica de escalação Haiku → Sonnet**
    - **Validates: Requirements 8.5**

  - [x] 10.4 Write property test para gate de pré-requisito do Bedrock
    - **Property 13: Gate de pré-requisito para Bedrock**
    - **Validates: Requirements 8.6**

- [x] 11. Checkpoint - Validar componentes de análise
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implementar Report Generator
  - [x] 12.1 Implementar gerador de relatórios (`src/report_generator.py`)
    - Implementar classe `ReportGenerator`
    - Implementar `generate` que produz `PoCReport` consolidado com status por validação
    - Implementar `classify_go_nogo`: GO se login+DRM+frames+Docker=PASS, NO_GO se alguma crítica=FAIL
    - Implementar `save_report` para salvar relatório em JSON
    - Incluir métricas de performance (browser_init_time, drm_ready_time, time_per_frame, bedrock_response_time)
    - Incluir caminho para log completo no relatório
    - Marcar validações não executáveis como SKIPPED com motivo da dependência
    - Para validações FAIL, incluir error_message e evidence_paths
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 12.2 Write property test para estrutura do relatório
    - **Property 15: Estrutura do relatório**
    - **Validates: Requirements 11.1, 11.2**

  - [x] 12.3 Write property test para decisão Go/No-Go
    - **Property 16: Decisão Go/No-Go**
    - **Validates: Requirements 11.4**

  - [x] 12.4 Write property test para lógica de skip por dependência
    - **Property 17: Lógica de skip por dependência**
    - **Validates: Requirements 11.6**

- [x] 13. Implementar PoC Orchestrator
  - [x] 13.1 Implementar orquestrador principal (`src/poc_orchestrator.py`)
    - Implementar classe `PoCOrchestrator` que executa todas as validações em sequência
    - Implementar cadeia de dependências: Auth → DRM → Playback/Telemetry → Frames → OpenCV → Bedrock
    - Se uma etapa crítica falha, marcar etapas dependentes como SKIPPED
    - Registrar versões de Playwright, Chromium, Python, OpenCV no início da execução
    - Inicializar Playwright com Chromium e Widevine CDM
    - Gerar relatório consolidado ao final da execução
    - Implementar entry point `__main__` para execução via `python -m src.poc_orchestrator`
    - _Requirements: 2.2, 9.1, 9.3, 10.8, 11.4, 11.6_

  - [x] 13.2 Write unit tests para PoC Orchestrator
    - Testar cadeia de dependências (skip em cascata)
    - Testar geração de relatório Go/No-Go
    - Testar logging de versões no início
    - _Requirements: 9.3, 11.4, 11.6_

- [x] 14. Implementar Docker e integração final
  - [x] 14.1 Criar Dockerfile e docker-compose.yml
    - Criar Dockerfile usando imagem base `mcr.microsoft.com/playwright/python:v1.40.0-jammy`
    - Instalar dependências de sistema: libnss3, libatk1.0-0, libatk-bridge2.0-0, libgbm1, libasound2, libxrandr2, libpango-1.0-0, libcairo2
    - Instalar dependências Python via requirements.txt
    - Instalar Chromium via `playwright install chromium`
    - Configurar variáveis de ambiente (LOG_LEVEL, DISPLAY)
    - Criar docker-compose.yml com volume para storageState e output
    - _Requirements: 9.1, 9.2, 9.4, 9.5_

  - [x] 14.2 Criar README.md com instruções de execução
    - Documentar pré-requisitos (Docker, AWS credentials para Bedrock)
    - Documentar processo de login manual e geração do storageState
    - Documentar como buildar e rodar o container
    - Documentar variáveis de ambiente configuráveis
    - Documentar interpretação do relatório Go/No-Go
    - _Requirements: 9.5, 9.6_

- [x] 15. Final checkpoint - Validação completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requirements específicos para rastreabilidade
- Checkpoints garantem validação incremental entre blocos de implementação
- Property tests validam propriedades universais de correção (lógica pura)
- Unit tests validam exemplos específicos e edge cases
- Os testes de integração (Docker + plataforma real) devem ser executados manualmente pelo desenvolvedor
- A linguagem de implementação é Python 3.10+ conforme definido no design

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1", "5.1"] },
    { "id": 3, "tasks": ["3.2", "4.2", "5.2", "5.3", "6.1"] },
    { "id": 4, "tasks": ["6.2", "6.3", "6.4", "8.1", "9.1"] },
    { "id": 5, "tasks": ["8.2", "8.3", "8.4", "9.2", "10.1"] },
    { "id": 6, "tasks": ["10.2", "10.3", "10.4", "12.1"] },
    { "id": 7, "tasks": ["12.2", "12.3", "12.4", "13.1"] },
    { "id": 8, "tasks": ["13.2", "14.1", "14.2"] }
  ]
}
```
