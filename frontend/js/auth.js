/**
 * Authentication module for BIM AI Agent.
 */
const Auth = {
    init() {
        this._bindEvents();
        this._checkExistingSession();
    },

    _bindEvents() {
        // Toggle forms
        document.getElementById('show-register')?.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('login-form').classList.remove('active');
            document.getElementById('register-form').classList.add('active');
            this._hideError();
        });

        document.getElementById('show-login')?.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('register-form').classList.remove('active');
            document.getElementById('login-form').classList.add('active');
            this._hideError();
        });

        // Login
        document.getElementById('login-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('login-email').value;
            const password = document.getElementById('login-password').value;

            try {
                this._setLoading('login-btn', true);
                const data = await API.login(email, password);
                this._saveSession(data);
                this._showApp();
            } catch (err) {
                this._showError(err.message);
            } finally {
                this._setLoading('login-btn', false);
            }
        });

        // Register
        document.getElementById('register-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = {
                full_name: document.getElementById('reg-name').value,
                email: document.getElementById('reg-email').value,
                password: document.getElementById('reg-password').value,
                role: document.getElementById('reg-role').value,
                company: document.getElementById('reg-company').value,
            };

            try {
                this._setLoading('register-btn', true);
                const result = await API.register(data);
                this._saveSession(result);
                this._showApp();
            } catch (err) {
                this._showError(err.message);
            } finally {
                this._setLoading('register-btn', false);
            }
        });

        // Logout
        document.getElementById('logout-btn')?.addEventListener('click', () => {
            this.logout();
        });
    },

    _checkExistingSession() {
        const token = localStorage.getItem('token');
        const user = localStorage.getItem('user');
        if (token && user) {
            this._showApp();
        }
    },

    _saveSession(data) {
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('user', JSON.stringify(data.user));
    },

    _showApp() {
        const user = JSON.parse(localStorage.getItem('user') || '{}');

        document.getElementById('auth-screen').classList.add('hidden');
        document.getElementById('app').classList.remove('hidden');

        // Update user info
        const nameEl = document.getElementById('user-name');
        const roleEl = document.getElementById('user-role');
        const avatarEl = document.getElementById('user-avatar');

        if (nameEl) nameEl.textContent = user.full_name || 'User';
        if (roleEl) {
            const roleMap = {
                'engineer': 'Kỹ sư',
                'architect': 'Kiến trúc sư',
                'project_manager': 'Quản lý dự án',
                'admin': 'Quản trị viên',
                'viewer': 'Người xem',
            };
            roleEl.textContent = roleMap[user.role] || user.role;
        }
        if (avatarEl) {
            avatarEl.textContent = (user.full_name || 'U').charAt(0).toUpperCase();
        }

        // Initialize app
        if (typeof App !== 'undefined') App.init();
    },

    logout() {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        document.getElementById('app').classList.add('hidden');
        document.getElementById('auth-screen').classList.remove('hidden');
        document.getElementById('login-form').classList.add('active');
        document.getElementById('register-form').classList.remove('active');
    },

    _showError(msg) {
        const el = document.getElementById('auth-error');
        if (el) {
            el.textContent = msg;
            el.classList.add('show');
        }
    },

    _hideError() {
        const el = document.getElementById('auth-error');
        if (el) el.classList.remove('show');
    },

    _setLoading(btnId, loading) {
        const btn = document.getElementById(btnId);
        if (btn) {
            btn.disabled = loading;
            btn.textContent = loading ? 'Đang xử lý...' : (btnId === 'login-btn' ? 'Đăng nhập' : 'Đăng ký');
        }
    },

    getUser() {
        return JSON.parse(localStorage.getItem('user') || '{}');
    },

    isLoggedIn() {
        return !!localStorage.getItem('token');
    },
};

// Auto-init
document.addEventListener('DOMContentLoaded', () => Auth.init());
