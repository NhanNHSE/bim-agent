/**
 * Theme toggle + connection status for BIM AI Agent.
 * Loaded before app.js
 */
const Theme = {
    _key: 'bim-theme',

    init() {
        const saved = localStorage.getItem(this._key) || 'dark';
        this._apply(saved);
        this._injectToggle();
    },

    toggle() {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';
        this._apply(next);
        localStorage.setItem(this._key, next);
    },

    _apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        const btn = document.getElementById('theme-toggle-btn');
        if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
    },

    _injectToggle() {
        // Insert theme toggle into topbar (after toggle-sidebar button)
        const topbar = document.querySelector('.topbar');
        if (!topbar) return;

        const btn = document.createElement('button');
        btn.className = 'btn-theme-toggle';
        btn.id = 'theme-toggle-btn';
        btn.title = 'Chuyển giao diện Sáng/Tối';
        btn.textContent = (localStorage.getItem(this._key) || 'dark') === 'dark' ? '☀️' : '🌙';
        btn.addEventListener('click', () => this.toggle());

        // Insert before the title
        const title = topbar.querySelector('.topbar-title');
        if (title) topbar.insertBefore(btn, title);
    },
};

/**
 * Connection status indicator.
 */
const ConnectionStatus = {
    _el: null,
    _interval: null,

    init() {
        this._injectBadge();
        this._check();
        this._interval = setInterval(() => this._check(), 30000);
    },

    async _check() {
        try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 5000);
            const res = await fetch('/api/v1/health', { signal: controller.signal });
            clearTimeout(timeout);
            this._setStatus(res.ok ? 'online' : 'offline');
        } catch {
            this._setStatus('offline');
        }
    },

    _setStatus(status) {
        if (!this._el) return;
        this._el.className = `connection-status ${status}`;
        this._el.querySelector('.status-text').textContent =
            status === 'online' ? 'Đang kết nối' : 'Mất kết nối';
    },

    _injectBadge() {
        const topbar = document.querySelector('.topbar');
        if (!topbar) return;

        const badge = document.createElement('div');
        badge.className = 'connection-status online';
        badge.innerHTML = '<span class="status-dot"></span><span class="status-text">Đang kết nối</span>';
        topbar.appendChild(badge);
        this._el = badge;
    },
};

/**
 * Skeleton loading helpers.
 */
const Skeleton = {
    /** Generate skeleton message placeholder HTML */
    messages(count = 3) {
        return Array.from({ length: count }, () => `
            <div class="skeleton-message">
                <div class="skeleton skeleton-avatar"></div>
                <div class="skeleton-content">
                    <div class="skeleton skeleton-line" style="width: ${60 + Math.random() * 30}%"></div>
                    <div class="skeleton skeleton-line" style="width: ${40 + Math.random() * 40}%"></div>
                    <div class="skeleton skeleton-line" style="width: ${30 + Math.random() * 30}%"></div>
                </div>
            </div>
        `).join('');
    },
};

// Auto-init after DOM ready (but before App.init)
document.addEventListener('DOMContentLoaded', () => {
    Theme.init();
    ConnectionStatus.init();

    // Attach UI Polish micro-interactions
    document.body.addEventListener('click', (e) => {
        const target = e.target.closest('.btn-primary, .btn-secondary, .suggestion-chip, .quick-action-card');
        if (!target) return;
        target.classList.add('pulse-effect');
        setTimeout(() => target.classList.remove('pulse-effect'), 400);
    });
});

