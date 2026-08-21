# Documentação Técnica — Channel Monitoring SKY+

## Visão Geral

Sistema de monitoramento automatizado de canais ao vivo da plataforma SKY+. Utiliza Chrome com Widevine DRM via Playwright para reproduzir conteúdo protegido e coletar telemetria em tempo real sobre vídeo, áudio, buffer, legendas e controles do player.

**Princípio central:** Canal saudável não consome IA. Apenas quando a telemetria detecta anomalias, o sistema escala para OpenCV e depois para Bedrock (Claude).

---

## Infraestrutura

### EC2 (Produção Atual)

| Item | Valor |
|------|-------|
| **Instance ID** | i-04d5ad90cc281b0cf |
| **Tipo** | t3.large |
| **Região** | sa-east-1 (São Paulo) |
| **OS** | Ubuntu 22.04 LTS |
| **IP Público** | 54.232.22.152 |
| **Acesso** | RDP (porta 3389) via xrdp |
| **Display** | DISPLAY=:10 (xrdp/Xorg) |
| **Chrome** | Google Chrome stable (/usr/bin/google-chrome) com Widevine CDM |
| **Python** | 3.11 |
| **Disco** | 30GB GP3 (EBS, persist on termination=false) |
| **Key Pair** | widevine-poc-key |
| **Security Group** | SSH (22) + RDP (3389) |

### IAM Role

- SSM Managed Instance (para comandos remotos)
- Bedrock InvokeModel (para diagnóstico IA)
- S3 Read/Write no bucket de artefatos

### CDK Stack

Arquivo: `infra/stacks/ec2_monitor_stack.py`  
Stack name: `widevine-poc-ec2-stack`  
Deploy: `cd infra && cdk deploy widevine-poc-ec2-stack`

### Diretórios na EC2

| Path | Descrição |
|------|-----------|
| `/home/ubuntu/ChannelMonitoring` | Repositório do projeto |
| `/data/chrome-profile` | Chrome profile com sessão SKY+ autenticada |
| `/home/ubuntu/ChannelMonitoring/output/` | Relatórios JSON gerados |

---

## Repositório Git

**URL:** https://github.com/HudsonVRamos/ChannelMonitoring  
**Branch principal:** `main`  
**Branch de desenvolvimento:** `feature/player-discovery`

---

## Estrutura do Código

```
CHANNEL_MONITORING/
├── src/
│   ├── __main__.py                    # Entry point da PoC original (python -m src)
│   ├── poc_orchestrator.py            # Orquestrador da PoC Widevine
│   ├── auth_manager.py                # Autenticação via storageState
│   ├── drm_validator.py               # Validação Widevine CDM
│   ├── telemetry_collector.py         # Coleta de métricas do HTMLMediaElement
│   ├── frame_capturer.py              # Captura de screenshots do player
│   ├── opencv_analyzer.py             # Análise visual (tela preta, freeze)
│   ├── bedrock_client.py              # Diagnóstico visual via Claude (Haiku/Sonnet)
│   ├── buffering_detector.py          # Detecção de buffering
│   ├── report_generator.py            # Geração de relatório Go/No-Go
│   ├── structured_logger.py           # Logger JSON para stdout
│   ├── models.py                      # Data models da PoC
│   ├── config.py                      # Config da PoC (PoCConfig)
│   │
│   ├── player_discovery/              # ★ MÓDULO NOVO — Player Discovery
│   │   ├── __init__.py                # Exporta PlayerDiscoveryOrchestrator
│   │   ├── main.py                    # Orquestrador principal
│   │   ├── run.py                     # Runner CLI (python -m src.player_discovery.run)
│   │   ├── config.py                  # PlayerDiscoveryConfig (dataclass + env vars)
│   │   ├── discovery/                 # Motor de descoberta de capabilities
│   │   │   ├── engine.py              # DiscoveryEngine (orquestra analyzers)
│   │   │   ├── dom_analyzer.py        # Análise semântica DOM (role, aria-label)
│   │   │   ├── js_analyzer.py         # Detecção de APIs JS do player
│   │   │   ├── browser_api_analyzer.py # Browser APIs (HTMLMediaElement, TextTrack)
│   │   │   ├── css_analyzer.py        # CSS auxiliar (max confidence 0.4)
│   │   │   ├── behavioral_tester.py   # Testes comportamentais (play, mute)
│   │   │   └── mutation_watcher.py    # MutationObserver com debounce
│   │   ├── models/                    # Data models
│   │   │   ├── enums.py              # InteractionLevel, ChannelHealthStatus, etc.
│   │   │   ├── capability.py         # Capability, PlayerInfo, CapabilityMapData
│   │   │   ├── capability_map.py     # CapabilityMap (JSON serializable)
│   │   │   ├── telemetry.py          # VideoTelemetry, AudioTelemetry, etc.
│   │   │   └── results.py            # InteractionResult, ChannelReport, etc.
│   │   ├── interaction/               # Gerenciamento de interação 3 níveis
│   │   │   └── manager.py            # InteractionManager (API→DOM→Visual)
│   │   ├── monitoring/                # Monitoramento multi-canal
│   │   │   ├── channel_monitor.py    # ChannelMonitor (rotação, escalação)
│   │   │   └── health_score.py       # HealthScoreCalculator
│   │   └── probes/                    # Probes de telemetria
│   │       ├── video_probe.py        # currentTime, frames, FPS, freeze
│   │       ├── audio_probe.py        # RMS, silence, mute (Web Audio API)
│   │       ├── subtitle_probe.py     # TextTrack API, activeCues
│   │       ├── buffer_probe.py       # buffer_ahead, waiting events
│   │       └── event_probe.py        # Todos eventos HTMLMediaElement
│   │
│   └── audio_subtitle_monitor/        # ★ MÓDULO EM DESENVOLVIMENTO
│       └── ...                        # Interação com UI do player (áudio/legendas)
│
├── tests/                             # ~230+ testes (unit + property-based)
│   ├── test_*.py                      # Unit tests
│   └── test_prop_*.py                 # Property-based tests (Hypothesis)
│
├── scripts/
│   ├── run_poc_ec2.sh                 # Script para rodar a PoC original
│   ├── run_player_discovery.sh        # Script para rodar o Player Discovery
│   ├── setup_auth.py                  # Script para autenticar Chrome no SKY+
│   ├── generate_storage_state.py      # Gerador de storageState
│   ├── check_cookies.py              # Verificação de cookies
│   └── check_widevine.py            # Verificação de Widevine CDM
│
├── infra/                             # CDK (infraestrutura como código)
│   ├── app.py                         # CDK App
│   ├── stacks/
│   │   ├── ec2_monitor_stack.py      # EC2 + VPC + IAM (sa-east-1)
│   │   └── widevine_poc_stack.py     # Stack da PoC (us-east-1)
│   └── cdk.json
│
├── .kiro/specs/                       # Specs (Kiro)
│   ├── widevine-poc/                  # Spec da PoC original
│   ├── player-discovery/              # Spec do Player Discovery (COMPLETA)
│   └── audio-subtitle-monitoring/     # Spec de áudio/legendas (EM ANDAMENTO)
│
├── Dockerfile                         # Container Docker para PoC
├── docker-compose.yml
├── buildspec.yml                      # AWS CodeBuild pipeline
├── requirements.txt                   # Dependências Python
└── pytest.ini                         # Configuração pytest
```

---

## Módulos do Sistema

### 1. PoC Widevine (Original)

**Objetivo:** Validar que Widevine DRM funciona com Playwright + Chrome em EC2/Docker.

**Entry point:** `python -m src` (usa `src/__main__.py`)

**Fluxo:** Auth → DRM → Telemetria → Frames → OpenCV → Bedrock

**Status:** ✅ Concluída (GO confirmado)

### 2. Player Discovery

**Objetivo:** Substituir seletores fixos por descoberta dinâmica e semântica das capabilities do player.

**Entry point:** `PYTHONPATH=. python -m src.player_discovery.run`

**Filosofia:** "Discovery uma vez, reutilização por todos os canais"

**Fluxo:**
1. Navega para o primeiro canal
2. Espera `<video>` carregar
3. Executa DiscoveryEngine (DOM + JS + Browser APIs + CSS + Behavioral)
4. Produz CapabilityMap (JSON serializado em memória)
5. Inicia MutationObserverWatcher (detecta mudanças no player)
6. Inicia rotação multi-canal com telemetria de 30s cada
7. Escalação determinística: HEALTHY → SUSPECT → OpenCV → Bedrock
8. Gera relatório JSON em output/

**Status:** ✅ Implementado (58 tasks completas)

### 3. Audio/Subtitle Monitoring (Em Desenvolvimento)

**Objetivo:** Testar funcionalidades de áudio e legendas interagindo com a UI customizada do player SKY+.

**Fluxo planejado:**
1. Mover cursor sobre player (mostrar controles)
2. Clicar no ícone de settings (último ícone na barra, parece fullscreen ⊞)
3. Identificar seções "IDIOMA ALTERNATIVO" e "LEGENDAS"
4. Iterar cada opção de áudio (30s de telemetria por track)
5. Iterar cada opção de legenda (verificar cues ativas)
6. Relatório por canal

**Status:** 🚧 Requisitos definidos, aguardando design e implementação

---

## Como Rodar

### Pré-requisitos na EC2

```bash
# Conectar via RDP (porta 3389)
# IP: 54.232.22.152, usuário: ubuntu

# Verificar que Chrome funciona
google-chrome-stable --version

# Verificar Python
python3 --version  # 3.11+
```

### Autenticar no SKY+ (uma vez)

```bash
cd ~/ChannelMonitoring
python3 scripts/setup_auth.py
# Faça login manualmente no Chrome que abrir
# Ctrl+C quando terminar
```

### Rodar Player Discovery

```bash
cd ~/ChannelMonitoring
PYTHONPATH=. python3 -m src.player_discovery.run
```

### Rodar com múltiplos canais (modo contínuo)

```bash
export PLAYER_DISCOVERY_CHANNELS="https://www.skymais.com.br/player/live/CH0100000000124,https://www.skymais.com.br/player/live/CH0100000000092,https://www.skymais.com.br/player/live/CH0100000000093"
PYTHONPATH=. python3 -m src.player_discovery.run --continuous
```

### Rodar PoC original

```bash
./scripts/run_poc_ec2.sh
```

### Rodar testes

```bash
cd ~/ChannelMonitoring
PYTHONPATH=. python3 -m pytest tests/ -v
```

---

## Variáveis de Ambiente

### Player Discovery (prefixo `PLAYER_DISCOVERY_`)

| Variável | Default | Descrição |
|----------|---------|-----------|
| `PLAYER_DISCOVERY_CHANNELS` | CH0100000000124 + 4 canais | Lista de URLs separadas por vírgula |
| `PLAYER_DISCOVERY_OBSERVATION_PERIOD_S` | 30 | Segundos de observação por canal |
| `PLAYER_DISCOVERY_TELEMETRY_INTERVAL_S` | 2.0 | Intervalo de coleta em segundos |
| `PLAYER_DISCOVERY_FUNCTIONAL_TEST_INTERVAL` | 5 | A cada N rotações, roda testes funcionais |
| `PLAYER_DISCOVERY_INVALIDATION_THRESHOLD` | 3 | Falhas consecutivas para invalidar mapa |
| `PLAYER_DISCOVERY_DEBOUNCE_WINDOW_MS` | 500 | Janela de debounce do MutationObserver |
| `PLAYER_DISCOVERY_LOG_LEVEL` | INFO | Nível de log (DEBUG, INFO, WARNING, ERROR) |
| `PLAYER_DISCOVERY_OUTPUT_DIR` | ./output | Diretório de relatórios |
| `CHROME_PROFILE_DIR` | /data/chrome-profile | Chrome profile com sessão autenticada |

---

## Player SKY+ — Informações Técnicas

### Tecnologia do Player

- **Biblioteca:** Shaka Player (detectado via `window.player`)
- **DRM:** Widevine (Chrome CDM nativo)
- **Streaming:** DASH/HLS adaptativo

### APIs JavaScript Disponíveis (via `window.player`)

| Método | Descrição |
|--------|-----------|
| `getAudioTracks()` | Lista tracks de áudio |
| `selectAudioTrack()` | Seleciona track de áudio |
| `getTextTracks()` | Lista tracks de legenda |
| `selectTextTrack()` | Seleciona track de legenda |
| `getVariantTracks()` | Lista variantes de qualidade |
| `selectVariantTrack()` | Seleciona variante |
| `getStats()` | Estatísticas de reprodução |
| `getPlaybackRate()` | Taxa de reprodução |
| `configure()` | Configuração do player |
| `getConfiguration()` | Configuração atual |
| `getNetworkingEngine()` | Engine de rede |

### Browser APIs Disponíveis

- HTMLMediaElement (`document.querySelector('video')`)
- TextTrackList (`video.textTracks`)
- MediaCapabilities (`navigator.mediaCapabilities`)
- MediaSession (`navigator.mediaSession`)
- Performance APIs (`performance.getEntriesByType`)
- VideoPlaybackQuality (`video.getVideoPlaybackQuality()`)

### Browser APIs NÃO Disponíveis

- `video.audioTracks` — Chrome não suporta AudioTrackList nativamente
- Por isso, seleção de áudio precisa ser feita via UI ou Shaka Player API

### Controles Visuais do Player (barra inferior)

Da esquerda para a direita:
1. **Logo do canal** (ex: ESPN2, CN)
2. **"Ao vivo"** (botão para ir ao vivo)
3. **Pause/Play** (⏸ / ▶)
4. **Picture-in-Picture** (📺)
5. **Volume** (🔊)
6. **Legendas/Áudio** (💬) — abre painel com "IDIOMA ALTERNATIVO" e "LEGENDAS"
7. **Settings/Fullscreen** (⊞) — último ícone, que TAMBÉM abre configurações em alguns canais

> **IMPORTANTE:** O ícone que abre as configurações de áudio/legenda pode variar entre o 💬 e o ⊞ dependendo do canal. O módulo de interação deve tentar ambos.

### Canais Monitorados

| ID | URL |
|----|-----|
| CH0100000000124 | https://www.skymais.com.br/player/live/CH0100000000124 |
| CH0100000000092 | https://www.skymais.com.br/player/live/CH0100000000092 |
| CH0100000000093 | https://www.skymais.com.br/player/live/CH0100000000093 |
| CH0100000000094 | https://www.skymais.com.br/player/live/CH0100000000094 |
| CH0100000000096 | https://www.skymais.com.br/player/live/CH0100000000096 |

---

## Capability Map — Exemplo Real (SKY+)

Resultado do discovery executado em 21/08/2026:

| Capability | Available | Confidence | Evidência Principal |
|---|---|---|---|
| settings | ✅ | 0.9 | window.player.configure, getConfiguration |
| quality_selection | ✅ | 1.0 | getVariantTracks, selectVariantTrack, getStats |
| subtitle_selection | ✅ | 0.8 | selectTextTrack, getTextTracks, TextTrackList |
| video_playback | ✅ | 0.7 | HTMLMediaElement, Performance, VideoPlaybackQuality |
| audio_selection | ❌ | 0.6 | getAudioTracks (JS) disponível mas video.audioTracks (browser) não |
| play | ❌ | 0.6 | video.play confirmado via behavioral test |
| pause | ❌ | 0.25 | video.pause disponível |
| fullscreen | ❌ | 0.25 | video.requestFullscreen disponível |
| mute/unmute | ❌ | 0.0 | Nenhuma API de mute encontrada |

---

## Pipeline de Escalação Determinística

```
Telemetria (2s) → Classificação → Escalação
                                    │
                    ┌───────────────┼────────────────┐
                    ▼               ▼                ▼
              HEALTHY          SUSPECT         DEGRADED/CRITICAL
              (nada)        (OpenCV)         (OpenCV + Bedrock)
                              │                    │
                              ▼                    ▼
                        OpenCV confirma?     OpenCV confirma?
                         Não → OK            Sim → Bedrock
                         Sim → Bedrock
```

---

## Dependências Python

```
playwright==1.40.0          # Automação de browser
opencv-python-headless==4.9.0.80  # Análise visual
numpy==1.26.4               # Operações numéricas
boto3==1.34.69              # AWS SDK (Bedrock)
pytest==8.1.1               # Testes
pytest-asyncio==0.23.5      # Testes assíncronos
hypothesis==6.99.13         # Property-based testing
dataclasses-json==0.6.4     # Serialização JSON de dataclasses
```

---

## Problemas Conhecidos e Soluções

| Problema | Causa | Solução |
|----------|-------|---------|
| Chrome não abre | DISPLAY não configurado | Rodar dentro da sessão RDP (DISPLAY=:10) |
| GPU process crashed | EC2 sem GPU | Remover `--disable-gpu` (PoC funciona sem) |
| Profile error | Profile corrompido | `rm -rf /data/chrome-profile && mkdir /data/chrome-profile` + reautenticar |
| Login pedido | Cookies expirados ou profile limpo | Rodar `setup_auth.py` para reautenticar |
| Chrome controlled by automation | Flag `--enable-automation` | Usar `ignore_default_args=["--enable-automation"]` |
| git pull: permission denied | SSM rodou como root | `sudo chown -R ubuntu:ubuntu ~/ChannelMonitoring` |
| Viewport corta controles | viewport fixo 1920x1080 | Usar `viewport=None` |
| audioTracks não funciona | Chrome não suporta | Usar Shaka Player API ou clicar na UI |

---

## Histórico de Specs

1. **widevine-poc** — Validação DRM (✅ Concluída, GO)
2. **player-discovery** — Descoberta dinâmica de capabilities (✅ 58/58 tasks)
3. **audio-subtitle-monitoring** — Teste de áudio/legendas via UI (🚧 Requisitos prontos)
