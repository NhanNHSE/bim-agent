/**
 * API communication layer for BIM AI Agent.
 */
const API = {
    BASE_URL: '/api/v1',

    /**
     * Get auth headers.
     */
    _headers() {
        const token = localStorage.getItem('token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return headers;
    },

    /**
     * Generic fetch wrapper.
     */
    async _fetch(url, options = {}) {
        const res = await fetch(this.BASE_URL + url, {
            ...options,
            headers: { ...this._headers(), ...(options.headers || {}) },
        });
        if (res.status === 401) {
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            location.reload();
            throw new Error('Unauthorized');
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({ message: 'Lỗi kết nối' }));
            // FastAPI detail can be string OR array of validation errors
            let msg = 'Lỗi không xác định';
            if (typeof err.detail === 'string') {
                msg = err.detail;
            } else if (Array.isArray(err.detail) && err.detail.length > 0) {
                msg = err.detail.map(e => e.msg || e.message || JSON.stringify(e)).join('; ');
            } else if (err.detail) {
                msg = JSON.stringify(err.detail);
            } else if (err.message) {
                msg = err.message;
            }
            throw new Error(msg);
        }
        return res;
    },

    // === Auth ===
    async register(data) {
        const res = await this._fetch('/auth/register', {
            method: 'POST',
            body: JSON.stringify(data),
        });
        return res.json();
    },

    async login(email, password) {
        const res = await this._fetch('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password }),
        });
        return res.json();
    },

    // === Chat ===
    async chatStream(message, conversationId, onChunk, onMeta, onDone, onError, mode) {
        const token = localStorage.getItem('token');
        const body = { message };
        if (conversationId) body.conversation_id = conversationId;
        if (mode) body.mode = mode;

        try {
            const res = await fetch(this.BASE_URL + '/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                },
                body: JSON.stringify(body),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Lỗi kết nối');
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            if (data.type === 'chunk') onChunk(data.content);
                            else if (data.type === 'meta') onMeta(data);
                            else if (data.type === 'done') onDone(data);
                            else if (data.type === 'error') onError(data.message);
                        } catch (e) { /* skip parse errors */ }
                    }
                }
            }
        } catch (err) {
            onError(err.message);
        }
    },

    // === Conversations ===
    async getConversations() {
        const res = await this._fetch('/conversations');
        return res.json();
    },

    async getMessages(conversationId) {
        const res = await this._fetch(`/conversations/${conversationId}/messages`);
        return res.json();
    },

    async deleteConversation(conversationId) {
        const res = await this._fetch(`/conversations/${conversationId}`, {
            method: 'DELETE',
        });
        return res.json();
    },

    // === Graph ===
    async getGraphStats() {
        const res = await this._fetch('/graph/stats');
        return res.json();
    },

    async searchGraph(keyword) {
        const res = await this._fetch(`/graph/search?keyword=${encodeURIComponent(keyword)}`);
        return res.json();
    },

    // === Health ===
    async healthCheck() {
        const res = await this._fetch('/health');
        return res.json();
    },

    // === IFC/BIM ===
    async uploadIFC(file) {
        const token = localStorage.getItem('token');
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(this.BASE_URL + '/ifc/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
            throw new Error(err.detail || 'Upload failed');
        }
        return res.json();
    },

    async getIFCStats() {
        const res = await this._fetch('/ifc/stats');
        return res.json();
    },

    async getIFCElements(storey) {
        const res = await this._fetch(`/ifc/elements?storey=${encodeURIComponent(storey)}`);
        return res.json();
    },

    async getIFCGeometry(filename) {
        const res = await this._fetch(`/ifc/geometry/${encodeURIComponent(filename)}`);
        return res.json();
    },

    async generateSampleIFC() {
        const res = await this._fetch('/ifc/generate-sample', { method: 'POST' });
        return res.json();
    },

    // === Design (Text-to-BIM) ===
    async designBuilding(description) {
        const res = await this._fetch('/ifc/design', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ description }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Design failed' }));
            throw new Error(err.detail || 'Design failed');
        }
        return res.json();
    },

    getIFCDownloadUrl(filename) {
        const token = localStorage.getItem('token');
        return `${this.BASE_URL}/ifc/download/${encodeURIComponent(filename)}?token=${token}`;
    },

    // === Feedback ===
    async setFeedback(messageId, feedback) {
        const res = await this._fetch(`/messages/${messageId}/feedback`, {
            method: 'PUT',
            body: JSON.stringify({ feedback }),
        });
        return res.json();
    },
};
