// ===== Modern JavaScript Utilities for Call Analyzer =====

// ===== Sidebar Toggle for Mobile =====
function initSidebar() {
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.querySelector('.sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    
    if (!sidebarToggle || !sidebar) return;
    
    // Toggle sidebar
    sidebarToggle.addEventListener('click', function(e) {
        e.preventDefault();
        sidebar.classList.toggle('show');
        if (sidebarOverlay) {
            sidebarOverlay.classList.toggle('show');
        }
        // Prevent body scroll when sidebar is open
        document.body.style.overflow = sidebar.classList.contains('show') ? 'hidden' : '';
    });
    
    // Close sidebar when clicking overlay
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', function() {
            closeSidebar();
        });
    }
    
    // Close sidebar when clicking on navigation links
    document.querySelectorAll('.sidebar .nav-link').forEach(link => {
        link.addEventListener('click', function() {
            if (window.innerWidth < 992) {
                closeSidebar();
            }
        });
    });
    
    // Close sidebar on window resize
    window.addEventListener('resize', function() {
        if (window.innerWidth >= 992) {
            closeSidebar();
        }
    });
    
    // Close sidebar on ESC key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && sidebar.classList.contains('show')) {
            closeSidebar();
        }
    });
}

function closeSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    
    if (sidebar) {
        sidebar.classList.remove('show');
    }
    if (sidebarOverlay) {
        sidebarOverlay.classList.remove('show');
    }
    document.body.style.overflow = '';
}

// ===== Password Toggle =====
function togglePassword(inputId, buttonId) {
    const input = document.getElementById(inputId);
    const button = document.getElementById(buttonId);
    const icon = button.querySelector('i');
    
    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.remove('fa-eye');
        icon.classList.add('fa-eye-slash');
        button.title = 'Скрыть пароль';
    } else {
        input.type = 'password';
        icon.classList.remove('fa-eye-slash');
        icon.classList.add('fa-eye');
        button.title = 'Показать пароль';
    }
}

// ===== Alert/Toast System =====
function showAlert(message, type = 'info', duration = 5000) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 1070; min-width: 300px; max-width: 500px;';
    
    let iconClass = 'fa-info-circle';
    if (type === 'success') iconClass = 'fa-check-circle';
    if (type === 'danger') iconClass = 'fa-exclamation-circle';
    if (type === 'warning') iconClass = 'fa-exclamation-triangle';
    
    alertDiv.innerHTML = `
        <div class="d-flex align-items-center gap-3">
            <i class="fas ${iconClass} fs-5"></i>
            <div class="flex-grow-1">${message}</div>
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;
    
    // Add to toast container or create one
    let toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        toastContainer.id = 'toastContainer';
        document.body.appendChild(toastContainer);
    }
    
    toastContainer.appendChild(alertDiv);
    
    // Auto close after duration
    setTimeout(() => {
        const alert = bootstrap.Alert.getOrCreateInstance(alertDiv);
        if (alert) {
            alert.close();
        }
    }, duration);
    
    return alertDiv;
}

// ===== Confirmation Modal =====
function showConfirm(message, onConfirm, onCancel = null) {
    const modalId = 'confirmModal_' + Date.now();
    
    const modalHtml = `
        <div class="modal fade" id="${modalId}" tabindex="-1" aria-labelledby="${modalId}Label" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="${modalId}Label">
                            <i class="fas fa-question-circle me-2"></i>Подтверждение
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <p class="mb-0 fs-6">${message}</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-light" data-bs-dismiss="modal">
                            <i class="fas fa-times me-2"></i>Отмена
                        </button>
                        <button type="button" class="btn btn-primary" id="${modalId}Confirm">
                            <i class="fas fa-check me-2"></i>Подтвердить
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    const modalElement = document.getElementById(modalId);
    const modal = new bootstrap.Modal(modalElement);
    modal.show();
    
    const confirmBtn = document.getElementById(`${modalId}Confirm`);
    confirmBtn.addEventListener('click', () => {
        if (onConfirm) onConfirm();
        modal.hide();
    });
    
    modalElement.addEventListener('hidden.bs.modal', () => {
        modalElement.remove();
        if (onCancel) onCancel();
    });
}

// ===== Date Formatting =====
function formatDate(dateString, options = {}) {
    const date = new Date(dateString);
    const defaultOptions = {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    };
    return date.toLocaleDateString('ru-RU', { ...defaultOptions, ...options });
}

function formatRelativeTime(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffSecs < 60) return 'только что';
    if (diffMins < 60) return `${diffMins} мин. назад`;
    if (diffHours < 24) return `${diffHours} ч. назад`;
    if (diffDays < 7) return `${diffDays} дн. назад`;
    return formatDate(dateString);
}

function formatTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

// ===== Utility Functions =====
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showAlert('Скопировано в буфер обмена', 'success');
        }).catch(err => {
            fallbackCopyToClipboard(text);
        });
    } else {
        fallbackCopyToClipboard(text);
    }
}

function fallbackCopyToClipboard(text) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        const successful = document.execCommand('copy');
        if (successful) {
            showAlert('Скопировано в буфер обмена', 'success');
        } else {
            showAlert('Ошибка копирования', 'danger');
        }
    } catch (err) {
        showAlert('Ошибка копирования', 'danger');
        console.error('Ошибка копирования:', err);
    }
    
    document.body.removeChild(textArea);
}

function formatNumber(num) {
    return new Intl.NumberFormat('ru-RU').format(num);
}

function formatPercent(value, decimals = 1) {
    return value.toFixed(decimals) + '%';
}

function safeGet(obj, path, defaultValue = null) {
    return path.split('.').reduce((acc, part) => acc && acc[part], obj) || defaultValue;
}

function isValidEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function isValidUrl(string) {
    try {
        new URL(string);
        return true;
    } catch (_) {
        return false;
    }
}

function generateId() {
    return 'id_' + Math.random().toString(36).substr(2, 9);
}

// ===== Loading States =====
function showLoading(containerId, message = 'Загрузка...') {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="text-center py-5">
                <div class="spinner-border text-primary mb-3" role="status" style="width: 3rem; height: 3rem;">
                    <span class="visually-hidden">Загрузка...</span>
                </div>
                <p class="text-muted mb-0">${message}</p>
            </div>
        `;
    }
}

function showError(containerId, message, actionText = null, actionCallback = null) {
    const container = document.getElementById(containerId);
    if (container) {
        let actionButton = '';
        if (actionText && actionCallback) {
            actionButton = `<button class="btn btn-primary btn-sm mt-3" onclick="${actionCallback}">${actionText}</button>`;
        }
        
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-exclamation-triangle text-danger mb-3" style="font-size: 3rem;"></i>
                <p class="text-danger mb-0">${message}</p>
                ${actionButton}
            </div>
        `;
    }
}

function showEmptyState(containerId, icon, title, description, actionText = null, actionCallback = null) {
    const container = document.getElementById(containerId);
    if (container) {
        let actionButton = '';
        if (actionText && actionCallback) {
            actionButton = `<button class="btn btn-primary mt-3" onclick="${actionCallback}">${actionText}</button>`;
        }
        
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-${icon}"></i>
                <h5>${title}</h5>
                <p>${description}</p>
                ${actionButton}
            </div>
        `;
    }
}

// ===== API Utilities =====
function fetchWithTimeout(url, options = {}, timeout = 30000) {
    return Promise.race([
        fetch(url, options),
        new Promise((_, reject) =>
            setTimeout(() => reject(new Error('Timeout')), timeout)
        )
    ]);
}

async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    
    try {
        const response = await fetchWithTimeout(url, { ...defaultOptions, ...options });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API request error:', error);
        throw error;
    }
}

// ===== Form Utilities =====
function serializeForm(form) {
    const formData = new FormData(form);
    const data = {};
    for (let [key, value] of formData.entries()) {
        data[key] = value;
    }
    return data;
}

function validateForm(form) {
    const inputs = form.querySelectorAll('input[required], select[required], textarea[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            input.classList.add('is-invalid');
            isValid = false;
        } else {
            input.classList.remove('is-invalid');
        }
    });
    
    return isValid;
}

// ===== Progress Bar =====
function updateProgress(progressId, value, text = null) {
    const progressBar = document.getElementById(progressId);
    if (progressBar) {
        progressBar.style.width = value + '%';
        progressBar.setAttribute('aria-valuenow', value);
        
        if (text) {
            const progressText = progressBar.parentElement.querySelector('.progress-text-custom');
            if (progressText) {
                progressText.textContent = text;
            }
        }
    }
}

// ===== Table Utilities =====
function sortTable(tableId, column, direction = 'asc') {
    const table = document.getElementById(tableId);
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    rows.sort((a, b) => {
        const aVal = a.cells[column].textContent.trim();
        const bVal = b.cells[column].textContent.trim();
        
        if (direction === 'asc') {
            return aVal.localeCompare(bVal);
        } else {
            return bVal.localeCompare(aVal);
        }
    });
    
    rows.forEach(row => tbody.appendChild(row));
}

function filterTable(tableId, searchText) {
    const table = document.getElementById(tableId);
    const rows = table.querySelectorAll('tbody tr');
    const lowerSearchText = searchText.toLowerCase();
    
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(lowerSearchText) ? '' : 'none';
    });
}

// ===== Keyboard Shortcuts =====
const keyboardShortcuts = {
    'ctrl+k': function() {
        // Focus search input
        const searchInput = document.querySelector('input[type="search"], input[name="search"]');
        if (searchInput) searchInput.focus();
    },
    'escape': function() {
        // Close modals and sidebar
        const modals = document.querySelectorAll('.modal.show');
        modals.forEach(modal => {
            const modalInstance = bootstrap.Modal.getInstance(modal);
            if (modalInstance) modalInstance.hide();
        });
        closeSidebar();
    }
};

function initKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        const key = [];
        if (e.ctrlKey) key.push('ctrl');
        if (e.altKey) key.push('alt');
        if (e.shiftKey) key.push('shift');
        key.push(e.key.toLowerCase());
        
        const shortcut = key.join('+');
        if (keyboardShortcuts[shortcut]) {
            e.preventDefault();
            keyboardShortcuts[shortcut]();
        }
    });
}

// ===== Initialization =====
document.addEventListener('DOMContentLoaded', function() {
    // Initialize sidebar
    initSidebar();
    
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function(tooltipTriggerEl) {
        new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialize popovers
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.forEach(function(popoverTriggerEl) {
        new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Initialize keyboard shortcuts
    initKeyboardShortcuts();
    
    // Add smooth scroll to anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            if (href !== '#' && href !== '#!') {
                const target = document.querySelector(href);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        });
    });
    
    // Auto-hide alerts after 5 seconds
    setTimeout(() => {
        document.querySelectorAll('.alert:not(.alert-permanent)').forEach(alert => {
            const alertInstance = bootstrap.Alert.getOrCreateInstance(alert);
            if (alertInstance) {
                alertInstance.close();
            }
        });
    }, 5000);
});

// ===== Global Error Handling =====
window.addEventListener('error', function(event) {
    console.error('Global error:', event.error);
});

window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

// ===== Export utilities =====
window.CallAnalyzerUtils = {
    showAlert,
    showConfirm,
    formatDate,
    formatRelativeTime,
    copyToClipboard,
    debounce,
    throttle,
    apiRequest,
    serializeForm,
    validateForm,
    showLoading,
    showError,
    showEmptyState
};
