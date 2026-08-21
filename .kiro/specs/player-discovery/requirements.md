# Requirements Document

## Introduction

Este documento define os requisitos para o sistema de Player Discovery — um mecanismo de descoberta dinâmica e agnóstica de capacidades do player de TV ao vivo da plataforma SKY+.

A PoC anterior (Widevine DRM) validou que Chrome + Playwright + OpenCV + Bedrock funciona end-to-end em EC2 com conteúdo DRM. O próximo passo é substituir qualquer dependência de seletores fixos (IDs, classes CSS, coordenadas) por um sistema que descobre semanticamente e comportamentalmente como o player funciona, gerando um Capability Map reutilizável por todos os canais.

Princípios centrais:
- **Player-agnostic**: nenhum seletor, ID ou classe CSS hardcoded.
- **Discovery uma vez**: o mesmo player é usado por todos os canais; discovery completo executa apenas no startup.
- **Detecção determinística primeiro**: OpenCV e Bedrock somente quando a detecção determinística confirma anomalia.
- **Canal saudável não consome IA.**

## Glossary

- **Discovery_Engine**: Módulo responsável por executar o processo completo de descoberta de capacidades do player no startup, analisando DOM, JavaScript, Browser APIs, CSS e evidência comportamental
- **Capability_Map**: Objeto JSON central que descreve todas as capacidades descobertas do player, incluindo disponibilidade, confidence, evidência e estratégia de interação para cada capability
- **Player**: Componente de vídeo da plataforma SKY+ que reproduz conteúdo ao vivo protegido por DRM, incluindo controles de interface
- **VideoProbe**: Módulo que coleta telemetria do elemento HTMLMediaElement (currentTime, readyState, paused, buffered, dropped frames, FPS, resolução, erro)
- **AudioProbe**: Módulo que coleta métricas de áudio via Web Audio API (RMS, peak, silêncio, mute, audio track)
- **SubtitleProbe**: Módulo que coleta informações de legendas via TextTrack API (tracks disponíveis, activeCues, mode, language, kind)
- **BufferProbe**: Módulo que coleta dados de buffer (buffered ranges, waiting events, segment latency)
- **EventProbe**: Módulo que registra todos os eventos do HTMLMediaElement com timestamps
- **Channel_Monitor**: Orquestrador que itera pelos canais utilizando o Capability_Map para monitorar cada canal
- **Confidence_Score**: Valor numérico entre 0.0 e 1.0 que indica o grau de certeza sobre uma capability descoberta
- **Evidence**: Lista de razões que justificam a classificação de uma capability (aria-label semântico, API disponível, teste comportamental confirmado, etc.)
- **MutationObserver_Watcher**: Componente que observa mudanças relevantes no DOM do player com debounce/coalescing para detectar invalidação do Capability_Map
- **Health_Score**: Score composto (0-100) calculado a partir das métricas de vídeo, áudio e funcionalidade, usado exclusivamente para tendência e priorização
- **Functional_Test**: Teste menos frequente que valida interações do player (play/pause, mute/unmute, seleção de áudio, seleção de legenda)

## Requirements

### Requirement 1: Descoberta Dinâmica do Player (POC-PLAYER-00)

**User Story:** Como sistema de monitoramento, eu quero descobrir dinamicamente as capacidades do player no startup, para que o monitoramento funcione sem depender de seletores hardcoded.

#### Acceptance Criteria

1. WHEN o monitor é inicializado e o primeiro canal é carregado, THE Discovery_Engine SHALL executar a descoberta completa de capacidades analisando DOM, JavaScript APIs, Browser APIs, CSS e evidência comportamental, e produzir um Capability_Map dentro de 60 segundos
2. WHEN o Discovery_Engine analisa o DOM, THE Discovery_Engine SHALL identificar elementos de controle buscando semanticamente por atributos role, aria-label, aria-haspopup, title, textContent, data-* e tabindex, sem utilizar seletores CSS fixos, IDs específicos ou classes CSS específicas
3. WHEN o Discovery_Engine analisa JavaScript, THE Discovery_Engine SHALL investigar objetos globais e propriedades do player para descobrir dinamicamente: player instance, player library, player version, track APIs, quality APIs, audio APIs, subtitle APIs e event APIs
4. WHEN o Discovery_Engine analisa Browser APIs, THE Discovery_Engine SHALL verificar a disponibilidade de HTMLMediaElement, TextTrackList, AudioTrackList, MediaCapabilities, Media Session e Performance APIs como fontes primárias de informação
5. WHEN o Discovery_Engine analisa CSS, THE Discovery_Engine SHALL utilizar propriedades visuais (display, visibility, opacity, pointer-events, estados active/selected) exclusivamente como evidência auxiliar, sem derivar identificação de capabilities a partir de classes CSS isoladamente
6. WHEN o Discovery_Engine identifica um possível controle, THE Discovery_Engine SHALL executar um teste comportamental seguro para confirmar a função (interação controlada → observação do resultado → confirmação via API/DOM) antes de classificar a capability como disponível com alta confidence
7. THE Discovery_Engine SHALL produzir um Capability_Map contendo, para cada capability descoberta: available (boolean), confidence (0.0-1.0), evidence (lista de razões) e interaction_strategy (player_api, semantic_dom ou visual_fallback)

### Requirement 2: Capability Map — Estrutura e Capabilities

**User Story:** Como sistema de monitoramento, eu quero um mapa central de capabilities estruturado, para que todos os módulos do monitor consumam informações do player de forma padronizada.

#### Acceptance Criteria

1. THE Capability_Map SHALL conter informações do player (library, version, video_elements) e uma seção de capabilities cobrindo no mínimo: play, pause, mute, unmute, audio_selection, subtitle_selection, quality_selection, fullscreen e settings
2. WHEN uma capability é descoberta com confidence igual ou superior a 0.7, THE Capability_Map SHALL classificá-la como available=true e registrar a interaction_strategy preferencial seguindo a ordem: player_api (Nível 1), semantic_dom (Nível 2), visual_fallback (Nível 3)
3. WHEN uma capability é descoberta com confidence inferior a 0.7, THE Capability_Map SHALL classificá-la como available=false com status UNKNOWN e THE Discovery_Engine SHALL tentar obter mais evidência antes de finalizar
4. THE Capability_Map SHALL ser o único ponto de acesso para informações de interação com o player — nenhum módulo do sistema SHALL acessar seletores, IDs ou classes CSS diretamente para interagir com controles do player
5. WHEN o Capability_Map é gerado, THE Discovery_Engine SHALL serializar o mapa em formato JSON e disponibilizá-lo em memória para consulta por todos os módulos do monitor

### Requirement 3: Cache e Reutilização do Capability Map

**User Story:** Como sistema de monitoramento, eu quero que o discovery execute apenas uma vez e o resultado seja reutilizado por todos os canais, para que o sistema seja eficiente e não repita análises desnecessárias.

#### Acceptance Criteria

1. WHEN o Capability_Map é gerado no startup, THE Channel_Monitor SHALL reutilizar o mesmo Capability_Map para todos os canais subsequentes sem executar discovery completo novamente
2. WHILE o Capability_Map está em memória e válido, THE Discovery_Engine SHALL rejeitar solicitações de discovery completo e retornar o mapa em cache
3. THE Discovery_Engine SHALL manter o Capability_Map em memória durante toda a sessão do monitor (enquanto o browser/player for considerado da mesma versão/estrutura)
4. WHEN o Channel_Monitor navega para um novo canal, THE Channel_Monitor SHALL utilizar o Capability_Map existente sem executar análise DOM completa, análise JS completa ou análise CSS completa para o novo canal

### Requirement 4: Detecção de Mudança e Re-Discovery

**User Story:** Como sistema de monitoramento, eu quero detectar quando o player muda e re-executar o discovery automaticamente, para que o sistema se adapte a atualizações do player sem intervenção manual.

#### Acceptance Criteria

1. WHILE o monitor está em execução, THE MutationObserver_Watcher SHALL observar mudanças relevantes no DOM do player (criação/remoção de controles, mudanças de atributos, mudanças de estrutura) com debounce de coalescing para agrupar múltiplas mutações em um único evento de avaliação
2. WHEN o MutationObserver_Watcher detecta mudanças acumuladas que indicam alteração estrutural do player, THE Discovery_Engine SHALL validar se o Capability_Map atual continua válido testando uma amostra das capabilities registradas
3. IF uma ação descoberta anteriormente falha durante execução (controle não encontrado, menu não apareceu, track não mudou), THEN THE Discovery_Engine SHALL invalidar o Capability_Map, executar novo discovery completo e produzir um novo Capability_Map
4. IF o MutationObserver_Watcher detectar mudanças que não invalidam o Capability_Map (mudanças cosméticas, atualizações de conteúdo), THEN THE Discovery_Engine SHALL manter o Capability_Map atual sem executar re-discovery
5. WHEN o re-discovery é executado, THE Discovery_Engine SHALL substituir o Capability_Map anterior pelo novo mapa e THE Channel_Monitor SHALL utilizar o novo mapa para os canais subsequentes

### Requirement 5: VideoProbe — Telemetria de Vídeo

**User Story:** Como sistema de monitoramento, eu quero coletar telemetria completa do vídeo em cada canal, para detectar problemas de reprodução, freeze, e degradação de qualidade.

#### Acceptance Criteria

1. WHILE o Player está reproduzindo conteúdo em um canal, THE VideoProbe SHALL coletar a cada 2 segundos: currentTime, duration, readyState, paused, playing, ended, seeking, playbackRate, networkState, buffered, videoWidth, videoHeight e error
2. WHEN a API getVideoPlaybackQuality está disponível, THE VideoProbe SHALL coletar totalVideoFrames e droppedVideoFrames, calcular drop_rate (droppedVideoFrames/totalVideoFrames) e estimar FPS médio, mínimo e máximo durante a janela de observação
3. WHEN o Player expõe informações de ABR (bitrate, representation, codec, framerate), THE VideoProbe SHALL registrar quality_changes, up_switches, down_switches e tempo em cada nível de qualidade
4. IF o Player reportar um error no elemento de vídeo, THEN THE VideoProbe SHALL capturar o código de erro e mensagem dentro de 500 milissegundos após o evento e registrar no relatório do canal
5. WHEN currentTime não avança por mais de 5 segundos consecutivos com paused=false, THE VideoProbe SHALL classificar o estado como possível freeze e sinalizar para investigação complementar (frames + OpenCV)

### Requirement 6: AudioProbe — Telemetria e Teste de Áudio

**User Story:** Como sistema de monitoramento, eu quero monitorar o áudio do player e validar a funcionalidade de seleção de áudio, para detectar ausência de áudio e falhas nos controles.

#### Acceptance Criteria

1. WHILE o Player está reproduzindo conteúdo, THE AudioProbe SHALL coletar via Web Audio API a cada 2 segundos: RMS, peak, silence_duration (duração acumulada de silêncio), e muted (estado de mute do player)
2. WHEN o RMS está abaixo de 0.01 por mais de 10 segundos consecutivos com muted=false, THE AudioProbe SHALL classificar o estado como NO_AUDIO e registrar alerta
3. WHEN o RMS está entre 0.01 e 0.05 por mais de 10 segundos consecutivos, THE AudioProbe SHALL classificar o estado como AUDIO_LOW
4. WHEN o Capability_Map indica audio_selection available=true, THE AudioProbe SHALL listar as tracks de áudio disponíveis utilizando a interaction_strategy registrada no mapa
5. WHEN um Functional_Test de áudio é executado, THE AudioProbe SHALL: abrir controle de áudio → listar tracks → selecionar track diferente → confirmar mudança via API/DOM → verificar áudio presente via Web Audio API → classificar como PASS ou FAIL
6. WHEN um Functional_Test de mute/unmute é executado, THE AudioProbe SHALL: acionar mute → verificar muted=true → acionar unmute → verificar muted=false e audio_level válido → classificar como PASS ou FAIL

### Requirement 7: SubtitleProbe — Telemetria e Teste de Legendas

**User Story:** Como sistema de monitoramento, eu quero monitorar legendas e validar a funcionalidade de seleção, para garantir que o serviço de legendas está funcionando.

#### Acceptance Criteria

1. WHILE o Player está reproduzindo conteúdo, THE SubtitleProbe SHALL coletar via TextTrack API: tracks_available (quantidade), language, label, kind e mode de cada track disponível
2. WHEN uma track de legenda está com mode=showing, THE SubtitleProbe SHALL monitorar activeCues e registrar a presença ou ausência de cues ativas a cada 5 segundos
3. WHEN o Capability_Map indica subtitle_selection available=true, THE SubtitleProbe SHALL listar as tracks de legenda disponíveis utilizando a interaction_strategy registrada no mapa
4. WHEN um Functional_Test de legenda é executado, THE SubtitleProbe SHALL: abrir controle de legenda → listar idiomas → selecionar idioma → verificar mode=showing → aguardar cue ativa (timeout 15 segundos) → classificar como PASS ou FAIL
5. IF nenhuma track de legenda for encontrada via TextTrack API, THEN THE SubtitleProbe SHALL classificar o estado como SUBTITLE_UNAVAILABLE e não executar teste funcional de legenda para o canal

### Requirement 8: BufferProbe — Telemetria de Buffer

**User Story:** Como sistema de monitoramento, eu quero monitorar o buffer do player em detalhe, para detectar problemas de rede e degradação de qualidade de serviço.

#### Acceptance Criteria

1. WHILE o Player está reproduzindo conteúdo, THE BufferProbe SHALL coletar a cada 2 segundos: buffered_start, buffered_end, buffer_ahead (diferença entre buffered_end e currentTime)
2. WHEN o Player emite evento waiting ou stalled, THE BufferProbe SHALL registrar o timestamp de início e calcular: waiting_count, waiting_total_ms, longest_wait_ms e time_since_last_wait
3. WHEN o buffer_ahead cai abaixo de 2 segundos com o Player em estado playing, THE BufferProbe SHALL classificar como buffer_low e registrar alerta
4. IF o Player emitir mais de 3 eventos waiting em uma janela de 60 segundos, THEN THE BufferProbe SHALL classificar o estado como BUFFERING_FREQUENT e sinalizar degradação de rede

### Requirement 9: EventProbe — Registro de Eventos

**User Story:** Como sistema de monitoramento, eu quero registrar todos os eventos do player com timestamps, para ter visibilidade completa do ciclo de vida da reprodução.

#### Acceptance Criteria

1. WHEN o Player inicia a reprodução de um canal, THE EventProbe SHALL registrar listeners para todos os eventos do HTMLMediaElement: loadstart, loadedmetadata, loadeddata, canplay, canplaythrough, play, playing, pause, waiting, stalled, seeking, seeked, ended e error
2. WHEN qualquer evento registrado é disparado, THE EventProbe SHALL capturar: event_type, timestamp (ISO 8601 com milissegundos), currentTime no momento do evento, e dados adicionais relevantes (error code para eventos error, buffered_seconds para eventos waiting)
3. WHEN o Channel_Monitor navega para um novo canal, THE EventProbe SHALL limpar o registro de eventos do canal anterior e iniciar novo registro para o canal atual
4. THE EventProbe SHALL manter em memória os eventos dos últimos 5 minutos de reprodução por canal para correlação com outras probes

### Requirement 10: Multi-Canal — Rotação e Reutilização

**User Story:** Como sistema de monitoramento, eu quero iterar por todos os canais da lista usando o mesmo Capability Map, para monitorar a plataforma completa de forma eficiente.

#### Acceptance Criteria

1. WHEN o Discovery_Engine produz um Capability_Map válido, THE Channel_Monitor SHALL iniciar a rotação pela lista de canais, aplicando o mesmo Capability_Map a cada canal sem re-discovery
2. WHEN o Channel_Monitor navega para um canal, THE Channel_Monitor SHALL ativar VideoProbe, AudioProbe, SubtitleProbe, BufferProbe e EventProbe para o canal corrente e coletar telemetria durante o período de observação configurado
3. WHEN o período de observação de um canal é concluído, THE Channel_Monitor SHALL consolidar os resultados das probes em um relatório do canal e navegar para o próximo canal da lista
4. IF o Channel_Monitor detectar que uma ação do Capability_Map falha em um canal específico, THEN THE Channel_Monitor SHALL registrar a falha para o canal, continuar a rotação, e acumular evidência — somente invalidar o Capability_Map se a falha ocorrer em múltiplos canais consecutivos (threshold configurável, padrão: 3)

### Requirement 11: Testes Funcionais — Execução Periódica

**User Story:** Como sistema de monitoramento, eu quero executar testes funcionais (play/pause, mute, áudio, legenda) com menor frequência que a telemetria, para validar que os controles do player funcionam sem impactar performance.

#### Acceptance Criteria

1. THE Channel_Monitor SHALL separar a coleta de telemetria (health check — toda rotação de canal) dos testes funcionais (Functional_Test — executados a cada N rotações, configurável, padrão: 5)
2. WHEN um ciclo de Functional_Test é acionado, THE Channel_Monitor SHALL executar os testes disponíveis no Capability_Map: play/pause, mute/unmute, audio_selection e subtitle_selection, na ordem de menor impacto para maior impacto
3. WHEN um Functional_Test falha, THE Channel_Monitor SHALL registrar: capability testada, ação executada, resultado esperado, resultado obtido e classificar como FUNCTIONAL_FAIL
4. IF um Functional_Test falha e a capability estava registrada com confidence >= 0.9, THEN THE Channel_Monitor SHALL sinalizar possível mudança no player e solicitar validação do Capability_Map

### Requirement 12: Três Níveis de Interação

**User Story:** Como sistema de monitoramento, eu quero que toda interação com o player siga uma hierarquia de preferência (API → DOM semântico → visual), para maximizar confiabilidade e minimizar fragilidade.

#### Acceptance Criteria

1. WHEN o Discovery_Engine identifica uma capability, THE Discovery_Engine SHALL classificar a interaction_strategy preferencial como: player_api (Nível 1 — chamada direta à API do player), semantic_dom (Nível 2 — locator via role, aria-label, text, data-attributes), ou visual_fallback (Nível 3 — interação visual sem coordenadas fixas)
2. WHEN um módulo do monitor precisa interagir com o player, THE Channel_Monitor SHALL tentar primeiro a interaction_strategy de Nível 1, e somente usar Nível 2 se Nível 1 falhar, e Nível 3 somente se Nível 2 também falhar
3. THE Discovery_Engine SHALL registrar no Capability_Map, para cada capability, todas as strategies disponíveis ordenadas por preferência, permitindo fallback automático sem re-discovery
4. THE Channel_Monitor SHALL rejeitar qualquer interação baseada em coordenadas fixas, posição absoluta ou índice posicional de elementos (primeiro botão, segundo item de menu)

### Requirement 13: Health Score — Composição e Uso

**User Story:** Como sistema de monitoramento, eu quero scores compostos de saúde do vídeo, áudio e funcionalidade, para tendência e priorização de canais com problemas.

#### Acceptance Criteria

1. WHEN a telemetria de um canal é consolidada, THE Channel_Monitor SHALL calcular um Video_Health_Score (0-100) com pesos: Playback 20%, Buffer 15%, Dropped Frames 15%, Freeze 10%, FPS 10%, Resolution 10%, DRM 20%
2. WHEN a telemetria de áudio de um canal é consolidada, THE Channel_Monitor SHALL calcular um Audio_Health_Score (0-100) com pesos: Audio present 40%, RMS 20%, Peak 10%, Silence 20%, Track 10%
3. WHEN testes funcionais são executados, THE Channel_Monitor SHALL calcular um Functional_Health_Score (0-100) com pesos iguais: Play/Pause 25%, Audio selection 25%, Subtitle selection 25%, Quality selection 25%
4. THE Health_Score SHALL ser utilizado exclusivamente para tendência e priorização — estados objetivos (PASS/FAIL, erro específico) SHALL ter precedência sobre scores numéricos para decisões de alerta

### Requirement 14: Detecção Determinística Primeiro

**User Story:** Como sistema de monitoramento, eu quero que anomalias sejam confirmadas por detecção determinística antes de acionar OpenCV ou Bedrock, para minimizar custo de IA e falsos positivos.

#### Acceptance Criteria

1. WHEN a telemetria indica canal saudável (currentTime avançando, buffer adequado, áudio presente, sem erros), THE Channel_Monitor SHALL classificar o canal como HEALTHY sem capturar frames adicionais ou acionar OpenCV/Bedrock
2. WHEN a telemetria indica suspeita de problema (freeze possível, buffer baixo, áudio ausente), THE Channel_Monitor SHALL capturar frames adicionais e acionar OpenCV para confirmar a anomalia deterministicamente
3. IF o OpenCV confirma anomalia (BLACK_SCREEN, FREEZE confirmado), THEN THE Channel_Monitor SHALL acionar Bedrock para diagnóstico visual detalhado
4. IF o OpenCV não confirma anomalia (conteúdo visual normal, movimento detectado), THEN THE Channel_Monitor SHALL classificar como alarme falso e não acionar Bedrock
5. WHILE o canal está classificado como HEALTHY, THE Channel_Monitor SHALL capturar apenas 1 frame de validação por ciclo — somente escalar para múltiplos frames quando houver suspeita

