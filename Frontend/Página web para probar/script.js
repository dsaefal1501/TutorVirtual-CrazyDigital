const API_URL = 'http://localhost:8000';

// DOM Elements
const chatForm = document.getElementById('chatForm');
const userInput = document.getElementById('userInput');
const chatContainer = document.getElementById('chatContainer');
const sendBtn = document.getElementById('sendBtn');
const connectionStatus = document.getElementById('connectionStatus');
const statusDot = document.querySelector('.status-dot');
const streamToggle = document.getElementById('streamToggle');
const toastEl = document.getElementById('liveToast');
const toastMessage = document.getElementById('toastMessage');
const toast = new bootstrap.Toast(toastEl);

// State
let isProcessing = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    checkConnection();
    userInput.focus();

    // Auto-resize textarea
    userInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value.trim() === '') {
            sendBtn.disabled = true;
        } else {
            sendBtn.disabled = false;
        }
    });

    // Enter to send (Shift+Enter for newline)
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled) {
                handleSubmit();
            }
        }
    });

    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        handleSubmit();
    });

    // Upload Form Handler
    document.getElementById('uploadForm').addEventListener('submit', handleUpload);
});

async function checkConnection() {
    try {
        const response = await fetch(`${API_URL}/`);
        if (response.ok) {
            updateStatus(true);
        } else {
            updateStatus(false);
        }
    } catch (error) {
        updateStatus(false);
        console.error('Connection failed:', error);
    }
}

function updateStatus(isOnline) {
    if (isOnline) {
        statusDot.className = 'status-dot online';
        connectionStatus.textContent = 'Conectado';
        connectionStatus.classList.remove('text-danger');
        connectionStatus.classList.add('text-success');
    } else {
        statusDot.className = 'status-dot offline';
        connectionStatus.textContent = 'Desconectado';
        connectionStatus.classList.add('text-danger');
        connectionStatus.classList.remove('text-success');
    }
}

async function handleSubmit() {
    const text = userInput.value.trim();
    if (!text || isProcessing) return;

    // Reset input
    userInput.value = '';
    userInput.style.height = 'auto';
    sendBtn.disabled = true;
    isProcessing = true;

    // Add User Message
    addMessage(text, 'user');

    // Show typing indicator
    const typingId = showTyping();

    try {
        const isStream = streamToggle.checked;
        const endpoint = isStream ? '/ask/stream' : '/ask';

        const response = await fetch(`${API_URL}${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                texto: text,
                usuario_id: 1  // ID temporal para pruebas
            })
        });

        if (!response.ok) {
            // Intentar obtener detalles del error (especialmente util para 422 Unprocessable Entity)
            let errorMsg = `Error ${response.status}`;
            try {
                const errorData = await response.json();
                if (errorData.detail) {
                    // FastAPI devuelve los errores de validación en 'detail'
                    if (Array.isArray(errorData.detail)) {
                        // Formatear errores de Pydantic amigablemente
                        const problems = errorData.detail.map(e => `${e.loc.join('.')} -> ${e.msg}`).join(', ');
                        errorMsg += `: Faltan datos o son incorrectos (${problems})`;
                    } else {
                        errorMsg += `: ${errorData.detail}`;
                    }
                } else {
                    errorMsg += `: ${response.statusText}`;
                }
            } catch (e) {
                errorMsg += `: ${response.statusText}`;
            }
            throw new Error(errorMsg);
        }

        // Remove typing indicator just before showing response
        removeTyping(typingId);

        if (isStream) {
            // Handle Streaming Response
            await handleStream(response);
        } else {
            // Handle Normal Response
            const data = await response.json();
            // Assuming the schema returns a field (maybe 'respuesta' or just the object)
            // Based on code: response_model=RespuestaTutor. Let's assume it has a field 'respuesta' or 'text'.
            // Actually, usually it returns the whole object. Let's check the code:
            // "return respuesta". We don't know the schema of RespuestaTutor.
            // Safe bet: JSON.stringify(data) if unsure, but likely it has a content field.
            // Common pattern is { "message": "..." } or { "response": "..." }.
            // The python code returns whatever `rag_service.preguntar_al_tutor` returns.
            // I'll assume it returns an object with a text field, or I'll just dump the whole thing if it's text.
            // Let's try to be smart: Use a field 'respuesta' or 'content' or 'detail', fallback to string.

            let botText = "Respuesta recibida";
            if (typeof data === 'string') botText = data;
            else if (data.respuesta) botText = data.respuesta;
            else if (data.mensaje) botText = data.mensaje;
            else if (data.content) botText = data.content;
            else botText = JSON.stringify(data, null, 2);

            addMessage(botText, 'bot');
        }

    } catch (error) {
        removeTyping(typingId);
        addMessage(`Error: ${error.message}`, 'bot'); // Show error as bot message for visibility
        console.error(error);
    } finally {
        isProcessing = false;
        userInput.focus();
    }
}

async function handleStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    // Create an empty bot message container
    const messageId = `msg-${Date.now()}`;
    const contentDiv = createMessageContainer('bot', messageId);

    let accumulatedText = "";
    let isFirstChunk = true;

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            accumulatedText += chunk;

            // Render Markdown
            contentDiv.innerHTML = marked.parse(accumulatedText);

            // Auto scroll
            scrollToBottom();
        }
    } catch (error) {
        contentDiv.innerHTML += `<br><small class="text-danger">[Error en stream: ${error.message}]</small>`;
    }
}

function addMessage(text, role) {
    const contentDiv = createMessageContainer(role);
    contentDiv.innerHTML = marked.parse(text);
    scrollToBottom();
}

function createMessageContainer(role, id = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    if (id) msgDiv.id = id;

    // Avatar
    const avatarDiv = document.createElement('div');
    avatarDiv.className = `avatar ${role === 'user' ? 'user-avatar' : 'bot-avatar'} shadow-sm`;
    avatarDiv.innerHTML = role === 'user' ? '<i class="bi bi-person-fill"></i>' : '<i class="bi bi-robot"></i>';

    // Content
    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'message-content shadow-sm';

    // Order depends on role (handled by CSS flex-direction) but structure is same
    msgDiv.appendChild(avatarDiv);
    msgDiv.appendChild(contentWrapper);

    chatContainer.appendChild(msgDiv);
    return contentWrapper;
}

function showTyping() {
    const id = `typing-${Date.now()}`;
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot';
    msgDiv.id = id;

    const avatarDiv = document.createElement('div');
    avatarDiv.className = 'avatar bot-avatar shadow-sm';
    avatarDiv.innerHTML = '<i class="bi bi-robot"></i>';

    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'message-content shadow-sm';
    contentWrapper.innerHTML = `
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;

    msgDiv.appendChild(avatarDiv);
    msgDiv.appendChild(contentWrapper);
    chatContainer.appendChild(msgDiv);
    scrollToBottom();
    return id;
}

function removeTyping(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

async function syncKnowledge() {
    const btn = document.getElementById('syncBtn');
    const originalText = btn.innerHTML;

    try {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sincronizando...';

        const response = await fetch(`${API_URL}/knowledge/sync`, { method: 'POST' });

        if (!response.ok) throw new Error('Falló la sincronización');

        const data = await response.json();
        const msg = data.mensaje || 'Sincronización completada';
        const count = data.registros_nuevos !== undefined ? ` (${data.registros_nuevos} nuevos)` : '';

        showNotification(`${msg}${count}`);
    } catch (error) {
        showNotification(`Error: ${error.message}`, true);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

function showNotification(message, isError = false) {
    toastMessage.textContent = message;
    const toastEl = document.getElementById('liveToast');
    if (isError) {
        toastEl.classList.replace('bg-primary', 'bg-danger');
    } else {
        toastEl.classList.replace('bg-danger', 'bg-primary');
    }
    toast.show();
}


async function handleUpload(e) {
    e.preventDefault();

    const accountId = document.getElementById('accountIdInput').value.trim();
    const fileInput = document.getElementById('pdfFileInput');
    const file = fileInput.files[0];
    const uploadBtn = document.getElementById('uploadBtn');
    const originalBtnText = uploadBtn.innerHTML;

    if (!file) {
        showNotification('Por favor selecciona un archivo PDF', true);
        return;
    }

    if (!accountId) {
        showNotification('Por favor ingresa un Account ID', true);
        return;
    }

    try {
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Procesando...';

        const formData = new FormData();
        formData.append('file', file);
        // Nota: account_id se envía como query param según la definición del endpoint
        const response = await fetch(`${API_URL}/upload/syllabus?account_id=${encodeURIComponent(accountId)}`, {
            method: 'POST',
            body: formData
        });

        const responseText = await response.text();
        let data;
        try {
            data = JSON.parse(responseText);
        } catch (jsonError) {
            console.error("Respuesta no es JSON:", responseText);
            throw new Error(response.ok ? 'Respuesta inesperada del servidor' : `Error ${response.status}: ${response.statusText}`);
        }

        if (!response.ok) {
            let errorMsg = data.detail || data.message || `Error ${response.status}`;
            if (typeof errorMsg === 'object') errorMsg = JSON.stringify(errorMsg);
            throw new Error(errorMsg);
        }

        // Cerrar el modal de manera segura
        const modalEl = document.getElementById('uploadModal');
        let modal = bootstrap.Modal.getInstance(modalEl);
        if (!modal) {
            modal = new bootstrap.Modal(modalEl);
        }
        modal.hide();

        // Limpiar backdrop si queda pegado
        const backdrops = document.querySelectorAll('.modal-backdrop');
        backdrops.forEach(backdrop => backdrop.remove());
        document.body.classList.remove('modal-open');
        document.body.style = '';

        // Limpiar formulario logicamente
        e.target.reset();

        showNotification(data.message || 'Archivo procesado exitosamente');

        // Opcional: Agregar mensaje del bot confirmando recepción
        addMessage(`✅ **Archivo subido exitosamente**\n\n${data.message}`, 'bot');

    } catch (error) {
        showNotification(`Error: ${error.message}`, true);
        console.error('Upload error:', error);
        addMessage(`❌ **Error en la subida**\n\n${error.message}`, 'bot');
    } finally {
        if (uploadBtn) {
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = originalBtnText;
        }
    }
}
