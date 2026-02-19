/* devs.js */
const API_URL = 'http://127.0.0.1:8000';

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

    // Solo mostrar "Cargando" si la tabla está vacía o si queremos feedback explícito
    // tableBody.innerHTML = '<tr><td colspan="5" class="text-center" style="padding:20px; color:var(--text-light)">Cargando...</td></tr>';

    try {
        const res = await fetch(`${API_URL}/dev/instructors`);
        if (!res.ok) throw new Error("Error al cargar lista");

        const instructors = await res.json();

        if (instructors.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px;">No hay instructores registrados.</td></tr>';
            // Aún así cargamos licencias
            loadLicenses();
            return;
        }

        tableBody.innerHTML = ''; // Limpiar tabla
        instructors.forEach(instruct => {
            const row = document.createElement('tr');

            const name = instruct.nombre || '-'; // nombre de usuario (login)
            const email = instruct.email || '-';

            row.innerHTML = `
                <td>#${instruct.id}</td>
                <td><span style="font-weight:600; color:#fff">${name}</span></td>
                <td>${email}</td>
                <td><span class="badge" style="background:rgba(59,130,246,0.2); color:#60a5fa; padding:4px 8px; border-radius:4px; font-size:0.75rem;">${instruct.rol}</span></td>
                <td>
                    <button class="btn-icon delete" title="Eliminar" onclick="deleteInstructor(${instruct.id}, '${name}')">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            `;
            tableBody.appendChild(row);
        });

    } catch (e) {
        console.error(e);
        tableBody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--error-text)">Error: ${e.message}</td></tr>`;
    }

    // Cargar licencias también
    loadLicenses();
}

async function loadLicenses() {
    const tbody = document.getElementById('licensesTableBody');
    if (!tbody) return;

    try {
        const res = await fetch(`${API_URL}/dev/licencias`);
        if (!res.ok) throw new Error('Error licencias');
        const data = await res.json();

        tbody.innerHTML = '';
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
