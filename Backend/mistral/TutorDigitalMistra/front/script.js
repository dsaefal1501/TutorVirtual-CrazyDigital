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

// Estado
let isChatOpen = false;
let isConversationMode = false; 
let recognition = null;
let botIsSpeaking = false; 
let isProcessing = false;

// --- CONFIGURACIÓN DE SUBTÍTULOS Y EMOCIONES ---
let botWordQueue = []; // Ahora guardará objetos {type: 'tag'|'word', value: '...'}
let isShowingSubtitle = false;
let streamBuffer = ""; 
const TIME_PER_WORD_MS = 320; 
const MIN_TIME_ON_SCREEN_MS = 1500;
const SUBTITLE_BATCH_SIZE = 7; 
const TAG_REGEX = /(\[.*?\])/g; // Regex para capturar [Etiquetas]

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
                setTimeout(() => { if(!botIsSpeaking) subtitleText.innerText = ""; }, 2000);
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
            setTimeout(() => { if(!botIsSpeaking) subtitleText.innerText = ""; }, 500);
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
    if(userInput.value.trim()) handleSendMessage(userInput.value.trim());
});

userInput.addEventListener('keydown', (e) => {
    if(e.key === 'Enter' && !e.shiftKey) { 
        e.preventDefault(); 
        if(userInput.value.trim()) handleSendMessage(userInput.value.trim()); 
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
        if(isConversationMode) stopConversationMode();
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
    } catch(e) {
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
    try { recognition.stop(); } catch(e){}
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

    clearBotSubtitles();
    addMessage(text, 'user');
    const typingId = showTyping();
    
    let fullLogText = ""; 
    try {
        await processBackendResponse(text, (chunk) => {
            fullLogText += chunk;
            // Mostramos todo el texto en el chat (incluyendo etiquetas si quieres depurar, 
            // o podrías limpiarlas visualmente aquí también si prefieres).
            // De momento lo dejamos raw para que veas qué llega.
            updateBotMessage(typingId, fullLogText);
        });
    } catch (error) {
        removeTyping(typingId);
        addMessage("Error: " + error.message, 'bot');
    } finally {
        isProcessing = false;
        sendBtn.disabled = false;
        flushStreamBuffer();
        const checkFinishInterval = setInterval(() => {
            if (botWordQueue.length === 0 && !isShowingSubtitle) {
                clearInterval(checkFinishInterval);
            }
        }, 500);
    }
}

async function handleConversationTurn(text) {
    botIsSpeaking = true; 
    try { recognition.stop(); } catch(e){}
    updateMicVisuals(false, "Pensando...");

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

    const checkFinishInterval = setInterval(() => {
        if (botWordQueue.length === 0 && !isShowingSubtitle) {
            clearInterval(checkFinishInterval);
            subtitleText.innerText = ""; 

            if(window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);

            if (isConversationMode) {
                botIsSpeaking = false;
                try { recognition.start(); } catch(e) {}
            } else {
                botIsSpeaking = false;
                updateMicVisuals(false, "Escuchando...");
            }
        }
    }, 500);
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
            
            if (chunk) queueBotWords(chunk);
            onChunkReceived(chunk);
        }
    } else {
        const data = await response.json();
        const result = data.respuesta || data.mensaje || JSON.stringify(data);
        
        if (result.length > 0) queueBotWords(result);
        onChunkReceived(result);
    }
}

// --- FUNCIONES DE INTERFAZ AUXILIARES ---

function updateUserSubtitle(text) {
    if (!text) return;
    subtitleText.className = "subtitle-text subtitle-user";
    const words = text.trim().split(/\s+/);
    const lastWords = words.length > 7 ? words.slice(-7) : words;
    subtitleText.innerText = lastWords.join(" ");
}

// --- LÓGICA DE SUBTÍTULOS INTELIGENTE (Detecta [Tag] vs Texto) ---

function queueBotWords(chunkText) {
    if (!chunkText) return;
    
    streamBuffer += chunkText;
    
    // Buscamos un punto seguro para cortar (último cierre de corchete o espacio)
    // para no dejar una etiqueta o palabra a medias.
    const lastTagClose = streamBuffer.lastIndexOf("]");
    const lastSpace = streamBuffer.lastIndexOf(" ");
    const safeIndex = Math.max(lastTagClose, lastSpace);

    if (safeIndex !== -1) {
        const completePart = streamBuffer.substring(0, safeIndex + 1);
        streamBuffer = streamBuffer.substring(safeIndex + 1);
        
        // Magia: Separamos las etiquetas del texto usando Regex
        const parts = completePart.split(TAG_REGEX);

        parts.forEach(part => {
            if (TAG_REGEX.test(part)) {
                // Es una etiqueta: [Happy]
                botWordQueue.push({ type: 'tag', value: part });
            } else if (part.trim().length > 0) {
                // Es texto normal: separamos en palabras
                const words = part.split(/\s+/).filter(w => w.length > 0);
                words.forEach(w => botWordQueue.push({ type: 'word', value: w }));
            }
        });
    }

    if (!isShowingSubtitle && botWordQueue.length > 0) {
        processBotSubtitleQueue();
    }
}

function flushStreamBuffer() {
    // Procesamos lo que quede en el buffer final
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
    if (!isShowingSubtitle && botWordQueue.length > 0) {
        processBotSubtitleQueue();
    }
}

function processBotSubtitleQueue() {
    if (botWordQueue.length === 0) {
        isShowingSubtitle = false;
        subtitleText.innerText = "";
        
        // Paramos animación de habla
        if(window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);
        return;
    }

    isShowingSubtitle = true;
    
    const currentItem = botWordQueue[0];

    // --- CASO 1: ETIQUETA DE EMOCIÓN ---
    if (currentItem.type === 'tag') {
        botWordQueue.shift();
        
        if(window.unityInstance) {
             window.unityInstance.SendMessage('Tutor', 'SetExpression', currentItem.value);
        }

        processBotSubtitleQueue(); 
        return;
    }

    // --- CASO 2: PALABRA (Texto visible) ---
    
    // Animación de habla ON
    if(window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 1);

    // Cogemos un lote de palabras
    let batch = [];
    let i = 0;
    
    // Llenamos el batch, pero paramos si nos topamos con una etiqueta
    while(i < SUBTITLE_BATCH_SIZE && botWordQueue.length > 0 && botWordQueue[0].type === 'word') {
        batch.push(botWordQueue.shift().value);
        i++;
    }

    const textToShow = batch.join(" ");
    subtitleText.className = "subtitle-text subtitle-bot";
    subtitleText.innerText = textToShow;

    // Calculamos duración de lectura
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
    if(window.unityInstance) window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 0);
}

function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `<div class="avatar">${role==='bot'?'🤖':'👤'}</div><div class="message-content"></div>`;
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