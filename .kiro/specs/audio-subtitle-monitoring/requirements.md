# Requirements Document

## Introduction

Este documento define os requisitos para o módulo de Monitoramento de Áudio e Legendas via interação com a UI do player SKY+ — um sistema que testa funcionalidades de áudio e legendas interagindo diretamente com os controles visuais do player (menu de configurações) e validando os resultados via Shaka Player API e Web Audio API.

O sistema Player Discovery existente detectou que as APIs JavaScript do player (window.player.getAudioTracks, getTextTracks) estão disponíveis, porém a API nativa do browser (video.audioTracks) não é suportada. A forma primária de mudar áudio/legendas é via a interface visual do player: clicar no ícone de configurações (⊞) e selecionar opções nos menus "IDIOMA ALTERNATIVO" (áudio) e "LEGENDAS" (legendas).

Este módulo integra-se ao Player Discovery existente (src/player_discovery/) e utiliza o Capability_Map para descobrir e interagir com os controles de configurações.

Escopo:
- **Interação via UI**: Playwright clica nos elementos visuais do player para acessar opções de áudio e legenda
- **Validação via API**: Shaka Player API confirma que a mudança de track realmente ocorreu
- **Monitoramento de áudio**: Web Audio API coleta telemetria de 30 segundos por track de áudio selecionado
- **Monitoramento de legendas**: TextTrack API verifica presença de cues ativas após seleção
- **Relatório consolidado**: Resultado por canal com status de cada track de áudio e legenda testado

Canais monitorados:
- https://www.skymais.com.br/player/live/CH0100000000124
- https://www.skymais.com.br/player/live/CH0100000000092
- https://www.skymais.com.br/player/live/CH0100000000093
- https://www.skymais.com.br/player/live/CH0100000000094
- https://www.skymais.com.br/player/live/CH0100000000096

## Glossary

- **Settings_Dialog**: Diálogo modal que aparece ao clicar no ícone de configurações (⊞) no player, contendo seções para áudio e legendas
- **Audio_Section**: Seção "IDIOMA ALTERNATIVO" dentro do Settings_Dialog que lista as opções de idioma de áudio disponíveis (ex: Português, Inglês)
- **Subtitle_Section**: Seção "LEGENDAS" dentro do Settings_Dialog que lista as opções de legenda disponíveis (ex: Desativadas, Português, Português [CC])
- **Settings_Icon**: Botão no canto inferior direito da barra de controles do player que abre o Settings_Dialog (ícone de linhas cruzadas ⊞)
- **Audio_Track**: Uma opção de idioma de áudio disponível para seleção no player
- **Subtitle_Track**: Uma opção de legenda disponível para seleção no player
- **Shaka_Player_API**: Interface JavaScript exposta em window.player com métodos getAudioTracks() e getTextTracks() para consulta e verificação de tracks
- **Web_Audio_API**: API do browser utilizada para capturar e analisar sinais de áudio do elemento video, medindo RMS e presença de áudio
- **TextTrack_API**: API do browser para consulta de tracks de texto (legendas) e monitoramento de cues ativas
- **Audio_Telemetry_Window**: Período de 30 segundos de coleta de dados de áudio via Web Audio API após seleção de um Audio_Track
- **Monitoring_Session**: Execução completa do teste de áudio e legendas em um canal específico
- **Track_Test_Result**: Resultado individual do teste de um track específico, contendo: track_name, status (PASS/FAIL/TIMEOUT), evidence e telemetry
- **Channel_Test_Report**: Relatório consolidado de uma Monitoring_Session contendo todos os Track_Test_Results de áudio e legenda para um canal
- **UI_Interaction_Module**: Componente que utiliza Playwright para clicar em elementos da UI do player seguindo a interaction_strategy do Capability_Map

## Requirements

### Requirement 1: Abertura do Settings Dialog via UI

**User Story:** Como sistema de monitoramento, eu quero abrir o diálogo de configurações do player clicando no ícone de settings, para acessar as opções de áudio e legendas.

#### Acceptance Criteria

1. WHEN uma Monitoring_Session inicia para um canal, THE UI_Interaction_Module SHALL localizar o Settings_Icon na barra de controles do player utilizando a interaction_strategy do Capability_Map (player_api, semantic_dom ou visual_fallback)
2. WHEN o Settings_Icon é localizado, THE UI_Interaction_Module SHALL clicar no Settings_Icon e aguardar até 5 segundos pela aparição do Settings_Dialog
3. WHEN o Settings_Dialog aparece, THE UI_Interaction_Module SHALL identificar a presença da Audio_Section ("IDIOMA ALTERNATIVO") e da Subtitle_Section ("LEGENDAS") no diálogo
4. IF o Settings_Icon não for encontrado ou o Settings_Dialog não aparecer dentro de 5 segundos após o clique, THEN THE UI_Interaction_Module SHALL classificar o teste como FAIL com evidence "settings_dialog_unavailable" e encerrar a Monitoring_Session para o canal
5. WHEN a barra de controles do player não está visível, THE UI_Interaction_Module SHALL mover o cursor sobre o player para acionar a exibição dos controles antes de buscar o Settings_Icon

### Requirement 2: Descoberta de Opções de Áudio Disponíveis

**User Story:** Como sistema de monitoramento, eu quero descobrir todas as opções de áudio disponíveis no canal, para testar cada uma individualmente.

#### Acceptance Criteria

1. WHEN o Settings_Dialog está aberto e a Audio_Section está visível, THE UI_Interaction_Module SHALL coletar todos os itens listados na Audio_Section, registrando o texto de cada opção (ex: "Português", "Inglês")
2. WHEN os itens da Audio_Section são coletados, THE UI_Interaction_Module SHALL identificar qual opção está atualmente selecionada (estado ativo/highlighted) e registrá-la como audio_track_initial
3. THE UI_Interaction_Module SHALL validar as opções descobertas na UI contra o resultado de window.player.getAudioTracks() via Shaka_Player_API para confirmar consistência entre UI e API
4. IF a Audio_Section não contiver opções visíveis ou não estiver presente no Settings_Dialog, THEN THE UI_Interaction_Module SHALL classificar o áudio como "audio_options_unavailable" e registrar no Channel_Test_Report

### Requirement 3: Teste Funcional de Tracks de Áudio via UI

**User Story:** Como sistema de monitoramento, eu quero clicar em cada opção de áudio disponível e monitorar o áudio resultante, para validar que todas as opções de idioma funcionam corretamente.

#### Acceptance Criteria

1. WHEN a lista de Audio_Tracks é conhecida, THE UI_Interaction_Module SHALL iterar por cada Audio_Track disponível, clicando na opção correspondente na Audio_Section do Settings_Dialog
2. WHEN um Audio_Track é selecionado via clique na UI, THE UI_Interaction_Module SHALL verificar via Shaka_Player_API (window.player.getAudioTracks()) que o track ativo mudou para o idioma selecionado dentro de 5 segundos
3. WHEN a mudança de Audio_Track é confirmada via API, THE Web_Audio_API SHALL coletar telemetria de áudio durante uma Audio_Telemetry_Window de 30 segundos, registrando: RMS médio, RMS mínimo, RMS máximo, presença de áudio (RMS acima de 0.01), e duração de silêncio
4. WHEN a Audio_Telemetry_Window é concluída, THE UI_Interaction_Module SHALL classificar o Track_Test_Result como PASS se áudio foi detectado (RMS acima de 0.01) em pelo menos 80 porcento das amostras coletadas
5. IF o áudio não for detectado (RMS abaixo de 0.01) em mais de 20 porcento das amostras durante a Audio_Telemetry_Window, THEN THE UI_Interaction_Module SHALL classificar o Track_Test_Result como FAIL com evidence contendo as métricas coletadas
6. IF a mudança de Audio_Track não for confirmada via Shaka_Player_API dentro de 5 segundos, THEN THE UI_Interaction_Module SHALL classificar o Track_Test_Result como FAIL com evidence "track_switch_not_confirmed"
7. WHEN todos os Audio_Tracks foram testados, THE UI_Interaction_Module SHALL restaurar o Audio_Track inicial (audio_track_initial) para deixar o player no estado original

### Requirement 4: Descoberta de Opções de Legendas Disponíveis

**User Story:** Como sistema de monitoramento, eu quero descobrir todas as opções de legenda disponíveis no canal, para testar cada uma individualmente.

#### Acceptance Criteria

1. WHEN o Settings_Dialog está aberto e a Subtitle_Section está visível, THE UI_Interaction_Module SHALL coletar todos os itens listados na Subtitle_Section, registrando o texto de cada opção (ex: "Desativadas", "Português", "Português [CC]")
2. WHEN os itens da Subtitle_Section são coletados, THE UI_Interaction_Module SHALL identificar qual opção está atualmente selecionada e registrá-la como subtitle_track_initial
3. THE UI_Interaction_Module SHALL validar as opções descobertas na UI contra o resultado de window.player.getTextTracks() via Shaka_Player_API para confirmar consistência entre UI e API
4. IF a Subtitle_Section não contiver opções visíveis ou não estiver presente no Settings_Dialog, THEN THE UI_Interaction_Module SHALL classificar as legendas como "subtitle_options_unavailable" e registrar no Channel_Test_Report

### Requirement 5: Teste Funcional de Tracks de Legendas via UI

**User Story:** Como sistema de monitoramento, eu quero clicar em cada opção de legenda disponível e verificar se a legenda aparece, para validar que o serviço de legendas funciona corretamente.

#### Acceptance Criteria

1. WHEN a lista de Subtitle_Tracks é conhecida, THE UI_Interaction_Module SHALL iterar por cada Subtitle_Track disponível (excluindo a opção "Desativadas"), clicando na opção correspondente na Subtitle_Section do Settings_Dialog
2. WHEN um Subtitle_Track é selecionado via clique na UI, THE UI_Interaction_Module SHALL verificar via Shaka_Player_API (window.player.getTextTracks()) que o track ativo mudou para o idioma selecionado dentro de 5 segundos
3. WHEN a mudança de Subtitle_Track é confirmada via API, THE TextTrack_API SHALL monitorar activeCues no TextTrack correspondente durante 15 segundos aguardando pelo menos uma cue ativa
4. WHEN uma cue ativa é detectada dentro de 15 segundos, THE UI_Interaction_Module SHALL classificar o Track_Test_Result como PASS com evidence contendo: track_name, cue_text (primeiros 50 caracteres), e tempo até primeira cue
5. IF nenhuma cue ativa for detectada dentro de 15 segundos, THEN THE UI_Interaction_Module SHALL classificar o Track_Test_Result como TIMEOUT com evidence "no_active_cues_within_15s"
6. IF a mudança de Subtitle_Track não for confirmada via Shaka_Player_API dentro de 5 segundos, THEN THE UI_Interaction_Module SHALL classificar o Track_Test_Result como FAIL com evidence "subtitle_switch_not_confirmed"
7. WHEN todos os Subtitle_Tracks foram testados, THE UI_Interaction_Module SHALL selecionar a opção subtitle_track_initial para restaurar o estado original do player

### Requirement 6: Gerenciamento do Settings Dialog durante Testes

**User Story:** Como sistema de monitoramento, eu quero gerenciar a abertura e fechamento do Settings Dialog de forma confiável durante a sequência de testes, para que as interações com o menu sejam consistentes.

#### Acceptance Criteria

1. WHEN o UI_Interaction_Module precisa clicar em uma opção dentro do Settings_Dialog e o diálogo não está visível, THE UI_Interaction_Module SHALL reabrir o Settings_Dialog clicando no Settings_Icon antes de tentar a seleção
2. WHEN uma opção é selecionada no Settings_Dialog e o diálogo fecha automaticamente, THE UI_Interaction_Module SHALL registrar que o diálogo foi fechado e reabri-lo para a próxima seleção
3. WHEN uma opção é selecionada no Settings_Dialog e o diálogo permanece aberto, THE UI_Interaction_Module SHALL continuar a seleção da próxima opção sem fechar e reabrir o diálogo
4. IF o Settings_Dialog não responder a interações (opções não clicáveis, diálogo congelado), THEN THE UI_Interaction_Module SHALL fechar o diálogo (pressionar Escape ou clicar fora), aguardar 2 segundos e tentar reabrir uma vez antes de classificar como FAIL
5. THE UI_Interaction_Module SHALL fechar o Settings_Dialog ao final de cada Monitoring_Session para restaurar o estado visual do player

### Requirement 7: Relatório Consolidado por Canal

**User Story:** Como sistema de monitoramento, eu quero um relatório consolidado com os resultados de todos os testes de áudio e legendas por canal, para ter visibilidade completa do status do serviço.

#### Acceptance Criteria

1. WHEN uma Monitoring_Session é concluída para um canal, THE UI_Interaction_Module SHALL produzir um Channel_Test_Report contendo: channel_url, timestamp, audio_results (lista de Track_Test_Results), subtitle_results (lista de Track_Test_Results) e overall_status
2. THE Channel_Test_Report SHALL calcular overall_status como PASS quando todos os Track_Test_Results de áudio e legenda são PASS, PARTIAL quando pelo menos um é PASS e pelo menos um é FAIL ou TIMEOUT, e FAIL quando todos são FAIL ou TIMEOUT
3. WHEN o Channel_Test_Report é gerado, THE UI_Interaction_Module SHALL serializar o relatório em formato JSON e armazená-lo no diretório de output configurado com nome no formato "audio_subtitle_report_{channel_id}_{timestamp}.json"
4. THE Channel_Test_Report SHALL incluir para cada Track_Test_Result: track_name, track_type (audio ou subtitle), status (PASS/FAIL/TIMEOUT), evidence (detalhes da falha ou sucesso), duration_ms (tempo total do teste) e telemetry (dados coletados quando aplicável)

### Requirement 8: Integração com Player Discovery e Capability Map

**User Story:** Como sistema de monitoramento, eu quero que o módulo de áudio/legendas se integre ao Player Discovery existente usando o Capability Map, para manter consistência arquitetural e reutilizar descobertas do player.

#### Acceptance Criteria

1. WHEN o módulo de monitoramento de áudio e legendas é inicializado, THE UI_Interaction_Module SHALL consultar o Capability_Map para obter a interaction_strategy da capability "settings" e utilizá-la para localizar o Settings_Icon
2. WHEN o Capability_Map indica settings available=true com interaction_strategy semantic_dom, THE UI_Interaction_Module SHALL localizar o Settings_Icon via Playwright locators semânticos (role, aria-label, text content) sem usar seletores CSS fixos
3. WHEN o Capability_Map indica settings available=true com interaction_strategy visual_fallback, THE UI_Interaction_Module SHALL localizar o Settings_Icon via atributos visuais e contextuais (posição relativa na barra de controles, ícone reconhecível)
4. IF o Capability_Map não contiver a capability "settings" ou indicar available=false, THEN THE UI_Interaction_Module SHALL tentar descoberta dinâmica do Settings_Icon usando heurísticas semânticas (busca por botões com aria-label contendo "settings", "configurações", "opções") antes de classificar como indisponível
5. THE UI_Interaction_Module SHALL registrar todas as interações executadas (cliques, verificações, tempos) como eventos no log estruturado para correlação com o EventProbe do Player Discovery

### Requirement 9: Orquestração Multi-Canal

**User Story:** Como sistema de monitoramento, eu quero executar os testes de áudio e legendas em todos os canais configurados em sequência, para ter visibilidade completa da plataforma.

#### Acceptance Criteria

1. THE UI_Interaction_Module SHALL iterar pela lista de canais configurados (CH0100000000124, CH0100000000092, CH0100000000093, CH0100000000094, CH0100000000096) executando uma Monitoring_Session completa em cada canal
2. WHEN o UI_Interaction_Module navega para um novo canal, THE UI_Interaction_Module SHALL aguardar o player iniciar reprodução (currentTime avançando) por até 30 segundos antes de iniciar a Monitoring_Session
3. IF o player não iniciar reprodução dentro de 30 segundos após navegação, THEN THE UI_Interaction_Module SHALL classificar o canal como "playback_not_started" no Channel_Test_Report e avançar para o próximo canal
4. WHEN todos os canais foram testados, THE UI_Interaction_Module SHALL produzir um relatório de execução consolidado contendo: total de canais testados, canais com status PASS, PARTIAL e FAIL, e tempo total de execução
5. IF um erro inesperado ocorrer durante a Monitoring_Session de um canal (crash, timeout de navegação, exceção não tratada), THEN THE UI_Interaction_Module SHALL registrar o erro no Channel_Test_Report, fechar e reabrir o Settings_Dialog se necessário, e avançar para o próximo canal sem interromper a execução

### Requirement 10: Validação Cruzada UI vs API

**User Story:** Como sistema de monitoramento, eu quero validar que as mudanças feitas via UI são refletidas na API do player, para garantir que a interface do player está funcionando corretamente e não apenas exibindo opções sem efeito.

#### Acceptance Criteria

1. WHEN um Audio_Track é selecionado via clique na UI, THE UI_Interaction_Module SHALL consultar window.player.getAudioTracks() e verificar que o track com o language correspondente está marcado como active
2. WHEN um Subtitle_Track é selecionado via clique na UI, THE UI_Interaction_Module SHALL consultar window.player.getTextTracks() e verificar que o track com o language correspondente está marcado como active
3. IF a UI indicar uma opção como selecionada mas a Shaka_Player_API não confirmar a mudança, THEN THE UI_Interaction_Module SHALL classificar como "ui_api_mismatch" e registrar ambos os estados (UI selecionado, API não ativo) como evidence no Track_Test_Result
4. THE UI_Interaction_Module SHALL registrar no Track_Test_Result o estado da API antes e depois de cada seleção via UI para permitir análise de consistência
