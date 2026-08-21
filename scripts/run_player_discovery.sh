#!/bin/bash
# =============================================================================
# Script de execução do Player Discovery na EC2
#
# Uso:
#   ./scripts/run_player_discovery.sh
#   ./scripts/run_player_discovery.sh --continuous    (modo loop infinito)
#
# Requer:
#   - Chrome instalado (Google Chrome stable)
#   - Xvfb (display virtual)
#   - Python 3.11+ com dependências instaladas
#   - Chrome profile com sessão autenticada em /data/chrome-profile
#
# Variáveis de ambiente opcionais (override):
#   PLAYER_DISCOVERY_OBSERVATION_PERIOD_S  (padrão: 30)
#   PLAYER_DISCOVERY_TELEMETRY_INTERVAL_S  (padrão: 2.0)
#   PLAYER_DISCOVERY_FUNCTIONAL_TEST_INTERVAL (padrão: 5)
#   PLAYER_DISCOVERY_LOG_LEVEL  (padrão: INFO)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

echo "============================================================"
echo "  Player Discovery — Monitoramento SKY+ Multi-Canal"
echo "============================================================"
echo "  Projeto: $PROJECT_DIR"
echo "  Data: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# --- 1. Matar processos Chrome antigos ---
echo "[1/5] Limpando processos Chrome anteriores..."
pkill -f "chrome" 2>/dev/null || true
sleep 2

# --- 2. Configurar display ---
echo "[2/5] Configurando display..."

# Se DISPLAY já está definido e funcional, usar esse
if [ -n "$DISPLAY" ] && xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    echo "  Usando display existente: $DISPLAY"
    USE_XVFB_RUN=false
else
    echo "  Nenhum display funcional detectado — usando xvfb-run"
    USE_XVFB_RUN=true
fi

# --- 3. Configurar variáveis de ambiente ---
echo "[3/5] Configurando variáveis de ambiente..."

# Diretório do Chrome profile com sessão autenticada
export CHROME_PROFILE_DIR="${CHROME_PROFILE_DIR:-/data/chrome-profile}"

# Configurações do Player Discovery (podem ser overridados externamente)
export PLAYER_DISCOVERY_OBSERVATION_PERIOD_S="${PLAYER_DISCOVERY_OBSERVATION_PERIOD_S:-30}"
export PLAYER_DISCOVERY_TELEMETRY_INTERVAL_S="${PLAYER_DISCOVERY_TELEMETRY_INTERVAL_S:-2.0}"
export PLAYER_DISCOVERY_FUNCTIONAL_TEST_INTERVAL="${PLAYER_DISCOVERY_FUNCTIONAL_TEST_INTERVAL:-5}"
export PLAYER_DISCOVERY_INVALIDATION_THRESHOLD="${PLAYER_DISCOVERY_INVALIDATION_THRESHOLD:-3}"
export PLAYER_DISCOVERY_DEBOUNCE_WINDOW_MS="${PLAYER_DISCOVERY_DEBOUNCE_WINDOW_MS:-500}"

# Log
export PLAYER_DISCOVERY_LOG_LEVEL="${PLAYER_DISCOVERY_LOG_LEVEL:-INFO}"

# Output
export PLAYER_DISCOVERY_OUTPUT_DIR="${PLAYER_DISCOVERY_OUTPUT_DIR:-./output}"
mkdir -p "$PLAYER_DISCOVERY_OUTPUT_DIR"

# Lista de canais SKY+ para monitorar
export PLAYER_DISCOVERY_CHANNELS="${PLAYER_DISCOVERY_CHANNELS:-https://www.skymais.com.br/player/live/CH0100000000124,https://www.skymais.com.br/player/live/CH0100000000001,https://www.skymais.com.br/player/live/CH0100000000002}"

echo "  CHROME_PROFILE_DIR=$CHROME_PROFILE_DIR"
echo "  OBSERVATION_PERIOD=${PLAYER_DISCOVERY_OBSERVATION_PERIOD_S}s"
echo "  TELEMETRY_INTERVAL=${PLAYER_DISCOVERY_TELEMETRY_INTERVAL_S}s"
echo "  FUNCTIONAL_TEST_INTERVAL=a cada ${PLAYER_DISCOVERY_FUNCTIONAL_TEST_INTERVAL} rotações"
echo "  LOG_LEVEL=$PLAYER_DISCOVERY_LOG_LEVEL"
echo "  OUTPUT_DIR=$PLAYER_DISCOVERY_OUTPUT_DIR"
echo "  CANAIS=$(echo $PLAYER_DISCOVERY_CHANNELS | tr ',' '\n' | wc -l) canais configurados"

# --- 4. Verificar dependências ---
echo "[4/5] Verificando dependências..."

if ! python3 -c "import playwright" 2>/dev/null; then
    echo "  ERRO: playwright não instalado. Execute: pip install playwright"
    exit 1
fi

if ! which google-chrome-stable > /dev/null 2>&1; then
    echo "  AVISO: google-chrome-stable não encontrado. Usando Chromium do Playwright."
fi

if [ ! -d "$CHROME_PROFILE_DIR" ]; then
    echo "  AVISO: Chrome profile não encontrado em $CHROME_PROFILE_DIR"
    echo "  O discovery vai funcionar mas sem autenticação SKY+."
    echo "  Para gerar o profile: python3 scripts/generate_storage_state.py"
fi

# --- 5. Executar Player Discovery ---
echo "[5/5] Iniciando Player Discovery..."
echo "============================================================"
echo ""

MODE="${1:-single}"

if [ "$MODE" == "--continuous" ] || [ "$MODE" == "-c" ]; then
    echo ">>> Modo CONTÍNUO (Ctrl+C para parar)"
    echo ""
    if [ "$USE_XVFB_RUN" = true ]; then
        xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" \
            python3 -m src.player_discovery.run --continuous
    else
        python3 -m src.player_discovery.run --continuous
    fi
else
    echo ">>> Modo SINGLE (uma rotação completa)"
    echo ""
    if [ "$USE_XVFB_RUN" = true ]; then
        xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" \
            python3 -m src.player_discovery.run
    else
        python3 -m src.player_discovery.run
    fi
fi

EXIT_CODE=$?

echo ""
echo "============================================================"
echo "  Player Discovery finalizado (exit_code=$EXIT_CODE)"
echo "  Relatórios em: $PLAYER_DISCOVERY_OUTPUT_DIR/"
echo "============================================================"

exit $EXIT_CODE
