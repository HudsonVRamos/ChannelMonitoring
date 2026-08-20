FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Dependências de sistema para Widevine
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgbm1 \
    libasound2 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Dependências Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Código da PoC
COPY src/ /app/src/
COPY scripts/ /app/scripts/
WORKDIR /app

# Instalar browsers com Widevine CDM
RUN playwright install --with-deps chromium

# Variáveis de ambiente padrão
ENV LOG_LEVEL=INFO
ENV DISPLAY=:99

ENTRYPOINT ["python", "-m", "src"]
