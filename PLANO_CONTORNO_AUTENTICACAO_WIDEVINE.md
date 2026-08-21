# Plano de Contorno — Autenticação SKY+ + Widevine no Container

**Versão:** 2.1  
**Data:** 20/08/2026

## 1. Objetivo

A PoC demonstrou que o principal bloqueio atual não é necessariamente o Widevine, mas a autenticação da SKY+ quando uma sessão criada localmente é reutilizada em ambiente AWS.

Resultados principais:

- Playwright + Chrome em container funciona.
- Chrome + Xvfb inicia corretamente no CodeBuild.
- Screenshots funcionam.
- CI/CD, Docker, S3 e testes estão funcionando.
- `storageState` criado localmente não é reconhecido no ambiente AWS.
- Chromium headless não inicializa Widevine.
- Chrome + Xvfb + Widevine ainda não foi validado porque a autenticação bloqueou o teste real.

> **Não considerar Widevine como inviável ainda. O próximo objetivo é destravar a autenticação no próprio ambiente AWS e então testar Widevine de forma real.**

## 2. Estratégia Recomendada

A primeira tentativa deve ser realizar o login **dentro do próprio ambiente que executará o monitoramento**.

Em vez de:

```text
Chrome local
  ↓
login
  ↓
storageState
  ↓
AWS
```

testar:

```text
AWS
 ↓
Chrome + Xvfb
 ↓
SKY+
 ↓
login
 ↓
CAPTCHA
 ↓
sessão criada no próprio ambiente
 ↓
player
 ↓
Widevine
```

Isso elimina a transferência de uma sessão criada em outro computador.

## 3. Não Automatizar CAPTCHA no Primeiro Momento

A primeira validação deve ser manual:

```text
Chrome + Xvfb
       ↓
SKY+
       ↓
login
       ↓
CAPTCHA manual
       ↓
sessão
       ↓
player
```

Não utilizar CAPTCHA solver no próximo teste.

## 4. Teste 1 — Login Dentro do Container

### Ambiente

```text
Docker
Chrome
Xvfb
Playwright
```

Não utilizar `headless=True`.

### Procedimento

1. Iniciar Chrome + Xvfb.
2. Abrir SKY+.
3. Realizar login manual.
4. Resolver CAPTCHA manualmente.
5. Confirmar visualmente que o usuário está autenticado.
6. Navegar para um canal.
7. Verificar se o player aparece.
8. Capturar screenshot.
9. Registrar URL final.
10. Registrar sinais do player.

### Critério de sucesso

O screenshot deve mostrar conteúdo SKY+, e não `/acessar` ou tela de login.

## 5. Teste 2 — Persistência da Sessão

Depois que o login manual funcionar:

```text
Chrome
 ↓
login
 ↓
fecha página
 ↓
abre novamente
 ↓
continua autenticado?
```

## 6. Teste 3 — Perfil Completo do Chrome

A PoC mostrou que `storageState` não é suficiente. Testar o perfil completo.

```text
/data/chrome-profile/
```

Iniciar Chrome usando:

```text
--user-data-dir=/data/chrome-profile
```

Fluxo:

```text
Container
 ↓
Chrome
 ↓
login manual
 ↓
profile criado
 ↓
Chrome encerrado
 ↓
Chrome reiniciado
 ↓
profile reutilizado
 ↓
sessão continua?
```

O objetivo não é copiar o perfil do computador local. É criar o perfil no próprio ambiente AWS.

## 7. Teste 4 — Restart do Container

```text
Container A
 ↓
Chrome
 ↓
login
 ↓
profile
 ↓
container encerrado
```

Depois:

```text
Container B
 ↓
mesmo profile persistido
 ↓
Chrome
 ↓
SKY+
```

Verificar se a sessão continua válida.

## 8. Teste 5 — Investigar API de Autenticação

No Chrome real:

```text
DevTools
 → Network
 → Preserve log
```

Realizar login e identificar:

- request de login;
- request de refresh;
- responses;
- headers;
- cookies;
- localStorage;
- sessionStorage;
- tokens;
- device identifiers;
- chamadas posteriores ao login.

Investigar se existem:

```text
access_token
refresh_token
id_token
session_id
device_id
expires_at
```

## 9. Investigar `1633938:session-data`

A PoC identificou:

```text
localStorage
└── 1633938:session-data
```

Analisar:

- formato;
- validade;
- access token;
- refresh token;
- timestamps;
- identificadores de sessão;
- identificadores de dispositivo.

Não assumir a estrutura antes de inspecionar o valor real.

## 10. Teste 6 — Refresh Token

Se existir refresh token:

```text
access token
    ↓
expira
    ↓
refresh
    ↓
novo access token
    ↓
localStorage atualizado
```

Esse seria o cenário ideal para evitar novos logins.

## 11. Teste 7 — IP Binding

Comparar:

### A — Local

```text
Chrome local
+
login local
+
player local
```

### B — AWS

```text
Chrome AWS
+
login AWS
+
player AWS
```

### C — Sessão transferida

```text
sessão local
+
Chrome AWS
+
player AWS
```

Interpretação:

| Resultado | Hipótese |
|---|---|
| A funciona / B funciona / C falha | transferência de sessão ou device binding |
| A funciona / B falha / C falha | ambiente AWS/IP pode estar sendo bloqueado |
| A funciona / B funciona / C funciona | problema anterior estava no uso do storageState |
| B autentica mas player falha | investigar autorização do player/DRM |

## 12. Teste 8 — IP Fixo

Somente se houver evidência de comportamento relacionado a IP:

```text
VPC
 ↓
NAT Gateway
 ↓
Elastic IP
 ↓
Internet
 ↓
SKY+
```

Não criar NAT Gateway apenas por hipótese, devido ao custo adicional.

## 13. Teste 9 — EC2 como Ambiente de Bootstrap

Se login manual for necessário, considerar uma pequena EC2:

```text
EC2
 ├── Docker
 ├── Chrome
 ├── Xvfb
 └── Chrome Profile
```

O operador realiza login uma vez e a sessão fica naquele ambiente.

## 14. Não Migrar para Selenium Agora

Não trocar Playwright por Selenium nesta etapa.

A PoC já demonstrou que Playwright + Chrome + container + Xvfb funciona como infraestrutura.

O problema atual é autenticação, não automação.

## 15. Widevine — Próximo Teste Real

A PoC ainda não concluiu se Widevine funciona em:

```text
Chrome
+
Xvfb
+
container
```

porque a autenticação bloqueou o teste.

Depois de resolver a autenticação:

```text
Chrome + Xvfb
       ↓
SKY+ autenticado
       ↓
player
       ↓
EME
       ↓
Widevine
       ↓
license
       ↓
decrypt
       ↓
video playback
```

## 16. Teste Widevine Isolado

Executar também um teste independente da SKY+ usando um player DRM legítimo de teste.

Objetivo:

```text
Chrome + Xvfb
        ↓
EME
        ↓
Widevine
        ↓
DRM test stream
        ↓
playback
```

Isso separa:

```text
Problema A: Chrome/container/Widevine
Problema B: SKY+/autenticação/player
```

## 17. Arquitetura Provisória

Enquanto os testes não terminarem, não assumir ECS Fargate como definitivo.

### Opção 1 — ECS Service

```text
ECS Service
 ↓
Chrome + Xvfb
 ↓
profile persistente
```

### Opção 2 — EC2

```text
EC2
 ↓
Chrome + Xvfb
 ↓
profile local persistente
```

### Opção 3 — ECS + armazenamento persistente

```text
ECS
 ↓
Chrome
 ↓
persistent profile
 ↓
storage
```

Adotar somente depois de provar que o perfil pode ser reutilizado.

## 18. Arquitetura de Monitoramento Após Autenticação

```text
EventBridge
      ↓
Monitor Controller
      ↓
Playwright + Chrome
      ↓
SKY+ Player
      ↓
Detecção determinística
      ↓
OpenCV
      ↓
Bedrock somente se necessário
      ↓
S3
      ↓
CloudWatch
      ↓
SES / Slack
```

## 19. Detecção de Sessão

Não confiar somente na URL.

A PoC mostrou que verificar apenas a URL produzia falso positivo.

A detecção deve considerar conteúdo da página:

```text
formulário de login presente
```

ou:

```text
player ausente
```

ou:

```text
elementos de usuário autenticado ausentes
```

Estados:

```text
AUTHENTICATED
AUTH_EXPIRED
AUTH_REQUIRED
AUTH_UNKNOWN
```

## 20. O Que Não Fazer Ainda

Até completar os testes:

- não implementar CAPTCHA solver;
- não migrar para Selenium;
- não criar infraestrutura complexa de NAT;
- não assumir que storageState é inútil em todos os cenários;
- não assumir que Widevine não funciona em container;
- não escalar para centenas de canais;
- não implementar toda a camada Bedrock de produção.

## 21. Ordem Exata de Execução

### Etapa 1

```text
Chrome + Xvfb
+
login manual
+
SKY+
```

### Etapa 2

```text
login
+
player
```

### Etapa 3

```text
login
+
player
+
Widevine
```

### Etapa 4

```text
Chrome profile persistente
+
restart
+
sessão
```

### Etapa 5

```text
container restart
+
profile persistente
+
sessão
```

### Etapa 6

```text
Network
+
descoberta da API de autenticação
```

### Etapa 7

```text
refresh token
```

### Etapa 8

```text
IP fixo
```

somente se necessário.

### Etapa 9

```text
escolha final:
EC2 / ECS Service / ECS + storage
```

### Etapa 10

```text
monitoramento em 1 canal
```

### Etapa 11

```text
10 canais
```

### Etapa 12

```text
50+
```

## 22. Critérios de Sucesso

A arquitetura será considerada viável se conseguirmos:

```text
✓ Login no ambiente AWS
✓ CAPTCHA resolvido manualmente
✓ Sessão válida
✓ Player autenticado
✓ Widevine funcionando
✓ Reprodução real
✓ Áudio
✓ Frames
✓ CurrentTime
✓ Buffer
✓ Legendas
✓ Reinicialização do browser
✓ Persistência da sessão
```

Idealmente:

```text
✓ Restart do container
✓ Sessão continua válida
```

## 23. Critério de Decisão

### Cenário A — Tudo funciona no container

Prosseguir com:

```text
ECS Service
+
Chrome persistente
+
monitoramento
```

### Cenário B — Funciona apenas em ambiente persistente

Considerar:

```text
EC2
```

ou ECS Service com armazenamento adequado.

### Cenário C — AWS é bloqueado

Investigar:

```text
IP
ASN
WAF
bot protection
geolocalização
```

e avaliar IP fixo.

### Cenário D — Widevine falha no ambiente AWS

Testar EC2 com Chrome + Xvfb antes de abandonar a abordagem de browser.

### Cenário E — SKY+ exige autenticação impossível de automatizar

Solicitar ao time de produto:

- credencial de serviço;
- API;
- mecanismo oficial de autenticação;
- endpoint de autorização para monitoramento.

## 24. Conclusão

A PoC não deve ser interpretada como:

> "Widevine não funciona no Docker."

A conclusão correta neste momento é:

> **"A autenticação não foi reproduzida no ambiente AWS e impediu a validação real do Widevine."**

A estratégia mais promissora agora é:

```text
Chrome real
+
Xvfb
+
login dentro do próprio ambiente AWS
+
perfil persistente
+
teste real do player
+
Widevine
```

Em paralelo:

```text
DevTools Network
+
investigação do auth flow
+
session-data
+
refresh token
+
device/IP binding
```

O objetivo é eliminar a dependência de copiar uma sessão criada em outro computador.

## 25. Próxima Ação Recomendada

Implementar primeiro uma PoC pequena:

```text
POC-AUTH-01

Chrome + Xvfb no ambiente AWS
        ↓
abrir SKY+
        ↓
login manual
        ↓
CAPTCHA manual
        ↓
confirmar sessão
        ↓
navegar para canal
        ↓
capturar screenshot
        ↓
verificar player
        ↓
verificar Widevine
```

**Não avançar para produção antes desse teste.**
