# Relatório da PoC Widevine DRM — Resultados

**Data:** 20/08/2026  
**Projeto:** Monitoramento Inteligente de Canais ao Vivo SKY+  
**Objetivo:** Validar se Widevine DRM funciona dentro de container Docker (CodeBuild/ECS Fargate)

---

## Resumo Executivo

| Validação | Status | Observação |
|-----------|--------|------------|
| Autenticação (storageState) | ✅ PASS | Sessão restaurada em ~2s |
| Playwright + Chromium em container | ✅ PASS | Browser inicializa em ~200ms |
| Navegação para player skymais | ✅ PASS | Página carrega sem redirect de login |
| Widevine CDM (headless) | ❌ FAIL | MediaKeys não criado — CDM não inicializa em headless |
| Widevine CDM (Xvfb + headed) | ⏱️ TIMEOUT | Container trava — player não inicia reprodução |
| Coleta de telemetria | ⊘ SKIPPED | Dependência: DRM |
| Captura de frames | ⊘ SKIPPED | Dependência: DRM |
| OpenCV + Bedrock | ⊘ SKIPPED | Dependência: Frames |

**Decisão:** NO_GO para Widevine em container headless puro. Necessária investigação adicional com Xvfb/ECS.

---

## Testes Executados no CodeBuild

### Build 1 — Ambiente Standard (sem Docker)
- **ID:** `eede510b-9eed-4a3d-9003-5b70e53f008a`
- **Ambiente:** `aws/codebuild/standard:7.0` (Python 3.11)
- **Resultado:** Login PASS, DRM FAIL
- **Motivo:** Imagem standard não tem Widevine CDM

### Build 2 — Docker com Playwright (headless=True)
- **ID:** `469f52e3-7b80-4ecc-ba3a-5255a27bfd33`
- **Ambiente:** Docker `mcr.microsoft.com/playwright/python:v1.40.0-jammy`
- **Resultado:** Login PASS (1.97s), DRM FAIL (15s timeout)
- **Erro:** "Timeout (15s): MediaKeys não foi criado"
- **Análise:** Chromium headless não ativa EME/Widevine. O CDM existe mas não inicializa sem display.

### Build 3 — Docker com Playwright (headless=False) + tentativa de play
- **ID:** `3298654c-a6e5-4a7c-8bc5-c852fdc14919`
- **Ambiente:** Mesmo Docker, `headless=False`, flags: `--no-sandbox`, `--disable-web-security`
- **Resultado:** Login PASS (2.26s), DRM FAIL (15s timeout)
- **Erro:** Mesmo — MediaKeys não criado
- **Análise:** `headless=False` sem display real/virtual não ajuda

### Build 4 — Docker com Xvfb (display virtual) + headed
- **ID:** `a20ef032-0a5e-47ac-baef-55f6e325b087`
- **Ambiente:** Docker + `xvfb-run` + `headless=False` + `DISPLAY=:99`
- **Resultado:** TIMED_OUT (827s / 14 min)
- **Análise:** O Chromium inicia com Xvfb mas o player da skymais trava. Possíveis causas:
  - Player precisa de interação JavaScript específica não coberta
  - O CDM inicializa mas a licença não é solicitada (player não detecta vídeo DRM)
  - A página carrega mas o stream não inicia sem user gesture adicional

### Build 5 — Docker com Xvfb + timeout forçado + DEBUG logs
- **ID:** `c1365d37-b0bb-4841-9fe4-3eba0e9784cd`
- **Ambiente:** Mesmo + `timeout --signal=KILL 180` + `DRM_TIMEOUT=60s`
- **Resultado:** TIMED_OUT (CodeBuild 15min limit)
- **Análise:** O `timeout` não propaga KILL para Docker-in-Docker. Container fica pendurado indefinidamente.

---

## Conclusões Técnicas

### O que funciona ✅

1. **StorageState/Sessão:** Playwright restaura sessão da skymais via storageState sem problemas. Cookies válidos, sem redirect para login.

2. **Playwright em Docker:** Browser inicializa em ~200ms, navega normalmente, JavaScript funciona.

3. **Pipeline CI/CD:** CodeBuild + CDK + S3 + SSM Parameter Store funcionam corretamente. Testes unitários (290) passam no container.

4. **Arquitetura de módulos:** Todos os 12 módulos Python funcionam isoladamente com testes passando.

### O que não funciona ❌

1. **Widevine CDM em headless:** O Chromium do Playwright v1.40 não ativa EME (Encrypted Media Extensions) em modo headless. `navigator.requestMediaKeySystemAccess` nunca é chamado pelo player.

2. **Docker-in-Docker timeout:** Sinais de timeout (SIGKILL) não propagam corretamente no Docker-in-Docker do CodeBuild.

### Inconclusivo ⏱️

1. **Widevine com Xvfb:** O container com display virtual inicia mas trava. Não foi possível confirmar se o CDM ativa com Xvfb porque o player da skymais não inicia a reprodução automaticamente no container.

---

## Recomendações para Investigação

### 1. Verificar se o player inicia (prioridade alta)
- Capturar screenshot do browser dentro do container para ver o estado visual da página
- Verificar se há botão de play, modal de termos, ou overlay bloqueando
- Tentar `page.evaluate('document.querySelector("video").play()')` direto

### 2. Testar com player DRM genérico
- Usar https://bitmovin.com/demos/drm ou https://demo.castlabs.com/ como URL de teste
- Se o CDM funcionar com player genérico, o problema é específico do player da skymais

### 3. Atualizar Playwright
- Versão 1.40 é de 2023. Versões mais recentes (v1.49+) têm melhor suporte a CDM
- Testar com `mcr.microsoft.com/playwright/python:v1.49.0-jammy`

### 4. Usar Chrome em vez de Chromium
- Chromium open source NÃO inclui Widevine. Chrome (Google) sim.
- Opção: instalar Google Chrome no container e usar `channel="chrome"` no Playwright

### 5. ECS Fargate com Xvfb
- Para produção, ECS Fargate com task definition configurando shm_size e Xvfb
- Mais recurso (CPU/memória) pode resolver o travamento

---

## Métricas de Performance Coletadas

| Métrica | Valor |
|---------|-------|
| Browser init (Docker Playwright) | 194-215 ms |
| Browser init (Standard CodeBuild) | 3.512 ms |
| Session restore (storageState) | 1.970-2.406 ms |
| DRM timeout (antes de falhar) | 15.000-15.434 ms |
| Docker build (imagem Playwright) | 53-83 s |
| Testes unitários (290 testes) | 56-70 s |

---

## Infraestrutura Deployada

| Recurso | Identificador | Região |
|---------|---------------|--------|
| Stack CloudFormation | `widevine-poc-stack` | us-east-1 |
| CodeBuild Project | `widevine-poc` | us-east-1 |
| S3 Bucket | `widevine-poc-artifacts-us-east-1-761018874615` | us-east-1 |
| SSM Parameter | `/widevine-poc/channel-url` | us-east-1 |
| SSM Parameter | `/widevine-poc/storage-state-path` | us-east-1 |
| SSM Parameter | `/widevine-poc/log-level` | us-east-1 |
| CodeStar Connection | GitHub `HudsonVRamos/ChannelMonitoring` | us-east-1 |

---

## Código Entregue

- **12 módulos Python** com type hints (Python 3.10+)
- **290 testes** (unit + property-based com Hypothesis)
- **17 correctness properties** validadas via PBT
- **Dockerfile** com Playwright + Widevine + Xvfb
- **buildspec.yml** para CodeBuild
- **CDK Stack** (infra completa)
- **Script de geração de storageState**

---

## Próximos Passos

1. [ ] Investigar por que o player da skymais não inicia no container
2. [ ] Testar com Google Chrome (em vez de Chromium) — tem Widevine built-in
3. [ ] Capturar screenshot dentro do container para diagnóstico visual
4. [ ] Testar com player DRM genérico para isolar se é problema do CDM ou do player
5. [ ] Considerar Playwright v1.49+ com melhor suporte a DRM
