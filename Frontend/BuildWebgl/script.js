const API_URL = 'http://192.168.18.6:8000'; // Tu IP local

// Elementos DOM
const chatWidget = document.getElementById('chat-widget');
const toggleBtn = document.getElementById('chatbot-toggle-btn');
const chatForm = document.getElementById('chatForm');
const userInput = document.getElementById('userInput');
const chatContainer = document.getElementById('chatContainer');
const sendBtn = document.getElementById('sendBtn');
const connectionStatus = document.getElementById('connectionStatus');
const statusDot = document.querySelector('.status-dot');
const streamToggle = document.getElementById('streamToggle');

let isProcessing = false;

// --- INICIALIZACIÓN ---
document.addEventListener('DOMContentLoaded', () => {
    checkConnection();
    
    if (userInput) {
        // Auto-resize del textarea
        userInput.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            if (sendBtn) sendBtn.disabled = this.value.trim() === '';
        });

        // Enviar con Enter
        userInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (sendBtn && !sendBtn.disabled) handleSubmit();
            }
        });
    }

    if (chatForm) {
        chatForm.addEventListener('submit', (e) => {
            e.preventDefault();
            handleSubmit();
        });
    }
});

// --- COMUNICACIÓN CON UNITY ---
function setUnityTalk(isTalking) {
    if (window.unityInstance) {
        try {
            window.unityInstance.SendMessage('Tutor', 'SetTalkingState', isTalking ? 1 : 0);
        } catch (e) {
            console.warn("Unity no está listo aún:", e);
        }
    }
}

// --- LÓGICA DEL CHAT ---
window.toggleChat = function() {
    if (!chatWidget || !toggleBtn) return;
    
    if (chatWidget.style.display === 'none' || chatWidget.style.display === '') {
        chatWidget.style.display = 'flex';
        toggleBtn.style.display = 'none';
        if(userInput) userInput.focus();
    } else {
        chatWidget.style.display = 'none';
        toggleBtn.style.display = 'flex';
    }
}

async function checkConnection() {
    try {
        const response = await fetch(`${API_URL}/`);
        updateStatus(response.ok);
    } catch (error) {
        updateStatus(false);
    }
}

function updateStatus(isOnline) {
    if (statusDot) statusDot.className = isOnline ? 'status-dot online' : 'status-dot offline';
    if (connectionStatus) {
        connectionStatus.textContent = isOnline ? 'Conectado' : 'Desconectado';
        connectionStatus.className = isOnline ? 'text-success' : 'text-danger';
    }
}

async function handleSubmit() {
    const text = userInput.value.trim();
    if (!text || isProcessing) return;

    // UI Reset
    userInput.value = '';
    userInput.style.height = 'auto';
    sendBtn.disabled = true;
    isProcessing = true;

    // Mostrar mensaje usuario
    addMessage(text, 'user');
    const typingId = showTyping();

    try {
        const isStream = streamToggle && streamToggle.checked;
        const endpoint = isStream ? '/ask/stream' : '/ask';

        const response = await fetch(`${API_URL}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ texto: text, usuario_id: 2 })
        });

        if (!response.ok) throw new Error(`Error ${response.status}`);

        removeTyping(typingId);

        // >>> ACTIVAR ANIMACIÓN UNITY <<<
        setUnityTalk(true);

        if (isStream) {
            await handleStream(response);
            // El stream termina dentro de handleStream
        } else {
            const data = await response.json();
            let botText = data.respuesta || data.mensaje || JSON.stringify(data);
            addMessage(botText, 'bot');
            
            // >>> DESACTIVAR ANIMACIÓN UNITY (Modo normal) <<<
            setUnityTalk(false);
        }

    } catch (error) {
        removeTyping(typingId);
        addMessage(`Error: ${error.message}`, 'bot');
        
        // >>> DESACTIVAR ANIMACIÓN UNITY (Error) <<<
        setUnityTalk(false);
    } finally {
        isProcessing = false;
        if(userInput) userInput.focus();
    }
}

async function handleStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const contentDiv = createMessageContainer('bot');
    let accumulatedText = "";

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                // >>> DESACTIVAR ANIMACIÓN UNITY (Fin Stream) <<<
                setUnityTalk(false);
                break;
            }
            const chunk = decoder.decode(value, { stream: true });
            accumulatedText += chunk;
            
            // Usamos marked si está disponible, sino texto plano
            if (typeof marked !== 'undefined') {
                contentDiv.innerHTML = marked.parse(accumulatedText);
            } else {
                contentDiv.innerText = accumulatedText;
            }
            
            scrollToBottom();
        }
    } catch (error) {
        contentDiv.innerHTML += `<br><small class="text-danger">Error en stream</small>`;
        setUnityTalk(false);
    }
}

// --- UTILIDADES UI ---
function addMessage(text, role) {
    const contentDiv = createMessageContainer(role);
    if (typeof marked !== 'undefined') {
        contentDiv.innerHTML = marked.parse(text);
    } else {
        contentDiv.innerText = text;
    }
    scrollToBottom();
}

function createMessageContainer(role) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    
    const avatarDiv = document.createElement('div');
    avatarDiv.className = `avatar ${role === 'user' ? 'user-avatar' : 'bot-avatar'} shadow-sm`;
    avatarDiv.innerHTML = role === 'user' ? '<i class="bi bi-person-fill"></i>' : '<i class="bi bi-robot"></i>';

    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'message-content shadow-sm';

    msgDiv.appendChild(avatarDiv);
    msgDiv.appendChild(contentWrapper);
    
    if(chatContainer) chatContainer.appendChild(msgDiv);
    return contentWrapper;
}

function showTyping() {
    const id = `typing-${Date.now()}`;
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot';
    msgDiv.id = id;
    msgDiv.innerHTML = `
        <div class="avatar bot-avatar shadow-sm"><i class="bi bi-robot"></i></div>
        <div class="message-content shadow-sm">
            <div class="typing-indicator">...</div>
        </div>`;
    
    if(chatContainer) {
        chatContainer.appendChild(msgDiv);
        scrollToBottom();
    }
    return id;
}

function removeTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function scrollToBottom() {
    if(chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
}