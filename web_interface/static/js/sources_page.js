/**
 * Объединённая страница источников: FTP + АТС/CRM
 */
/* global bootstrap */

function escapeHtml(text) {
    if (text === undefined || text === null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDateUTC(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleString('ru-RU', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}

/**
 * ISO (UTC) → значение для input[type=datetime-local]: компоненты в UTC (как в legacy ftp.html).
 * Без часового пояса в строке; при сохранении используйте datetimeLocalValueToUtcIso().
 */
function formatDatetimeLocal(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (v) => String(v).padStart(2, '0');
    return (
        d.getUTCFullYear() +
        '-' +
        pad(d.getUTCMonth() + 1) +
        '-' +
        pad(d.getUTCDate()) +
        'T' +
        pad(d.getUTCHours()) +
        ':' +
        pad(d.getUTCMinutes())
    );
}

/**
 * Значение datetime-local (YYYY-MM-DDTHH:mm) интерпретируем как момент в UTC → ISO для API.
 * Согласовано с formatDatetimeLocal (оба — «настенные» UTC часы, не локальный пояс браузера).
 */
function datetimeLocalValueToUtcIso(val) {
    if (!val || typeof val !== 'string') return null;
    const m = val.trim().match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (!m) return null;
    const y = parseInt(m[1], 10);
    const mo = parseInt(m[2], 10) - 1;
    const da = parseInt(m[3], 10);
    const h = parseInt(m[4], 10);
    const mi = parseInt(m[5], 10);
    const sec = m[6] != null ? parseInt(m[6], 10) : 0;
    const t = Date.UTC(y, mo, da, h, mi, sec, 0);
    if (Number.isNaN(t)) return null;
    return new Date(t).toISOString();
}

function scrollToSource(elId) {
    const el = document.getElementById(elId);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function openFtpSection() {
    scrollToSource('sources-ftp');
}

function openRostelecomSection() {
    const p = document.getElementById('rostelecomPanel');
    if (p) {
        p.style.display = 'block';
        loadRostelecomConnections();
    }
    scrollToSource('sources-rostelecom');
}

function openStocrmSection() {
    const p = document.getElementById('stocrmPanel');
    if (p) {
        p.style.display = 'block';
        loadStocrmConnections();
    }
    scrollToSource('sources-stocrm');
}

function openCustomApiSection() {
    const p = document.getElementById('customApiPanel');
    if (p) {
        p.style.display = 'block';
        loadCustomApiConnections();
    }
    scrollToSource('sources-custom-api');
}

function toggleCustomApiPanel() {
    const p = document.getElementById('customApiPanel');
    if (!p) return;
    const show = p.style.display === 'none';
    p.style.display = show ? 'block' : 'none';
    if (show) loadCustomApiConnections();
}

function toggleRostelecomPanel() {
    const p = document.getElementById('rostelecomPanel');
    if (!p) return;
    const show = p.style.display === 'none';
    p.style.display = show ? 'block' : 'none';
    if (show) loadRostelecomConnections();
}

function toggleStocrmPanel() {
    const p = document.getElementById('stocrmPanel');
    if (!p) return;
    const show = p.style.display === 'none';
    p.style.display = show ? 'block' : 'none';
    if (show) loadStocrmConnections();
}

async function refreshConnectedSummary() {
    const host = document.getElementById('connectedSourcesSummary');
    if (!host) return;
    try {
        const [ftpR, rtR, stR, caR] = await Promise.all([
            fetch('/api/ftp/connections').then((r) => r.json()),
            fetch('/api/ats/rostelecom/connections').then((r) => r.json()),
            fetch('/api/ats/stocrm/connections').then((r) => r.json()),
            fetch('/api/ats/custom_api/connections').then((r) => r.json()),
        ]);
        const ftp = Array.isArray(ftpR) ? ftpR : [];
        const rt = Array.isArray(rtR) ? rtR : [];
        const st = Array.isArray(stR) ? stR : [];
        const ca = Array.isArray(caR) ? caR : [];
        const parts = [];
        ftp.forEach((c) => {
            parts.push(
                `<div class="connected-source-card"><div class="badge-type">FTP/SFTP</div><strong>${escapeHtml(c.name)}</strong><div class="small text-muted">${escapeHtml(c.host)}</div><div class="small">${c.last_sync ? formatDateUTC(c.last_sync) : 'Синхр.: —'}</div></div>`
            );
        });
        rt.forEach((c) => {
            parts.push(
                `<div class="connected-source-card"><div class="badge-type">Ростелеком</div><strong>${escapeHtml(c.name)}</strong><div class="small text-muted">${escapeHtml(c.api_url || '')}</div><div class="small">${c.last_sync ? formatDateUTC(c.last_sync) : 'Синхр.: —'}</div></div>`
            );
        });
        st.forEach((c) => {
            parts.push(
                `<div class="connected-source-card"><div class="badge-type">StoCRM</div><strong>${escapeHtml(c.name)}</strong><div class="small text-muted">${escapeHtml(c.domain)}.stocrm.ru</div><div class="small">${c.last_sync ? formatDateUTC(c.last_sync) : 'Синхр.: —'}</div></div>`
            );
        });
        ca.forEach((c) => {
            const url = (c.request_config && c.request_config.url) || '';
            parts.push(
                `<div class="connected-source-card"><div class="badge-type">Кастомный API</div><strong>${escapeHtml(c.name)}</strong><div class="small text-muted">${escapeHtml(url)}</div><div class="small">${c.last_sync ? formatDateUTC(c.last_sync) : 'Синхр.: —'}</div></div>`
            );
        });
        if (!parts.length) {
            host.innerHTML =
                '<p class="connected-empty-hint mb-0">Пока нет подключений. Выберите провайдера ниже и добавьте первое подключение.</p>';
            return;
        }
        host.innerHTML = `<div class="connected-sources-grid w-100">${parts.join('')}</div>`;
    } catch (e) {
        console.error(e);
        host.innerHTML = '<p class="text-danger small">Не удалось загрузить сводку подключений.</p>';
    }
}

// ——— FTP ———
let connections = [];

document.addEventListener('DOMContentLoaded', function () {
    loadConnections();
    refreshConnectedSummary();
    document.getElementById('connProtocol')?.addEventListener('change', function () {
        const portInput = document.getElementById('connPort');
        if (!portInput) return;
        if (this.value === 'ftp') portInput.value = '21';
        else if (this.value === 'sftp') portInput.value = '22';
    });
    if (window.location.hash === '#sources-ftp') openFtpSection();
    if (window.location.hash === '#sources-rostelecom') openRostelecomSection();
    if (window.location.hash === '#sources-stocrm') openStocrmSection();
    if (window.location.hash === '#sources-custom-api') openCustomApiSection();
});

async function loadConnections() {
    try {
        const response = await fetch('/api/ftp/connections');
        connections = await response.json();
        renderConnections();
        refreshConnectedSummary();
    } catch (error) {
        console.error('Ошибка загрузки подключений:', error);
        if (typeof showAlert === 'function') showAlert('Ошибка загрузки подключений', 'danger');
    }
}

function renderConnections() {
    const grid = document.getElementById('connectionsGrid');
    if (!grid) return;
    if (connections.error) {
        grid.innerHTML = `<div class="col-12"><div class="alert alert-danger">Ошибка: ${connections.error}</div></div>`;
        return;
    }
    if (connections.length === 0) {
        grid.innerHTML = `
            <div class="empty-state-ftp">
                <i class="fas fa-server"></i>
                <h4>Нет FTP/SFTP подключений</h4>
                <p class="text-muted">Добавьте подключение кнопкой выше или через карточку «FTP/SFTP»</p>
                <button class="btn btn-primary mt-3" type="button" onclick="showAddModal()">
                    <i class="fas fa-plus me-2"></i>Добавить подключение
                </button>
            </div>`;
        return;
    }
    grid.innerHTML = connections
        .map((conn) => {
            const statusClass = conn.is_active ? 'active' : 'inactive';
            const statusText = conn.is_active ? 'Активно' : 'Неактивно';
            return `
        <div class="ftp-connection-card ${!conn.is_active ? 'inactive' : ''}" data-id="${conn.id}">
            <div class="ftp-connection-header">
                <div class="ftp-connection-info">
                    <div class="ftp-connection-name">${escapeHtml(conn.name)}</div>
                    <div class="ftp-connection-host">
                        <i class="fas fa-${conn.protocol === 'sftp' ? 'lock' : 'folder-open'}"></i>
                        <span>${conn.protocol.toUpperCase()}://${escapeHtml(conn.host)}:${conn.port}</span>
                    </div>
                </div>
                <div class="ftp-connection-status ${statusClass}">
                    <span class="status-dot"></span>${statusText}
                </div>
            </div>
            <div class="ftp-connection-details">
                <div class="ftp-detail-item"><div class="ftp-detail-label">Папка</div><div class="ftp-detail-value">${escapeHtml(conn.remote_path)}</div></div>
                <div class="ftp-detail-item"><div class="ftp-detail-label">Интервал</div><div class="ftp-detail-value">${conn.sync_interval} сек</div></div>
                <div class="ftp-detail-item"><div class="ftp-detail-label">Последняя синхронизация</div><div class="ftp-detail-value">
                    ${conn.last_sync ? formatDateUTC(conn.last_sync) : 'Никогда'}
                    ${conn.last_error ? `<br><small class="text-danger">${escapeHtml(conn.last_error.substring(0, 40))}…</small>` : ''}
                </div></div>
                <div class="ftp-detail-item"><div class="ftp-detail-label">Протокол</div><div class="ftp-detail-value">${conn.protocol.toUpperCase()}</div></div>
            </div>
            <div class="ftp-connection-stats">
                <div class="ftp-stat"><div class="ftp-stat-value">${conn.download_count || 0}</div><div class="ftp-stat-label">Файлов</div></div>
                <div class="ftp-stat"><div class="ftp-stat-value">${conn.sync_interval}с</div><div class="ftp-stat-label">Интервал</div></div>
            </div>
            <div class="ftp-connection-actions">
                <button class="btn btn-primary btn-ftp-action btn-sm" type="button" onclick="editConnection(${conn.id})"><i class="fas fa-edit me-1"></i>Изменить</button>
                <button class="btn btn-success btn-ftp-action btn-sm" type="button" onclick="syncConnection(${conn.id})"><i class="fas fa-sync me-1"></i>Синхронизировать</button>
                <button class="btn btn-outline-primary btn-ftp-action btn-sm" type="button" onclick="testConnectionId(${conn.id})"><i class="fas fa-vial me-1"></i>Тест</button>
                <button class="btn btn-danger btn-ftp-action btn-sm" type="button" onclick="deleteConnection(${conn.id})"><i class="fas fa-trash me-1"></i>Удалить</button>
            </div>
        </div>`;
        })
        .join('');
}

function showAddModal() {
    const mt = document.getElementById('modalTitle');
    if (mt) mt.innerHTML = '<i class="fas fa-plus me-2"></i>Добавить FTP подключение';
    document.getElementById('connectionForm')?.reset();
    const cid = document.getElementById('connectionId');
    if (cid) cid.value = '';
    const cp = document.getElementById('connPort');
    if (cp) cp.value = '21';
    const cprot = document.getElementById('connProtocol');
    if (cprot) cprot.value = 'ftp';
    const cs = document.getElementById('connSyncInterval');
    if (cs) cs.value = '300';
    const sf = document.getElementById('connStartFrom');
    if (sf) sf.value = '';
    const lpi = document.getElementById('connLastProcessedInfo');
    if (lpi) lpi.innerHTML = '—';
    const ia = document.getElementById('connIsActive');
    if (ia) ia.checked = true;
    const rp = document.getElementById('connRemotePath');
    if (rp) rp.value = '/';
    const pwd = document.getElementById('connPassword');
    if (pwd) {
        pwd.required = true;
        pwd.value = '';
    }
    const pr = document.getElementById('passwordRequired');
    if (pr) pr.style.display = 'inline';
    const ph = document.getElementById('passwordHint');
    if (ph) ph.style.display = 'none';
    const modalEl = document.getElementById('connectionModal');
    if (modalEl) new bootstrap.Modal(modalEl).show();
}

function editConnection(id) {
    const conn = connections.find((c) => c.id === id);
    if (!conn) {
        if (typeof showAlert === 'function') showAlert('Подключение не найдено', 'danger');
        return;
    }
    const mt = document.getElementById('modalTitle');
    if (mt) mt.innerHTML = '<i class="fas fa-edit me-2"></i>Редактировать FTP подключение';
    document.getElementById('connectionId').value = conn.id;
    document.getElementById('connName').value = conn.name;
    document.getElementById('connHost').value = conn.host;
    document.getElementById('connPort').value = conn.port;
    document.getElementById('connProtocol').value = conn.protocol;
    document.getElementById('connUser').value = conn.username;
    document.getElementById('connPassword').value = '';
    document.getElementById('connPassword').required = false;
    document.getElementById('passwordRequired').style.display = 'none';
    document.getElementById('passwordHint').style.display = 'inline';
    document.getElementById('connRemotePath').value = conn.remote_path;
    document.getElementById('connSyncInterval').value = conn.sync_interval;
    document.getElementById('connStartFrom').value = formatDatetimeLocal(conn.start_from);
    renderLastProcessedInfo(conn);
    document.getElementById('connIsActive').checked = conn.is_active;
    new bootstrap.Modal(document.getElementById('connectionModal')).show();
}

async function saveConnection() {
    const form = document.getElementById('connectionForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const id = document.getElementById('connectionId').value;
    const data = {
        name: document.getElementById('connName').value,
        host: document.getElementById('connHost').value,
        port: parseInt(document.getElementById('connPort').value, 10),
        protocol: document.getElementById('connProtocol').value,
        username: document.getElementById('connUser').value,
        password: document.getElementById('connPassword').value,
        remote_path: document.getElementById('connRemotePath').value,
        sync_interval: parseInt(document.getElementById('connSyncInterval').value, 10),
        is_active: document.getElementById('connIsActive').checked,
    };
    const startFromValue = document.getElementById('connStartFrom').value;
    data.start_from = datetimeLocalValueToUtcIso(startFromValue);
    try {
        const url = id ? `/api/ftp/connections/${id}` : '/api/ftp/connections';
        const method = id ? 'PUT' : 'POST';
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const result = await response.json();
        if (result.success) {
            if (typeof showAlert === 'function') showAlert(result.message || 'Подключение сохранено', 'success');
            bootstrap.Modal.getInstance(document.getElementById('connectionModal')).hide();
            loadConnections();
        } else if (typeof showAlert === 'function') showAlert(result.message || 'Ошибка сохранения', 'danger');
    } catch (error) {
        console.error(error);
        if (typeof showAlert === 'function') showAlert('Ошибка сохранения подключения', 'danger');
    }
}

async function testConnection() {
    const id = document.getElementById('connectionId').value;
    if (!id) {
        if (typeof showAlert === 'function') showAlert('Для тестирования сначала сохраните подключение', 'warning');
        return;
    }
    await testConnectionId(id);
}

async function testConnectionId(id) {
    try {
        if (typeof showAlert === 'function') showAlert('Тестирование подключения...', 'info');
        const response = await fetch(`/api/ftp/connections/${id}/test`, { method: 'POST' });
        const result = await response.json();
        if (typeof showAlert === 'function') {
            showAlert(result.message || (result.success ? 'Успешно' : 'Ошибка'), result.success ? 'success' : 'danger');
        }
    } catch (error) {
        console.error(error);
        if (typeof showAlert === 'function') showAlert('Ошибка тестирования подключения', 'danger');
    }
}

async function syncConnection(id) {
    if (typeof showConfirm !== 'function') {
        if (!confirm('Запустить синхронизацию?')) return;
        await _doSync(id);
        return;
    }
    showConfirm('Запустить синхронизацию сейчас?', async () => {
        await _doSync(id);
    });
}

async function _doSync(id) {
    try {
        const response = await fetch(`/api/ftp/connections/${id}/sync`, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            if (typeof showAlert === 'function') showAlert(result.message || 'Синхронизация запущена', 'success');
            setTimeout(() => loadConnections(), 2000);
        } else if (typeof showAlert === 'function') showAlert(result.message || 'Ошибка', 'danger');
    } catch (error) {
        console.error(error);
        if (typeof showAlert === 'function') showAlert('Ошибка запуска синхронизации', 'danger');
    }
}

async function deleteConnection(id) {
    const run = async () => {
        try {
            const response = await fetch(`/api/ftp/connections/${id}`, { method: 'DELETE' });
            const result = await response.json();
            if (result.success) {
                if (typeof showAlert === 'function') showAlert(result.message || 'Удалено', 'success');
                loadConnections();
            } else if (typeof showAlert === 'function') showAlert(result.message || 'Ошибка удаления', 'danger');
        } catch (error) {
            console.error(error);
            if (typeof showAlert === 'function') showAlert('Ошибка удаления', 'danger');
        }
    };
    if (typeof showConfirm === 'function') showConfirm('Удалить это подключение?', run);
    else if (confirm('Удалить?')) await run();
}

function renderLastProcessedInfo(conn) {
    const infoEl = document.getElementById('connLastProcessedInfo');
    if (!infoEl) return;
    if (!conn || !conn.last_processed_mtime) {
        infoEl.innerHTML = '—';
        return;
    }
    let html = escapeHtml(formatDateUTC(conn.last_processed_mtime));
    if (conn.last_processed_filename) html += `<br><small>${escapeHtml(conn.last_processed_filename)}</small>`;
    infoEl.innerHTML = html;
}

// ——— Ростелеком / StoCRM (из ats.html) ———

function setDirectionCheckboxes(arr) {
    ['incoming', 'outbound', 'internal'].forEach((v) => {
        const id = v === 'incoming' ? 'Incoming' : v === 'outbound' ? 'Outbound' : 'Internal';
        const el = document.getElementById('rostelecomDir' + id);
        if (el) el.checked = !arr || arr.length === 0 || arr.includes(v);
    });
}

function getDirectionCheckboxes() {
    const arr = [];
    if (document.getElementById('rostelecomDirIncoming').checked) arr.push('incoming');
    if (document.getElementById('rostelecomDirOutbound').checked) arr.push('outbound');
    if (document.getElementById('rostelecomDirInternal').checked) arr.push('internal');
    return arr.length === 3 ? null : arr;
}

function loadRostelecomConnections() {
    fetch('/api/ats/rostelecom/connections')
        .then((r) => r.json())
        .then((data) => {
            const list = document.getElementById('rostelecomConnectionsList');
            const empty = document.getElementById('rostelecomEmpty');
            if (!list) return;
            list.innerHTML = '';
            if (!data.length) {
                if (empty) empty.style.display = 'block';
                refreshConnectedSummary();
                return;
            }
            if (empty) empty.style.display = 'none';
            data.forEach((c) => {
                const card = document.createElement('div');
                card.className = 'rostelecom-conn-card';
                const dirLabels = { incoming: 'Входящие', outbound: 'Исходящие', internal: 'Внутр.' };
                const dirStr =
                    c.allowed_directions && c.allowed_directions.length
                        ? c.allowed_directions.map((d) => dirLabels[d] || d).join(', ')
                        : 'Все';
                const startFromStr = c.start_from ? new Date(c.start_from).toLocaleString('ru-RU') : 'Не задано';
                const lastSyncStr = c.last_sync ? new Date(c.last_sync).toLocaleString('ru-RU') : '—';
                card.innerHTML = `
                    <div>
                        <strong>${escapeHtml(c.name)}</strong> ${c.is_active ? '<span class="badge bg-success ms-1">Активно</span>' : '<span class="badge bg-secondary ms-1">Неактивно</span>'}
                        <div class="small text-muted">${escapeHtml(c.api_url)} • ${escapeHtml(c.client_id)}</div>
                        <div class="small">Направления: ${escapeHtml(dirStr)}</div>
                        <div class="small">С даты: ${escapeHtml(startFromStr)}</div>
                        <div class="small">Синхронизация: ${escapeHtml(lastSyncStr)}</div>
                        <div class="small">Интервал: ${c.sync_interval_minutes || 60} мин</div>
                        ${c.last_error ? '<div class="small text-danger">Ошибка: ' + escapeHtml(c.last_error) + '</div>' : ''}
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-sm btn-success" type="button" onclick="syncRostelecomConnection(${c.id})"><i class="fas fa-sync me-1"></i>Синхр.</button>
                        <button class="btn btn-sm btn-outline-primary" type="button" onclick="testRostelecomConnection(${c.id})"><i class="fas fa-vial me-1"></i>Проверить</button>
                        <button class="btn btn-sm btn-outline-primary" type="button" onclick="editRostelecomConnection(${c.id})"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-sm btn-outline-danger" type="button" onclick="deleteRostelecomConnection(${c.id})"><i class="fas fa-trash"></i></button>
                    </div>`;
                list.appendChild(card);
            });
            refreshConnectedSummary();
        })
        .catch((e) => console.error(e));
}

function showRostelecomModal(id) {
    document.getElementById('rostelecomConnId').value = id || '';
    document.getElementById('rostelecomName').value = 'Ростелеком';
    document.getElementById('rostelecomApiUrl').value = 'https://api.cloudpbx.rt.ru';
    document.getElementById('rostelecomClientId').value = '';
    document.getElementById('rostelecomSignKey').value = '';
    document.getElementById('rostelecomStartFrom').value = '';
    document.getElementById('rostelecomSyncInterval').value = 60;
    document.getElementById('rostelecomActive').checked = true;
    setDirectionCheckboxes(null);
    const modalEl = document.getElementById('rostelecomModal');
    if (id) {
        fetch('/api/ats/rostelecom/connections')
            .then((r) => r.json())
            .then((list) => {
                const c = list.find((x) => x.id === parseInt(id, 10));
                if (c) {
                    document.getElementById('rostelecomName').value = c.name;
                    document.getElementById('rostelecomApiUrl').value = c.api_url || 'https://api.cloudpbx.rt.ru';
                    document.getElementById('rostelecomStartFrom').value = formatDatetimeLocal(c.start_from);
                    document.getElementById('rostelecomSyncInterval').value = c.sync_interval_minutes || 60;
                    setDirectionCheckboxes(c.allowed_directions);
                    new bootstrap.Modal(modalEl).show();
                } else if (typeof showAlert === 'function') {
                    showAlert('Подключение не найдено', 'danger');
                }
            })
            .catch((e) => {
                console.error(e);
                if (typeof showAlert === 'function') showAlert('Не удалось загрузить подключение', 'danger');
            });
        return;
    }
    new bootstrap.Modal(modalEl).show();
}

function editRostelecomConnection(id) {
    const modalEl = document.getElementById('rostelecomModal');
    fetch('/api/ats/rostelecom/connections')
        .then((r) => r.json())
        .then((list) => {
            const c = list.find((x) => x.id === parseInt(id, 10));
            if (!c) {
                if (typeof showAlert === 'function') showAlert('Подключение не найдено', 'danger');
                return;
            }
            document.getElementById('rostelecomConnId').value = id;
            document.getElementById('rostelecomName').value = c.name;
            document.getElementById('rostelecomApiUrl').value = c.api_url || 'https://api.cloudpbx.rt.ru';
            document.getElementById('rostelecomStartFrom').value = formatDatetimeLocal(c.start_from);
            document.getElementById('rostelecomSyncInterval').value = c.sync_interval_minutes || 60;
            setDirectionCheckboxes(c.allowed_directions);
            document.getElementById('rostelecomClientId').value = '';
            document.getElementById('rostelecomSignKey').value = '';
            new bootstrap.Modal(modalEl).show();
        })
        .catch((e) => {
            console.error(e);
            if (typeof showAlert === 'function') showAlert('Не удалось загрузить подключение', 'danger');
        });
}

function saveRostelecomConnection() {
    const id = document.getElementById('rostelecomConnId').value;
    const startFromVal = document.getElementById('rostelecomStartFrom').value;
    const payload = {
        name: document.getElementById('rostelecomName').value,
        api_url: document.getElementById('rostelecomApiUrl').value,
        client_id: document.getElementById('rostelecomClientId').value,
        sign_key: document.getElementById('rostelecomSignKey').value,
        is_active: document.getElementById('rostelecomActive').checked,
        allowed_directions: getDirectionCheckboxes(),
        start_from: datetimeLocalValueToUtcIso(startFromVal),
        sync_interval_minutes: parseInt(document.getElementById('rostelecomSyncInterval').value, 10) || 60,
    };
    if (!payload.api_url) {
        alert('Укажите адрес API');
        return;
    }
    if (!id && (!payload.client_id || !payload.sign_key)) {
        alert('При создании укажите код идентификации и ключ подписи');
        return;
    }
    const url = id ? `/api/ats/rostelecom/connections/${id}` : '/api/ats/rostelecom/connections';
    const method = id ? 'PUT' : 'POST';
    let body = payload;
    if (id) {
        body = { ...payload };
        if (!String(body.client_id || '').trim()) delete body.client_id;
        if (!String(body.sign_key || '').trim()) delete body.sign_key;
    }
    fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.success) {
                bootstrap.Modal.getInstance(document.getElementById('rostelecomModal')).hide();
                loadRostelecomConnections();
                if (typeof showToast === 'function') showToast(data.message || 'Сохранено', 'success');
            } else alert(data.message || 'Ошибка');
        })
        .catch((e) => alert('Ошибка: ' + e));
}

async function syncRostelecomConnection(id) {
    try {
        if (typeof showToast === 'function') showToast('Запуск синхронизации...', 'info');
        const r = await fetch(`/api/ats/rostelecom/connections/${id}/sync`, { method: 'POST' });
        const data = await r.json();
        if (data.success) {
            if (typeof showToast === 'function') showToast(data.message || 'OK', 'success');
            loadRostelecomConnections();
        } else if (typeof showToast === 'function') showToast(data.message || 'Ошибка', 'danger');
        else alert(data.message || 'Ошибка');
    } catch (e) {
        alert('Ошибка: ' + e);
    }
}

async function testRostelecomConnection(id) {
    try {
        if (typeof showToast === 'function') showToast('Проверка...', 'info');
        const r = await fetch(`/api/ats/rostelecom/connections/${id}/test`, { method: 'POST' });
        const data = await r.json();
        if (typeof showToast === 'function')
            showToast(data.message || (data.success ? 'OK' : 'Ошибка'), data.success ? 'success' : 'danger');
        else alert(data.message);
    } catch (e) {
        alert(e);
    }
}

function deleteRostelecomConnection(id) {
    if (!confirm('Удалить это подключение Ростелеком?')) return;
    fetch(`/api/ats/rostelecom/connections/${id}`, { method: 'DELETE' })
        .then((r) => r.json())
        .then((data) => {
            if (data.success) {
                loadRostelecomConnections();
                if (typeof showToast === 'function') showToast(data.message || 'Удалено', 'success');
                else if (typeof showAlert === 'function') showAlert(data.message || 'Удалено', 'success');
            } else {
                const msg = data.message || 'Ошибка удаления';
                if (typeof showToast === 'function') showToast(msg, 'danger');
                else if (typeof showAlert === 'function') showAlert(msg, 'danger');
                else alert(msg);
            }
        })
        .catch((e) => {
            console.error(e);
            if (typeof showToast === 'function') showToast('Ошибка удаления', 'danger');
            else if (typeof showAlert === 'function') showAlert('Ошибка удаления', 'danger');
            else alert('Ошибка удаления');
        });
}

function loadStocrmConnections() {
    fetch('/api/ats/stocrm/connections')
        .then((r) => r.json())
        .then((data) => {
            const list = document.getElementById('stocrmConnectionsList');
            const empty = document.getElementById('stocrmEmpty');
            if (!list) return;
            list.innerHTML = '';
            if (!Array.isArray(data) || !data.length) {
                if (empty) empty.style.display = 'block';
                refreshConnectedSummary();
                return;
            }
            if (empty) empty.style.display = 'none';
            data.forEach((c) => {
                const card = document.createElement('div');
                card.className = 'stocrm-conn-card';
                const dirLabels = { IN: 'Входящие', OUT: 'Исходящие' };
                const dirStr =
                    c.allowed_directions && c.allowed_directions.length
                        ? c.allowed_directions.map((d) => dirLabels[d] || d).join(', ')
                        : 'Все';
                const startFromStr = c.start_from ? new Date(c.start_from).toLocaleString('ru-RU') : 'Последние 7 дней';
                const lastSyncStr = c.last_sync ? new Date(c.last_sync).toLocaleString('ru-RU') : '—';
                card.innerHTML = `
                    <div>
                        <strong>${escapeHtml(c.name)}</strong> ${c.is_active ? '<span class="badge bg-success ms-1">Активно</span>' : '<span class="badge bg-secondary ms-1">Неактивно</span>'}
                        <div class="small text-muted">${escapeHtml(c.domain)}.stocrm.ru</div>
                        <div class="small">Направления: ${escapeHtml(dirStr)}</div>
                        <div class="small">С даты: ${escapeHtml(startFromStr)}</div>
                        <div class="small">Последняя синхр.: ${escapeHtml(lastSyncStr)}</div>
                        <div class="small">Интервал: ${c.sync_interval_minutes || 60} мин</div>
                        ${c.last_error ? '<div class="small text-danger">Ошибка: ' + escapeHtml(c.last_error) + '</div>' : ''}
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-sm btn-success" type="button" onclick="syncStocrmConnection(${c.id})"><i class="fas fa-sync me-1"></i>Синхр.</button>
                        <button class="btn btn-sm btn-outline-primary" type="button" onclick="testStocrmConnection(${c.id})"><i class="fas fa-vial me-1"></i>Проверить</button>
                        <button class="btn btn-sm btn-outline-primary" type="button" onclick="editStocrmConnection(${c.id})"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-sm btn-outline-danger" type="button" onclick="deleteStocrmConnection(${c.id})"><i class="fas fa-trash"></i></button>
                    </div>`;
                list.appendChild(card);
            });
            refreshConnectedSummary();
        })
        .catch((e) => console.error(e));
}

function setStocrmDirCheckboxes(arr) {
    document.getElementById('stocrmDirIn').checked = !arr || arr.length === 0 || arr.includes('IN');
    document.getElementById('stocrmDirOut').checked = !arr || arr.length === 0 || arr.includes('OUT');
}

function getStocrmDirCheckboxes() {
    const arr = [];
    if (document.getElementById('stocrmDirIn').checked) arr.push('IN');
    if (document.getElementById('stocrmDirOut').checked) arr.push('OUT');
    return arr.length === 2 ? null : arr;
}

function showStocrmModal() {
    document.getElementById('stocrmConnId').value = '';
    document.getElementById('stocrmName').value = 'StoCRM';
    document.getElementById('stocrmDomain').value = '';
    document.getElementById('stocrmSid').value = '';
    document.getElementById('stocrmStartFrom').value = '';
    document.getElementById('stocrmSyncInterval').value = 60;
    document.getElementById('stocrmActive').checked = true;
    setStocrmDirCheckboxes(null);
    new bootstrap.Modal(document.getElementById('stocrmModal')).show();
}

function editStocrmConnection(id) {
    const modalEl = document.getElementById('stocrmModal');
    fetch('/api/ats/stocrm/connections')
        .then((r) => {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then((list) => {
            if (!Array.isArray(list)) {
                const msg = 'Некорректный ответ сервера';
                if (typeof showToast === 'function') showToast(msg, 'danger');
                else if (typeof showAlert === 'function') showAlert(msg, 'danger');
                else alert(msg);
                return;
            }
            const c = list.find((x) => x.id === parseInt(id, 10));
            if (!c) {
                const msg = 'Подключение не найдено';
                if (typeof showToast === 'function') showToast(msg, 'danger');
                else if (typeof showAlert === 'function') showAlert(msg, 'danger');
                else alert(msg);
                return;
            }
            document.getElementById('stocrmConnId').value = c.id;
            document.getElementById('stocrmName').value = c.name;
            document.getElementById('stocrmDomain').value = c.domain;
            document.getElementById('stocrmSid').value = '';
            document.getElementById('stocrmStartFrom').value = formatDatetimeLocal(c.start_from);
            document.getElementById('stocrmSyncInterval').value = c.sync_interval_minutes || 60;
            document.getElementById('stocrmActive').checked = c.is_active;
            setStocrmDirCheckboxes(c.allowed_directions);
            new bootstrap.Modal(modalEl).show();
        })
        .catch((e) => {
            console.error(e);
            const msg = 'Не удалось загрузить подключение';
            if (typeof showToast === 'function') showToast(msg, 'danger');
            else if (typeof showAlert === 'function') showAlert(msg, 'danger');
            else alert(msg);
        });
}

function saveStocrmConnection() {
    const id = document.getElementById('stocrmConnId').value;
    const domain = document.getElementById('stocrmDomain').value.trim();
    const sid = document.getElementById('stocrmSid').value.trim();
    const startFromVal = document.getElementById('stocrmStartFrom').value;
    if (!domain) {
        alert('Укажите поддомен');
        return;
    }
    if (!id && !sid) {
        alert('При создании укажите SID-ключ');
        return;
    }
    const payload = {
        name: document.getElementById('stocrmName').value,
        domain,
        is_active: document.getElementById('stocrmActive').checked,
        allowed_directions: getStocrmDirCheckboxes(),
        start_from: datetimeLocalValueToUtcIso(startFromVal),
        sync_interval_minutes: parseInt(document.getElementById('stocrmSyncInterval').value, 10) || 60,
    };
    if (sid) payload.sid = sid;
    const url = id ? `/api/ats/stocrm/connections/${id}` : '/api/ats/stocrm/connections';
    const method = id ? 'PUT' : 'POST';
    fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then((r) => r.json())
        .then((data) => {
            if (data.success) {
                bootstrap.Modal.getInstance(document.getElementById('stocrmModal')).hide();
                loadStocrmConnections();
                if (typeof showToast === 'function') showToast(data.message || 'Сохранено', 'success');
            } else alert(data.message || 'Ошибка');
        })
        .catch((e) => alert('Ошибка: ' + e));
}

async function syncStocrmConnection(id) {
    try {
        if (typeof showToast === 'function') showToast('Запуск синхронизации StoCRM...', 'info');
        const r = await fetch(`/api/ats/stocrm/connections/${id}/sync`, { method: 'POST' });
        const data = await r.json();
        if (data.success) {
            if (typeof showToast === 'function') showToast(data.message || 'OK', 'success');
            setTimeout(loadStocrmConnections, 3000);
        } else if (typeof showToast === 'function') showToast(data.message || 'Ошибка', 'danger');
    } catch (e) {
        alert(e);
    }
}

async function testStocrmConnection(id) {
    try {
        if (typeof showToast === 'function') showToast('Проверка StoCRM...', 'info');
        const r = await fetch(`/api/ats/stocrm/connections/${id}/test`, { method: 'POST' });
        const data = await r.json();
        if (typeof showToast === 'function')
            showToast(data.message || (data.success ? 'OK' : 'Ошибка'), data.success ? 'success' : 'danger');
        else alert(data.message);
    } catch (e) {
        alert(e);
    }
}

function deleteStocrmConnection(id) {
    if (!confirm('Удалить это подключение StoCRM?')) return;
    fetch(`/api/ats/stocrm/connections/${id}`, { method: 'DELETE' })
        .then((r) => r.json())
        .then((data) => {
            if (data.success) {
                loadStocrmConnections();
                if (typeof showToast === 'function') showToast(data.message || 'Удалено', 'success');
                else if (typeof showAlert === 'function') showAlert(data.message || 'Удалено', 'success');
            } else {
                const msg = data.message || 'Ошибка удаления';
                if (typeof showToast === 'function') showToast(msg, 'danger');
                else if (typeof showAlert === 'function') showAlert(msg, 'danger');
                else alert(msg);
            }
        })
        .catch((e) => {
            console.error(e);
            if (typeof showToast === 'function') showToast('Ошибка удаления', 'danger');
            else if (typeof showAlert === 'function') showAlert('Ошибка удаления', 'danger');
            else alert('Ошибка удаления');
        });
}

// ——— Кастомный API ———

function customApiGatherPayload() {
    const method = (document.getElementById('customApiMethod') || {}).value || 'GET';
    let jsonBody = null;
    const jbRaw = (document.getElementById('customApiJsonBody') || {}).value;
    if (method === 'POST' && jbRaw && String(jbRaw).trim()) {
        try {
            jsonBody = JSON.parse(String(jbRaw).trim());
        } catch (e) {
            jsonBody = null;
        }
    }
    const request_config = {
        url: (document.getElementById('customApiUrl') || {}).value.trim(),
        method,
        headers: {},
        params: {},
        json_body: jsonBody,
        timeout_sec: parseInt(document.getElementById('customApiTimeout').value, 10) || 30,
        verify_ssl: document.getElementById('customApiVerifySsl').checked,
        auth_type: document.getElementById('customApiAuthType').value,
        auth_token: (document.getElementById('customApiAuthToken') || {}).value,
        auth_username: (document.getElementById('customApiAuthUser') || {}).value,
        auth_password: (document.getElementById('customApiAuthPass') || {}).value,
        auth_header_name: (document.getElementById('customApiHdrName') || {}).value.trim(),
        auth_header_value: (document.getElementById('customApiHdrVal') || {}).value,
    };
    const mapping_config = {
        items_path: (document.getElementById('customApiItemsPath') || {}).value.trim(),
        record_url_field: (document.getElementById('customApiRecordField') || {}).value.trim() || 'record_url',
        station_field: (document.getElementById('customApiStationField') || {}).value.trim() || 'station',
        original_filename_field: (document.getElementById('customApiOrigField') || {}).value.trim() || 'filename',
        external_id_field: (document.getElementById('customApiExtIdField') || {}).value.trim(),
        timestamp_field: (document.getElementById('customApiTsField') || {}).value.trim(),
        recording_base_url: (document.getElementById('customApiRecordingBaseUrl') || {}).value.trim(),
    };
    return {
        name: (document.getElementById('customApiName') || {}).value,
        is_active: document.getElementById('customApiActive').checked,
        request_config,
        mapping_config,
        start_from: datetimeLocalValueToUtcIso((document.getElementById('customApiStartFrom') || {}).value),
        sync_interval_minutes: parseInt(document.getElementById('customApiSyncInterval').value, 10) || 60,
    };
}

function customApiUpdateAuthPanels() {
    const t = document.getElementById('customApiAuthType').value;
    document.getElementById('customApiAuthBearer').classList.toggle('d-none', t !== 'bearer');
    document.getElementById('customApiAuthBasic').classList.toggle('d-none', t !== 'basic');
    document.getElementById('customApiAuthHeader').classList.toggle('d-none', t !== 'header');
}

function loadCustomApiConnections() {
    fetch('/api/ats/custom_api/connections')
        .then((r) => r.json())
        .then((data) => {
            const list = document.getElementById('customApiConnectionsList');
            const empty = document.getElementById('customApiEmpty');
            if (!list) return;
            list.innerHTML = '';
            if (!Array.isArray(data) || !data.length) {
                if (empty) empty.style.display = 'block';
                refreshConnectedSummary();
                return;
            }
            if (empty) empty.style.display = 'none';
            data.forEach((c) => {
                const card = document.createElement('div');
                card.className = 'stocrm-conn-card';
                const url = (c.request_config && c.request_config.url) || '';
                const lastSyncStr = c.last_sync ? new Date(c.last_sync).toLocaleString('ru-RU') : '—';
                card.innerHTML = `
                    <div>
                        <strong>${escapeHtml(c.name)}</strong> ${c.is_active ? '<span class="badge bg-success ms-1">Активно</span>' : '<span class="badge bg-secondary ms-1">Неактивно</span>'}
                        <div class="small text-muted">${escapeHtml(url)}</div>
                        <div class="small">Последняя синхр.: ${escapeHtml(lastSyncStr)}</div>
                        <div class="small">Интервал: ${c.sync_interval_minutes || 60} мин</div>
                        ${c.last_error ? '<div class="small text-danger">Ошибка: ' + escapeHtml(c.last_error) + '</div>' : ''}
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-sm btn-success" type="button" onclick="syncCustomApiConnection(${c.id})"><i class="fas fa-sync me-1"></i>Синхр.</button>
                        <button class="btn btn-sm btn-outline-primary" type="button" onclick="testCustomApiConnection(${c.id})"><i class="fas fa-vial me-1"></i>Разбор JSON</button>
                        <button class="btn btn-sm btn-outline-primary" type="button" onclick="editCustomApiConnection(${c.id})"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-sm btn-outline-danger" type="button" onclick="deleteCustomApiConnection(${c.id})"><i class="fas fa-trash"></i></button>
                    </div>`;
                list.appendChild(card);
            });
            refreshConnectedSummary();
        })
        .catch((e) => console.error(e));
}

function showCustomApiModal() {
    document.getElementById('customApiConnId').value = '';
    document.getElementById('customApiName').value = 'Кастомный API';
    document.getElementById('customApiUrl').value = '';
    document.getElementById('customApiMethod').value = 'GET';
    document.getElementById('customApiJsonBody').value = '';
    document.getElementById('customApiJsonBodyRow').classList.add('d-none');
    document.getElementById('customApiTimeout').value = 30;
    document.getElementById('customApiVerifySsl').checked = true;
    document.getElementById('customApiItemsPath').value = '';
    document.getElementById('customApiRecordField').value = 'record_url';
    document.getElementById('customApiStationField').value = 'station';
    document.getElementById('customApiOrigField').value = 'filename';
    document.getElementById('customApiRecordingBaseUrl').value = '';
    document.getElementById('customApiExtIdField').value = '';
    document.getElementById('customApiTsField').value = '';
    document.getElementById('customApiAuthType').value = 'none';
    document.getElementById('customApiAuthToken').value = '';
    document.getElementById('customApiAuthUser').value = '';
    document.getElementById('customApiAuthPass').value = '';
    document.getElementById('customApiHdrName').value = '';
    document.getElementById('customApiHdrVal').value = '';
    document.getElementById('customApiStartFrom').value = '';
    document.getElementById('customApiSyncInterval').value = 60;
    document.getElementById('customApiActive').checked = true;
    customApiUpdateAuthPanels();
    new bootstrap.Modal(document.getElementById('customApiModal')).show();
}

function editCustomApiConnection(id) {
    fetch('/api/ats/custom_api/connections')
        .then((r) => r.json())
        .then((list) => {
            if (!Array.isArray(list)) return;
            const c = list.find((x) => x.id === parseInt(id, 10));
            if (!c) {
                if (typeof showToast === 'function') showToast('Подключение не найдено', 'danger');
                return;
            }
            document.getElementById('customApiConnId').value = c.id;
            document.getElementById('customApiName').value = c.name;
            const req = c.request_config || {};
            document.getElementById('customApiUrl').value = req.url || '';
            document.getElementById('customApiMethod').value = (req.method || 'GET').toUpperCase() === 'POST' ? 'POST' : 'GET';
            const jb = req.json_body;
            document.getElementById('customApiJsonBody').value = jb ? (typeof jb === 'string' ? jb : JSON.stringify(jb, null, 0)) : '';
            document.getElementById('customApiJsonBodyRow').classList.toggle('d-none', document.getElementById('customApiMethod').value !== 'POST');
            document.getElementById('customApiTimeout').value = req.timeout_sec || 30;
            document.getElementById('customApiVerifySsl').checked = req.verify_ssl !== false;
            const map = c.mapping_config || {};
            document.getElementById('customApiItemsPath').value = map.items_path || '';
            document.getElementById('customApiRecordField').value = map.record_url_field || 'record_url';
            document.getElementById('customApiStationField').value = map.station_field || 'station';
            document.getElementById('customApiOrigField').value = map.original_filename_field || 'filename';
            document.getElementById('customApiRecordingBaseUrl').value = map.recording_base_url || '';
            document.getElementById('customApiExtIdField').value = map.external_id_field || '';
            document.getElementById('customApiTsField').value = map.timestamp_field || '';
            document.getElementById('customApiAuthType').value = req.auth_type || 'none';
            document.getElementById('customApiAuthToken').value = '';
            document.getElementById('customApiAuthUser').value = req.auth_username || '';
            document.getElementById('customApiAuthPass').value = '';
            document.getElementById('customApiHdrName').value = req.auth_header_name || '';
            document.getElementById('customApiHdrVal').value = '';
            document.getElementById('customApiStartFrom').value = formatDatetimeLocal(c.start_from);
            document.getElementById('customApiSyncInterval').value = c.sync_interval_minutes || 60;
            document.getElementById('customApiActive').checked = c.is_active;
            customApiUpdateAuthPanels();
            new bootstrap.Modal(document.getElementById('customApiModal')).show();
        })
        .catch((e) => console.error(e));
}

function saveCustomApiConnection() {
    const id = document.getElementById('customApiConnId').value;
    const payload = customApiGatherPayload();
    if (!payload.request_config.url) {
        alert('Укажите URL');
        return;
    }
    const url = id ? `/api/ats/custom_api/connections/${id}` : '/api/ats/custom_api/connections';
    const method = id ? 'PUT' : 'POST';
    const body =
        id
            ? {
                  ...payload,
                  request_config: {
                      ...payload.request_config,
                      auth_token: document.getElementById('customApiAuthToken').value || undefined,
                      auth_password: document.getElementById('customApiAuthPass').value || undefined,
                      auth_header_value: document.getElementById('customApiHdrVal').value || undefined,
                  },
              }
            : payload;
    if (id) {
        if (!String(body.request_config.auth_token || '').trim()) delete body.request_config.auth_token;
        if (!String(body.request_config.auth_password || '').trim()) delete body.request_config.auth_password;
        if (!String(body.request_config.auth_header_value || '').trim()) delete body.request_config.auth_header_value;
    }
    fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.success) {
                bootstrap.Modal.getInstance(document.getElementById('customApiModal')).hide();
                loadCustomApiConnections();
                if (typeof showToast === 'function') showToast(data.message || 'Сохранено', 'success');
            } else alert(data.message || 'Ошибка');
        })
        .catch((e) => alert('Ошибка: ' + e));
}

async function syncCustomApiConnection(id) {
    try {
        if (typeof showToast === 'function') showToast('Запуск синхронизации...', 'info');
        const r = await fetch(`/api/ats/custom_api/connections/${id}/sync`, { method: 'POST' });
        const data = await r.json();
        if (data.success) {
            if (typeof showToast === 'function') showToast(data.message || 'OK', 'success');
            setTimeout(loadCustomApiConnections, 3000);
        } else if (typeof showToast === 'function') showToast(data.message || 'Ошибка', 'danger');
    } catch (e) {
        alert(e);
    }
}

async function testCustomApiConnection(id) {
    try {
        if (typeof showToast === 'function') showToast('Проверка разбора JSON...', 'info');
        const r = await fetch(`/api/ats/custom_api/connections/${id}/test`, { method: 'POST' });
        const data = await r.json();
        const msg = data.message || (data.success ? `OK, записей: ${data.total}` : 'Ошибка');
        if (typeof showToast === 'function') showToast(msg, data.success ? 'success' : 'danger');
        else alert(msg);
        if (data.success && data.sample) console.log('custom_api sample', data.sample);
    } catch (e) {
        alert(e);
    }
}

function deleteCustomApiConnection(id) {
    if (!confirm('Удалить это подключение Кастомный API?')) return;
    fetch(`/api/ats/custom_api/connections/${id}`, { method: 'DELETE' })
        .then((r) => r.json())
        .then((data) => {
            if (data.success) {
                loadCustomApiConnections();
                if (typeof showToast === 'function') showToast('Удалено', 'success');
            } else alert(data.message || 'Ошибка');
        })
        .catch((e) => alert(e));
}

(function bindCustomApiModalHelpers() {
    document.addEventListener('DOMContentLoaded', function () {
        const m = document.getElementById('customApiMethod');
        if (m) {
            m.addEventListener('change', function () {
                const row = document.getElementById('customApiJsonBodyRow');
                if (row) row.classList.toggle('d-none', this.value !== 'POST');
            });
        }
        const at = document.getElementById('customApiAuthType');
        if (at) at.addEventListener('change', customApiUpdateAuthPanels);
    });
})();
