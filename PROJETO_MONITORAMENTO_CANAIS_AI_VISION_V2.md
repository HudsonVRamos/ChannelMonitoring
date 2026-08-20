# Projeto v2 — Monitoramento Inteligente de Canais ao Vivo com Diagnóstico por IA

**Versão:** 2.0  
**Data:** 20/08/2026  
**Objetivo:** monitorar canais ao vivo com baixo custo, alta confiabilidade e uso seletivo de IA.

---

## 1. Resumo Executivo

Este projeto propõe um sistema automatizado para monitoramento da qualidade de canais ao vivo da plataforma SKY+, utilizando Playwright/Chromium para reprodução autenticada do conteúdo protegido por DRM e uma arquitetura em camadas para detecção de problemas.

A principal mudança em relação à arquitetura anterior é retirar a IA do caminho principal de monitoramento.

O sistema será dividido em quatro níveis:

1. **Aquisição e telemetria:** Playwright reproduz o canal e coleta informações do player.
2. **Detecção determinística:** regras objetivas identificam falhas sem custo de IA.
3. **Análise visual barata:** OpenCV compara frames e confirma anomalias visuais.
4. **Diagnóstico por IA:** Amazon Bedrock é acionado somente quando existe uma anomalia que exige interpretação visual ou diagnóstico mais complexo.

### Princípio central

> **Canal saudável não deve consumir IA.**

A IA deve funcionar como uma camada de diagnóstico e investigação, não como o mecanismo primário de health check.

---

# 2. Problema

Atualmente, a verificação da qualidade dos canais depende de operadores humanos acessando manualmente cada canal.

Isso apresenta:

- demora para verificar centenas de canais;
- inconsistência entre operadores;
- baixa escalabilidade;
- ausência de monitoramento contínuo;
- detecção reativa de problemas;
- dificuldade de produzir evidências objetivas dos incidentes.

O objetivo deste projeto é transformar o processo em um health check automatizado, mantendo a capacidade de diagnóstico visual semelhante à análise humana quando realmente necessário.

---

# 3. Objetivos

## 3.1 Objetivos principais

- Detectar canais fora do ar.
- Detectar falhas de DRM.
- Detectar falhas de reprodução.
- Detectar buffering persistente.
- Detectar vídeo congelado.
- Detectar tela preta.
- Detectar ausência de áudio.
- Detectar problemas de legenda.
- Detectar resolução inesperada.
- Detectar possíveis artefatos visuais.
- Detectar conteúdo incorreto quando houver expectativa conhecida.
- Produzir evidências dos incidentes.
- Enviar alertas somente quando necessário.
- Minimizar o custo de Amazon Bedrock.
- Permitir escala para centenas de canais.

## 3.2 Objetivo de custo

A arquitetura deve ser construída para que:

```text
Canal saudável
    ↓
Checks determinísticos
    ↓
OK
    ↓
Nenhuma chamada de IA
```

O custo de IA deve crescer principalmente com a quantidade de incidentes e casos suspeitos, e não linearmente com o número total de verificações.

---

# 4. Arquitetura Conceitual

```text
                         EventBridge Scheduler
                                │
                                ▼
                         ECS Fargate Task
                                │
                                ▼
                    Playwright + Chromium
                                │
                                ▼
                    SKY+ / Player autenticado
                                │
                                ▼
                  ┌─────────────────────────┐
                  │ AQUISIÇÃO + TELEMETRIA │
                  │                         │
                  │ • currentTime           │
                  │ • readyState            │
                  │ • paused                │
                  │ • buffered              │
                  │ • player errors         │
                  │ • DRM status            │
                  │ • áudio                 │
                  │ • legendas              │
                  │ • resolução             │
                  │ • frames                │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌─────────────────────────┐
                  │ DETECÇÃO DETERMINÍSTICA│
                  │                         │
                  │ • player health        │
                  │ • DRM                   │
                  │ • buffering             │
                  │ • currentTime           │
                  │ • áudio                 │
                  │ • tela preta            │
                  │ • resolução             │
                  │ • legendas              │
                  └────────────┬────────────┘
                               │
                       Anomalia encontrada?
                          /          \
                        NÃO          SIM
                        │             │
                        ▼             ▼
                       OK          OpenCV
                                      │
                              Anomalia confirmada?
                                  /        \
                                NÃO        SIM
                                │           │
                                ▼           ▼
                           falso positivo  Bedrock
                                             │
                                      ┌──────┴──────┐
                                      │             │
                                    Haiku         Sonnet
                                      │             │
                                      └──────┬──────┘
                                             ▼
                                        Diagnóstico
                                             │
                         ┌───────────────────┼───────────────────┐
                         ▼                   ▼                   ▼
                        S3              CloudWatch          Alertas
                    Evidências           Métricas          SES/Slack
```

---

# 5. Princípio de Detecção em Camadas

A ordem obrigatória de processamento é:

```text
1. Player
2. Regras determinísticas
3. OpenCV
4. Bedrock Haiku
5. Bedrock Sonnet
```

Nenhuma etapa posterior deve ser executada se a etapa anterior já tiver evidência suficiente para concluir o estado.

## Exemplo

```text
Player não carregou
    ↓
timeout
    ↓
FALHA_CRITICA
    ↓
não chama OpenCV
    ↓
não chama Bedrock
```

Outro exemplo:

```text
Player carregou
    ↓
currentTime avançando
    ↓
áudio presente
    ↓
frame não preto
    ↓
sem buffering
    ↓
OK
    ↓
não chama Bedrock
```

---

# 6. Playwright e Chromium

## 6.1 Responsabilidade

Playwright será responsável por:

- abrir o player;
- restaurar a sessão;
- reproduzir o conteúdo;
- lidar com modais;
- aguardar carregamento;
- coletar telemetria;
- capturar frames;
- observar eventos do player;
- identificar erros de DRM;
- executar JavaScript no contexto da página.

## 6.2 Sessão

Fluxo:

```text
Login manual inicial
        ↓
storageState
        ↓
S3 ou Secrets Manager
        ↓
ECS baixa sessão
        ↓
Playwright restaura sessão
```

Uma conta dedicada deve ser utilizada para evitar conflitos com sessões de usuários reais.

## 6.3 CAPTCHA

CAPTCHA solving externo não fará parte do MVP.

Se a sessão expirar:

```text
Sessão inválida
    ↓
Alerta operacional
    ↓
Renovação manual
    ↓
Novo storageState
```

Automação de CAPTCHA somente deverá ser considerada posteriormente caso a renovação manual se torne um problema operacional relevante.

---

# 7. Coleta de Telemetria do Player

Cada canal deve gerar uma estrutura semelhante a:

```json
{
  "channel_id": "CH0100000000092",
  "timestamp": "2026-08-20T14:00:00Z",
  "video": {
    "current_time": 1234.56,
    "video_width": 1920,
    "video_height": 1080,
    "ready_state": 4,
    "paused": false,
    "error": null,
    "buffered_seconds": 12.5
  },
  "audio": {
    "average_level": 45.2,
    "peak_level": 78.1,
    "is_muted": false
  },
  "subtitles": {
    "tracks_available": 2,
    "active_track": "Portuguese",
    "has_active_cues": true
  },
  "player": {
    "playing": true,
    "buffering": false,
    "drm_ok": true
  }
}
```

---

# 8. Motor de Detecção Determinística

Esta é a camada mais importante do projeto.

## 8.1 Player não reproduz

Condições possíveis:

- player não carregou;
- `readyState` permanece baixo;
- `playing` não ocorre;
- timeout excedido;
- erro explícito do player;
- erro de DRM.

Resultado:

```text
FALHA_CRITICA
```

---

## 8.2 CurrentTime parado

Capturar:

```text
currentTime(t0)
currentTime(t1)
```

Se:

```text
currentTime(t1) - currentTime(t0) ≈ 0
```

durante uma janela definida:

```text
possível_freeze = true
```

Essa condição deve ser combinada com análise de frames para aumentar a confiança.

---

# 9. Detecção de Freeze com OpenCV

Capturar pelo menos dois frames:

```text
Frame A
   ↓
intervalo
   ↓
Frame B
```

Comparar os frames utilizando métricas de similaridade, como:

- diferença absoluta de pixels;
- SSIM;
- percentual de pixels alterados.

Exemplo conceitual:

```text
currentTime parado
+
frame_similarity muito alta
=
FREEZE confirmado
```

Não considerar somente similaridade visual.

Canais podem apresentar naturalmente imagens quase estáticas.

---

# 10. Detecção de Tela Preta

Antes da IA, executar análise de pixels.

Exemplos de sinais:

```text
média de luminância muito baixa
+
alto percentual de pixels próximos de preto
```

A decisão deve considerar uma tolerância para:

- fade;
- cenas muito escuras;
- transições;
- conteúdo cinematográfico.

Apenas tela preta persistente deve gerar incidente.

---

# 11. Detecção de Áudio

Utilizar Web Audio API ou mecanismo equivalente disponível no player.

Monitorar:

- average level;
- peak level;
- mute state;
- duração do silêncio.

Não considerar um instante isolado de silêncio como falha.

Exemplo:

```text
silêncio curto
    ↓
ignorar

silêncio persistente
    ↓
NO_AUDIO
```

---

# 12. Detecção de Buffering

Monitorar:

- `waiting`;
- `stalled`;
- `playing`;
- `buffered_seconds`;
- transições entre estados.

Exemplo:

```text
waiting
   ↓
playing
```

não é necessariamente problema.

Enquanto:

```text
waiting
   ↓
waiting
   ↓
waiting
   ↓
sem recuperação
```

deve gerar:

```text
BUFFERING_PERSISTENT
```

---

# 13. Detecção de DRM

Monitorar:

- criação de MediaKeys;
- eventos de erro;
- falhas de licença;
- falha de inicialização;
- impossibilidade de iniciar reprodução.

Resultado:

```text
DRM_ERROR
```

Esse tipo de erro não precisa de IA.

---

# 14. Detecção de Resolução

Comparar resolução observada com a expectativa configurada para o canal.

Exemplo:

```json
{
  "channel_id": "ESPN",
  "expected": {
    "width": 1920,
    "height": 1080
  }
}
```

Se o player entregar resolução inesperada:

```text
RESOLUTION_DEGRADED
```

A regra deve permitir tolerâncias e canais com resolução variável.

---

# 15. Detecção de Legendas

Separar quatro estados:

```text
subtitle_track_available
subtitle_track_active
subtitle_cues_present
subtitle_visual_rendering
```

A existência da track não significa necessariamente que a legenda esteja sendo renderizada.

Problemas simples podem ser determinados pelo player.

Problemas de renderização visual podem ser encaminhados para análise visual.

---

# 16. OpenCV como Segunda Camada

OpenCV deve ser usado para:

- comparação entre frames;
- detecção de tela preta;
- análise de mudanças;
- identificação de frames congelados;
- detecção de padrões visuais simples;
- confirmação de suspeitas geradas pelo player.

O OpenCV não precisa interpretar semanticamente o conteúdo.

Sua função é responder:

> "Existe uma alteração visual consistente com a reprodução?"

---

# 17. Amazon Bedrock como Terceira Camada

Bedrock será usado somente quando:

- existe uma anomalia visual;
- é necessário interpretar o conteúdo;
- existe suspeita de conteúdo incorreto;
- existe suspeita de artefato;
- existe problema de overlay/logo;
- OpenCV não consegue concluir;
- há baixa confiança na classificação automática;
- um incidente crítico precisa de diagnóstico adicional.

## 17.1 Haiku

Haiku será o modelo padrão de diagnóstico.

Objetivo:

- classificação;
- triagem;
- descrição simples;
- identificação de anomalias.

## 17.2 Sonnet

Sonnet será utilizado somente para:

- casos ambíguos;
- baixa confiança do Haiku;
- incidentes críticos;
- diagnóstico visual complexo.

Fluxo:

```text
Anomalia
   ↓
Haiku
   ↓
confidence >= threshold?
   ├── SIM → resultado
   └── NÃO → Sonnet
```

---

# 18. Prompt de Diagnóstico

O prompt deve ser orientado a diagnóstico, não a monitoramento geral.

```text
Você é um especialista em diagnóstico de qualidade de vídeo de TV ao vivo.

Analise o frame fornecido e determine se existe evidência visual de:

1. tela preta;
2. congelamento;
3. macroblocking;
4. pixelização;
5. glitches;
6. tearing;
7. conteúdo incorreto;
8. overlay/OSD incorreto;
9. logo ausente;
10. erro visual do player;
11. outro problema evidente.

Não classifique como problema apenas porque o conteúdo parece uma propaganda,
transição, cena escura ou programa diferente do esperado, salvo se houver
evidência objetiva.

Retorne somente JSON.
```

---

# 19. Estrutura da Resposta da IA

```json
{
  "status": "OK",
  "diagnosis": "normal",
  "issues": [],
  "description": "Conteúdo normal de televisão.",
  "confidence": 0.96,
  "requires_human_review": false
}
```

Em caso de problema:

```json
{
  "status": "DEGRADED",
  "diagnosis": "visual_artifact",
  "issues": [
    "macroblocking"
  ],
  "description": "Artefatos de compressão visíveis na imagem.",
  "confidence": 0.91,
  "requires_human_review": false
}
```

---

# 20. Estratégia de Confiança

O sistema deve produzir confiança baseada em evidências.

Exemplo:

```text
currentTime parado
+
frames idênticos
+
buffer baixo
=
confiança alta em FREEZE
```

Enquanto:

```text
frames semelhantes
+
currentTime normal
+
player normal
=
não gerar incidente
```

A IA também deve retornar:

```text
confidence
```

para permitir escalonamento.

---

# 21. Máquina de Estados

Cada canal deverá possuir um estado operacional.

```text
UNKNOWN
   ↓
CHECKING
   ↓
HEALTHY
   │
   ├── suspeita → SUSPECTED
   │
   └── falha → CRITICAL
```

Estados:

```text
UNKNOWN
CHECKING
HEALTHY
DEGRADED
SUSPECTED
CRITICAL
```

A transição para `CRITICAL` deve exigir evidência objetiva sempre que possível.

---

# 22. Evitando Falsos Positivos

Não alertar por uma única amostra.

Exemplo:

```text
check 1 → suspeito
check 2 → normal
```

Não gerar incidente persistente.

Para problemas intermitentes:

```text
check 1 → suspeito
check 2 → suspeito
check 3 → suspeito
```

Gerar alerta.

Para falhas críticas objetivas:

```text
DRM_ERROR
PLAYER_ERROR
PLAYER_TIMEOUT
```

o alerta pode ser imediato.

---

# 23. Monitoramento por Tiers

Os canais não precisam possuir a mesma frequência.

## Tier 1 — Crítico

Exemplos:

- principais canais;
- eventos;
- esportes;
- canais prioritários.

Frequência sugerida:

```text
15–30 minutos
```

## Tier 2 — Normal

```text
1–2 horas
```

## Tier 3 — Baixa prioridade

```text
4–6 horas
```

A frequência deve ser configurável por canal.

---

# 24. Concorrência

Não iniciar um browser independente para cada canal.

Preferir:

```text
1 Chromium
   ├── Page / Context 1
   ├── Page / Context 2
   ├── Page / Context 3
   └── ...
```

com concorrência controlada.

O número exato de canais simultâneos deve ser determinado pela PoC de ECS, observando:

- CPU;
- RAM;
- estabilidade do Chromium;
- uso de GPU/software rendering;
- consumo de rede;
- estabilidade do DRM;
- tempo médio por canal.

Não assumir que 100 canais simultâneos em um único browser serão suportados sem teste.

---

# 25. Evidências

S3 será utilizado para armazenar:

```text
s3://channel-monitor/
    ├── executions/
    │   └── YYYY-MM-DD/
    ├── screenshots/
    │   └── YYYY-MM-DD/
    ├── incidents/
    │   └── YYYY-MM-DD/
    └── reports/
        └── YYYY-MM-DD/
```

Guardar screenshot principalmente quando:

- houver incidente;
- Bedrock for acionado;
- houver necessidade de auditoria;
- houver amostra explicitamente solicitada.

Não armazenar screenshots de todos os checks normais indefinidamente.

Isso reduz custo e armazenamento desnecessário.

---

# 26. DynamoDB

DynamoDB é opcional no MVP.

## MVP

Priorizar:

- S3;
- CloudWatch Logs;
- CloudWatch Metrics.

## Produção

Adicionar DynamoDB quando forem necessários:

- histórico por canal;
- dashboard operacional;
- consultas rápidas;
- SLA;
- tendências;
- histórico de incidentes;
- agregações.

Estrutura sugerida:

```text
PK = CHANNEL#{channel_id}
SK = CHECK#{timestamp}
```

Incidentes:

```text
PK = INCIDENT#{incident_id}
SK = EVENT#{timestamp}
```

---

# 27. CloudWatch

CloudWatch deverá registrar métricas como:

```text
ChannelHealth
PlayerLoadSuccess
DRMError
Buffering
FreezeDetected
BlackScreen
AudioFailure
SubtitleFailure
ResolutionFailure
AIInvocations
AIHaikuInvocations
AISonnetInvocations
FalsePositive
ExecutionDuration
```

Também registrar:

```text
channels_checked
channels_healthy
channels_degraded
channels_critical
channels_suspected
```

---

# 28. Alertas

## CRITICAL

Exemplos:

- player não inicia;
- DRM falha;
- tela preta persistente;
- reprodução completamente indisponível.

Enviar:

```text
SES
+
Slack
```

## DEGRADED

Exemplos:

- buffering persistente;
- áudio ausente;
- artefatos;
- resolução degradada.

Enviar alerta dependendo da política do canal.

## OK

Não enviar alerta.

Somente registrar métricas.

---

# 29. Cooldown de Alertas

Evitar spam.

Exemplo:

```text
ESPN DOWN
10:00 → alerta
10:05 → não alertar novamente
10:10 → não alertar novamente
10:30 → ainda down
```

Enviar apenas atualização quando:

- estado mudar;
- incidente for resolvido;
- passar um intervalo configurado.

---

# 30. Estrutura de Configuração

A lista de canais deve conter:

```json
{
  "channel_id": "CH0100000000092",
  "channel_name": "ESPN",
  "enabled": true,
  "tier": 1,
  "expected_resolution": {
    "width": 1920,
    "height": 1080
  },
  "audio_required": true,
  "subtitle_required": true,
  "expected_content": "ESPN",
  "monitoring_interval_minutes": 30
}
```

---

# 31. Fluxo Completo de Execução

```text
1. EventBridge dispara execução.

2. ECS inicia.

3. Container carrega configuração.

4. Container recupera sessão.

5. Playwright inicia Chromium.

6. Sistema seleciona canais conforme tier.

7. Para cada canal:
   a. abre player;
   b. restaura sessão;
   c. fecha modais;
   d. aguarda player;
   e. aguarda DRM;
   f. verifica reprodução;
   g. coleta telemetria;
   h. captura frames somente quando necessário.

8. Executa checks determinísticos.

9. Se tudo estiver normal:
   → HEALTHY.

10. Se houver suspeita:
   → OpenCV.

11. Se OpenCV confirmar ou não conseguir concluir:
   → Bedrock Haiku.

12. Se Haiku tiver baixa confiança:
   → Bedrock Sonnet.

13. Salva resultado.

14. Salva evidência quando necessário.

15. Publica métricas.

16. Gera alerta se necessário.

17. Finaliza canal.

18. Finaliza execução.

19. Publica relatório consolidado.
```

---

# 32. Resultado Consolidado

Exemplo:

```json
{
  "execution_id": "2026-08-20T14:00:00Z",
  "total_channels": 100,
  "summary": {
    "healthy": 94,
    "degraded": 3,
    "suspected": 1,
    "critical": 2
  },
  "ai": {
    "haiku_invocations": 5,
    "sonnet_invocations": 1
  }
}
```

O indicador de maior importância será:

```text
AI invocations / total checks
```

Quanto menor, melhor, desde que a qualidade da detecção seja mantida.

---

# 33. Arquitetura AWS do MVP

## Obrigatório

```text
ECS Fargate
EventBridge
ECR
S3
CloudWatch
Secrets Manager
Bedrock
```

## Opcional inicialmente

```text
DynamoDB
SNS
```

## Alertas

```text
EventBridge / Lambda
        ├── SES
        └── Slack
```

---

# 34. Infraestrutura

| Recurso | Nome sugerido | Obrigatório |
|---|---|---|
| ECS Cluster | `channel-monitor-cluster` | Sim |
| ECS Task Definition | `channel-monitor-task` | Sim |
| ECR | `channel-monitor` | Sim |
| S3 | `channel-monitor-evidence-{account}` | Sim |
| EventBridge | `channel-monitor-schedule` | Sim |
| CloudWatch | `channel-monitor` | Sim |
| Secrets Manager | `channel-monitor/session` | Sim |
| Bedrock | Claude Haiku | Sim |
| Bedrock | Claude Sonnet | Condicional |
| DynamoDB | `channel-monitor-results` | Não no MVP |
| SNS | `channel-monitor-alerts` | Não |

---

# 35. Segurança

A task deve possuir somente permissões necessárias.

Permissões esperadas:

```text
s3:GetObject
s3:PutObject

secretsmanager:GetSecretValue

bedrock:InvokeModel

cloudwatch:PutMetricData
logs:CreateLogStream
logs:PutLogEvents
```

Evitar permissões administrativas.

A sessão/cookies nunca devem aparecer em:

- logs;
- screenshots;
- relatórios;
- mensagens de alerta.

---

# 36. Custos

A arquitetura foi desenhada para reduzir o principal componente variável: IA.

## Estratégia

```text
100 canais
× checks
        ↓
checks locais
        ↓
~maioria dos canais
        ↓
0 chamadas Bedrock
```

Somente suspeitas seguem para:

```text
OpenCV
    ↓
Haiku
    ↓
Sonnet somente se necessário
```

O custo final deverá ser medido durante a PoC antes de definir um orçamento de produção.

Não assumir valores fixos de Bedrock ou Fargate sem validar os preços atuais e o consumo real.

---

# 37. Métricas de Sucesso

A PoC deve medir:

## Performance

- tempo médio por canal;
- canais/minuto;
- CPU;
- RAM;
- estabilidade do Chromium.

## Qualidade

- true positives;
- false positives;
- false negatives;
- tempo para detectar incidente.

## IA

- número de chamadas;
- Haiku vs Sonnet;
- custo por execução;
- confiança média;
- percentual de casos escalados para Sonnet.

## Operação

- taxa de sessão expirada;
- falhas de DRM;
- falhas do player;
- taxa de execução concluída.

---

# 38. PoC — Fase 1

Antes de construir a infraestrutura completa:

```text
1 canal
+
Playwright
+
SKY+
+
Widevine
+
áudio
+
frames
+
OpenCV
+
Bedrock
```

Validar obrigatoriamente:

- login;
- storageState;
- sessão persistida;
- DRM;
- reprodução;
- captura de frame;
- áudio;
- legendas;
- currentTime;
- buffering;
- detecção de tela preta;
- freeze detection;
- chamada Bedrock;
- execução em Docker.

---

# 39. PoC em ECS

Depois da PoC local:

```text
Docker
   ↓
ECR
   ↓
ECS Fargate
   ↓
1 canal
```

Validar:

- Widevine no ambiente ECS;
- estabilidade do Chromium;
- memória;
- CPU;
- rede;
- tempo de inicialização;
- sessão;
- DRM;
- screenshots.

Somente depois disso aumentar a concorrência.

---

# 40. MVP — 10 Canais

Implementar:

- 10 canais;
- scheduler;
- S3;
- CloudWatch;
- alertas;
- OpenCV;
- Haiku;
- Sonnet condicional;
- relatório JSON;
- evidências;
- cooldown de alertas.

Objetivo:

> provar que a arquitetura funciona sem depender de IA em todos os checks.

---

# 41. Produção — Centenas de Canais

Escalar progressivamente:

```text
10
 ↓
25
 ↓
50
 ↓
100
 ↓
200+
```

Em cada etapa medir:

- CPU;
- RAM;
- estabilidade;
- tempo;
- custo;
- taxa de erro;
- consumo de Bedrock.

Nunca saltar diretamente de 10 para centenas sem benchmark.

---

# 42. Roadmap

| Fase | Duração sugerida | Resultado |
|---|---:|---|
| PoC local | 1 semana | DRM + Playwright + 1 canal |
| PoC OpenCV | 2–3 dias | freeze/black screen |
| PoC Bedrock | 2–3 dias | diagnóstico seletivo |
| ECS | 3–5 dias | execução cloud |
| MVP | 1–2 semanas | 10 canais |
| Escala | 1–2 semanas | 50–100 canais |
| Produção | contínuo | centenas de canais |

---

# 43. Decisões Arquiteturais

## DEC-001 — IA não será usada em todos os checks

**Decisão:** usar IA somente para diagnóstico.

**Motivo:** custo e latência.

---

## DEC-002 — OpenCV antes do Bedrock

**Decisão:** análise visual matemática precede IA.

**Motivo:** detectar anomalias simples sem custo variável.

---

## DEC-003 — Haiku antes de Sonnet

**Decisão:** Haiku é o modelo de triagem.

**Motivo:** reduzir custo.

---

## DEC-004 — Sonnet somente em escalonamento

**Decisão:** usar Sonnet apenas quando necessário.

**Motivo:** casos complexos ou baixa confiança.

---

## DEC-005 — DynamoDB não é obrigatório no MVP

**Decisão:** iniciar com S3 + CloudWatch.

**Motivo:** reduzir complexidade e custo operacional.

---

## DEC-006 — CAPTCHA solving fora do MVP

**Decisão:** renovação manual da sessão inicialmente.

**Motivo:** reduzir dependências e complexidade.

---

# 44. Principais Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Widevine não funcionar no ECS | Muito alto | PoC específica antes do MVP |
| Sessão expirar | Alto | Conta dedicada + monitoramento |
| Player mudar | Alto | seletores resilientes |
| Falso positivo de freeze | Médio | combinar currentTime + OpenCV |
| Conteúdo escuro gerar black screen | Médio | janela temporal + thresholds |
| Custo de IA crescer | Alto | IA somente sob demanda |
| Chromium consumir muita RAM | Alto | benchmark de concorrência |
| DRM falhar intermitentemente | Alto | retry controlado |
| API do player mudar | Médio | camada de abstração |
| Alertas excessivos | Médio | cooldown + state machine |

---

# 45. Critério de Go/No-Go

A arquitetura somente deve avançar para produção se a PoC demonstrar:

```text
✓ Widevine funcional no ambiente alvo
✓ Sessão persistente
✓ Reprodução confiável
✓ Detecção determinística funcional
✓ Freeze detection funcional
✓ Black screen detection funcional
✓ Áudio detectável
✓ Buffering detectável
✓ Bedrock somente em casos suspeitos
✓ Custo de IA controlado
✓ Concorrência estável
✓ Evidências armazenadas
✓ Alertas confiáveis
```

---

# 46. Arquitetura Final Recomendada

A arquitetura final deve seguir:

```text
                  ┌─────────────────┐
                  │   EventBridge    │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  ECS Fargate    │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │    Playwright   │
                  │    Chromium     │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Player Health   │
                  │ + Telemetria    │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Deterministic   │
                  │ Detection       │
                  └────────┬────────┘
                           │
                  ┌────────┴────────┐
                  │                 │
                 OK              Suspeita
                  │                 │
                  ▼                 ▼
               CloudWatch        OpenCV
                                    │
                           ┌────────┴────────┐
                           │                 │
                        Normal          Confirmado/
                                         Incerto
                                           │
                                           ▼
                                      Bedrock Haiku
                                           │
                                    baixa confiança?
                                      /          \
                                    não          sim
                                    │             │
                                    ▼             ▼
                                Resultado      Sonnet
                                    │             │
                                    └──────┬──────┘
                                           ▼
                                      Diagnóstico
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                             S3        CloudWatch     Alertas
                                                       │
                                                   SES/Slack
```

---

# 47. Conclusão

A versão 2 deve ser construída com uma filosofia simples:

> **Automação determina se existe um problema. IA explica o problema.**

Isso evita transformar cada verificação de canal em uma chamada multimodal.

O sistema passa a ter:

- menor custo;
- menor latência;
- maior previsibilidade;
- melhor explicabilidade;
- menor dependência de IA;
- melhor escalabilidade;
- maior facilidade de operação.

A arquitetura também preserva o principal benefício da proposta original: a capacidade de analisar visualmente conteúdo protegido por DRM através do browser real.

O maior risco técnico continua sendo a validação de Widevine/DRM no ambiente de execução escolhido. Por isso, a primeira etapa obrigatória é uma PoC mínima antes de investir na infraestrutura de produção.

**Princípio final do projeto:**

```text
HEALTH CHECK = DETERMINÍSTICO
VISUAL CONFIRMATION = OPENCV
DIAGNÓSTICO = BEDROCK
EVIDÊNCIA = S3
OBSERVABILIDADE = CLOUDWATCH
ORQUESTRAÇÃO = EVENTBRIDGE + ECS
ALERTAS = SES + SLACK
```
