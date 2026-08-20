# Requirements Document

## Introduction

Este documento define os requisitos para a Proof of Concept (PoC) de validação do Widevine DRM com Playwright em container Docker. Esta PoC é a primeira etapa obrigatória do projeto de Monitoramento Inteligente de Canais ao Vivo da plataforma SKY+.

O maior risco técnico do projeto é determinar se Widevine/DRM funciona dentro de um container Docker (e posteriormente ECS Fargate). Esta PoC tem como objetivo eliminar esse risco antes de investir na infraestrutura de produção.

Princípio central: **Canal saudável não deve consumir IA.**

## Glossary

- **PoC_System**: Sistema de Proof of Concept que orquestra todos os testes de validação do Widevine DRM com Playwright em Docker
- **Playwright_Browser**: Instância do Chromium gerenciada pelo Playwright com suporte a Widevine CDM para reprodução de conteúdo DRM
- **Player**: Componente de vídeo da plataforma SKY+ que reproduz conteúdo ao vivo protegido por DRM
- **StorageState**: Arquivo JSON gerado pelo Playwright contendo cookies e localStorage que permite restaurar uma sessão autenticada
- **Widevine_CDM**: Content Decryption Module do Google que permite ao Chromium reproduzir conteúdo protegido por DRM
- **Telemetry_Collector**: Módulo responsável por coletar métricas do Player via JavaScript (currentTime, readyState, buffered, áudio, etc.)
- **Frame_Capturer**: Módulo responsável por capturar screenshots/frames do Player durante a reprodução
- **OpenCV_Analyzer**: Módulo que utiliza OpenCV para análise visual de frames (detecção de tela preta, freeze)
- **Bedrock_Client**: Cliente que realiza chamadas ao Amazon Bedrock para diagnóstico visual por IA
- **Docker_Container**: Ambiente containerizado onde o PoC_System executa com todas as dependências necessárias

## Requirements

### Requirement 1: Autenticação e Persistência de Sessão

**User Story:** Como desenvolvedor da PoC, eu quero validar que o Playwright consegue autenticar na plataforma SKY+ e persistir a sessão, para que execuções futuras não necessitem de login interativo.

#### Acceptance Criteria

1. WHEN um login manual é realizado na plataforma SKY+, THE Playwright_Browser SHALL exportar o storageState para um arquivo JSON contendo cookies e localStorage, e o arquivo resultante SHALL ter tamanho maior que 0 bytes e conter ao menos um cookie de sessão
2. WHEN um storageState é fornecido e o Playwright_Browser navega para a plataforma SKY+, THE Playwright_Browser SHALL restaurar a sessão autenticada sem redirecionamento para página de login e sem exibição de formulário de credenciais, dentro de 15 segundos após a navegação
3. WHEN uma sessão é restaurada via storageState, THE Player SHALL carregar o conteúdo protegido por DRM sem solicitar nova autenticação dentro de 30 segundos após o carregamento da página
4. IF o Playwright_Browser detectar redirecionamento para página de login ou receber resposta HTTP 401/403 ao tentar acessar conteúdo protegido após restauração do storageState, THEN THE PoC_System SHALL classificar o storageState como expirado e registrar um log de erro indicando a necessidade de renovação manual da sessão

### Requirement 2: Reprodução de Conteúdo DRM (Widevine)

**User Story:** Como desenvolvedor da PoC, eu quero validar que o Playwright com Chromium consegue reproduzir conteúdo protegido por Widevine DRM da SKY+, para confirmar a viabilidade técnica do monitoramento automatizado.

#### Acceptance Criteria

1. WHEN o Player é carregado com sessão válida, THE Playwright_Browser SHALL inicializar o Widevine CDM (criação de MediaKeys e geração de license request) e obter a licença DRM dentro de 15 segundos sem eventos de erro no CDM
2. WHEN o DRM é inicializado com sucesso, THE Player SHALL atingir readyState >= 3, currentTime > 0 e paused == false dentro de 30 segundos
3. WHILE o conteúdo está sendo reproduzido, THE Telemetry_Collector SHALL coletar o currentTime a cada 2 segundos e verificar que o valor incrementa em pelo menos 1 segundo entre amostras consecutivas
4. IF o Widevine CDM falhar na inicialização, THEN THE PoC_System SHALL capturar o erro específico do DRM e registrar em log
5. IF a licença DRM não for obtida dentro de 15 segundos após o license request, THEN THE PoC_System SHALL registrar o código de erro e a mensagem associada e classificar o estado como DRM_ERROR

### Requirement 3: Coleta de Telemetria do Player

**User Story:** Como desenvolvedor da PoC, eu quero coletar métricas de telemetria do player em tempo real, para validar que o sistema consegue monitorar o estado da reprodução programaticamente.

#### Acceptance Criteria

1. WHILE o Player está reproduzindo conteúdo, THE Telemetry_Collector SHALL coletar currentTime, readyState, paused, e buffered_seconds a cada 2 segundos
2. WHILE o Player está reproduzindo conteúdo, THE Telemetry_Collector SHALL coletar o nível de áudio (average_level e peak_level) em escala numérica de 0.0 a 100.0, a cada 2 segundos, via Web Audio API ou mecanismo equivalente
3. WHILE o Player está reproduzindo conteúdo, THE Telemetry_Collector SHALL coletar a cada 2 segundos os dados de legenda contendo: quantidade de tracks disponíveis (tracks_available), nome da track ativa (active_track) e indicador booleano de cues presentes (has_active_cues)
4. WHEN a telemetria é coletada, THE Telemetry_Collector SHALL produzir um objeto JSON com a estrutura definida no documento de arquitetura contendo as seções video, audio, subtitles e player
5. IF o Player reportar um erro, THEN THE Telemetry_Collector SHALL capturar o código e mensagem de erro dentro de no máximo 500 milissegundos após o evento de erro
6. IF a análise de áudio não estiver disponível (Web Audio API não conectável ao contexto do Player), THEN THE Telemetry_Collector SHALL registrar average_level e peak_level como null e incluir indicação de indisponibilidade no objeto de telemetria

### Requirement 4: Captura de Frames do Player

**User Story:** Como desenvolvedor da PoC, eu quero validar que o sistema consegue capturar frames/screenshots do player durante a reprodução de conteúdo DRM, para confirmar que a análise visual é viável.

#### Acceptance Criteria

1. WHILE o Player está reproduzindo conteúdo DRM, THE Frame_Capturer SHALL capturar screenshots do viewport do player em formato PNG
2. WHEN um frame é capturado, THE Frame_Capturer SHALL produzir uma imagem com resolução mínima de 1280x720 pixels e tamanho máximo de 5 MB
3. WHEN múltiplos frames são capturados em sequência, THE Frame_Capturer SHALL garantir um intervalo mínimo entre capturas com valor padrão de 5 segundos, configurável entre 1 e 60 segundos
4. WHEN um frame é capturado, THE Frame_Capturer SHALL verificar que o frame contém conteúdo visual do vídeo calculando a média de luminância da imagem e confirmando que o valor excede 16 em escala 0-255
5. IF a verificação de conteúdo visual indicar que o frame capturado é uma tela preta (luminância média igual ou inferior a 16/255), THEN THE Frame_Capturer SHALL registrar um log de warning indicando possível proteção DRM ativa e descartar o frame da análise subsequente

### Requirement 5: Detecção de Tela Preta

**User Story:** Como desenvolvedor da PoC, eu quero validar que o OpenCV consegue detectar tela preta nos frames capturados, para confirmar a viabilidade da detecção determinística.

#### Acceptance Criteria

1. WHEN um frame é fornecido ao OpenCV_Analyzer, THE OpenCV_Analyzer SHALL converter o frame para escala de cinza e calcular a média de luminância (escala 0-255) e o percentual de pixels com valor inferior a 20 (em escala 0-255)
2. WHEN a média de luminância está abaixo do threshold configurado (padrão: 10) E o percentual de pixels com valor inferior a 20 excede 95%, THE OpenCV_Analyzer SHALL classificar o frame como BLACK_SCREEN
3. WHEN um frame contém cena escura legítima (filme, transição), THE OpenCV_Analyzer SHALL diferenciar de tela preta total verificando se a variância dos pixels é superior a 50 — indicando distribuição não uniforme e portanto conteúdo visual presente
4. IF o frame fornecido for inválido (dimensões zero, dados corrompidos ou formato não suportado), THEN THE OpenCV_Analyzer SHALL registrar um log de erro e retornar status ANALYSIS_ERROR sem classificar o frame

### Requirement 6: Detecção de Freeze (Congelamento)

**User Story:** Como desenvolvedor da PoC, eu quero validar que o sistema consegue detectar congelamento de vídeo combinando telemetria e análise visual, para confirmar a viabilidade da detecção de freeze.

#### Acceptance Criteria

1. WHEN dois frames consecutivos são fornecidos ao OpenCV_Analyzer, THE OpenCV_Analyzer SHALL calcular a similaridade entre os frames utilizando SSIM ou diferença absoluta de pixels e produzir um valor numérico de similaridade entre 0.0 (totalmente diferentes) e 1.0 (idênticos)
2. IF a similaridade entre frames excede o threshold configurado (padrão: 0.98) E a diferença de currentTime entre duas coletas consecutivas é menor que 0.5 segundos ao longo de uma janela de observação de pelo menos 5 segundos, THEN THE PoC_System SHALL classificar o estado como freeze confirmado
3. IF a similaridade entre frames excede o threshold configurado (padrão: 0.98) MAS a diferença de currentTime entre coletas consecutivas é igual ou superior a 0.5 segundos, THEN THE PoC_System SHALL classificar o estado como conteúdo estático legítimo e não gerar alerta
4. IF o OpenCV_Analyzer não conseguir comparar os frames (dimensões diferentes, frame corrompido ou dados insuficientes), THEN THE PoC_System SHALL registrar um log de erro indicando o motivo da falha na comparação e não classificar o estado como freeze

### Requirement 7: Detecção de Buffering

**User Story:** Como desenvolvedor da PoC, eu quero validar que o sistema consegue detectar buffering persistente do player, para confirmar a viabilidade da detecção determinística de problemas de rede.

#### Acceptance Criteria

1. WHILE o Player reporta estado waiting ou stalled, THE Telemetry_Collector SHALL registrar o timestamp de início do buffering e calcular a duração acumulada a cada 1 segundo
2. WHEN o buffering persiste por mais tempo que o threshold configurado (default: 10 segundos) sem que o Player transite para o estado playing com currentTime avançando, THE PoC_System SHALL classificar o estado como BUFFERING_PERSISTENT
3. WHEN o Player transiciona de waiting ou stalled para playing com currentTime avançando dentro do threshold configurado (default: 10 segundos), THE PoC_System SHALL classificar o evento como buffering normal e não gerar alerta
4. IF o Player reportar um readyState diferente de waiting, stalled ou playing durante o monitoramento de buffering, THEN THE Telemetry_Collector SHALL registrar o estado inesperado em log e manter o monitoramento ativo sem interromper a detecção

### Requirement 8: Chamada ao Amazon Bedrock

**User Story:** Como desenvolvedor da PoC, eu quero validar que o sistema consegue enviar frames capturados ao Amazon Bedrock para diagnóstico visual, para confirmar a viabilidade da camada de IA seletiva.

#### Acceptance Criteria

1. WHEN um frame com anomalia detectada é fornecido ao Bedrock_Client, THE Bedrock_Client SHALL enviar o frame codificado em base64 ao modelo Claude Haiku com o prompt de diagnóstico definido na arquitetura e aguardar resposta por no máximo 30 segundos
2. WHEN o Bedrock retorna uma resposta válida, THE Bedrock_Client SHALL parsear o JSON de resposta e validar a presença dos campos status (valores aceitos: OK, DEGRADED, UNKNOWN), diagnosis, issues, description e confidence (valor numérico entre 0.0 e 1.0)
3. IF a chamada ao Bedrock falhar por timeout de 30 segundos ou erro de API, THEN THE Bedrock_Client SHALL registrar o erro com o código e mensagem recebidos e retornar um resultado com status UNKNOWN e confidence 0.0 sem interromper a execução
4. IF o Bedrock retornar uma resposta que não é JSON válido ou que não contém os campos obrigatórios, THEN THE Bedrock_Client SHALL registrar o conteúdo da resposta como erro e retornar um resultado com status UNKNOWN e confidence 0.0
5. IF a confidence retornada pelo Haiku for inferior ao threshold configurado, THEN THE Bedrock_Client SHALL escalar a análise para o modelo Claude Sonnet com o mesmo frame e prompt
6. IF uma anomalia não foi confirmada pelas camadas anteriores (detecção determinística ou OpenCV), THEN THE Bedrock_Client SHALL rejeitar a requisição sem enviar chamada ao Bedrock

### Requirement 9: Execução em Docker

**User Story:** Como desenvolvedor da PoC, eu quero validar que todo o sistema funciona dentro de um container Docker, para confirmar a viabilidade de execução em ambiente containerizado (ECS Fargate).

#### Acceptance Criteria

1. THE Docker_Container SHALL executar o PoC_System completo (Playwright, Chromium, Widevine CDM, OpenCV, Bedrock Client) com todas as dependências instaladas
2. WHEN o Docker_Container é iniciado, THE Playwright_Browser SHALL inicializar o Chromium com Widevine CDM dentro do container, confirmado pela obtenção bem-sucedida de uma licença DRM, em no máximo 60 segundos após o início do container
3. WHEN o PoC_System executa dentro do Docker_Container, THE Player SHALL reproduzir conteúdo DRM validado pelos seguintes critérios: currentTime avança continuamente, telemetria é coletada com sucesso, frames são capturados com resolução mínima de 1280x720, e OpenCV_Analyzer produz métricas de análise
4. THE Docker_Container SHALL utilizar imagem base compatível com Playwright e incluir as bibliotecas de sistema necessárias para Widevine (libnss3, libatk, libgbm, libasound2, libxrandr, libpango)
5. WHEN o storageState é montado como volume ou copiado para o container, THE Playwright_Browser SHALL restaurar a sessão autenticada dentro do Docker_Container sem necessidade de login interativo
6. IF o Widevine CDM falhar na inicialização dentro do Docker_Container, THEN THE PoC_System SHALL registrar em log o erro específico, as bibliotecas de sistema disponíveis e as permissões do processo, para diagnóstico do ambiente containerizado

### Requirement 10: Logging e Observabilidade

**User Story:** Como desenvolvedor da PoC, eu quero que o sistema produza logs detalhados de cada etapa da execução, para que eu saiba exatamente o que está acontecendo em cada momento e possa diagnosticar problemas rapidamente.

#### Acceptance Criteria

1. THE PoC_System SHALL utilizar logging estruturado em formato JSON com os campos: timestamp, level, stage_id, message e data, utilizando os níveis DEBUG, INFO, WARNING e ERROR
2. WHEN o Playwright_Browser executa uma ação (navegação, clique, espera), THE PoC_System SHALL registrar em log nível INFO a ação executada, o seletor utilizado e o tempo decorrido em milissegundos
3. WHEN o Widevine CDM inicia o processo de obtenção de licença, THE PoC_System SHALL registrar em log nível INFO cada etapa do handshake DRM (criação de MediaKeys, geração de request, resposta da licença) com o tempo decorrido de cada etapa em milissegundos
4. WHEN o Telemetry_Collector coleta uma amostra, THE PoC_System SHALL registrar em log nível DEBUG os valores coletados (currentTime, readyState, buffered, áudio)
5. WHEN o Frame_Capturer captura um frame, THE PoC_System SHALL registrar em log nível INFO o timestamp da captura, o tamanho do arquivo em bytes e a resolução do frame em pixels
6. WHEN o OpenCV_Analyzer processa um frame, THE PoC_System SHALL registrar em log nível INFO as métricas calculadas (luminância média, percentual de pixels pretos, SSIM)
7. WHEN o Bedrock_Client envia ou recebe uma requisição, THE PoC_System SHALL registrar em log nível INFO o modelo utilizado, o tamanho do payload em bytes, o tempo de resposta em milissegundos e o status HTTP
8. WHEN o Docker_Container inicia, THE PoC_System SHALL registrar em log nível INFO as versões de Playwright, Chromium, Python, OpenCV e as bibliotecas de sistema disponíveis
9. IF qualquer operação falhar, THEN THE PoC_System SHALL registrar em log nível ERROR o stack trace completo, o identificador da etapa onde ocorreu a falha, o contexto da operação e os dados relevantes para reprodução do problema
10. THE PoC_System SHALL incluir timestamps em formato ISO 8601 com precisão de milissegundos e identificador da etapa (stage_id) em cada entrada de log
11. THE PoC_System SHALL direcionar toda a saída de logs para stdout, permitindo configuração do nível mínimo de log exibido via variável de ambiente ou parâmetro de inicialização

### Requirement 11: Relatório de Resultados da PoC

**User Story:** Como desenvolvedor da PoC, eu quero que o sistema produza um relatório consolidado dos testes executados, para documentar os resultados e suportar a decisão de Go/No-Go.

#### Acceptance Criteria

1. WHEN todos os testes da PoC são executados, THE PoC_System SHALL produzir um relatório JSON consolidado contendo, para cada validação (login, DRM, telemetria, frames, OpenCV, Bedrock, Docker), o status (PASS, FAIL ou SKIPPED), o timestamp de início e fim, e a duração em milissegundos
2. IF um teste falha, THEN THE PoC_System SHALL incluir no relatório o motivo da falha, a mensagem de erro capturada e referências às evidências geradas (caminho para screenshots e arquivo de log)
3. THE PoC_System SHALL registrar métricas de performance em milissegundos incluindo tempo de inicialização do browser, tempo para DRM ready, tempo por frame capturado e tempo de resposta do Bedrock
4. WHEN o relatório é gerado, THE PoC_System SHALL classificar o resultado geral como GO (todas as validações críticas — login, DRM, frames e Docker — passaram) ou NO_GO (alguma dessas validações críticas falhou)
5. WHEN o relatório é gerado, THE PoC_System SHALL incluir o caminho para o arquivo de log completo da execução como referência para análise detalhada
6. IF uma validação não puder ser executada devido a falha em etapa anterior, THEN THE PoC_System SHALL registrá-la no relatório com status SKIPPED e indicar qual dependência impediu sua execução
