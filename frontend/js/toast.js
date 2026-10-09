/**
 * Toast notification system for BIM AI Agent.
 * Usage: Toast.success('Title', 'Message')
 *        Toast.error('Title', 'Message')
 *        Toast.warning('Title', 'Message')
 *        Toast.info('Title', 'Message')
 */
const Toast = {
    _container: null,
    _defaultDuration: 4000,

    _icons: {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️',
    },

    _ensureContainer() {
        if (!this._container) {
            this._container = document.createElement('div');
            this._container.className = 'toast-container';
            this._container.id = 'toast-container';
            document.body.appendChild(this._container);
        }
        return this._container;
    },

    /**
     * Show a toast notification.
     * @param {'success'|'error'|'warning'|'info'} type
     * @param {string} title
     * @param {string} [message]
     * @param {number} [duration]
     */
    show(type, title, message = '', duration = this._defaultDuration) {
        const container = this._ensureContainer();

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${escapeHtml(this._icons[type] || 'ℹ️')}</span>
            <div class="toast-body">
                <div class="toast-title">${escapeHtml(title)}</div>
                ${message ? `<div class="toast-message">${escapeHtml(message)}</div>` : ''}
            </div>
            <button class="toast-close" title="Đóng">✕</button>
        `;

        // Close button
        toast.querySelector('.toast-close').addEventListener('click', () => {
            this._dismiss(toast);
        });

        container.appendChild(toast);

        // Auto-dismiss
        if (duration > 0) {
            setTimeout(() => this._dismiss(toast), duration);
        }

        // Limit to 5 toasts max
        while (container.children.length > 5) {
            this._dismiss(container.children[0]);
        }

        return toast;
    },

    _dismiss(toast) {
        if (!toast || !toast.parentNode) return;
        toast.classList.add('hiding');
        setTimeout(() => toast.remove(), 300);
    },

    success(title, message, duration) {
        return this.show('success', title, message, duration);
    },

    error(title, message, duration) {
        return this.show('error', title, message, duration || 6000);
    },

    warning(title, message, duration) {
        return this.show('warning', title, message, duration);
    },

    info(title, message, duration) {
        return this.show('info', title, message, duration);
    },
};
