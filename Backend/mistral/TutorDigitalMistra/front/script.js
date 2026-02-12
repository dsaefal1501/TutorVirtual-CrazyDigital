// --- CONFIGURACIÓN E INICIALIZACIÓN DE UNITY ---
function loadUnity() {
    var canvas = document.querySelector("#unity-canvas");
    var config = {
        dataUrl: "BuildVanilla/Build/BuildVanilla.data.unityweb",
        frameworkUrl: "BuildVanilla/Build/BuildVanilla.framework.js.unityweb",
        codeUrl: "BuildVanilla/Build/BuildVanilla.wasm.unityweb",
        streamingAssetsUrl: "BuildVanilla/StreamingAssets",
        companyName: "DefaultCompany",
        productName: "TutorVirtual",
        productVersion: "0.1.0",
    };

    var script = document.createElement("script");
    script.src = "BuildVanilla/Build/BuildVanilla.loader.js";
    script.onload = () => {
        createUnityInstance(canvas, config).then((unityInstance) => {
            window.unityInstance = unityInstance;
            document.getElementById('loading-overlay').style.display = 'none';
            document.getElementById('statusDot').classList.add('online');
            document.getElementById('connectionStatus').innerText = "En línea";
        }).catch((message) => { alert(message); });
    };
    script.onerror = () => { document.getElementById('loading-overlay').style.display = 'none'; }
    document.body.appendChild(script);
}

// Iniciar Unity al cargar la página
document.addEventListener("DOMContentLoaded", loadUnity);


// --- LÓGICA DE LA APLICACIÓN (CHAT & RECONOCIMIENTO) ---

const API_URL = 'http://192.168.18.6:8000'; // Asegúrate de que esta IP sea accesible

// Referencias del DOM
const chatWidget = document.getElementById('chat-widget');
const toggleBtn = document.getElementById('chatbot-toggle-btn');
const closeChatBtn = document.getElementById('close-chat-btn');
const userInput = document.getElementById('userInput');
const chatContainer = document.getElementById('chatContainer');
const micBtn = document.getElementById('mic-btn');
const micIcon = document.getElementById('mic-icon');
const micLabel = document.getElementById('mic-label');
const streamToggle = document.getElementById('streamToggle');
const sendBtn = document.getElementById('sendBtn');
const subtitleText = document.getElementById('subtitle-text');
const chatForm = document.getElementById('chatForm');
const ttsToggle = document.getElementById('ttsToggle');

// Estado
let isChatOpen = false;
let isConversationMode = false;
let recognition = null;
let botIsSpeaking = false;
let isProcessing = false;

// --- TTS Estado ---
let currentAudio = null;       // HTMLAudioElement activo
let currentAudioUrl = null;    // URL.createObjectURL activo (para liberar memoria)
let ttsEnabled = true;         // Toggle global de TTS

// --- NUEVO: TTS Chunked Pipeline ---
let ttsChunkQueue = [];         // Cola de chunks: { text, audioPromise, audioBlob, subtitleWords }
let ttsIsPlaying = false;       // ¿Hay un chunk reproduciéndose?
let ttsSentenceBuffer = "";     // Buffer para construir oraciones desde el streaming
let ttsAborted = false;         // Flag para abortar el pipeline
let ttsOnEndCallback = null;    // Callback final cuando todo termina
let ttsChunkIndex = 0;          // Índice para tracking

// --- CONFIGURACIÓN DE SUBTÍTULOS Y EMOCIONES ---
let botWordQueue = []; // Para modo sin TTS: guardará objetos {type: 'tag'|'word', value: '...'}
let isShowingSubtitle = false;
let streamBuffer = "";
const TIME_PER_WORD_MS = 320;
const MIN_TIME_ON_SCREEN_MS = 1500;
const TAG_REGEX = /(\\[.*?\\])/g; // Regex para capturar [Etiquetas]

// Configuración subtítulos con TTS (palabras por línea)
const SUBTITLE_MAX_WORDS = 14; // Máximo de palabras por línea de subtítulo

// Configuración de Reconocimiento de Voz
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'es-ES';
    recognition.continuous = false;
    recognition.interimResults = true;

    recognition.onstart = () => {
        updateMicVisuals(true, "Escuchando...");
        clearBotSubtitles();
    };

    recognition.onend = () => {
        if (isConversationMode && !botIsSpeaking) {
            updateMicVisuals(false, "Pausado");
        }
        if (!isProcessing && !botIsSpeaking) {
            setTimeout(() => { if (!botIsSpeaking) subtitleText.innerText = ""; }, 2000);
        }
    };

    recognition.onresult = (event) => {
        let transcript = '';
        let interimTranscript = '';
        let isFinal = false;

        for (let i = event.resultIndex; i < event.results.length; ++i) {
            const t = event.results[i][0].transcript;
            transcript += t;
            interimTranscript += t;
            if (event.results[i].isFinal) isFinal = true;
        }

        updateUserSubtitle(interimTranscript);

        if (isChatOpen) {
            userInput.value = transcript;
            autoResizeInput();
        }

        if (isFinal && transcript.trim() !== "") {
            setTimeout(() => { if (!botIsSpeaking) subtitleText.innerText = ""; }, 500);
            if (isChatOpen) {
                handleSendMessage(transcript);
            } else {
                handleConversationTurn(transcript);
            }
        }
    };
}

// --- EVENT LISTENERS ---

micBtn.addEventListener('click', handleMicClick);
toggleBtn.addEventListener('click', toggleChat);
closeChatBtn.addEventListener('click', toggleChat);

chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (userInput.value.trim()) handleSendMessage(userInput.value.trim());
});

// TTS toggle
if (ttsToggle) {
    ttsToggle.addEventListener('change', () => {
        ttsEnabled = ttsToggle.checked;
        if (!ttsEnabled) stopTTS();
    });
}

userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (userInput.value.trim()) handleSendMessage(userInput.value.trim());
    }
});


// --- FUNCIONES LÓGICAS ---

function handleMicClick() {
    if (!recognition) return alert("Navegador no compatible");
    if (isChatOpen) {
        if (micBtn.classList.contains('is-listening')) recognition.stop();
        else recognition.start();
    } else {
        if (isConversationMode) stopConversationMode();
        else startConversationMode();
    }
}

function toggleChat() {
    if (chatWidget.style.display === 'none' || chatWidget.style.display === '') {
        chatWidget.style.display = 'flex';
        toggleBtn.style.display = 'none';
        micBtn.classList.add('mic-shifted');
        isChatOpen = true;
        if (isConversationMode) stopConversationMode();
        scrollToBottom();
    } else {
        chatWidget.style.display = 'none';
        toggleBtn.style.display = 'flex';
        micBtn.classList.remove('mic-shifted');
        isChatOpen = false;
    }
}

function startConversationMode() {
    isConversationMode = true;
    try {
        recognition.start();
    } catch (e) {
        if (e.name !== 'InvalidStateError') {
            console.error("Error al iniciar el micro:", e);
            alert("No se pudo iniciar el micrófono: " + e.message);
        }
    }
}

function stopConversationMode() {
    isConversationMode = false;
    botIsSpeaking = false;
    clearBotSubtitles();
    try { recognition.stop(); } catch (e) { }
    updateMicVisuals(false, "Escuchando...");
}

function updateMicVisuals(listening, text) {
    micLabel.innerText = text;
    if (listening) {
        micBtn.classList.add('is-listening');
        micBtn.classList.remove('is-bot-speaking');
        micIcon.className = "bi bi-mic-fill";
    } else {
        micBtn.classList.remove('is-listening');
        if (botIsSpeaking && isConversationMode) {
            micBtn.classList.add('is-bot-speaking');
            micIcon.className = "bi bi-volume-up-fill";
            micLabel.innerText = "Hablando...";
        } else {
            micBtn.classList.remove('is-bot-speaking');
            micIcon.className = "bi bi-mic-fill";
        }
    }
}

// --- GESTIÓN DE MENSAJES Y BACKEND ---

async function handleSendMessage(text) {
    if (!text || isProcessing) return;
    isProcessing = true;
    userInput.value = '';
    autoResizeInput();
    sendBtn.disabled = true;

    stopTTS(); // Detener cualquier audio anterior
    clearBotSubtitles();
    addMessage(text, 'user');
    const typingId = showTyping();

    let fullLogText = "";
    try {
        await processBackendResponse(text, (chunk) => {
            fullLogText += chunk;
            updateBotMessage(typingId, fullLogText);
        });
    } catch (error) {
        removeTyping(typingId);
        addMessage("Error: " + error.message, 'bot');
    } finally {
        isProcessing = false;
        sendBtn.disabled = false;
        flushStreamBuffer();

        // Flush TTS sentence buffer (por si quedó algo pendiente)
        if (ttsEnabled) {
            flushTTSSentenceBuffer();
        }

        // Si NO hay TTS, mantener el sistema anterior de subtítulos
        if (!ttsEnabled) {
            const checkFinishInterval = setInterval(() => {
                if (botWordQueue.length === 0 && !isShowingSubtitle) {
                    clearInterval(checkFinishInterval);
                }
            }, 500);
        }
    }
}

async function handleConversationTurn(text) {
    botIsSpeaking = true;
    try { recognition.stop(); } catch (e) { }
    updateMicVisuals(false, "Pensando...");

    stopTTS(); // Detener audio anterior
    clearBotSubtitles();
    addMessage(text, 'user');
    const typingId = showTyping();

    let fullLogText = "";
    try {
        await processBackendResponse(text, (chunk) => {
            fullLogText += chunk;
            updateBotMessage(typingId, fullLogText);
        });
    } catch (error) {
        console.error(error);
        removeTyping(typingId);
    }

    updateMicVisuals(false, "Hablando...");
    flushStreamBuffer();

    // Flush TTS sentence buffer
    if (ttsEnabled) {
        flushTTSSentenceBuffer();

        // Configurar callback para cuando todo el pipeline termine
        ttsOnEndCallback = () => {
            subtitleText.innerText = "";
            if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);

            if (isConversationMode) {
                botIsSpeaking = false;
                try { recognition.start(); } catch (e) { }
            } else {
                botIsSpeaking = false;
                updateMicVisuals(false, "Escuchando...");
            }
        };

        // Si no hay chunks pendientes ni reproduciéndose, llamar callback inmediatamente
        if (ttsChunkQueue.length === 0 && !ttsIsPlaying) {
            const cb = ttsOnEndCallback;
            ttsOnEndCallback = null;
            if (cb) cb();
        }
    } else {
        // Sin TTS: fallback al sistema anterior de subtítulos
        const checkFinishInterval = setInterval(() => {
            if (botWordQueue.length === 0 && !isShowingSubtitle) {
                clearInterval(checkFinishInterval);
                subtitleText.innerText = "";
                if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);

                if (isConversationMode) {
                    botIsSpeaking = false;
                    try { recognition.start(); } catch (e) { }
                } else {
                    botIsSpeaking = false;
                    updateMicVisuals(false, "Escuchando...");
                }
            }
        }, 500);
    }
}

async function processBackendResponse(text, onChunkReceived) {
    const isStream = streamToggle && streamToggle.checked;
    const endpoint = isStream ? '/ask/stream' : '/ask';

    const response = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texto: text, usuario_id: 2 })
    });

    if (!response.ok) throw new Error("Error del servidor: " + response.status);

    if (isStream) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });

            // Sistema de subtítulos sin TTS
            if (chunk) queueBotWords(chunk);

            // Sistema de TTS chunked: alimentar el buffer de oraciones
            if (ttsEnabled && chunk) {
                feedTTSSentenceBuffer(chunk);
            }

            onChunkReceived(chunk);
        }
    } else {
        const data = await response.json();
        const result = data.respuesta || data.mensaje || JSON.stringify(data);

        if (result.length > 0) queueBotWords(result);

        // Para TTS chunked con respuesta no-stream, dividir en oraciones directamente
        if (ttsEnabled && result.length > 0) {
            feedTTSSentenceBuffer(result);
        }

        onChunkReceived(result);
    }
}

// --- FUNCIONES DE INTERFAZ AUXILIARES ---

function updateUserSubtitle(text) {
    if (!text) return;
    subtitleText.className = "subtitle-text subtitle-user";
    const words = text.trim().split(/\s+/);
    const lastWords = words.length > 10 ? words.slice(-10) : words;
    subtitleText.innerText = lastWords.join(" ");
}

// --- LÓGICA DE SUBTÍTULOS INTELIGENTE (Detecta [Tag] vs Texto) ---
// (Se mantiene para el modo sin TTS)

function queueBotWords(chunkText) {
    if (!chunkText) return;

    streamBuffer += chunkText;

    const lastTagClose = streamBuffer.lastIndexOf("]");
    const lastSpace = streamBuffer.lastIndexOf(" ");
    const safeIndex = Math.max(lastTagClose, lastSpace);

    if (safeIndex !== -1) {
        const completePart = streamBuffer.substring(0, safeIndex + 1);
        streamBuffer = streamBuffer.substring(safeIndex + 1);

        const parts = completePart.split(TAG_REGEX);

        parts.forEach(part => {
            if (TAG_REGEX.test(part)) {
                botWordQueue.push({ type: 'tag', value: part });
            } else if (part.trim().length > 0) {
                const words = part.split(/\s+/).filter(w => w.length > 0);
                words.forEach(w => botWordQueue.push({ type: 'word', value: w }));
            }
        });
    }

    // Solo procesar subtítulos si TTS está deshabilitado
    if (!ttsEnabled && !isShowingSubtitle && botWordQueue.length > 0) {
        processBotSubtitleQueue();
    }
}

function flushStreamBuffer() {
    if (streamBuffer.trim().length > 0) {
        const parts = streamBuffer.split(TAG_REGEX);
        parts.forEach(part => {
            if (TAG_REGEX.test(part)) {
                botWordQueue.push({ type: 'tag', value: part });
            } else if (part.trim().length > 0) {
                const words = part.split(/\s+/).filter(w => w.length > 0);
                words.forEach(w => botWordQueue.push({ type: 'word', value: w }));
            }
        });
        streamBuffer = "";
    }
    if (!ttsEnabled && !isShowingSubtitle && botWordQueue.length > 0) {
        processBotSubtitleQueue();
    }
}

function processBotSubtitleQueue() {
    if (botWordQueue.length === 0) {
        isShowingSubtitle = false;
        subtitleText.innerText = "";
        if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);
        return;
    }

    isShowingSubtitle = true;

    const currentItem = botWordQueue[0];

    // --- CASO 1: ETIQUETA DE EMOCIÓN ---
    if (currentItem.type === 'tag') {
        botWordQueue.shift();
        if (window.unityInstance) {
            window.unityInstance.SendMessage('Tutor', 'SetExpression', currentItem.value);
        }
        processBotSubtitleQueue();
        return;
    }

    // --- CASO 2: PALABRA (Texto visible) ---
    if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 1);

    let batch = [];
    let i = 0;

    while (i < SUBTITLE_MAX_WORDS && botWordQueue.length > 0 && botWordQueue[0].type === 'word') {
        batch.push(botWordQueue.shift().value);
        i++;
    }

    const textToShow = batch.join(" ");
    subtitleText.className = "subtitle-text subtitle-bot";
    subtitleText.innerText = textToShow;

    const duration = Math.max(MIN_TIME_ON_SCREEN_MS, batch.length * TIME_PER_WORD_MS);

    setTimeout(() => {
        processBotSubtitleQueue();
    }, duration);
}

function clearBotSubtitles() {
    botWordQueue = [];
    isShowingSubtitle = false;
    streamBuffer = "";
    subtitleText.innerText = "";
    stopTTS();
    if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);
}

function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `<div class="avatar">${role === 'bot' ? '🤖' : '👤'}</div><div class="message-content"></div>`;
    const content = div.querySelector('.message-content');
    content.innerHTML = typeof marked !== 'undefined' ? marked.parse(text) : text;
    chatContainer.appendChild(div);
    scrollToBottom();
}

function showTyping() {
    const id = `msg-${Date.now()}`;
    const div = document.createElement('div');
    div.className = 'message bot';
    div.id = id;
    div.innerHTML = `<div class="avatar">🤖</div><div class="message-content">...</div>`;
    chatContainer.appendChild(div);
    scrollToBottom();
    return id;
}

function updateBotMessage(id, cleanText) {
    const el = document.getElementById(id);
    if (!el) return;
    const content = el.querySelector('.message-content');
    content.innerText = cleanText;
    scrollToBottom();
}

function removeTyping(id) { document.getElementById(id)?.remove(); }
function scrollToBottom() { setTimeout(() => { chatContainer.scrollTop = chatContainer.scrollHeight; }, 50); }
function autoResizeInput() { userInput.style.height = 'auto'; userInput.style.height = userInput.scrollHeight + 'px'; }


// ===========================================================================
// TTS CHUNKED PIPELINE — Audio casi instantáneo con subtítulos sincronizados
// ===========================================================================

/**
 * Limpia el texto para TTS: elimina etiquetas [Emotion], markdown, etc.
 */
function cleanTextForTTS(rawText) {
    let cleaned = rawText
        .replace(/\[.*?\]/g, '')      // Eliminar [Tags]
        .replace(/[#*_~`>]/g, '')     // Eliminar marcadores Markdown
        .replace(/\n{2,}/g, '. ')     // Doble salto → pausa
        .replace(/\n/g, ' ')          // Salto simple → espacio
        .replace(/\s{2,}/g, ' ')      // Múltiples espacios
        .trim();
    return cleaned;
}

/**
 * Divide texto en oraciones usando delimitadores naturales.
 * Busca: . ! ? ; : y también comas seguidas de espacio si la frase es larga.
 */
function splitIntoSentences(text) {
    // Dividir por puntos finales de oración (.!?), punto y coma, dos puntos
    // Mantenemos el delimitador con la oración
    const raw = text.match(/[^.!?;:]+[.!?;:]*/g) || [text];

    const sentences = [];
    for (let s of raw) {
        s = s.trim();
        if (!s) continue;

        const words = s.split(/\s+/);
        // Si la oración es muy larga (>30 palabras), dividirla por comas
        if (words.length > 30) {
            const subParts = s.match(/[^,]+,?/g) || [s];
            let accumulated = "";
            for (const sub of subParts) {
                accumulated += sub;
                const accWords = accumulated.trim().split(/\s+/);
                if (accWords.length >= 15) {
                    sentences.push(accumulated.trim());
                    accumulated = "";
                }
            }
            if (accumulated.trim()) {
                sentences.push(accumulated.trim());
            }
        } else if (words.length >= 3) {
            // Oración con al menos 3 palabras → chunk válido
            sentences.push(s);
        } else {
            // Muy corta → unir con la anterior si existe
            if (sentences.length > 0) {
                sentences[sentences.length - 1] += " " + s;
            } else {
                sentences.push(s);
            }
        }
    }

    return sentences.filter(s => s.trim().length > 0);
}

/**
 * Alimenta el buffer de oraciones conforme llega texto del streaming.
 * Cuando detecta un final de oración, lanza la petición TTS en paralelo.
 */
function feedTTSSentenceBuffer(chunk) {
    ttsSentenceBuffer += chunk;

    // Buscar oraciones completas en el buffer
    // Una oración está completa cuando encontramos un delimitador seguido de espacio o fin
    const sentenceEnders = /([.!?;:])\s/g;
    let match;
    let lastCutIndex = 0;

    while ((match = sentenceEnders.exec(ttsSentenceBuffer)) !== null) {
        const endIndex = match.index + match[1].length; // incluir el delimitador
        const sentence = ttsSentenceBuffer.substring(lastCutIndex, endIndex).trim();
        lastCutIndex = match.index + match[0].length; // después del espacio

        if (sentence) {
            const cleaned = cleanTextForTTS(sentence);
            if (cleaned.length > 2) { // Evitar chunks triviales
                enqueueTTSChunk(cleaned);
            }
        }
    }

    // Mantener solo lo que no se ha procesado
    if (lastCutIndex > 0) {
        ttsSentenceBuffer = ttsSentenceBuffer.substring(lastCutIndex);
    }
}

/**
 * Flushea lo que quede en el buffer de oraciones (al final del streaming).
 */
function flushTTSSentenceBuffer() {
    if (ttsSentenceBuffer.trim()) {
        const cleaned = cleanTextForTTS(ttsSentenceBuffer.trim());
        if (cleaned.length > 2) {
            enqueueTTSChunk(cleaned);
        }
        ttsSentenceBuffer = "";
    }
}

/**
 * Encola un chunk de texto para TTS.
 * Lanza la petición de generación de audio inmediatamente (en paralelo).
 * El audio se reproducirá en orden cuando le toque.
 */
function enqueueTTSChunk(text) {
    if (ttsAborted) return;

    const chunkId = ttsChunkIndex++;
    console.log(`[TTS Chunk ${chunkId}] Encolando: "${text.substring(0, 60)}..."`);

    // Lanzar la petición TTS inmediatamente (en paralelo)
    const audioPromise = fetchTTSAudio(text);

    // Crear las palabras para subtítulos
    const subtitleWords = text.split(/\s+/).filter(w => w.length > 0);

    const chunk = {
        id: chunkId,
        text: text,
        audioPromise: audioPromise,
        subtitleWords: subtitleWords,
        resolved: false,
        audioBlob: null,
    };

    // Resolver la promesa y guardarlo
    audioPromise.then(blob => {
        chunk.audioBlob = blob;
        chunk.resolved = true;
        console.log(`[TTS Chunk ${chunkId}] Audio listo (${blob ? blob.size : 0} bytes)`);
    }).catch(err => {
        console.error(`[TTS Chunk ${chunkId}] Error:`, err);
        chunk.resolved = true; // Marcarlo como resuelto aunque falle
        chunk.audioBlob = null;
    });

    ttsChunkQueue.push(chunk);

    // Si es el primer chunk, arrancar el pipeline de reproducción
    if (!ttsIsPlaying) {
        playNextTTSChunk();
    }
}

/**
 * Hace la petición HTTP al backend para generar el audio de un texto.
 * Retorna un Blob con el audio MP3.
 */
async function fetchTTSAudio(text) {
    const formData = new FormData();
    formData.append('texto', text);
    formData.append('voz', 'onyx');
    // No enviamos instrucciones — el backend aplica las suyas fijas para mantener voz consistente

    const response = await fetch(`${API_URL}/tts`, {
        method: 'POST',
        body: formData,
    });

    if (!response.ok) {
        const errText = await response.text();
        console.error('[TTS fetch error]', response.status, errText);
        return null;
    }

    return await response.blob();
}

/**
 * Reproduce el siguiente chunk en la cola.
 * Espera a que su audio esté listo, lo reproduce y muestra subtítulos sincronizados.
 */
async function playNextTTSChunk() {
    if (ttsAborted) {
        ttsIsPlaying = false;
        return;
    }

    if (ttsChunkQueue.length === 0) {
        ttsIsPlaying = false;

        // Todo terminó → ejecutar callback final
        if (ttsOnEndCallback) {
            const cb = ttsOnEndCallback;
            ttsOnEndCallback = null;
            cb();
        }
        return;
    }

    ttsIsPlaying = true;
    const chunk = ttsChunkQueue.shift();

    // Esperar a que el audio esté listo (si aún no lo está)
    if (!chunk.resolved) {
        console.log(`[TTS Chunk ${chunk.id}] Esperando audio...`);
        try {
            await chunk.audioPromise;
        } catch (e) {
            // Error ya manejado en el .then/.catch del enqueueTTSChunk
        }
    }

    if (ttsAborted) {
        ttsIsPlaying = false;
        return;
    }

    // Si no hay blob (error), saltar al siguiente
    if (!chunk.audioBlob) {
        console.warn(`[TTS Chunk ${chunk.id}] Sin audio, saltando`);
        playNextTTSChunk();
        return;
    }

    // Activar animación de habla
    botIsSpeaking = true;
    if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 1);
    updateMicVisuals(false, "Hablando...");
    try {
        const formData = new FormData();
        formData.append('texto', texto);
        formData.append('voz', 'onyx');
        formData.append('instrucciones', 'Habla con acento castellano de España, de forma natural, cálida y expresiva, como un profesor cercano. Evita sonar robótico. Usa entonación variada y pausas naturales.');

        return new Promise((resolve) => {
            // Cuando se carguen los metadatos, sabemos la duración
            audio.addEventListener('loadedmetadata', () => {
                const duration = audio.duration; // en segundos
                console.log(`[TTS Chunk ${chunk.id}] Reproduciendo (${duration.toFixed(2)}s): "${chunk.text.substring(0, 40)}..."`);

                // Mostrar subtítulos sincronizados con la duración real del audio
                showSyncedSubtitles(chunk.subtitleWords, duration);
            });

            if (!response.ok) {
                const errText = await response.text();
                console.error('TTS error:', response.status, errText);
                finishTTS(onEnd);
                return;
            }

            const audioBlob = await response.blob();
            const audioUrl = URL.createObjectURL(audioBlob);

            // Liberar URL anterior si existe
            if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);

            const audio = new Audio(audioUrl);
            currentAudio = audio;
            currentAudioUrl = audioUrl;

            // Esperar a que el audio tenga duración para sincronizar subtítulos
            audio.addEventListener('loadedmetadata', () => {
                const duration = audio.duration; // segundos
                if (duration && duration > 0) {
                    showSyncedSubtitles(texto, duration);
                }
            });

            audio.addEventListener('ended', () => {
                URL.revokeObjectURL(audioUrl);
                currentAudio = null;
                currentAudioUrl = null;
                resolve();

                // Reproducir siguiente chunk
                playNextTTSChunk();
            });

            audio.addEventListener('error', (e) => {
                console.error(`[TTS Chunk ${chunk.id}] Error reproduciendo:`, e);
                URL.revokeObjectURL(audioUrl);
                currentAudio = null;
                currentAudioUrl = null;
                resolve();
                playNextTTSChunk();
            });

            audio.play().catch(err => {
                console.error(`[TTS Chunk ${chunk.id}] Error play():`, err);
                resolve();
                playNextTTSChunk();
            });
        });
    }

/**
 * Muestra subtítulos sincronizados con la duración real del audio.
 * Divide las palabras en grupos legibles y los muestra progresivamente.
 */
function showSyncedSubtitles(words, audioDurationSec) {
        if (!words || words.length === 0) return;

        const totalWords = words.length;
        const totalDurationMs = audioDurationSec * 1000;

        // Calcular cuántas "pantallas" de subtítulos necesitamos
        // Usamos grupos de hasta SUBTITLE_MAX_WORDS palabras
        const groups = [];
        for (let i = 0; i < totalWords; i += SUBTITLE_MAX_WORDS) {
            groups.push(words.slice(i, i + SUBTITLE_MAX_WORDS).join(" "));
        }

        // Duración por grupo, proporcional a las palabras que contiene
        const timePerWord = totalDurationMs / totalWords;

        let elapsed = 0;
        groups.forEach((groupText, idx) => {
            const wordsInGroup = groupText.split(/\s+/).length;
            const groupDuration = wordsInGroup * timePerWord;

            setTimeout(() => {
                if (ttsAborted) return;
                subtitleText.className = "subtitle-text subtitle-bot";
                subtitleText.innerText = groupText;
            }, elapsed);

            elapsed += groupDuration;
        });
    }


    // ===========================================================================
    // TTS — Control (stop, etc.)
    // ===========================================================================

    /**
     * Detiene todo el pipeline TTS.
     */
    function stopTTS() {
        ttsAborted = true;
        ttsChunkQueue = [];
        ttsIsPlaying = false;
        ttsSentenceBuffer = "";
        ttsChunkIndex = 0;
        ttsOnEndCallback = null;

        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            currentAudio = null;
        }
        if (currentAudioUrl) {
            URL.revokeObjectURL(currentAudioUrl);
            currentAudioUrl = null;
        }
        botIsSpeaking = false;
        // Limpiar subtítulos sincronizados
        if (window._subtitleTimer) {
            clearInterval(window._subtitleTimer);
            window._subtitleTimer = null;
        }
        subtitleText.innerText = "";
    }

    /**
     * Muestra subtítulos sincronizados con la duración real del audio TTS.
     * Divide el texto en lotes y los muestra proporcionalmente a la duración.
     */
    function showSyncedSubtitles(texto, audioDurationSec) {
        // Limpiar timer anterior
        if (window._subtitleTimer) clearInterval(window._subtitleTimer);

        const words = texto.split(/\s+/).filter(w => w.length > 0);
        if (words.length === 0) return;

        const batchSize = SUBTITLE_BATCH_SIZE; // 7 palabras
        const batches = [];
        for (let i = 0; i < words.length; i += batchSize) {
            batches.push(words.slice(i, i + batchSize).join(' '));
        }

        const intervalMs = (audioDurationSec * 1000) / batches.length;
        let batchIndex = 0;

        // Activar animación de habla
        if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 1);
        subtitleText.className = "subtitle-text subtitle-bot";

        // Mostrar primer lote inmediatamente
        subtitleText.innerText = batches[0];
        batchIndex = 1;

        window._subtitleTimer = setInterval(() => {
            if (batchIndex >= batches.length) {
                clearInterval(window._subtitleTimer);
                window._subtitleTimer = null;
                return;
            }
            subtitleText.innerText = batches[batchIndex];
            batchIndex++;
        }, intervalMs);
    }
}