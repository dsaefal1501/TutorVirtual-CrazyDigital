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
            const dot = document.getElementById('statusDot');
            if (dot) dot.classList.add('online');
            const status = document.getElementById('connectionStatus');
            if (status) status.innerText = "En línea";
        }).catch((message) => { alert(message); });
    };
    script.onerror = () => { document.getElementById('loading-overlay').style.display = 'none'; }
    document.body.appendChild(script);
}

// Iniciar Unity al cargar la página
// Iniciar Unity al cargar la página
document.addEventListener("DOMContentLoaded", () => {
    loadUnity();
    loadChatHistory();
    initUserProfile();
    initEventListeners(); // Configurar eventos
});


// --- LÓGICA DE LA APLICACIÓN (CHAT & RECONOCIMIENTO) ---

const API_URL = 'http://127.0.0.1:8000'; // Ajustar IP/Puerto según entorno

// Obtener token JWT del almacenamiento local
const authToken = localStorage.getItem('authToken');

// Si no hay token, redirigir al login (protección básica de frontend)
if (!authToken && window.location.pathname.endsWith('tutor.html')) {
    window.location.href = 'login.html';
}

// Configurar headers globales
const authHeaders = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${authToken}`
};

// Cargar historial al iniciar
// Cargar historial al iniciar
async function loadChatHistory() {
    try {
        const userId = getUserId();
        if (!userId) {
            console.warn("No authentication token found or invalid.");
            return;
        }

        const response = await fetch(`${API_URL}/chat/history?user_id=${userId}`, { // Force user_id param if needed or rely on backend token parsing
            method: 'GET',
            headers: authHeaders
        });

        if (response.status === 401) {
            console.warn("Sesión expirada o inválida. Redirigiendo al login.");
            localStorage.removeItem('authToken');

            window.location.href = 'login.html';
            return;
        }

        if (response.ok) {
            const history = await response.json();
            history.forEach(msg => {
                // Mapear rol 'assistant' a 'bot' para el frontend
                const role = msg.role === 'assistant' ? 'bot' : 'user';
                addMessage(msg.content, role, false); // false = no scroll animation if possible
            });
            // Scroll al final tras cargar todo
            scrollToBottom();
        }
    } catch (e) {
        console.error("Error cargando historial:", e);
    }
}

// Cargar perfil de usuario desde sessionStorage
function initUserProfile() {
    const alias = sessionStorage.getItem('userAlias') || 'Usuario';
    const role = sessionStorage.getItem('userRole') || 'Alumno';
    const initial = alias.charAt(0).toUpperCase();

    const nameEl = document.getElementById('profileName');
    const roleEl = document.getElementById('profileRole');
    const avatarBtn = document.getElementById('userAvatarBtn');
    const avatarSm = document.getElementById('profileAvatarSm');

    if (nameEl) nameEl.innerText = alias;
    if (roleEl) roleEl.innerText = role;
    if (avatarBtn) avatarBtn.innerText = initial;
    if (avatarSm) avatarSm.innerText = initial;
}

function logoutUser() {
    localStorage.removeItem('authToken');
    sessionStorage.clear();
    window.location.href = 'login.html';
}

const role = sessionStorage.getItem('userRole') || 'Alumno';
// document.getElementById('profileRole').textContent = role; // Ya se hace en initUserProfile

function toggleUserMenu() {
    const dropdown = document.getElementById('userProfileDropdown');
    if (dropdown) dropdown.classList.toggle('open');
}

// Cerrar menú al hacer click fuera
document.addEventListener('click', (e) => {
    const wrapper = document.getElementById('userProfileWrapper');
    const dropdown = document.getElementById('userProfileDropdown');
    if (wrapper && !wrapper.contains(e.target) && dropdown && dropdown.classList.contains('open')) {
        dropdown.classList.remove('open');
    }
});


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
let ttsSpeed = 1.2;            // Velocidad aumentada (antes 1.0)
let ttsPitch = "+0Hz";         // Tono base (se puede ajustar ej: +5Hz)

// --- TTS Chunked Pipeline v2 ---
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
console.log("SpeechRecognition supported:", !!SpeechRecognition);
if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    console.log("Recognition instance created:", recognition);
    recognition.lang = 'es-ES';
    recognition.continuous = false;
    recognition.interimResults = true;

    recognition.onstart = () => {
        console.log("Recognition started");
        updateMicVisuals(true, "Escuchando...");
        clearBotSubtitles();
    };

    recognition.onerror = (event) => {
        console.error("Recognition error:", event.error);
        updateMicVisuals(false, "Error");

        if (event.error === 'not-allowed') {
            alert("Acceso al micrófono denegado. Por favor, asegúrate de permitir el uso del micrófono en la barra de direcciones de tu navegador y que estás usando 'localhost' o un servidor HTTPS.");
        }
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

function initEventListeners() {
    if (micBtn) micBtn.addEventListener('click', handleMicClick);
    if (toggleBtn) toggleBtn.addEventListener('click', toggleChat);
    if (closeChatBtn) closeChatBtn.addEventListener('click', toggleChat);

    if (chatForm) {
        chatForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (userInput.value.trim()) handleSendMessage(userInput.value.trim());
        });
    }

    if (userInput) {
        userInput.addEventListener('input', autoResizeInput);
        userInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (userInput.value.trim()) handleSendMessage(userInput.value.trim());
            }
        });
    }

    // TTS Control
    if (ttsToggle) {
        ttsToggle.addEventListener('change', () => {
            ttsEnabled = ttsToggle.checked;
            const speedControl = document.getElementById('ttsSpeedControl');
            if (speedControl) speedControl.style.opacity = ttsEnabled ? '1' : '0.4';
            if (!ttsEnabled) stopTTS();
        });
    }

    // TTS Speed Slider removed
    // if (ttsSpeedSlider) {
    //     ttsSpeedSlider.addEventListener('input', () => {
    //         ttsSpeed = parseFloat(ttsSpeedSlider.value);
    //         if (ttsSpeedLabel) ttsSpeedLabel.textContent = ttsSpeed.toFixed(1) + 'x';
    //     });
    // }
}


// --- FUNCIONES LÓGICAS ---

function handleMicClick() {
    console.log("Mic clicked. isChatOpen:", isChatOpen, "isConversationMode:", isConversationMode, "recognition:", !!recognition);
    if (!recognition) {
        alert("Tu navegador no soporta reconocimiento de voz o no se pudo inicializar.");
        return;
    }

    // Feedback visual inmediato
    micBtn.classList.add('active-press');
    setTimeout(() => micBtn.classList.remove('active-press'), 200);

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
    updateMicVisuals(false, "Pausado");
}

function updateMicVisuals(listening, text) {
    console.log(`[Mic Visuals] listening=${listening}, text="${text}"`);
    if (!micLabel || !micBtn || !micIcon) return;
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

            // Configurar callback para cuando el audio termine
            ttsOnEndCallback = () => {
                subtitleText.innerText = "";
                botIsSpeaking = false;
                if (window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);
                updateMicVisuals(false, "Escuchando...");
            };

            // Si no hay chunks pendientes ni reproduciéndose, limpiar inmediatamente
            if (ttsChunkQueue.length === 0 && !ttsIsPlaying) {
                const cb = ttsOnEndCallback;
                ttsOnEndCallback = null;
                if (cb) cb();
            }
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
    // Si no existe el toggle en el DOM, streaming activado por defecto
    const isStream = streamToggle ? streamToggle.checked : true;
    const endpoint = isStream ? '/ask/stream' : '/ask'; // Keep this line from original for endpoint determination

    try {
        const userId = getUserId();
        if (!userId) {
            alert("Error de sesión: No se pudo identificar al usuario. Por favor, inicia sesión de nuevo.");
            window.location.href = 'login.html';
            return;
        }

        const payload = {
            usuario_id: userId,
            texto: text,
            sesion_id: null // El backend gestiona esto ahora
        };

        const response = await fetch(`${API_URL}/ask/stream`, { // O /ask normal
            method: 'POST',
            headers: authHeaders,
            body: JSON.stringify(payload)
        });

        if (response.status === 401) {
            console.warn("Sesión expirada (401) en chat. Redirigiendo.");
            localStorage.removeItem('authToken');

            window.location.href = 'login.html';
            return;
        }

        if (!response.ok) throw new Error("Error en la respuesta del servidor");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });

            if (chunk) {
                // Call the callback for UI updates
                onChunkReceived(chunk);

                // Feed TTS buffer if enabled
                if (ttsEnabled && typeof feedTTSSentenceBuffer === 'function') {
                    feedTTSSentenceBuffer(chunk);
                }
            }
        }
    } catch (e) {
        console.error("Error envío:", e);
        // Propagate error or handle it via callback if possible, 
        // but here we might just let the caller handle UI reset
        throw e;
    }
}

// --- FUNCIONES DE INTERFAZ AUXILIARES ---

function updateUserSubtitle(text) {
    if (!text) return;
    subtitleText.className = "subtitle-text subtitle-user";
    const words = text.trim().split(/\s+/);
    const lastWords = words.length > 10 ? words.slice(-10) : words;
    const textToDisplay = lastWords.join(" ");
    subtitleText.innerHTML = typeof marked !== 'undefined' ? marked.parseInline(textToDisplay) : textToDisplay;
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
    subtitleText.innerHTML = typeof marked !== 'undefined' ? marked.parseInline(textToShow) : textToShow;

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
    // Limpiar etiquetas de emoción [Tag] para la visualización
    //const cleanText = (role === 'bot') ? text.replace(/\[.*?\]\s*/g, '') : text;
    const cleanText = text;

    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `<div class="message-content"></div>`;
    const content = div.querySelector('.message-content');
    content.innerHTML = typeof marked !== 'undefined' ? marked.parse(cleanText) : cleanText;
    chatContainer.appendChild(div);
    scrollToBottom();
}

function showTyping() {
    const id = `msg-${Date.now()}`;
    const div = document.createElement('div');
    div.className = 'message bot';
    div.id = id;
    div.innerHTML = `<div class="message-content">...</div>`;
    chatContainer.appendChild(div);
    scrollToBottom();
    return id;
}

function updateBotMessage(id, cleanText) {
    const el = document.getElementById(id);
    if (!el) return;
    const content = el.querySelector('.message-content');
    // Limpiar etiquetas de emoción durante el streaming
    const textToDisplay = cleanText; // quiero desactivar el ocultado de etiquetas

    content.innerHTML = typeof marked !== 'undefined' ? marked.parse(textToDisplay) : textToDisplay;
    scrollToBottom();
}

function removeTyping(id) { document.getElementById(id)?.remove(); }
function scrollToBottom() { setTimeout(() => { chatContainer.scrollTop = chatContainer.scrollHeight; }, 50); }
function autoResizeInput() { userInput.style.height = 'auto'; userInput.style.height = userInput.scrollHeight + 'px'; }


// ===========================================================================
// TTS CHUNKED PIPELINE v2 — Audio ultra-rápido con pre-fetching paralelo
// ===========================================================================
// Mientras reproduce un chunk, ya está generando los siguientes en paralelo.
// Primer chunk se envía con solo 1 oración completa para mínima latencia.

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
 * Extrae las etiquetas de emoción del texto crudo y sus posiciones (en número de palabra).
 * Retorna un array de { tag: '[Happy]', wordIndex: N } indicando en qué palabra
 * del texto limpio debe activarse cada emoción.
 */
function extractEmotionSchedule(rawText) {
    const parts = rawText.split(/(\[.*?\])/g);
    const schedule = [];
    let wordCount = 0;

    for (const part of parts) {
        if (/^\[.*\]$/.test(part)) {
            schedule.push({ tag: part, wordIndex: wordCount });
        } else {
            const cleaned = part
                .replace(/[#*_~`>]/g, '')
                .replace(/\n/g, ' ')
                .trim();
            if (cleaned) {
                const words = cleaned.split(/\s+/).filter(w => w.length > 0);
                wordCount += words.length;
            }
        }
    }

    return schedule;
}

/**
 * Divide texto en oraciones usando delimitadores naturales.
 */
function splitIntoSentences(text) {
    const raw = text.match(/[^.!?;:]+[.!?;:]*/g) || [text];

    const sentences = [];
    for (let s of raw) {
        s = s.trim();
        if (!s) continue;

        const words = s.split(/\s+/);
        if (words.length > 40) {
            const subParts = s.match(/[^,]+,?/g) || [s];
            let accumulated = "";
            for (const sub of subParts) {
                accumulated += sub;
                const accWords = accumulated.trim().split(/\s+/);
                if (accWords.length >= 20) {
                    sentences.push(accumulated.trim());
                    accumulated = "";
                }
            }
            if (accumulated.trim()) {
                sentences.push(accumulated.trim());
            }
        } else if (words.length >= 5) {
            sentences.push(s);
        } else {
            if (sentences.length > 0) {
                sentences[sentences.length - 1] += " " + s;
            } else {
                sentences.push(s);
            }
        }
    }

    const merged = [];
    for (const s of sentences) {
        if (merged.length > 0) {
            const lastWords = merged[merged.length - 1].split(/\s+/).length;
            const curWords = s.split(/\s+/).length;
            if (lastWords < 8 && curWords < 8) {
                merged[merged.length - 1] += " " + s;
                continue;
            }
        }
        merged.push(s);
    }

    return merged.filter(s => s.trim().length > 0);
}


// ── Configuración del pipeline chunked v2 ──
const TTS_FIRST_CHUNK_SENTENCES = 1;    // Primer chunk: solo 1 oración (latencia mínima)
const TTS_NORMAL_CHUNK_SENTENCES = 3;   // Chunks siguientes: 3 oraciones (MEJOR FLUIDEZ)
const TTS_FIRST_CHUNK_MIN_WORDS = 1;    // Mínimo de palabras: 1 (ej: "Sí." se dice ya)
const TTS_MAX_PREFETCH = 2;             // Reducimos prefetch para no saturar red
let ttsAbortController = null;          // Para cancelar fetches en vuelo

/**
 * Alimenta el buffer de texto conforme llega del streaming.
 * ESTRATEGIA OPTIMIZADA: Para el primer chunk, cortamos incluso en comas
 * o pausas breves para que el audio arranque INMEDIATAMENTE.
 */
function feedTTSSentenceBuffer(chunk) {
    ttsSentenceBuffer += chunk;

    // Detectar terminadores: . ! ? y también , : ; para el primer chunk
    const isFirstChunk = (ttsChunkIndex === 0);
    const sentenceEnders = isFirstChunk ? /[.!?](?:\s|$)|[,:;]\s/g : /[.!?](?:\s|$)/g;

    let lastSentenceEnd = 0;
    let sentenceCount = 0;
    let match;

    while ((match = sentenceEnders.exec(ttsSentenceBuffer)) !== null) {
        lastSentenceEnd = match.index + match[0].length;
        sentenceCount++;
    }

    if (lastSentenceEnd === 0 || sentenceCount === 0) return;

    // Decidir cuántas oraciones necesitamos para disparar un chunk
    // Si es el primero, con 1 fragmento (aunque sea una coma) nos vale.
    const requiredSentences = isFirstChunk ? 1 : TTS_NORMAL_CHUNK_SENTENCES;

    if (sentenceCount >= requiredSentences) {
        const readyPart = ttsSentenceBuffer.substring(0, lastSentenceEnd);
        const wordCount = readyPart.trim().split(/\s+/).length;

        // Para el primer chunk, verificar mínimo de palabras (ahora es 1)
        if (isFirstChunk && wordCount < TTS_FIRST_CHUNK_MIN_WORDS) return;

        const rawText = readyPart.trim();
        ttsSentenceBuffer = ttsSentenceBuffer.substring(lastSentenceEnd);

        // Extraer emociones y limpiar
        const emotionTags = extractEmotionSchedule(rawText);
        const cleaned = cleanTextForTTS(rawText);
        if (cleaned.length > 1) { // Min len reduced
            console.log(`[TTS v2] Chunk ${ttsChunkIndex} listo (${sentenceCount} orac, ${wordCount} pal, 1er=${isFirstChunk})`);
            enqueueTTSChunk(cleaned, emotionTags);
        }
    }
}

/**
 * Envía lo que quede en el buffer como último chunk TTS.
 */
function flushTTSSentenceBuffer() {
    if (ttsSentenceBuffer.trim()) {
        const rawText = ttsSentenceBuffer.trim();
        const emotionTags = extractEmotionSchedule(rawText);
        const cleaned = cleanTextForTTS(rawText);
        if (cleaned.length > 2) {
            console.log(`[TTS v2] Flush final (${cleaned.length} chars)`);
            enqueueTTSChunk(cleaned, emotionTags);
        }
        ttsSentenceBuffer = "";
    }
}

/**
 * Encola un chunk de texto para TTS.
 * Lanza la petición de generación de audio INMEDIATAMENTE (en paralelo).
 * Pre-fetching: hasta TTS_MAX_PREFETCH requests en vuelo simultáneamente.
 */
function enqueueTTSChunk(text, emotionTags = []) {
    if (ttsAborted) return;

    const chunkId = ttsChunkIndex++;
    const startTime = performance.now();
    console.log(`[TTS Chunk ${chunkId}] Encolando: "${text.substring(0, 60)}..."`);

    // Lanzar la petición TTS inmediatamente (en paralelo con la reproducción actual)
    const audioPromise = fetchTTSAudio(text);

    // Crear las palabras para subtítulos
    const subtitleWords = text.split(/\s+/).filter(w => w.length > 0);

    const chunk = {
        id: chunkId,
        text: text,
        audioPromise: audioPromise,
        subtitleWords: subtitleWords,
        emotionTags: emotionTags,
        resolved: false,
        audioBlob: null,
        fetchStartTime: startTime,
    };

    // Resolver la promesa y guardarlo
    audioPromise.then(blob => {
        chunk.audioBlob = blob;
        chunk.resolved = true;
        const elapsed = (performance.now() - startTime).toFixed(0);
        console.log(`[TTS Chunk ${chunkId}] Audio listo en ${elapsed}ms (${blob ? blob.size : 0} bytes)`);
    }).catch(err => {
        console.error(`[TTS Chunk ${chunkId}] Error:`, err);
        chunk.resolved = true;
        chunk.audioBlob = null;
    });

    ttsChunkQueue.push(chunk);

    // Si no hay reproducción activa, arrancar el pipeline
    if (!ttsIsPlaying) {
        playNextTTSChunk();
    }
}

/**
 * Hace la petición HTTP al backend para generar el audio de un texto.
 * Retorna un Blob con el audio MP3.
 * Usa AbortController para poder cancelar requests en vuelo.
 */
async function fetchTTSAudio(text) {
    if (!ttsAbortController) {
        ttsAbortController = new AbortController();
    }

    const formData = new FormData();
    formData.append('texto', text);
    formData.append('voz', 'alvaro');
    formData.append('speed', ttsSpeed.toString());
    formData.append('pitch', ttsPitch); // Enviar pitch

    try {
        const response = await fetch(`${API_URL}/tts`, {
            method: 'POST',
            body: formData,
            signal: ttsAbortController.signal,
        });

        if (!response.ok) {
            const errText = await response.text();
            console.error('[TTS fetch error]', response.status, errText);
            return null;
        }

        return await response.blob();
    } catch (err) {
        if (err.name === 'AbortError') {
            console.log('[TTS] Fetch abortado');
            return null;
        }
        throw err;
    }
}

/**
 * Reproduce el siguiente chunk en la cola.
 * PIPELINE v2: Mientras reproduce, el audio del siguiente chunk ya se está
 * generando en paralelo. Usa pre-decode del blob para eliminar el gap.
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
        const waitStart = performance.now();
        console.log(`[TTS Chunk ${chunk.id}] Esperando audio...`);
        try {
            await chunk.audioPromise;
        } catch (e) {
            // Error ya manejado
        }
        const waitTime = (performance.now() - waitStart).toFixed(0);
        console.log(`[TTS Chunk ${chunk.id}] Esperó ${waitTime}ms por el audio`);
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

    playTTSChunk(chunk);
} // Cierre de playNextTTSChunk

function playTTSChunk(chunk) {
    // Crear y reproducir el audio
    const audioUrl = URL.createObjectURL(chunk.audioBlob);
    const audio = new Audio(audioUrl);
    currentAudio = audio;
    currentAudioUrl = audioUrl;

    // Pre-cargar el audio para start más rápido
    audio.preload = 'auto';

    return new Promise((resolve) => {
        audio.addEventListener('loadedmetadata', () => {
            const duration = audio.duration;
            console.log(`[TTS Chunk ${chunk.id}] ▶ Reproduciendo (${duration.toFixed(2)}s, ${chunk.subtitleWords.length} pal)`);

            // Mostrar subtítulos y emociones sincronizados
            showSyncedSubtitles(chunk.subtitleWords, duration, chunk.emotionTags);
        });

        audio.addEventListener('ended', () => {
            URL.revokeObjectURL(audioUrl);
            currentAudio = null;
            currentAudioUrl = null;
            resolve();

            // Siguiente chunk — el audio ya debería estar pre-generado
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
 * Programa etiquetas de emoción para Unity en el momento correcto.
 */
function showSyncedSubtitles(words, audioDurationSec, emotionTags = []) {
    if (!words || words.length === 0) return;

    const totalWords = words.length;
    const totalDurationMs = audioDurationSec * 1000;
    const timePerWord = totalDurationMs / totalWords;

    // --- Programar etiquetas de emoción ---
    if (emotionTags && emotionTags.length > 0) {
        emotionTags.forEach(({ tag, wordIndex }) => {
            const triggerAt = wordIndex * timePerWord;
            setTimeout(() => {
                if (ttsAborted) return;
                console.log(`[Emotion] ${tag} @ palabra ${wordIndex} (${(triggerAt / 1000).toFixed(1)}s)`);
                if (window.unityInstance) {
                    window.unityInstance.SendMessage('Tutor', 'SetExpression', tag);
                }
            }, triggerAt);
        });

        if (emotionTags[0].wordIndex === 0 && window.unityInstance) {
            window.unityInstance.SendMessage('Tutor', 'SetExpression', emotionTags[0].tag);
        }
    }

    // --- Programar subtítulos ---
    const groups = [];
    for (let i = 0; i < totalWords; i += SUBTITLE_MAX_WORDS) {
        groups.push(words.slice(i, i + SUBTITLE_MAX_WORDS).join(" "));
    }

    let elapsed = 0;
    groups.forEach((groupText, idx) => {
        const wordsInGroup = groupText.split(/\s+/).length;
        const groupDuration = wordsInGroup * timePerWord;

        setTimeout(() => {
            if (ttsAborted) return;
            subtitleText.className = "subtitle-text subtitle-bot";
            subtitleText.innerHTML = typeof marked !== 'undefined' ? marked.parseInline(groupText) : groupText;
        }, elapsed);

        elapsed += groupDuration;
    });
}


// ===========================================================================
// TTS — Control (stop, etc.)
// ===========================================================================

/**
 * Detiene todo el pipeline TTS.
 * Cancela fetches en vuelo con AbortController.
 */
function stopTTS() {
    ttsAborted = true;
    ttsChunkQueue = [];
    ttsIsPlaying = false;
    ttsSentenceBuffer = "";
    ttsChunkIndex = 0;
    ttsOnEndCallback = null;

    // Cancelar fetches en vuelo
    if (ttsAbortController) {
        ttsAbortController.abort();
        ttsAbortController = null;
    }

    if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        currentAudio = null;
    }
    window.speechSynthesis.cancel();

    if (currentAudioUrl) {
        URL.revokeObjectURL(currentAudioUrl);
        currentAudioUrl = null;
    }
    botIsSpeaking = false;

    // Resetear el flag de abort para la próxima vez
    setTimeout(() => { ttsAborted = false; }, 50);
}

// --- UTILIDADES ---
function getUserId() {
    // 1. Intentar desde sessionStorage
    let uid = sessionStorage.getItem('userId');
    if (uid) return parseInt(uid, 10);

    // 2. Intentar recuperar del Token JWT
    const token = localStorage.getItem('authToken');
    if (token) {
        try {
            const base64Url = token.split('.')[1];
            const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
            const jsonPayload = decodeURIComponent(window.atob(base64).split('').map(function (c) {
                return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
            }).join(''));
            const payload = JSON.parse(jsonPayload);

            if (payload.sub) {
                console.log("UserID recuperado del token:", payload.sub);
                sessionStorage.setItem('userId', payload.sub);
                return parseInt(payload.sub, 10);
            }
        } catch (e) {
            console.error("Error parseando token:", e);
        }
    }
    return null;
}