// ===== Общие JavaScript функции для Call Analyzer =====

// Переключение видимости пароля
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

// Показать уведомление
function showAlert(message, type) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed animate-fade-in`;
    alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px; max-width: 500px;';
    
    let iconClass = 'fa-info-circle';
    if (type === 'success') iconClass = 'fa-check-circle';
    if (type === 'danger') iconClass = 'fa-exclamation-circle';
    if (type === 'warning') iconClass = 'fa-exclamation-triangle';
    
    alertDiv.innerHTML = `
        <div class="d-flex align-items-center">
            <i class="fas ${iconClass} me-2 fs-5"></i>
            <div class="flex-grow-1">${message}</div>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    document.body.appendChild(alertDiv);
    
    // Автоматическое закрытие через 5 секунд
    setTimeout(() => {
        const alert = bootstrap.Alert.getOrCreateInstance(alertDiv);
        if (alert) {
            alert.close();
        }
    }, 5000);
}

// Показать подтверждение
function showConfirm(message, onConfirm) {
    const modalId = 'confirmModal';
    
    // Удаляем существующий модал если есть
    const existingModal = document.getElementById(modalId);
    if (existingModal) {
        existingModal.remove();
    }
    
    const modalHtml = `
        <div class="modal fade" id="${modalId}" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-question-circle me-2"></i>Подтверждение
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p class="mb-0">${message}</p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            <i class="fas fa-times me-2"></i>Отмена
                        </button>
                        <button type="button" class="btn btn-primary" id="confirmBtn">
                            <i class="fas fa-check me-2"></i>Подтвердить
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    const modal = new bootstrap.Modal(document.getElementById(modalId));
    modal.show();
    
    document.getElementById('confirmBtn').addEventListener('click', () => {
        onConfirm();
        modal.hide();
        setTimeout(() => {
            document.getElementById(modalId).remove();
        }, 300);
    });
    
    document.getElementById(modalId).addEventListener('hidden.bs.modal', () => {
        setTimeout(() => {
            const modalEl = document.getElementById(modalId);
            if (modalEl) {
                modalEl.remove();
            }
        }, 300);
    });
}

// Форматирование даты
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Форматирование относительного времени
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

// Дебаунс функция
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

// Throttle функция
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

// Копирование в буфер обмена
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showAlert('Скопировано в буфер обмена', 'success');
    }).catch(err => {
        showAlert('Ошибка копирования', 'danger');
        console.error('Ошибка копирования:', err);
    });
}

// Форматирование числа с разделителями
function formatNumber(num) {
    return new Intl.NumberFormat('ru-RU').format(num);
}

// Форматирование процентов
function formatPercent(value, decimals = 1) {
    return value.toFixed(decimals) + '%';
}

// Безопасное получение значения из объекта
function safeGet(obj, path, defaultValue = null) {
    return path.split('.').reduce((acc, part) => acc && acc[part], obj) || defaultValue;
}

// Валидация email
function isValidEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

// Валидация URL
function isValidUrl(string) {
    try {
        new URL(string);
        return true;
    } catch (_) {
        return false;
    }
}

// Генерация случайного ID
function generateId() {
    return 'id_' + Math.random().toString(36).substr(2, 9);
}

// Парсинг YAML (упрощенный)
function parseYAML(str) {
    try {
        // Для простых случаев используем парсинг вручную
        // Для сложных случаев можно подключить библиотеку js-yaml
        const lines = str.split('\n');
        const result = {};
        let currentKey = null;
        let indentLevel = 0;
        
        lines.forEach(line => {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith('#')) return;
            
            const indent = line.search(/\S|$/);
            const colonIndex = trimmed.indexOf(':');
            
            if (colonIndex > 0) {
                const key = trimmed.substring(0, colonIndex).trim();
                const value = trimmed.substring(colonIndex + 1).trim();
                
                if (indent === 0) {
                    if (value) {
                        result[key] = value;
                    }
                    currentKey = key;
                }
            }
        });
        
        return result;
    } catch (error) {
        console.error('Ошибка парсинга YAML:', error);
        return {};
    }
}

// Загрузка с timeout
function fetchWithTimeout(url, options = {}, timeout = 30000) {
    return Promise.race([
        fetch(url, options),
        new Promise((_, reject) =>
            setTimeout(() => reject(new Error('Timeout')), timeout)
        )
    ]);
}

// Показать загрузку
function showLoading(containerId, message = 'Загрузка...') {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="text-center py-5">
                <div class="spinner-border text-primary mb-3" role="status" style="width: 3rem; height: 3rem;">
                    <span class="visually-hidden">Загрузка...</span>
                </div>
                <p class="text-muted">${message}</p>
            </div>
        `;
    }
}

// Показать ошибку
function showError(containerId, message) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="alert alert-danger text-center">
                <i class="fas fa-exclamation-triangle mb-2 fs-4"></i>
                <p class="mb-0">${message}</p>
            </div>
        `;
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    // Инициализация всех тултипов
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Инициализация всех popovers
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Sidebar toggle для мобильных
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.querySelector('.sidebar');
    const sidebarOverlay = document.createElement('div');
    sidebarOverlay.className = 'sidebar-overlay';
    sidebarOverlay.id = 'sidebarOverlay';
    document.body.appendChild(sidebarOverlay);
    
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', function() {
            sidebar.classList.toggle('show');
            sidebarOverlay.classList.toggle('show');
        });
        
        sidebarOverlay.addEventListener('click', function() {
            sidebar.classList.remove('show');
            sidebarOverlay.classList.remove('show');
        });
    }
    
    // Закрытие sidebar при клике на ссылку
    document.querySelectorAll('.sidebar .nav-link').forEach(link => {
        link.addEventListener('click', function() {
            if (window.innerWidth < 992) {
                sidebar.classList.remove('show');
                sidebarOverlay.classList.remove('show');
            }
        });
    });
});

// Обработка ошибок глобально
window.addEventListener('error', function(event) {
    console.error('Глобальная ошибка:', event.error);
});

// Обработка ошибок Promise
window.addEventListener('unhandledrejection', function(event) {
    console.error('Необработанное отклонение Promise:', event.reason);
});
