# Widevine PoC — Monitoramento de Canais ao Vivo SKY+

Proof of Concept para validação do Widevine DRM com Playwright em container Docker. Esta PoC é a primeira etapa obrigatória do projeto de Monitoramento Inteligente de Canais ao Vivo da plataforma SKY+.

O objetivo é eliminar o maior risco técnico do projeto: confirmar que Widevine/DRM funciona dentro de um container Docker (e posteriormente ECS Fargate) antes de investir na infraestrutura de produção.

**Princípio central:** Canal saudável não deve consumir IA.

---

## Pré-requisitos

| Requisito | Versão mínima | Observação |
|-----------|---------------|------------|
| Python | 3.10+ | Com type hints (para desenvolvimento local) |
| AWS CLI | 2.x | Configurado com credenciais válidas |
| AWS Credentials | — | Acesso ao Amazon Bedrock (Claude Haiku e Sonnet) |
| AWS CodeBuild | — | Para build e execução containerizada |

> **Nota:** Não é necessário Docker Desktop local. O build e execução do container são feitos via AWS CodeBuild.

### Credenciais AWS

O módulo de diagnóstico visual utiliza o Amazon Bedrock. Configure suas credenciais:

```bash
aws configure
# Região recomendada: us-east-1 (suporte a Claude Haiku/Sonnet)
```

Ou exporte as variáveis de ambiente:

```bash
export AWS_ACCESS_KEY_ID=sua-access-key
export AWS_SECRET_ACCESS_KEY=sua-secret-key
export AWS_DEFAULT_REGION=us-east-1
```

> **Nota:** O Bedrock é utilizado apenas quando anomalias são detectadas pelas camadas anteriores. Se o canal estiver saudável, nenhuma chamada à IA será feita.

---

## Quick Start via AWS CodeBuild

### 1. Gerar o storageState (login manual — primeira vez)

Antes de rodar a PoC, é necessário gerar o arquivo `storageState.json` com a sessão autenticada na plataforma SKY+. Este processo é manual e precisa ser repetido quando a sessão expirar.

#### Opção A: Usando Playwright Codegen

```bash
# Instalar Playwright localmente (se ainda não tiver)
pip install playwright
playwright install chromium

# Abrir browser interativo para login manual
python -m playwright codegen --save-storage=storageState.json "https://www.skyplus.com.br"
```

1. O browser abrirá automaticamente
2. Faça login manualmente na plataforma SKY+
3. Navegue até um canal ao vivo para garantir que os cookies de reprodução sejam capturados
4. Feche o browser — o arquivo `storageState.json` será salvo automaticamente

#### Opção B: Browser manual com script de exportação

```bash
python -c "
import asyncio
from playwright.async_api import async_playwright

async def export_session():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto('https://www.skyplus.com.br')
        input('Faça login e pressione ENTER quando estiver logado...')
        await context.storage_state(path='storageState.json')
        await browser.close()
        print('storageState.json salvo com sucesso!')

asyncio.run(export_session())
"
```

### 2. Executar via AWS CodeBuild

A PoC executa em container Docker via CodeBuild. O `buildspec.yml` na raiz do projeto configura todo o pipeline.

#### Configurar o projeto CodeBuild:

1. **Source:** Apontar para o repositório Git deste projeto
2. **Environment:**
   - Imagem: `aws/codebuild/standard:7.0` (Ubuntu, privileged mode para Playwright)
   - Compute: Pelo menos 7 GB de memória (para Chromium + Widevine)
   - Privileged: Habilitado (necessário para shm_size adequado)
3. **Environment Variables:** Definir no projeto CodeBuild:
   - `POC_CHANNEL_URL` — URL do canal ao vivo para teste
   - `POC_STORAGE_STATE_PATH` — Caminho para o storageState no S3 ou inline
4. **Artifacts:** Configurar bucket S3 para receber `output/poc_report.json`

#### Upload do storageState para S3:

```bash
# Após gerar o storageState.json localmente
aws s3 cp storageState.json s3://seu-bucket/widevine-poc/storage_state/state.json
```

#### Iniciar build manualmente:

```bash
aws codebuild start-build \
  --project-name widevine-poc \
  --environment-variables-override \
    "name=POC_CHANNEL_URL,value=https://www.skyplus.com.br/canal/ao-vivo,type=PLAINTEXT" \
    "name=POC_STORAGE_STATE_PATH,value=storage_state/state.json,type=PLAINTEXT"
```

#### Artefatos gerados:

Após a execução, o CodeBuild exporta:
- `output/poc_report.json` — Relatório consolidado com decisão Go/No-Go
- `output/poc_execution.log` — Log completo da execução

### 3. Executar localmente (desenvolvimento e testes)

```bash
# Instalar dependências
pip install -r requirements.txt

# Instalar Chromium com Widevine
playwright install chromium

# Rodar testes
python -m pytest tests/ -v

# Executar a PoC (requer storageState e canal válidos)
POC_STORAGE_STATE_PATH=./storageState.json \
POC_CHANNEL_URL=https://www.skyplus.com.br/canal/ao-vivo \
python -m src
```

---

## Variáveis de Ambiente

Todas as configurações podem ser ajustadas via variáveis de ambiente com prefixo `POC_`:

| Variável | Descrição | Valor Padrão |
|----------|-----------|--------------|
| `POC_STORAGE_STATE_PATH` | Caminho para o arquivo storageState.json | `""` (obrigatório) |
| `POC_CHANNEL_URL` | URL do canal ao vivo para teste | `""` (obrigatório) |
| `POC_OUTPUT_DIR` | Diretório para relatórios e evidências | `./output` |
| `POC_LOG_LEVEL` | Nível mínimo de log (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `POC_SESSION_RESTORE_TIMEOUT` | Timeout para restaurar sessão (segundos) | `15` |
| `POC_DRM_TIMEOUT` | Timeout para inicialização DRM (segundos) | `15` |
| `POC_PLAYBACK_TIMEOUT` | Timeout para início da reprodução (segundos) | `30` |
| `POC_BEDROCK_TIMEOUT` | Timeout para chamadas ao Bedrock (segundos) | `30` |
| `POC_DOCKER_STARTUP_TIMEOUT` | Timeout para startup do container (segundos) | `60` |
| `POC_TELEMETRY_INTERVAL` | Intervalo de coleta de telemetria (segundos) | `2.0` |
| `POC_TELEMETRY_DURATION` | Duração total da coleta de telemetria (segundos) | `30.0` |
| `POC_FRAME_INTERVAL` | Intervalo entre capturas de frame (1-60 segundos) | `5.0` |
| `POC_FRAME_MIN_RESOLUTION` | Resolução mínima aceita (formato WIDTHxHEIGHT) | `1280x720` |
| `POC_FRAME_MAX_SIZE` | Tamanho máximo do frame em bytes | `5242880` (5 MB) |
| `POC_BLACK_SCREEN_LUMINANCE_THRESHOLD` | Threshold de luminância para tela preta | `10.0` |
| `POC_FREEZE_SIMILARITY_THRESHOLD` | Threshold de similaridade SSIM para freeze | `0.98` |
| `POC_BUFFERING_THRESHOLD` | Tempo máximo de buffering antes de alerta (segundos) | `10.0` |
| `POC_BEDROCK_REGION` | Região AWS para chamadas ao Bedrock | `us-east-1` |
| `POC_BEDROCK_CONFIDENCE_THRESHOLD` | Confiança mínima para aceitar diagnóstico Haiku | `0.7` |

Exemplo de uso:

```bash
POC_STORAGE_STATE_PATH=./storageState.json \
POC_CHANNEL_URL=https://www.skyplus.com.br/canal/ao-vivo \
POC_LOG_LEVEL=DEBUG \
python -m src.poc_orchestrator
```

---

## Executar Testes

```bash
# Instalar dependências de desenvolvimento
pip install -r requirements.txt

# Rodar todos os testes
pytest

# Rodar apenas testes unitários
pytest tests/test_*.py --ignore=tests/test_prop_*.py

# Rodar apenas property-based tests
pytest tests/test_prop_*.py

# Rodar testes de um módulo específico
pytest tests/test_opencv_analyzer.py -v

# Rodar com output detalhado
pytest -v --tb=short
```

Os property-based tests usam [Hypothesis](https://hypothesis.readthedocs.io/) e geram automaticamente casos de teste para validar propriedades universais dos componentes.

---

## Interpretação do Relatório Go/No-Go

Ao final da execução, a PoC gera um relatório JSON em `output/` com a decisão consolidada.

### Decisão Geral

| Decisão | Significado |
|---------|-------------|
| **GO** | Todas as validações críticas passaram. Widevine funciona em Docker. Prosseguir com infraestrutura de produção. |
| **NO_GO** | Alguma validação crítica falhou. Há risco técnico não resolvido. Investigar antes de prosseguir. |

### Validações Críticas (determinam Go/No-Go)

| Validação | O que testa |
|-----------|-------------|
| `login` | Sessão pode ser restaurada via storageState |
| `drm` | Widevine CDM inicializa e obtém licença |
| `frames` | Frames de conteúdo DRM podem ser capturados |
| `docker` | Todo o pipeline funciona dentro do container |

### Status por Validação

| Status | Significado |
|--------|-------------|
| `PASS` | Validação executada com sucesso |
| `FAIL` | Validação falhou — consulte `error_message` e `evidence_paths` no relatório |
| `SKIPPED` | Validação não executada porque uma dependência anterior falhou |

### Cadeia de Dependências

```
Auth/Login → DRM → Playback/Telemetria → Frames → OpenCV → Bedrock
```

Se uma etapa falha, as etapas dependentes são automaticamente marcadas como `SKIPPED`.

### Exemplo de Relatório

```json
{
  "execution_id": "poc-20240115-143022",
  "decision": "GO",
  "total_duration_ms": 45230,
  "validations": [
    {"name": "login", "status": "PASS", "duration_ms": 3200},
    {"name": "drm", "status": "PASS", "duration_ms": 8500},
    {"name": "telemetry", "status": "PASS", "duration_ms": 32000},
    {"name": "frames", "status": "PASS", "duration_ms": 12000},
    {"name": "opencv", "status": "PASS", "duration_ms": 800},
    {"name": "bedrock", "status": "SKIPPED", "skipped_reason": "Nenhuma anomalia detectada"}
  ],
  "performance": {
    "browser_init_time_ms": 2100,
    "drm_ready_time_ms": 8500,
    "time_per_frame_ms": 450,
    "bedrock_response_time_ms": null
  },
  "log_file_path": "./output/poc-20240115-143022.log"
}
```

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                      Docker Container                             │
│                                                                   │
│  ┌─────────────────┐                                             │
│  │ PoC Orchestrator│──────────────────────────────────┐          │
│  └────────┬────────┘                                  │          │
│           │                                           ▼          │
│  ┌────────▼────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Auth Manager   │  │ DRM Validator│  │ Report Generator │   │
│  └────────┬────────┘  └──────┬───────┘  └──────────────────┘   │
│           │                   │                                   │
│  ┌────────▼───────────────────▼────────┐                         │
│  │     Playwright + Chromium + CDM     │                         │
│  └────────┬───────────────────┬────────┘                         │
│           │                   │                                   │
│  ┌────────▼────────┐  ┌──────▼───────┐                          │
│  │Telemetry Collect│  │Frame Capturer│                          │
│  └─────────────────┘  └──────┬───────┘                          │
│                               │                                   │
│  ┌────────────────────────────▼────────┐                         │
│  │         OpenCV Analyzer             │                         │
│  │  (Tela Preta / Freeze / Buffering)  │                         │
│  └────────────────────────────┬────────┘                         │
│                               │ (somente se anomalia)            │
│  ┌────────────────────────────▼────────┐                         │
│  │         Bedrock Client              │                         │
│  │    (Claude Haiku → Sonnet)          │                         │
│  └─────────────────────────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  SKY+ Platform      │
                    │  (Canal ao Vivo)    │
                    └─────────────────────┘
```

### Hierarquia de Detecção

O sistema segue uma abordagem em camadas para minimizar custos de IA:

1. **Telemetria do Player** — Detecta problemas óbvios (currentTime parado, buffering)
2. **Regras Determinísticas** — Classifica falhas críticas sem IA
3. **OpenCV** — Análise visual de frames (tela preta, freeze, similaridade)
4. **Bedrock (Haiku)** — Diagnóstico visual quando anomalia é confirmada
5. **Bedrock (Sonnet)** — Escalação quando confiança do Haiku é baixa

Canal saudável: apenas camadas 1-2 são executadas (custo zero de IA).

---

## Troubleshooting

### Sessão expirada / Redirect para login

```
ERROR - storageState classificado como expirado
```

**Solução:** Gere novamente o `storageState.json` seguindo o processo de login manual descrito acima. Cookies de sessão da plataforma SKY+ expiram periodicamente.

### Widevine CDM não inicializa no Docker

```
ERROR - CDM falha na inicialização
```

**Possíveis causas:**
- Bibliotecas de sistema faltando — verifique se o Dockerfile inclui: `libnss3`, `libatk1.0-0`, `libgbm1`, `libasound2`, `libxrandr2`, `libpango-1.0-0`
- Permissões insuficientes — o Chrome precisa de `--no-sandbox` em containers
- Imagem base incorreta — use `mcr.microsoft.com/playwright/python:v1.40.0-jammy`

### Frames capturados são tela preta

```
WARNING - Frame descartado: luminância média ≤ 16 (possível proteção DRM)
```

**Possíveis causas:**
- Proteção DRM impedindo captura de tela — este é justamente o risco que a PoC valida
- Canal fora do ar ou conteúdo indisponível
- storageState expirado (DRM não está decifrando o conteúdo)

### Bedrock timeout ou erro de API

```
ERROR - Bedrock timeout (30s) ou erro de API
```

**Possíveis causas:**
- Credenciais AWS não configuradas ou sem permissão para Bedrock
- Região incorreta — verifique se `POC_BEDROCK_REGION` aponta para região com suporte a Claude
- Limite de taxa atingido — aguarde e tente novamente

### Testes falhando localmente

```bash
# Verificar se todas as dependências estão instaladas
pip install -r requirements.txt

# Verificar se o Playwright está instalado
playwright install chromium

# Rodar com mais detalhes
pytest -v --tb=long
```

### Container não inicia (timeout 60s)

**Possíveis causas:**
- Recursos insuficientes — Chromium precisa de pelo menos 2GB de RAM
- Rede bloqueada — o container precisa de acesso à internet para licença DRM
- Volume do storageState não montado corretamente

---

## Estrutura do Projeto

```
CHANNEL_MONITORING/
├── src/
│   ├── __init__.py
│   ├── __main__.py              # Entry point
│   ├── poc_orchestrator.py      # Orquestrador principal
│   ├── auth_manager.py          # Autenticação e storageState
│   ├── drm_validator.py         # Validação do Widevine CDM
│   ├── telemetry_collector.py   # Coleta de métricas do player
│   ├── frame_capturer.py        # Captura de screenshots
│   ├── opencv_analyzer.py       # Análise visual (tela preta, freeze)
│   ├── bedrock_client.py        # Diagnóstico via IA (Haiku/Sonnet)
│   ├── buffering_detector.py    # Detecção de buffering persistente
│   ├── report_generator.py      # Relatório Go/No-Go
│   ├── structured_logger.py     # Logger JSON estruturado
│   ├── models.py                # Data models e enums
│   └── config.py                # Configuração com env vars
├── tests/
│   ├── test_*.py                # Unit tests
│   └── test_prop_*.py           # Property-based tests (Hypothesis)
├── output/                      # Relatórios e evidências (gerados)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## Licença

Projeto interno — uso restrito à equipe de desenvolvimento SKY+.
