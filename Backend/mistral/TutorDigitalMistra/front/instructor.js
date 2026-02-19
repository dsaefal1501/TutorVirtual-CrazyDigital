/* instructor.js */
const API_URL = 'http://127.0.0.1:8000';
let licenseStatus = { current: 0, max: 0 };
const LICENCIA_ID = sessionStorage.getItem('licenciaId') || 1;

// ---- DOM References ----
const uploadForm = document.getElementById('uploadForm');
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const dzEmpty = document.getElementById('dzEmpty');
const dzSelected = document.getElementById('dzSelected');
const fileNameEl = document.getElementById('fileName');
const fileSizeEl = document.getElementById('fileSize');
const clearFileBtn = document.getElementById('clearFileBtn');
const uploadBtn = document.getElementById('uploadBtn');
const processingStatusContainer = document.getElementById('processingStatusContainer');
const progressBar = document.getElementById('progressBar');

// ---- Initialization ----
document.addEventListener('DOMContentLoaded', () => {
    checkSyllabusStatus();

    // --- Set Profile (Instructor) ---
    const userName = sessionStorage.getItem('userAlias') || sessionStorage.getItem('userName') || 'Instructor';
    const avatarEl = document.getElementById('instructorAvatar');
    const nameEl = document.getElementById('instructorName');

    if (nameEl) nameEl.textContent = userName;
    if (avatarEl) {
        const initial = userName.charAt(0).toUpperCase();
        avatarEl.textContent = initial;

        // Random color based on char code
        const colors = ['#f56565', '#ed8936', '#ecc94b', '#48bb78', '#38b2ac', '#4299e1', '#667eea', '#9f7aea', '#ed64a6'];
        const index = initial.charCodeAt(0) % colors.length;
        avatarEl.style.backgroundColor = colors[index];
        avatarEl.style.color = '#fff';
    }

    // Restore active tab
    const savedTab = localStorage.getItem('instructorActiveTab');
    if (savedTab) {
        switchTab(savedTab);
    } else {
        // Default call to ensuring everything initializes correctly
        switchTab('temario');
    }

    // Delete Input Validation
    const deleteInput = document.getElementById('deleteConfirmInput');
    const deleteBtn = document.getElementById('btnConfirmDelete');
    if (deleteInput && deleteBtn) {
        deleteInput.addEventListener('input', () => {
            if (deleteInput.value.trim().toUpperCase() === 'CONFIRMAR') {
                deleteBtn.classList.add('enabled');
                deleteBtn.style.opacity = '1';
                deleteBtn.style.pointerEvents = 'all';
                deleteInput.classList.add('valid');
            } else {
                deleteBtn.classList.remove('enabled');
                deleteBtn.style.opacity = '0.5';
                deleteBtn.style.pointerEvents = 'none';
                deleteInput.classList.remove('valid');
            }
        });
    }
});

function logoutUser() {
    window.location.href = 'login.html';
}

// -------------------------------------------------------------------------
// 1. TABS & NAVIGATION
// -------------------------------------------------------------------------
function switchTab(tabName) {
    // Save state
    localStorage.setItem('instructorActiveTab', tabName);

    document.querySelectorAll('.nav-item').forEach(btn => {
        if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(tabName)) btn.classList.add('active');
        else btn.classList.remove('active');
    });

    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    const target = document.getElementById(`view-${tabName}`);
    if (target) target.classList.add('active');

    if (tabName === 'alumnos') loadAlumnos();
    if (tabName === 'uploads') loadUploads();
}

/**
 * Toggles visual active state for tutor gender buttons
 */
function selectTutorGender(btn) {
    const parent = btn.parentElement;
    parent.querySelectorAll('.btn-glass').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}


// -------------------------------------------------------------------------
// 2. UPLOAD LOGIC (MODAL to BOTTOM BAR)
// -------------------------------------------------------------------------
function openUploadModal() {
    const modal = document.getElementById('uploadModalOverlay');
    if (modal) modal.classList.add('open');
}

function closeUploadModal() {
    const modal = document.getElementById('uploadModalOverlay');
    if (modal) modal.classList.remove('open');
    clearFile();
}

if (dropzone) {
    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('drag-over'); });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) {
            handleFiles(e.dataTransfer.files);
        }
    });
}
if (fileInput) fileInput.addEventListener('change', () => {
    if (fileInput.files.length) handleFiles(fileInput.files);
});

function handleFiles(files) {
    if (files.length > 0) {
        const file = files[0];
        if (file.name.toLowerCase().endsWith('.pdf')) {
            // Assign to input using DataTransfer
            const dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;

            showFile(file);
        } else {
            showToast('Solo archivos PDF', true);
        }
    }
}

function showFile(file) {
    fileNameEl.textContent = file.name;
    const size = (file.size / (1024 * 1024)).toFixed(1);
    fileSizeEl.textContent = size + ' MB';
    dzEmpty.style.display = 'none';
    dzSelected.style.display = 'flex';

    // Auto-fill title from filename (remove extension)
    const titleInput = document.getElementById('uploadTitle');
    if (titleInput) {
        titleInput.value = file.name.replace(/\.pdf$/i, '');
    }
}

function clearFile() {
    if (fileInput) fileInput.value = '';
    if (dzEmpty) dzEmpty.style.display = 'flex';
    if (dzSelected) dzSelected.style.display = 'none';
    // Clear title
    const titleInput = document.getElementById('uploadTitle');
    if (titleInput) titleInput.value = '';
}

if (clearFileBtn) clearFileBtn.onclick = (e) => { e.stopPropagation(); clearFile(); };

if (uploadBtn) {
    uploadBtn.onclick = async (e) => {
        e.preventDefault();

        // Validation
        if (!fileInput.files || !fileInput.files.length) {
            return showToast('Selecciona un archivo PDF válido', true);
        }

        const fileToUpload = fileInput.files[0];
        const titleVal = document.getElementById('uploadTitle').value.trim();

        // UI Logic: Close modal immediately, show bottom bar
        closeUploadModal();
        if (processingStatusContainer) processingStatusContainer.classList.add('active');
        if (progressBar) progressBar.style.width = '0%';
        updateStatusText('Iniciando subida...');

        try {
            const fd = new FormData();
            fd.append('file', fileToUpload);
            if (titleVal) {
                fd.append('title', titleVal);
            }

            updateStatusText('Subiendo archivo al servidor...');

            const res = await fetch(`${API_URL}/upload/syllabus?account_id=${LICENCIA_ID}&licencia_id=${LICENCIA_ID}`, {
                method: 'POST',
                body: fd
            });

            if (!res.ok) {
                let errorDetails = `Error ${res.status}`;
                try {
                    const errorData = await res.json();
                    if (errorData.detail) errorDetails = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
                } catch (e) { }
                throw new Error(errorDetails);
            }

            updateStatusText('Archivo recibido. Procesando...');
            await pollProcessingConfig(); // Real-time polling

            updateStatusText('¡Completado!');
            showToast('Procesado correctamente');
            checkSyllabusStatus(true);

            setTimeout(() => {
                if (processingStatusContainer) processingStatusContainer.classList.remove('active');
            }, 5000);

        } catch (err) {
            console.error(err);
            updateStatusText('Error: ' + err.message);
            showToast(err.message, true);
            setTimeout(() => {
                if (processingStatusContainer) processingStatusContainer.classList.remove('active');
            }, 10000);
        }
    };
}

function updateStatusText(text) {
    const el = document.getElementById('currentStatusText');
    if (el) el.innerText = text;
}

async function pollProcessingConfig() {
    return new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
            try {
                // Poll progress for current license
                const res = await fetch(`${API_URL}/upload/progress/${LICENCIA_ID}`);
                if (!res.ok) return;

                const data = await res.json();

                if (data.message) updateStatusText(data.message);
                if (progressBar) progressBar.style.width = (data.percent || 0) + '%';

                // Refresh Uploads Tab if active
                const uploadsView = document.getElementById('view-uploads');
                if (uploadsView && uploadsView.classList.contains('active')) {
                    loadUploads();
                }

                // Stop condition
                if (data.status === 'completed' || (data.percent >= 100 && data.status !== 'processing' && data.status !== 'error')) {
                    clearInterval(interval);
                    resolve();
                } else if (data.status === 'error') {
                    clearInterval(interval);
                    reject(new Error(data.message || 'Error desconocido en procesado'));
                }
            } catch (e) {
                console.error("Polling error:", e);
            }
        }, 1000); // Poll every 1s
    });
}

// -------------------------------------------------------------------------
// 3. DELETE LOGIC
// -------------------------------------------------------------------------
function handleEliminar() {
    const modal = document.getElementById('deleteModalOverlay');
    const input = document.getElementById('deleteConfirmInput');
    const btn = document.getElementById('btnConfirmDelete');

    input.value = '';
    input.classList.remove('valid');
    btn.classList.remove('enabled');
    btn.style.opacity = '0.5';
    btn.style.pointerEvents = 'none';

    if (modal) modal.classList.add('open');
    setTimeout(() => input.focus(), 100);
}

function closeDeleteModal() {
    document.getElementById('deleteModalOverlay').classList.remove('open');
}

async function executeDelete() {
    const btn = document.getElementById('btnConfirmDelete');
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
        if (!syllabusData.length) {
            closeDeleteModal();
            return;
        }

        const books = [...new Set(syllabusData.map(i => i.libro_id).filter(id => id != null))];
        for (const bid of books) {
            await fetch(`${API_URL}/syllabus/libro/${bid}`, { method: 'DELETE' });
        }

        showToast('Todo el temario eliminado');
        checkSyllabusStatus(true);
        closeDeleteModal();
    } catch (e) {
        showToast("Error: " + e.message, true);
    } finally {
        btn.innerHTML = 'Eliminar Definitivamente';
    }
}

// -------------------------------------------------------------------------
// 4. SYLLABUS TREE
// -------------------------------------------------------------------------
let syllabusData = [];
window.checkSyllabusStatus = checkSyllabusStatus;

async function checkSyllabusStatus(force = false) {
    const container = document.getElementById('syllabusTree');
    if (!container) return;
    if (force) container.innerHTML = '<div class="text-center mt-5"><div class="spinner-border text-primary"></div></div>';

    try {
        const res = await fetch(`${API_URL}/syllabus?licencia_id=${LICENCIA_ID}`);
        if (!res.ok) throw new Error("Error API");
        syllabusData = await res.json();
        renderSyllabusTree(syllabusData);
    } catch (e) {
        console.error(e);
        renderSyllabusTree([]);
    }
}

function renderSyllabusTree(data) {
    const container = document.getElementById('syllabusTree');
    container.innerHTML = '';

    if (!data || !data.length) {
        document.getElementById('contentViewArea').innerHTML = `
            <div class="content-placeholder" id="contentPlaceholder">
                <div style="font-size: 3rem; opacity:0.3;"><i class="bi bi-journal-bookmark"></i></div>
                <div>No hay temario cargado</div>
            </div>
        `;
        container.innerHTML = `
            <div class="empty-syllabus">
                <i class="bi bi-journal-x"></i>
                <p>Lista vacía.</p>
                <button class="btn-glass" onclick="openUploadModal()">Subir PDF</button>
            </div>
        `;
        return;
    }

    const books = {};
    data.forEach(d => {
        const bid = d.libro_id || 'default';
        if (!books[bid]) books[bid] = [];
        books[bid].push(d);
    });

    Object.keys(books).forEach(bid => {
        const items = books[bid];
        const nodeMap = {};
        items.forEach(i => nodeMap[i.id] = { ...i, children: [] });
        const roots = [];
        items.forEach(i => {
            if (i.parent_id && nodeMap[i.parent_id]) nodeMap[i.parent_id].children.push(nodeMap[i.id]);
            else roots.push(nodeMap[i.id]);
        });
        roots.sort((a, b) => (a.orden || 0) - (b.orden || 0));

        const bookName = items[0].libro_titulo || ('Libro ' + bid);

        const wrapper = document.createElement('div');
        wrapper.className = 'book-wrapper mb-3';

        const header = document.createElement('div');
        header.className = 'book-header';

        header.innerHTML = `
            <i class="bi bi-book me-2"></i>
            <span class="flex-grow-1 text-truncate">${bookName}</span>
            <i class="bi bi-chevron-down book-toggle" style="font-size:0.9rem; opacity:0.8;"></i>
        `;

        const body = document.createElement('div');
        body.className = 'book-body ps-1';

        header.onclick = () => {
            const toggle = header.querySelector('.book-toggle');
            if (body.style.display === 'none') {
                body.style.display = 'block';
                toggle.className = 'bi bi-chevron-down book-toggle';
            } else {
                body.style.display = 'none';
                toggle.className = 'bi bi-chevron-right book-toggle';
            }
        };

        const rootContainer = document.createElement('div');
        rootContainer.className = 'tree-root-container';

        roots.forEach(r => rootContainer.appendChild(createNodeElement(r)));
        body.appendChild(rootContainer);

        wrapper.appendChild(header);
        wrapper.appendChild(body);
        container.appendChild(wrapper);
    });
}

function createNodeElement(node) {
    // Main Wrapper for the Item + Children
    const wrapper = document.createElement('div');
    wrapper.className = 'tree-item-wrapper';

    // The "Tab" / Header
    const header = document.createElement('div');
    header.className = 'tree-item-header';
    header.dataset.id = node.id;

    const hasChildren = node.children && node.children.length > 0;

    // 1. Icon / Toggle
    if (hasChildren) {
        const icon = document.createElement('i');
        icon.className = 'bi bi-chevron-right item-toggle-icon';
        // Click on chevron toggles children
        icon.onclick = (e) => {
            e.stopPropagation();
            const content = wrapper.querySelector('.tree-item-content');
            if (content.style.display === 'none') {
                content.style.display = 'block';
                icon.className = 'bi bi-chevron-down item-toggle-icon';
            } else {
                content.style.display = 'none';
                icon.className = 'bi bi-chevron-right item-toggle-icon';
            }
        };
        header.appendChild(icon);
    } else {
        // Spacer for alignment
        const sp = document.createElement('span');
        sp.className = 'item-spacer';
        sp.innerHTML = '<i class="bi bi-dot"></i>';
        header.appendChild(sp);
    }

    // 2. Name
    const name = document.createElement('span');
    name.className = 'item-name';
    name.innerText = node.nombre;
    header.appendChild(name);

    // Header click selects the topic
    header.onclick = () => selectTopic(node.id, header);

    wrapper.appendChild(header);

    // 3. Children (Dropdown Content)
    if (hasChildren) {
        const content = document.createElement('div');
        content.className = 'tree-item-content';
        content.style.display = 'none'; // Hidden by default

        node.children.sort((a, b) => a.orden - b.orden);
        // Recursive call
        node.children.forEach(c => content.appendChild(createNodeElement(c)));

        wrapper.appendChild(content);
    }

    return wrapper;
}

// -------------------------------------------------------------------------
// 5. CONTENT VIEW
// -------------------------------------------------------------------------
async function selectTopic(id, rowEl) {
    document.querySelectorAll('.tree-item-header').forEach(t => t.classList.remove('active'));
    if (rowEl) rowEl.classList.add('active');

    const view = document.getElementById('contentViewArea');
    view.innerHTML = '<div class="p-5 text-center"><div class="spinner-border text-primary"></div></div>';

    try {
        const res = await fetch(`${API_URL}/syllabus/${id}/content`);
        const data = await res.json();
        const raw = data.contenido || 'Sin contenido';

        // Usamos marked para parsear markdown
        const finalHtml = marked.parse(raw);

        view.innerHTML = `
            <div class="content-title-main">${data.titulo}</div>
            <div class="d-flex mb-4">
                <button class="btn-glass" onclick="enableEdit(${id})">
                    <i class="bi bi-pencil"></i> Editar
                </button>
            </div>
            <div class="content-body-text markdown-body" style="white-space: normal; line-height:1.6; max-width:100%;">${finalHtml}</div>
            <div class="content-meta">Bloques: ${data.bloques_count || 0}</div>
        `;

    } catch (e) {
        view.innerHTML = `<div class="text-danger p-4">Error: ${e.message}</div>`;
    }
}

async function enableEdit(id) {
    const view = document.getElementById('contentViewArea');
    const curr = view.querySelector('.content-body-text').innerText;

    view.innerHTML = `
        <h3>Editando...</h3>
        <textarea id="editArea" class="form-control mb-3" style="height:400px; font-family:monospace;">${curr}</textarea>
        <button class="btn-secondary-glass me-2" onclick="selectTopic(${id})">Cancelar</button>
        <button class="btn-premium" onclick="saveContent(${id})">Guardar</button>
    `;
}

async function saveContent(id) {
    const val = document.getElementById('editArea').value;
    try {
        await fetch(`${API_URL}/syllabus/${id}/content`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ contenido: val })
        });
        showToast('Guardado');
        selectTopic(id);
    } catch (e) { showToast(e.message, true); }
}

// -------------------------------------------------------------------------
// 7. UPLOAD DASHBOARD
// -------------------------------------------------------------------------
async function loadUploads() {
    const list = document.getElementById('uploads-list');
    if (!list) return;

    // Don't wipe content if refreshing to avoid flicker, only if empty
    if (!list.children.length) list.innerHTML = '<div class="spinner-border text-primary"></div>';

    try {
        const res = await fetch(`${API_URL}/libros?licencia_id=${LICENCIA_ID}`);
        const books = await res.json();

        const progRes = await fetch(`${API_URL}/upload/progress/${LICENCIA_ID}`);
        const progData = await progRes.json();

        // Re-render
        list.innerHTML = '';
        if (!books.length) {
            list.innerHTML = '<div class="text-center p-5 text-muted">No hay libros subidos.</div>';
            return;
        }

        books.forEach(b => {
            let isProcessing = false;
            let percent = 0;
            let message = '';

            // Check if this book is the one being processed
            // Robust match using title if available, else filename
            const isMatch = (progData.titulo && progData.titulo === b.titulo) ||
                (progData.filename && progData.filename.includes(b.titulo));

            if (progData.status === 'processing' && isMatch) {
                isProcessing = true;
                percent = progData.percent || 0;
                message = progData.message;
            }

            // Content for the circular indicator
            let indicatorHtml = '';

            if (isProcessing) {
                const circumference = 113; // 2 * PI * 18
                const offset = circumference - (percent / 100 * circumference);
                indicatorHtml = `
                    <div class="progress-circle-wrapper">
                        <svg class="progress-circle-svg" viewBox="0 0 44 44">
                            <circle class="progress-circle-bg" cx="22" cy="22" r="18"></circle>
                            <circle class="progress-circle-fg" cx="22" cy="22" r="18" style="stroke-dashoffset: ${offset}"></circle>
                        </svg>
                        <div style="position:absolute; font-size:0.65rem; font-weight:800; color:var(--sky-600);">${Math.round(percent)}%</div>
                    </div>
                 `;
            } else if (b.activo) {
                indicatorHtml = `<i class="bi bi-check-circle-fill progress-circle-check"></i>`;
            } else {
                // Not active, not processing (maybe queued or error?)
                indicatorHtml = `<i class="bi bi-clock-history text-muted fs-4"></i>`;
            }

            const card = document.createElement('div');
            card.className = 'col-md-6 mb-3'; // Wider cards for better layout

            // Delete button logic
            const deleteDisabled = isProcessing ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : '';
            const deleteAction = isProcessing ? '' : `onclick="deleteBook(${b.id}, '${b.titulo.replace(/'/g, "\\'")}')"`;
            const editAction = isProcessing ? '' : `onclick="openEditBook(${b.id}, '${b.titulo.replace(/'/g, "\\'")}')"`;

            card.innerHTML = `
                <div class="upload-card d-flex flex-row align-items-center gap-3 p-3" style="height:auto; min-height:80px;">
                    <div class="card-icon mb-0" style="width:48px; height:48px; min-width:48px; font-size:1.4rem; background:var(--sky-100); color:var(--sky-600);">
                        <i class="bi bi-file-earmark-pdf"></i>
                    </div>
                    <div class="flex-grow-1" style="min-width:0;">
                        <div class="fw-bold text-dark text-truncate" title="${b.titulo}">${b.titulo}</div>
                        <div class="text-muted small"><i class="bi bi-calendar3"></i> ${new Date(b.fecha_creacion).toLocaleDateString()}</div>
                        ${isProcessing ? `<div class="small text-primary mt-1 text-truncate">${message}</div>` : ''}
                    </div>
                    <div class="flex-shrink-0 ms-2 d-flex align-items-center gap-2">
                         <button class="delete-circle-btn" ${deleteDisabled} ${editAction} title="Editar Libro" style="color:var(--primary-600); background:var(--primary-50);">
                            <i class="bi bi-pencil"></i>
                        </button>
                         <button class="delete-circle-btn" ${deleteDisabled} ${deleteAction} title="Eliminar Libro">
                            <i class="bi bi-trash"></i>
                        </button>
                        ${indicatorHtml}
                    </div>
                </div>
             `;
            list.appendChild(card);
        });

    } catch (e) {
        console.error(e);
        // Only show error if list was empty
        if (!list.children.length) list.innerHTML = `<div class="text-danger">Error: ${e.message}</div>`;
    }
}

// -------------------------------------------------------------------------
// 7.1 EDIT BOOK
// -------------------------------------------------------------------------
function openEditBook(id, title) {
    const panel = document.getElementById('edit-book-panel');
    const list = document.getElementById('uploads-list');
    const input = document.getElementById('editBookTitle');
    const idInput = document.getElementById('editBookId');

    if (panel && list && input && idInput) {
        input.value = title;
        idInput.value = id;
        panel.style.display = 'block';
        list.style.opacity = '0.3';
        list.style.pointerEvents = 'none';

        // Scroll to top of panel
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setTimeout(() => input.focus(), 100);
    }
}

function cancelEditBook() {
    const panel = document.getElementById('edit-book-panel');
    const list = document.getElementById('uploads-list');
    if (panel) panel.style.display = 'none';
    if (list) {
        list.style.opacity = '1';
        list.style.pointerEvents = 'all';
    }
}

async function saveBookTitle() {
    const id = document.getElementById('editBookId').value;
    const title = document.getElementById('editBookTitle').value.trim();

    if (!title) return showToast('El título no puede estar vacío', true);

    try {
        const res = await fetch(`${API_URL}/libros/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ titulo: title })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Error al actualizar');
        }

        showToast('Título actualizado');
        cancelEditBook();
        loadUploads(); // Refresh list
    } catch (e) {
        showToast("Error: " + e.message, true);
    }
}


// -------------------------------------------------------------------------
// 7.2 DELETE BOOK (Single)
// -------------------------------------------------------------------------
async function deleteBook(id, title) {
    if (!confirm(`¿Estás seguro de que quieres eliminar el libro "${title}" y todo su contenido? Esta acción no se puede deshacer.`)) {
        return;
    }

    try {
        const res = await fetch(`${API_URL}/syllabus/libro/${id}`, { method: 'DELETE' });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Error al eliminar');
        }
        showToast('Libro eliminado correctamente');
        loadUploads(); // Refresh list
        checkSyllabusStatus(); // Refresh tree if needed
    } catch (e) {
        showToast("Error: " + e.message, true);
    }
}

// -------------------------------------------------------------------------
// 6. STUDENTS
// -------------------------------------------------------------------------
async function loadAlumnos() {
    const grid = document.getElementById('alumnos-grid');
    const badge = document.getElementById('student-limit-badge');
    if (!grid) return;
    grid.innerHTML = '<div class="spinner-border text-primary"></div>';

    try {
        const [resAlumnos, resLicencia] = await Promise.all([
            fetch(`${API_URL}/licencias/${LICENCIA_ID}/alumnos`),
            fetch(`${API_URL}/licencias/${LICENCIA_ID}`)
        ]);

        const list = await resAlumnos.json();
        const licencia = await resLicencia.json();

        // Actualizar estado global para validaciones
        licenseStatus.current = list.length;
        licenseStatus.max = licencia.max_alumnos;

        // Actualizar el badge de límite
        if (badge && licencia) {
            badge.innerText = `${list.length} / ${licencia.max_alumnos} Alumnos`;
            // Cambiar color si se llega al límite
            if (list.length >= licencia.max_alumnos) {
                badge.style.background = 'rgba(239, 68, 68, 0.1)';
                badge.style.color = '#dc2626';
                badge.style.borderColor = '#fecaca';
            } else {
                badge.style.background = 'rgba(14, 165, 233, 0.1)';
                badge.style.color = 'var(--primary-600)';
                badge.style.borderColor = 'var(--primary-100)';
            }
        }

        grid.innerHTML = '';
        if (!list.length) {
            grid.innerHTML = '<div class="text-center p-5 text-muted">No hay alumnos.</div>';
            return;
        }

        list.forEach(a => {
            const card = document.createElement('div');
            card.className = 'student-card';

            const username = a.nombre;
            const displayName = a.alias || a.nombre;

            card.innerHTML = `
                <div class="student-header">
                    <div class="student-avatar" style="background:#e0f2fe;color:#0369a1;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;">${displayName.charAt(0)}</div>
                    <div class="student-info">
                        <div class="student-name fw-bold text-truncate" style="max-width:140px;" title="${displayName}">${displayName}</div>
                        <div class="student-status text-success small">Activo</div>
                    </div>
                </div>
                
                <div class="mt-3">
                    <!-- Username Field -->
                    <div class="field-row">
                        <div style="min-width:0; margin-right:8px;">
                            <span class="field-label">Usuario</span>
                            <div class="field-value" title="${username}">${username}</div>
                        </div>
                        <button class="btn-icon-small" onclick="copyText('${username}')" title="Copiar Usuario">
                            <i class="bi bi-clipboard"></i>
                        </button>
                    </div>

                    <!-- Token Field -->
                    <div class="field-row">
                        <div style="min-width:0; margin-right:8px; flex-grow:1;">
                            <span class="field-label">Token / Acceso</span>
                            ${a.must_change_password ?
                    `<div class="field-value code" id="token-${a.id}">••••••••</div>` :
                    `<div class="field-value" style="font-size: 0.75rem; color: #94a3b8; font-style: italic;">El usuario ya ha establecido una contraseña</div>`
                }
                        </div>
                        ${a.must_change_password ? `
                            <div class="d-flex gap-1">
                                <button class="btn-icon-small" onclick="toggleToken(this, 'token-${a.id}', '${a.token}')" title="Ver/Ocultar">
                                    <i class="bi bi-eye"></i>
                                </button>
                                <button class="btn-icon-small" onclick="copyText('${a.token}')" title="Copiar Token">
                                    <i class="bi bi-clipboard"></i>
                                </button>
                            </div>
                        ` : ''}
                    </div>

                </div>

                <!-- Footer Actions -->
                <div class="mt-2 text-end pt-2 border-top d-flex justify-content-end">
                    <button class="delete-circle-btn" onclick="confirmDeleteStudent(${a.id}, '${displayName}')" title="Eliminar Alumno">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            `;
            grid.appendChild(card);
        });
    } catch (e) {
        grid.innerHTML = `<div class="text-danger">Error: ${e.message}</div>`;
    }
}

// Global variable to store the ID of the student to be deleted
let studentToDeleteId = null;

function toggleToken(btn, elementId, token) {
    const el = document.getElementById(elementId);
    const icon = btn.querySelector('i');

    if (el.innerText === '••••••••') {
        if (confirm('¿Quieres mostrar el token de acceso? Asegúrate de que nadie esté mirando.')) {
            el.innerText = token;
            icon.className = 'bi bi-eye-slash';
            btn.style.color = 'var(--sky-600)';
            btn.style.background = 'var(--sky-100)';
        }
    } else {
        el.innerText = '••••••••';
        icon.className = 'bi bi-eye';
        btn.style.color = '';
        btn.style.background = '';
    }
}

function copyText(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => showToast('Copiado al portapapeles'));
    } else {
        prompt("Copiar:", text);
    }
}

function confirmDeleteStudent(id, name) {
    studentToDeleteId = id;
    const modal = document.getElementById('deleteStudentModalOverlay');
    const input = document.getElementById('deleteStudentInput');
    const confirmBtn = document.getElementById('btnConfirmDeleteStudent');

    // Reset state
    input.value = '';
    confirmBtn.classList.remove('enabled');
    // document.querySelector('#deleteStudentModalOverlay h3').innerText = `¿Eliminar a ${name}?`; // Optional customization

    modal.classList.add('open');
    input.focus();

    // Input validation listener (usa 'input' para capturar cualquier cambio)
    input.oninput = (e) => {
        const val = e.target.value.trim().toUpperCase(); // Asegura mayúsculas y sin espacios

        if (val === 'ELIMINAR') {
            confirmBtn.classList.add('enabled');
            confirmBtn.style.pointerEvents = 'auto'; // Permitir clic
            confirmBtn.style.opacity = '1';
        } else {
            confirmBtn.classList.remove('enabled');
            confirmBtn.style.pointerEvents = 'none'; // Bloquear clic
            confirmBtn.style.opacity = '0.5';
        }
    };

    // Enter key listener
    input.onkeydown = (e) => {
        if (e.key === 'Enter') {
            const val = e.target.value.trim().toUpperCase();
            if (val === 'ELIMINAR') {
                executeDeleteStudent();
            }
        }
    };
}

function closeDeleteStudentModal() {
    studentToDeleteId = null;
    document.getElementById('deleteStudentModalOverlay').classList.remove('open');
}

async function executeDeleteStudent() {
    if (!studentToDeleteId) return;

    const confirmBtn = document.getElementById('btnConfirmDeleteStudent');
    confirmBtn.innerHTML = '<div class="spinner-border spinner-border-sm"></div> Eliminando...';

    try {
        const res = await fetch(`${API_URL}/licencias/${LICENCIA_ID}/alumnos/${studentToDeleteId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error("Error al eliminar");

        showToast('Alumno eliminado');
        closeDeleteStudentModal();
        loadAlumnos();
    } catch (e) {
        showToast(e.message, true);
        closeDeleteStudentModal();
    } finally {
        confirmBtn.innerHTML = 'Eliminar';
    }
}

function handleAddAlumno() {
    if (licenseStatus.current >= licenseStatus.max && licenseStatus.max > 0) {
        document.getElementById('limitReachedModalOverlay').classList.add('open');
    } else {
        new bootstrap.Modal(document.getElementById('addStudentModal')).show();
    }
}

function closeLimitModal() {
    document.getElementById('limitReachedModalOverlay').classList.remove('open');
}

async function saveNewStudent() {
    const name = document.getElementById('newStudentName').value;
    if (!name) return showToast('Nombre obligatorio', true);

    try {
        await fetch(`${API_URL}/licencias/${LICENCIA_ID}/alumnos`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nombre: name, licencia_id: Number(LICENCIA_ID) })
        });

        const el = document.getElementById('addStudentModal');
        const modal = bootstrap.Modal.getInstance(el);
        modal.hide();
        document.getElementById('newStudentName').value = '';
        showToast('Alumno creado');
        loadAlumnos();
    } catch (e) { showToast(e.message, true); }
}



function showToast(msg, isError) {
    const el = document.getElementById('toast');
    const txt = document.getElementById('toastMsg');
    const ico = document.getElementById('toastIco');
    if (txt) txt.innerText = msg;
    if (ico) ico.innerHTML = isError ? '<i class="bi bi-x-circle"></i>' : '<i class="bi bi-check-circle"></i>';
    if (el) {
        el.style.display = 'flex';
        el.className = 'toast-msg' + (isError ? ' is-error' : '');
        setTimeout(() => el.style.display = 'none', 3000);
    }
}
