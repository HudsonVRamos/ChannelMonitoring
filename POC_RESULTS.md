# Relatório da PoC Widevine DRM — Resultados

**Data:** 20-21/08/2026  
**Projeto:** Monitoramento Inteligente de Canais ao Vivo SKY+  
**Objetivo:** Validar se Widevine DRM funciona dentro de container Docker (CodeBuild/ECS Fargate)  
**Plataforma alvo:** https://www.skymais.com.br

---

## Resumo Executivo

| Validação | Status | Observação |
|-----------|--------|------------|
| Autenticação (storageState) | ❌ FAIL | Sessão não persiste — server redireciona para login |
| Detecção de sessão expirada | ✅ OK | Sistema detecta corretamente quando não está logado |
| Playwright + Chrome em container | ✅ PASS | Browser inicializa em ~5s com Xvfb |
| Widevine CDM (headless) | ❌ FAIL | CDM não inicializa sem display |
| Widevine CDM (Chrome + Xvfb) | ⏱️ Inconclusivo | Não testado — bloqueado pela autenticação |
| Capturar screenshot diagnóstico | ✅ PASS | Screenshots funcionam no container |

**Decisão: NO_GO — Bloqueado pela autenticação**

O principal blocker não é o Widevine em si, mas a **impossibilidade de manter sessão autenticada** na plataforma skymais em ambiente remoto.

---

## Achados Técnicos Detalhados

### 1. Autenticação — Blocker Principal

A plataforma skymais.com.br usa um sistema de autenticação que **não é replicável via storageState**:

- **Cookies:** Todos os 43 cookies capturados são de tracking/analytics (GA, Facebook, Criteo, TikTok). Nenhum é cookie de sessão da SKY+.
- **localStorage:** Contém `1633938:session-data` com token, mas o server não reconhece a sessão quando acessada de IP diferente.
- **Captcha:** A página de login usa captcha que bloqueia Playwright/Chromium (detecta automação).
- **Comportamento:** Mesmo com storageState válido (gerado localmente com Chrome real), o server redireciona para `/acessar` quando acessado do CodeBuild.

**Conclusão:** A autenticação da skymais provavelmente valida:
1. IP de origem (CodeBuild tem IP diferente do local)
2. Fingerprint do browser
3. Token de curta duração que expira entre geração local e uso no CodeBuild

### 2. Widevine CDM

| Ambiente | Resultado |
|----------|-----------|
| Chromium headless (Playwright) | ❌ CDM não inicializa — EME desabilitado |
| Chromium headed sem display | ❌ Falha — sem display não funciona |
| Chrome + Xvfb (display virtual) | ⏱️ Inconclusivo — bloqueado por auth |
| Docker-in-Docker | ❌ Timeout não propaga signals |
| CodeBuild direto + Xvfb | ✅ Chrome inicia corretamente |

### 3. Pipeline CI/CD — Funcionando

| Componente | Status |
|------------|--------|
| CDK Deploy (us-east-1) | ✅ |
| CodeBuild Project | ✅ |
| S3 Artifacts | ✅ |
| SSM Parameter Store | ✅ |
| CodeStar Connection (GitHub) | ✅ |
| Docker build (imagem Playwright) | ✅ |
| Testes unitários no CI | ✅ (290 passando) |
| Screenshots diagnóstico | ✅ |
| Relatório JSON com decisão | ✅ |

### 4. Código — Completo e Testado

- 12 módulos Python implementados
- 290 testes passando (unit + property-based)
- 17 correctness properties validadas
- Detecção de sessão por conteúdo (formulário de login) funcionando

---

## Builds Executados

| # | Build ID | Ambiente | Resultado | Motivo |
|---|----------|----------|-----------|--------|
| 1 | eede510b | CodeBuild Standard | Login PASS, DRM FAIL | Chromium sem Widevine |
| 2 | 469f52e3 | Docker Playwright headless | Login PASS*, DRM FAIL (15s) | headless=True sem CDM |
| 3 | 3298654c | Docker Playwright headed | Login PASS*, DRM FAIL (15s) | Sem display real |
| 4 | a20ef032 | Docker + Xvfb | TIMEOUT (14min) | Docker-in-Docker trava |
| 5 | c1365d37 | Docker + Xvfb + kill | TIMEOUT | Signals não propagam |
| 6 | 37868d37 | CodeBuild + Chrome + Xvfb | Login PASS*, DRM FAIL (15s) | Auth falso-positivo |
| 7 | 7ecc6b85 | CodeBuild + Chrome + Xvfb + screenshot | Login PASS*, DRM FAIL | Screenshot = tela de login! |
| 8 | 031a6c3d | + detecção por conteúdo | PRE_BUILD FAIL | Teste quebrado |
| 9 | 30914e1b | Fix testes | Login PASS*, DRM FAIL (15s) | Detecção não pegou (JS lento) |
| 10 | 6b25881c | + wait 3s + timeout 60s + DEBUG | Login PASS*, DRM FAIL (60s timeout) | |
| 11 | b3213bb8 | + novo storageState c/ localStorage | **Login FAIL (correto!)** | Sessão não reconhecida |

*Login PASS = falso positivo (URL não contém padrão de login, mas conteúdo mostra login)

---

## Opções para Contornar o Blocker de Autenticação

### Opção A: Login Programático via API (Recomendada)

Investigar a API de autenticação da skymais (provavelmente OAuth2/OIDC) e fazer login via requests HTTP direto, sem browser:

```python
# Exemplo conceitual
response = requests.post("https://api.skymais.com.br/auth/login", json={
    "email": "user@email.com",
    "password": "senha"
})
token = response.json()["access_token"]
# Injetar token no localStorage via page.evaluate()
```

**Prós:** Não depende de captcha, não depende de IP  
**Contras:** Precisa descobrir a API de auth, pode mudar

### Opção B: VPN/IP Fixo no CodeBuild

Usar VPC com NAT Gateway com IP fixo elástico para que o CodeBuild sempre use o mesmo IP que o ambiente local:

**Prós:** Resolve se o blocker for IP-based  
**Contras:** Custo adicional, pode não resolver se for fingerprint

### Opção C: Selenium/CDP com Chrome Real + Perfil Persistente

Usar um approach diferente do Playwright — iniciar Chrome com perfil real (User Data Dir) montado como volume:

**Prós:** Máximo de compatibilidade  
**Contras:** Perfil do Chrome é grande (~GB), complexo de manter

### Opção D: Interceptar Token via Proxy (MitM)

Usar mitmproxy para capturar o token de autenticação quando o usuário loga localmente, e re-injetar no container:

**Prós:** Funciona independente do mecanismo de auth  
**Contras:** Complexidade operacional

### Opção E: Parceria com Time de Produto SKY+

Solicitar credenciais de serviço / API key dedicada para monitoramento:

**Prós:** Solução limpa e sustentável  
**Contras:** Dependência de outro time, processo pode ser lento

---

## Métricas de Performance

| Métrica | Valor |
|---------|-------|
| Browser init (Chrome + Xvfb) | 5.423 ms |
| Browser init (Docker Playwright) | 194-215 ms |
| Session restore (storageState) | 2.000-2.500 ms |
| Detecção de login (conteúdo) | ~5.000 ms |
| DRM timeout (Chromium headless) | 15.000 ms |
| Docker build (imagem Playwright) | 53-89 s |
| Testes unitários (290 testes) | 56-70 s |
| Pipeline completo (install→post) | ~190 s |

---

## Infraestrutura Deployada

| Recurso | Identificador | Região |
|---------|---------------|--------|
| Stack CloudFormation | `widevine-poc-stack` | us-east-1 |
| CodeBuild Project | `widevine-poc` | us-east-1 |
| S3 Bucket | `widevine-poc-artifacts-us-east-1-761018874615` | us-east-1 |
| SSM Parameters | `/widevine-poc/*` | us-east-1 |
| CodeStar Connection | GitHub `HudsonVRamos/ChannelMonitoring` | us-east-1 |

---

## Próximos Passos

1. [ ] **Investigar API de auth da skymais** — usar DevTools Network para capturar as chamadas de login e replicar programaticamente
2. [ ] **Testar com token injetado** — se conseguir o token via API, injetar no localStorage via `page.evaluate()` antes de navegar
3. [ ] **Testar Widevine isolado** — usar player DRM genérico (Bitmovin/CastLabs) para confirmar que Chrome + Xvfb + Widevine funciona (sem dependência da auth skymais)
4. [ ] **Avaliar VPC + IP fixo** — se a validação de sessão for IP-based
5. [ ] **Alinhar com time de produto** — solicitar mecanismo de auth para monitoramento automatizado
