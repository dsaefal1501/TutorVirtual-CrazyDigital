const API_URL = 'http://127.0.0.1:8000';
let openLicenseIds = new Set();
let lastInstructorsData = null;
let lastLicensesData = null;


// ---- MAIN INITIALIZATION ----
document.addEventListener('DOMContentLoaded', () => {
    // Inicializar vista
    // Inicializar vista
    switchTab('create');
    loadInstructors(); // Cargar la lista en segundo plano

    // Auto-refresco en tiempo real (Polling cada 2s)
    setInterval(() => {
        const listPanel = document.getElementById('view-list');
        if (listPanel && listPanel.style.display !== 'none') {
            loadInstructors();
        }
    }, 2000);
});

// ---- NAVIGATION ----
function switchTab(tabId) {
    // Ocultar todos los paneles
    document.querySelectorAll('.view-panel').forEach(el => {
        el.style.display = 'none';
        el.classList.remove('active');
    });

    // Mostrar el panel seleccionado
    const panel = document.getElementById(`view-${tabId}`);
    if (panel) {
        panel.style.display = 'block';
        setTimeout(() => panel.classList.add('active'), 10);
    }

    // Actualizar botones del sidebar
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));

    // Buscar el botón que corresponde a este tab
    // Nota: Esto busca por el atributo onclick que contiene el tabId
    const activeBtn = Array.from(document.querySelectorAll('.nav-btn')).find(btn =>
        btn.getAttribute('onclick').includes(`switchTab('${tabId}')`)
    );
    if (activeBtn) activeBtn.classList.add('active');

    // Si vamos a la lista, recargar datos por si hubo cambios
    if (tabId === 'list') {
        loadInstructors();
    }
}

// ---- CREATE INSTRUCTOR ----
async function createInstructor() {
    const username = document.getElementById('username').value.trim();
    const fullname = document.getElementById('fullname').value.trim();
    const maxStudents = document.getElementById('maxStudents').value;
    const passInput = document.getElementById('password');
    const password = passInput.value.trim();
    const msgBox = document.getElementById('msgBoxCreate');
    const btn = document.getElementById('btnCreate');

    // Reset mensajes
    msgBox.style.display = 'none';
    msgBox.className = 'message-box';

    if (!username || !password || !fullname) {
        showMessage(msgBox, 'Por favor completa todos los campos.', 'error');
        return;
    }

    // UI Loading
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Procesando...';

    try {
        const response = await fetch(`${API_URL}/dev/create-instructor`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: username,
                password: password,
                nombre_completo: fullname,
                max_alumnos: parseInt(maxStudents) || 10
            })
        });

        const data = await response.json();

        if (response.ok) {
            showMessage(msgBox, `¡Éxito! ${data.mensaje}`, 'success');
            // Limpiar formulario
            document.getElementById('username').value = '';
            document.getElementById('fullname').value = '';
            document.getElementById('maxStudents').value = '10';
            passInput.value = '';

            // Recargar lista para que aparezca el nuevo
            loadInstructors();
        } else {
            throw new Error(data.detail || 'Error desconocido');
        }

    } catch (error) {
        console.error("Create error:", error);
        showMessage(msgBox, error.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ---- LIST INSTRUCTORS ----
async function loadInstructors() {
    const tableBody = document.getElementById('instructorsTableBody');
    if (!tableBody) return;

    try {
        const res = await fetch(`${API_URL}/dev/instructors`);
        if (!res.ok) throw new Error("Error al cargar lista");

        const instructors = await res.json();

        // --- SMART UPDATE: Only rebuild if data actually changed ---
        const currentDataStr = JSON.stringify(instructors);
        if (currentDataStr === lastInstructorsData) {
            // Data hasn't changed, but refresh sub-tables if open
            instructors.forEach(instruct => {
                if (openLicenseIds.has(instruct.licencia_id)) {
                    fetchAndRenderStudents(instruct.licencia_id);
                }
            });
            loadLicenses();
            return;
        }
        lastInstructorsData = currentDataStr;

        if (instructors.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px;">No hay instructores registrados.</td></tr>';
            loadLicenses();
            return;
        }

        tableBody.innerHTML = '';
        const fragment = document.createDocumentFragment();

        instructors.forEach(instruct => {
            const row = document.createElement('tr');
            const name = instruct.nombre || '-';
            const email = instruct.email || '-';
            const licId = instruct.licencia_id;
            const isExpanded = openLicenseIds.has(licId);

            row.innerHTML = `
                <td>#${instruct.id}</td>
                <td><span style="font-weight:600; color:#fff">${name}</span></td>
                <td>${email}</td>
                <td><span class="badge" style="background:rgba(59,130,246,0.2); color:#60a5fa; padding:4px 8px; border-radius:4px; font-size:0.75rem;">${instruct.rol}</span></td>
                <td>
                    <button class="btn-icon view-students ${isExpanded ? 'active' : ''}" title="Ver Alumnos" onclick="toggleStudents(this, ${licId})" style="margin-right:8px; color:#34d399; background:rgba(16,185,129,0.1);">
                        <i class="bi ${isExpanded ? 'bi-chevron-up' : 'bi-people'}"></i>
                    </button>
                    <button class="btn-icon delete" title="Eliminar" onclick="deleteInstructor(${instruct.id}, '${name}')">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            `;
            fragment.appendChild(row);

            const subRow = document.createElement('tr');
            subRow.className = 'sub-table-row';
            subRow.style.display = isExpanded ? 'table-row' : 'none';
            subRow.innerHTML = `
                <td colspan="5" style="padding:0; background:rgba(255,255,255,0.02);">
                    <div class="sub-table-container" style="padding:15px 20px; border-bottom:1px solid rgba(255,255,255,0.05);">
                        <div style="font-size:0.85rem; color:#9ca3af; margin-bottom:10px;"><i class="bi bi-person-badge"></i> Alumnos asociados a Licencia #${licId}</div>
                        <table class="data-table" style="width:100%; font-size:0.85rem;">
                            <thead>
                                <tr style="background:rgba(0,0,0,0.2);">
                                    <th style="padding:8px;">ID</th>
                                    <th style="padding:8px;">Nombre</th>
                                    <th style="padding:8px;">Usuario</th>
                                    <th style="padding:8px;">Token</th>
                                    <th style="padding:8px;">Estado</th>
                                </tr>
                            </thead>
                            <tbody id="students-list-${licId}">
                            </tbody>
                        </table>
                    </div>
                </td>
            `;
            fragment.appendChild(subRow);

        });
        tableBody.appendChild(fragment);

        instructors.forEach(instruct => {
            if (openLicenseIds.has(instruct.licencia_id)) {
                fetchAndRenderStudents(instruct.licencia_id);
            }
        });

    } catch (e) {
        console.error(e);
        tableBody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--error-text)">Error: ${e.message}</td></tr>`;
    }

    loadLicenses();
}

async function loadLicenses() {
    const tbody = document.getElementById('licensesTableBody');
    if (!tbody) return;

    try {
        const res = await fetch(`${API_URL}/dev/licencias`);
        if (!res.ok) throw new Error('Error licencias');
        const data = await res.json();

        // --- SMART UPDATE: Only rebuild if data actually changed ---
        const currentDataStr = JSON.stringify(data);
        if (currentDataStr === lastLicensesData) return;
        lastLicensesData = currentDataStr;

        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6">No hay licencias</td></tr>';
            return;
        }

        data.forEach(lic => {
            const tr = document.createElement('tr');
            const isActive = lic.activa;

            tr.innerHTML = `
                <td>#${lic.id}</td>
                <td><span style="font-weight:600; color:#fff">${lic.cliente}</span></td>
                <td>${lic.max_alumnos}</td>
                <td>${lic.usuarios_actuales} / ${lic.max_alumnos}</td>
                <td><span class="badge" style="background:${isActive ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}; color:${isActive ? '#34d399' : '#f87171'}; padding:4px 8px; border-radius:4px; font-size:0.75rem;">
                    ${isActive ? 'Activa' : 'Inactiva'}
                </span></td>
                <td>${lic.fecha_fin || '∞'}</td>
                <td>
                    ${lic.id !== 1 ? `
                    ` : '<span class="text-muted" style="font-size:12px">Sistema</span>'}
                </td>
            `;
            tbody.appendChild(tr);
        });

    } catch (e) {
        console.error("Error cargando licencias:", e);
    }
}

async function deleteLicense(id, clientName) {
    if (!confirm(`⚠️ PELIGRO: Eliminar la licencia "${clientName}" (ID: ${id}) borrará TODOS sus usuarios, libros y datos asociados de forma permanente.\n\n¿Estás seguro?`)) return;

    try {
        const res = await fetch(`${API_URL}/dev/licencia/${id}`, { method: 'DELETE' });

        if (res.ok) {
            loadLicenses();
            loadInstructors(); // Refrescar también la lista de instructores por si se borraron
        } else {
            const data = await res.json();
            throw new Error(data.detail || 'Error al eliminar licencia');
        }
    } catch (e) {
        alert("Error: " + e.message);
    }
}

async function deleteInstructor(id, name) {
    if (!confirm(`¿Estás seguro de eliminar al instructor "${name}"? Esta acción eliminará su cuenta y su licencia.`)) return;

    try {
        const res = await fetch(`${API_URL}/dev/instructor/${id}`, { method: 'DELETE' });

        if (res.ok) {
            // alert('Instructor eliminado correctamente');
            loadInstructors(); // Recargar tabla
        } else {
            const data = await res.json();
            throw new Error(data.detail || 'Error al eliminar');
        }

    } catch (e) {
        alert("Error: " + e.message);
    }
}

// ---- VIEW STUDENTS INSTRUCTOR ----
async function fetchAndRenderStudents(licId) {
    const tbody = document.getElementById(`students-list-${licId}`);
    if (!tbody) return;

    try {
        const res = await fetch(`${API_URL}/licencias/${licId}/alumnos`);
        if (!res.ok) throw new Error("Error fetching students");

        const students = await res.json();

        if (students.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:15px; font-size:0.85rem;">No hay alumnos registrados.</td></tr>';
            return;
        }

        const fragment = document.createDocumentFragment();
        students.forEach(s => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
            const tokenDisplay = s.token ? `<span class="copy-token" onclick="navigator.clipboard.writeText('${s.token}').then(()=>alert('Token copiado'))" style="cursor:pointer" title="Click para copiar">${s.token.substring(0, 8)}...</span>` : '-';

            tr.innerHTML = `
                <td style="padding:8px 12px; color:#94a3b8;">${s.id}</td>
                <td style="padding:8px 12px; color:#e2e8f0; font-weight:500;">${s.alias || s.nombre}</td>
                <td style="padding:8px 12px; color:#9ca3af;" class="user-select-all">${s.nombre}</td>
                <td style="padding:8px 12px; font-family:monospace; color:#60a5fa;">${tokenDisplay}</td>
                <td style="padding:8px 12px;">
                    <span class="badge" style="background:${s.activo ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}; color:${s.activo ? '#34d399' : '#f87171'}; font-size:0.7rem;">
                        ${s.activo ? 'Activo' : 'Inactivo'}
                    </span>
                </td>
            `;
            fragment.appendChild(tr);
        });

        tbody.innerHTML = '';
        tbody.appendChild(fragment);

    } catch (e) {
        console.error(e);
        tbody.innerHTML = `<tr><td colspan="5" class="text-danger text-center" style="padding:10px;">Error: ${e.message}</td></tr>`;
    }
}

async function toggleStudents(btn, licId) {
    const row = btn.closest('tr');
    const subRow = row.nextElementSibling;

    if (!subRow || !subRow.classList.contains('sub-table-row')) {
        console.error("Sub-row not found for toggle");
        return;
    }

    if (openLicenseIds.has(licId)) {
        openLicenseIds.delete(licId);
        subRow.style.display = 'none';
        btn.innerHTML = '<i class="bi bi-people"></i>';
        btn.classList.remove('active');
    } else {
        openLicenseIds.add(licId);
        subRow.style.display = 'table-row';
        btn.innerHTML = '<i class="bi bi-chevron-up"></i>';
        btn.classList.add('active');


        fetchAndRenderStudents(licId);
    }
}

// ---- VIEW STUDENTS INSTRUCTOR ----
async function fetchAndRenderStudents(licId) {
    const tbody = document.getElementById(`students-list-${licId}`);
    if (!tbody) return;

    try {
        const res = await fetch(`${API_URL}/licencias/${licId}/alumnos`);
        if (!res.ok) throw new Error("Error fetching students");

        const students = await res.json();

        if (students.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:15px; font-size:0.85rem;">No hay alumnos registrados.</td></tr>';
            return;
        }

        let newHtml = '';
        students.forEach(s => {
            const tokenDisplay = s.token ? `<span class="copy-token" onclick="navigator.clipboard.writeText('${s.token}').then(()=>alert('Token copiado'))" style="cursor:pointer" title="Click para copiar">${s.token.substring(0, 8)}...</span>` : '-';
            newHtml += `
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05)">
                    <td style="padding:8px 12px; color:#94a3b8;">${s.id}</td>
                    <td style="padding:8px 12px; color:#e2e8f0; font-weight:500;">${s.alias || s.nombre}</td>
                    <td style="padding:8px 12px; color:#9ca3af;" class="user-select-all">${s.nombre}</td>
                    <td style="padding:8px 12px; font-family:monospace; color:#60a5fa;">${tokenDisplay}</td>
                    <td style="padding:8px 12px;">
                        <span class="badge" style="background:${s.activo ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}; color:${s.activo ? '#34d399' : '#f87171'}; font-size:0.7rem;">
                            ${s.activo ? 'Activo' : 'Inactivo'}
                        </span>
                    </td>
                </tr>
            `;
        });

        if (tbody.innerHTML !== newHtml) {
            tbody.innerHTML = newHtml;
        }

    } catch (e) {
        console.error(e);
        tbody.innerHTML = `<tr><td colspan="5" class="text-danger text-center" style="padding:10px;">Error: ${e.message}</td></tr>`;
    }
}


// ---- UTILS ----
function togglePass() {
    const passInput = document.getElementById('password');
    const eyeIcon = document.getElementById('eyeIcon');
    if (passInput.type === "password") {
        passInput.type = "text";
        eyeIcon.className = 'bi bi-eye-slash-fill toggle-password';
    } else {
        passInput.type = "password";
        eyeIcon.className = 'bi bi-eye-fill toggle-password';
    }
}

function showMessage(element, text, type) {
    element.innerText = text;
    element.className = 'message-box ' + type;
    element.style.display = 'block';
}
