FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Dependências de sistema para Widevine + Xvfb (display virtual)
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgbm1 \
    libasound2 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    xvfb \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Instalar Google Chrome (tem Widevine CDM built-in)
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && dpkg -i google-chrome-stable_current_amd64.deb || apt-get -fy install \
    && rm google-chrome-stable_current_amd64.deb

# Dependências Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Código da PoC
COPY src/ /app/src/
COPY scripts/ /app/scripts/
WORKDIR /app

# Variáveis de ambiente padrão
ENV LOG_LEVEL=INFO
ENV DISPLAY=:99

# Entrypoint com Xvfb (display virtual para Widevine DRM)
ENTRYPOINT ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1920x1080x24", "python", "-m", "src"]
