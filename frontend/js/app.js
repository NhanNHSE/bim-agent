/**
 * Main application controller for BIM AI Agent.
 */
const App = {
    currentConversationId: null,
    isStreaming: false,
    graphVisible: false,
    currentMode: 'consult',  // 'consult' | 'design' | 'analyze'

    init() {
        this._bindEvents();
        this._loadConversations();
        this._autoResizeInput();
        GraphViz.init();
        if (typeof IFCViewer !== 'undefined') IFCViewer.init();
    },

    // ===== Event Binding =====
    _bindEvents() {
        // Send message
        document.getElementById('send-btn')?.addEventListener('click', () => this._sendMessage());

        document.getElementById('message-input')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._sendMessage();
            }
        });

        // Input validation
        document.getElementById('message-input')?.addEventListener('input', () => {
            const input = document.getElementById('message-input');
            const btn = document.getElementById('send-btn');
            if (btn) btn.disabled = !input.value.trim() || this.isStreaming;
        });

        // New chat
        document.getElementById('new-chat-btn')?.addEventListener('click', () => {
            this.currentConversationId = null;
            this._showWelcome();
            this._updateTitle('Cuộc hội thoại mới');
            this._clearActiveConv();
        });

        // Toggle sidebar
        document.getElementById('toggle-sidebar')?.addEventListener('click', () => {
            const sidebar = document.querySelector('.sidebar');
            const overlay = document.getElementById('sidebar-overlay');
            sidebar?.classList.toggle('collapsed');
            overlay?.classList.toggle('active', !sidebar?.classList.contains('collapsed'));
        });

        // Close sidebar on overlay click (mobile)
        document.getElementById('sidebar-overlay')?.addEventListener('click', () => {
            document.querySelector('.sidebar')?.classList.add('collapsed');
            document.getElementById('sidebar-overlay')?.classList.remove('active');
        });

        // Toggle graph panel
        document.getElementById('toggle-graph')?.addEventListener('click', () => {
            this.graphVisible = !this.graphVisible;
            const panel = document.getElementById('graph-panel');
            const btn = document.getElementById('toggle-graph');
            if (panel) panel.classList.toggle('hidden', !this.graphVisible);
            if (btn) btn.classList.toggle('active', this.graphVisible);
            if (this.graphVisible) {
                setTimeout(() => GraphViz._resize(), 100);
            }
        });

        // Suggestion chips
        document.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const query = chip.dataset.query;
                const input = document.getElementById('message-input');
                if (input) {
                    // Auto-switch mode based on chip
                    if (query.includes('Thiết kế')) this._setMode('design');
                    input.value = query;
                    input.dispatchEvent(new Event('input'));
                    this._sendMessage();
                }
            });
        });

        // Mode selector
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this._setMode(btn.dataset.mode);
            });
        });
    },

    _setMode(mode) {
        this.currentMode = mode;
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
        document.querySelector(`.mode-btn[data-mode="${mode}"]`)?.classList.add('active');
        const input = document.getElementById('message-input');
        const hint = document.getElementById('mode-hint');
        const placeholders = {
            consult: 'Hỏi về quy chuẩn xây dựng...',
            design: 'Mô tả công trình cần thiết kế... (VD: nhà 5 tầng văn phòng 200m²)',
            analyze: 'Hỏi về mô hình BIM đã tải lên...',
        };
        const hints = {
            consult: 'Tra cứu QCVN/TCVN, tư vấn kỹ thuật',
            design: 'AI tạo mô hình 3D + kiểm tra quy chuẩn',
            analyze: 'Truy vấn cấu kiện, vật liệu trong mô hình IFC',
        };
        if (input) input.placeholder = placeholders[mode] || placeholders.consult;
        if (hint) hint.textContent = hints[mode] || hints.consult;
    },

    // ===== Auto-resize textarea =====
    _autoResizeInput() {
        const input = document.getElementById('message-input');
        if (!input) return;
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        });
    },

    // ===== Send Message =====
    async _sendMessage() {
        const input = document.getElementById('message-input');
        const message = input?.value?.trim();
        if (!message || this.isStreaming) return;

        // Hide welcome, show messages
        this._hideWelcome();

        // Add user message
        this._appendMessage('user', message);
        input.value = '';
        input.style.height = 'auto';
        document.getElementById('send-btn').disabled = true;

        // Add typing indicator
        const typingEl = this._appendTyping();

        // Stream response
        this.isStreaming = true;
        let assistantEl = null;
        let fullResponse = '';

        await API.chatStream(
            message,
            this.currentConversationId,
            // onChunk
            (chunk) => {
                if (typingEl?.parentNode) typingEl.remove();
                if (!assistantEl) {
                    assistantEl = this._appendMessage('assistant', '');
                }
                fullResponse += chunk;
                this._updateMessageContent(assistantEl, fullResponse);
                this._scrollToBottom();
            },
            // onMeta
            (meta) => {
                if (meta.conversation_id) {
                    this.currentConversationId = meta.conversation_id;
                }
                // Update graph
                if (meta.citations && this.graphVisible) {
                    GraphViz.updateFromCitations(meta.citations, meta.entities);
                }
                // Store citations for later
                this._pendingCitations = meta.citations || [];
                // Store design result
                this._pendingDesign = meta.design || null;
            },
            // onDone
            (doneData) => {
                this.isStreaming = false;
                if (typingEl?.parentNode) typingEl.remove();
                // Add citations
                if (assistantEl && this._pendingCitations?.length > 0) {
                    this._appendCitations(assistantEl, this._pendingCitations);
                }
                // Add design compliance report + download
                if (assistantEl && this._pendingDesign) {
                    this._appendDesignResult(assistantEl, this._pendingDesign);
                }

                // Bind message_id to feedback buttons
                const msgId = doneData?.message_id;
                if (msgId && assistantEl) {
                    const msgBody = assistantEl.closest('.msg-body') || assistantEl.parentElement;
                    const fbWrap = msgBody?.querySelector('.msg-feedback');
                    if (fbWrap) fbWrap.dataset.messageId = msgId;
                }

                // Show confidence badge from self-reflection
                if (doneData?.confidence != null && assistantEl) {
                    const msgBody = assistantEl.closest('.msg-body') || assistantEl.parentElement;
                    if (msgBody) {
                        const badge = document.createElement('div');
                        badge.className = 'confidence-badge';
                        const score = doneData.confidence;
                        const label = doneData.confidence_label || '';
                        let level = 'high';
                        if (score < 0.5) level = 'low';
                        else if (score < 0.7) level = 'medium';
                        badge.classList.add(`confidence-${level}`);
                        badge.innerHTML = `<span class="confidence-dot"></span> ${escapeHtml(label)} (${escapeHtml(Math.round(score * 100))}%)`;
                        badge.title = doneData.reflection_feedback || '';
                        msgBody.appendChild(badge);
                    }
                }

                document.getElementById('send-btn').disabled = false;
                this._loadConversations();

                // Auto-show graph on first response
                if (!this.graphVisible && this._pendingCitations?.length > 0) {
                    document.getElementById('toggle-graph')?.click();
                }

                // Update topbar title
                if (this.currentConversationId) {
                    this._loadConversations();
                }
            },
            // onError
            (err) => {
                this.isStreaming = false;
                if (typingEl?.parentNode) typingEl.remove();
                this._appendMessage('assistant', `⚠️ Lỗi: ${err}`);
                document.getElementById('send-btn').disabled = false;
                if (typeof Toast !== 'undefined') Toast.error('Lỗi kết nối', err);
            },
            this.currentMode,
        );
    },

    // ===== Message Rendering =====
    _appendMessage(role, content, messageId = null, feedbackState = null) {
        const container = document.getElementById('messages');
        const user = Auth.getUser();

        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role}`;

        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        avatar.textContent = role === 'user'
            ? (user.full_name || 'U').charAt(0)
            : 'AI';

        const msgBody = document.createElement('div');
        msgBody.style.cssText = 'display:flex;flex-direction:column;min-width:0;position:relative;';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'msg-content';
        contentDiv.innerHTML = this._renderMarkdown(content);

        // Timestamp
        const timeEl = document.createElement('div');
        timeEl.className = 'msg-time';
        timeEl.textContent = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });

        msgBody.appendChild(contentDiv);
        msgBody.appendChild(timeEl);

        // Copy button for assistant messages
        if (role === 'assistant' && content) {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'btn-copy';
            copyBtn.innerHTML = '📋';
            copyBtn.title = 'Copy';
            copyBtn.addEventListener('click', () => {
                const text = contentDiv.innerText;
                navigator.clipboard.writeText(text).then(() => {
                    copyBtn.innerHTML = '✅';
                    copyBtn.classList.add('copied');
                    setTimeout(() => {
                        copyBtn.innerHTML = '📋';
                        copyBtn.classList.remove('copied');
                    }, 2000);
                });
            });
            msgDiv.appendChild(copyBtn);
        }

        // Feedback buttons for assistant messages
        if (role === 'assistant') {
            const fbWrap = document.createElement('div');
            fbWrap.className = 'msg-feedback';
            if (messageId) fbWrap.dataset.messageId = messageId;

            const likeBtn = document.createElement('button');
            likeBtn.className = 'feedback-btn like';
            likeBtn.innerHTML = '👍';
            likeBtn.title = 'Hữu ích';

            const dislikeBtn = document.createElement('button');
            dislikeBtn.className = 'feedback-btn dislike';
            dislikeBtn.innerHTML = '👎';
            dislikeBtn.title = 'Chưa tốt';

            // Apply initial feedback state if available
            if (feedbackState === 'like') likeBtn.classList.add('active');
            if (feedbackState === 'dislike') dislikeBtn.classList.add('active');

            const handleFeedback = async (type) => {
                const mid = fbWrap.dataset.messageId;
                if (!mid) return;
                try {
                    const result = await API.setFeedback(parseInt(mid), type);
                    likeBtn.classList.toggle('active', result.feedback === 'like');
                    dislikeBtn.classList.toggle('active', result.feedback === 'dislike');
                } catch (e) {
                    if (typeof Toast !== 'undefined') Toast.error('Lỗi', 'Không thể gửi đánh giá');
                }
            };

            likeBtn.addEventListener('click', () => handleFeedback('like'));
            dislikeBtn.addEventListener('click', () => handleFeedback('dislike'));

            fbWrap.appendChild(likeBtn);
            fbWrap.appendChild(dislikeBtn);
            msgBody.appendChild(fbWrap);
        }

        msgDiv.appendChild(avatar);
        msgDiv.appendChild(msgBody);
        container.appendChild(msgDiv);
        this._scrollToBottom();

        return contentDiv;
    },

    _updateMessageContent(el, text) {
        if (el) el.innerHTML = this._renderMarkdown(text);
    },

    _appendCitations(contentEl, citations) {
        if (!citations?.length || !contentEl) return;

        const citDiv = document.createElement('div');
        citDiv.className = 'citations';

        citations.forEach(c => {
            const tag = document.createElement('span');
            tag.className = 'citation-tag';

            // Source indicator dot
            const dot = document.createElement('span');
            dot.className = `cite-source ${c.source === 'knowledge_graph' ? 'graph' : 'vector'}`;
            tag.appendChild(dot);

            let label = c.standard_code || 'N/A';
            if (c.article_number) label += ` Đ.${c.article_number}`;
            tag.appendChild(document.createTextNode(label));

            tag.title = c.text_preview || '';
            citDiv.appendChild(tag);
        });

        contentEl.appendChild(citDiv);
    },

    _appendDesignResult(contentEl, design) {
        if (!design || !contentEl) return;
        const wrapper = document.createElement('div');

        // Spec Card — adaptive for building or bridge
        const spec = design.spec || {};
        const isBridge = spec.structure_type === 'bridge' || spec.bridge_name || spec.total_length;
        let specHtml;

        if (isBridge) {
            specHtml = `
            <div class="design-spec-card">
                <h4>🌉 Thông số thiết kế cầu</h4>
                <div class="spec-grid">
                    <div class="spec-item"><label>Loại cầu</label><span>${escapeHtml(spec.bridge_type === 'beam' ? 'Dầm BTCT' : spec.bridge_type || '?')}</span></div>
                    <div class="spec-item"><label>Tổng chiều dài</label><span>${escapeHtml(((spec.total_length || 0)/1000).toFixed(0))}m</span></div>
                    <div class="spec-item"><label>Số nhịp</label><span>${escapeHtml(spec.num_spans || '?')}</span></div>
                    <div class="spec-item"><label>Nhịp cầu</label><span>${escapeHtml(((spec.span_length || 0)/1000).toFixed(0))}m</span></div>
                    <div class="spec-item"><label>Bề rộng mặt cầu</label><span>${escapeHtml(((spec.deck_width || 0)/1000).toFixed(1))}m</span></div>
                    <div class="spec-item"><label>Số làn xe</label><span>${escapeHtml(spec.num_lanes || '?')}</span></div>
                    <div class="spec-item"><label>Dầm cầu</label><span>${escapeHtml(spec.girder_type || 'I')}-${escapeHtml(spec.girder_height || 0)}mm</span></div>
                    <div class="spec-item"><label>Trụ cầu</label><span>${escapeHtml(spec.num_piers || '?')} trụ, H=${escapeHtml(((spec.pier_height || 0)/1000).toFixed(0))}m</span></div>
                    <div class="spec-item"><label>Lan can</label><span>${escapeHtml(spec.barrier_height || '?')}mm</span></div>
                    <div class="spec-item"><label>Cọc móng</label><span>D${escapeHtml(spec.pile_diameter || '?')}, L=${escapeHtml(((spec.pile_depth || 0)/1000).toFixed(0))}m</span></div>
                    <div class="spec-item"><label>VL Dầm</label><span>${escapeHtml(spec.girder_material || '?')}</span></div>
                    <div class="spec-item"><label>Tải trọng</label><span>${escapeHtml(spec.design_load || 'HL-93')}</span></div>
                </div>
            </div>
        `;
        } else {
            specHtml = `
            <div class="design-spec-card">
                <h4>📐 Thông số thiết kế</h4>
                <div class="spec-grid">
                    <div class="spec-item"><label>Tầng</label><span>${escapeHtml(spec.num_storeys || '?')}</span></div>
                    <div class="spec-item"><label>Chiều cao tầng</label><span>${escapeHtml(((spec.storey_height || 0)/1000).toFixed(1))}m</span></div>
                    <div class="spec-item"><label>Mặt bằng</label><span>${escapeHtml(((spec.footprint_length||0)/1000).toFixed(0))} × ${escapeHtml(((spec.footprint_width||0)/1000).toFixed(0))}m</span></div>
                    <div class="spec-item"><label>Diện tích sàn</label><span>${escapeHtml(((spec.footprint_length||0)/1000 * (spec.footprint_width||0)/1000).toFixed(0))}m²</span></div>
                    <div class="spec-item"><label>Cột</label><span>${escapeHtml(spec.column_size || '?')}mm</span></div>
                    <div class="spec-item"><label>Cầu thang</label><span>${escapeHtml(spec.num_staircases || 0)}</span></div>
                    <div class="spec-item"><label>VL Cột</label><span>${escapeHtml(spec.column_material || '?')}</span></div>
                    <div class="spec-item"><label>VL Tường</label><span>${escapeHtml(spec.wall_material || '?')}</span></div>
                </div>
            </div>
        `;
        }

        // Compliance Report
        const violations = design.violations || [];
        const errors = violations.filter(v => v.severity === 'error');
        const warnings = violations.filter(v => v.severity === 'warning');
        const passes = violations.filter(v => v.severity === 'pass');
        const infos = violations.filter(v => v.severity === 'info');

        const severityIcon = (s) => s === 'error' ? '❌' : s === 'warning' ? '⚠️' : s === 'pass' ? '✅' : 'ℹ️';

        let complianceHtml = `
            <div class="compliance-report">
                <div class="compliance-header">
                    <h4>📋 Kiểm tra Quy chuẩn</h4>
                    <div class="compliance-summary">
                        ${errors.length ? `<span class="compliance-badge error">${escapeHtml(errors.length)} lỗi</span>` : ''}
                        ${warnings.length ? `<span class="compliance-badge warning">${escapeHtml(warnings.length)} cảnh báo</span>` : ''}
                        ${passes.length ? `<span class="compliance-badge pass">${escapeHtml(passes.length)} đạt</span>` : ''}
                    </div>
                </div>
                <div class="compliance-items">
        `;

        for (const v of [...errors, ...warnings, ...infos, ...passes]) {
            complianceHtml += `
                <div class="compliance-item">
                    <span class="compliance-icon">${escapeHtml(severityIcon(v.severity))}</span>
                    <div class="compliance-content">
                        <div class="compliance-rule">${escapeHtml(v.rule || '')}</div>
                        <div class="compliance-issue">${escapeHtml(v.issue || '')}</div>
                        ${v.suggestion ? `<div class="compliance-suggestion">💡 ${escapeHtml(v.suggestion)}</div>` : ''}
                    </div>
                </div>
            `;
        }
        complianceHtml += '</div></div>';

        // Download + 3D buttons
        let actionsHtml = '<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">';
        if (design.filename) {
            const downloadUrl = API.getIFCDownloadUrl(design.filename);
            actionsHtml += `<a href="${escapeHtml(downloadUrl)}" class="btn-download" download>📥 Tải file IFC</a>`;
            // Store spec+filename in global array for 3D viewer
            if (!window._designSpecs) window._designSpecs = [];
            const specIdx = window._designSpecs.length;
            window._designSpecs.push({ spec: design.spec, filename: design.filename });
            actionsHtml += `<button class="btn-download" style="background:linear-gradient(135deg,#3b82f6,#06b6d4)" onclick="App._openDesign3D(${escapeHtml(specIdx)})">🏗️ Xem 3D</button>`;
        }
        actionsHtml += '</div>';

        wrapper.innerHTML = specHtml + complianceHtml + actionsHtml;
        contentEl.appendChild(wrapper);
    },

    _appendTyping() {
        const container = document.getElementById('messages');
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant';
        msgDiv.innerHTML = `
            <div class="msg-avatar">AI</div>
            <div class="msg-content">
                <div class="typing-indicator"><span></span><span></span><span></span></div>
            </div>
        `;
        container.appendChild(msgDiv);
        this._scrollToBottom();
        return msgDiv;
    },

    // ===== Simple Markdown Renderer =====
    _renderMarkdown(text) {
        if (!text) return '';
        let html = text
            // Escape HTML
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            // Headers
            .replace(/^### (.+)$/gm, '<h3>$1</h3>')
            .replace(/^## (.+)$/gm, '<h3>$1</h3>')
            // Bold
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            // Inline code
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            // Unordered lists
            .replace(/^[•\-\*] (.+)$/gm, '<li>$1</li>')
            // Ordered lists
            .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
            // Paragraphs
            .replace(/\n\n/g, '</p><p>')
            .replace(/\n/g, '<br>');

        // Wrap lists
        html = html.replace(/(<li>.*?<\/li>)/gs, '<ul>$1</ul>');
        // Clean double-wrapped lists
        html = html.replace(/<\/ul><ul>/g, '');

        // Simple table support
        if (html.includes('|')) {
            html = html.replace(
                /^(\|.+\|)$/gm,
                (match) => {
                    const cells = match.split('|').filter(c => c.trim());
                    if (cells.every(c => /^[\-\s:]+$/.test(c.trim()))) return '';
                    const tag = 'td';
                    return '<tr>' + cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join('') + '</tr>';
                }
            );
            if (html.includes('<tr>')) {
                html = html.replace(/(<tr>.*?<\/tr>)/gs, '<table>$1</table>');
                html = html.replace(/<\/table><br><table>/g, '');
            }
        }

        const raw = `<p>${html}</p>`.replace(/<p><\/p>/g, '');
        // Sanitize to prevent XSS (defense-in-depth)
        return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(raw) : raw;
    },

    // ===== Conversations =====
    async _loadConversations() {
        try {
            const convos = await API.getConversations();
            const list = document.getElementById('conversations-list');
            if (!list) return;

            list.innerHTML = convos.map(c => `
                <div class="conv-item ${c.id === this.currentConversationId ? 'active' : ''}"
                     data-id="${escapeHtml(c.id)}">
                    <span class="conv-title">${escapeHtml(c.title || 'Cuộc hội thoại mới')}</span>
                    <button class="conv-delete" data-delete-id="${escapeHtml(c.id)}" title="Xóa">✕</button>
                </div>
            `).join('');

            // Event delegation — more reliable than inline onclick
            list.onclick = (e) => {
                // Delete button clicked
                const deleteBtn = e.target.closest('.conv-delete');
                if (deleteBtn) {
                    e.stopPropagation();
                    const id = parseInt(deleteBtn.dataset.deleteId);
                    if (id) this._deleteConversation(id);
                    return;
                }
                // Conversation title/row clicked
                const convItem = e.target.closest('.conv-item');
                if (convItem) {
                    const id = parseInt(convItem.dataset.id);
                    if (id) this._selectConversation(id);
                }
            };
        } catch (e) {
            // Silently fail — conversations will load on next try
        }
    },

    async _deleteConversation(id) {
        if (!confirm('Xóa cuộc hội thoại này?')) return;
        try {
            await API.deleteConversation(id);
            if (this.currentConversationId === id) {
                this.currentConversationId = null;
                this._showWelcome();
                this._updateTitle('Cuộc hội thoại mới');
            }
            this._loadConversations();
            if (typeof Toast !== 'undefined') Toast.success('Đã xóa', 'Cuộc hội thoại đã được xóa');
        } catch (e) {
            if (typeof Toast !== 'undefined') Toast.error('Lỗi', 'Không thể xóa cuộc hội thoại');
        }
    },

    async _selectConversation(id) {
        this.currentConversationId = id;
        this._hideWelcome();
        this._clearActiveConv();

        // Mark active
        document.querySelectorAll('.conv-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.id) === id);
        });

        // Show loading state
        const container = document.getElementById('messages');
        container.innerHTML = typeof Skeleton !== 'undefined'
            ? Skeleton.messages(3)
            : '<div class="loading-overlay" style="position:relative;min-height:200px"><div class="loading-spinner"></div></div>';

        // Load messages
        try {
            const messages = await API.getMessages(id);
            container.innerHTML = '';

            messages.forEach(msg => {
                const el = this._appendMessage(msg.role, msg.content, msg.id, msg.feedback);
                if (msg.citations?.length && msg.role === 'assistant') {
                    // Separate regular citations from design results
                    const regularCitations = [];
                    let designData = null;
                    for (const c of msg.citations) {
                        if (c._type === 'design_result') {
                            designData = c;
                        } else {
                            regularCitations.push(c);
                        }
                    }
                    if (regularCitations.length) {
                        this._appendCitations(el, regularCitations);
                    }
                    if (designData) {
                        this._appendDesignResult(el, designData);
                    }
                }
            });
        } catch (e) {
            container.innerHTML = '';
            if (typeof Toast !== 'undefined') Toast.error('Lỗi', 'Không thể tải tin nhắn');
        }
    },

    // ===== Design 3D Panel Management =====
    _openDesign3D(specIdx) {
        const data = window._designSpecs?.[specIdx];
        if (!data) return;
        // Hide graph panel
        const graphPanel = document.getElementById('graph-panel');
        if (graphPanel) graphPanel.classList.add('hidden');
        this.graphVisible = false;
        document.getElementById('toggle-graph')?.classList.remove('active');

        // Show loading overlay in 3D container
        const container = document.getElementById('ifc-3d-container');
        if (container) {
            container.innerHTML = `
                <div class="loading-overlay">
                    <div class="loading-spinner"></div>
                    <div class="loading-text">Đang tải mô hình 3D...</div>
                </div>
            `;
        }

        // Show 3D (delayed to allow loading overlay to render)
        setTimeout(() => {
            IFCViewer._showDesignModel(data.spec, data.filename);
        }, 50);
    },

    _closeDesign3D() {
        const panel = document.getElementById('ifc-viewer-panel');
        if (panel) {
            panel.classList.add('hidden');
            panel.classList.remove('fullscreen');
        }
    },

    // ===== Helpers =====
    _showWelcome() {
        const welcome = document.getElementById('welcome-screen');
        const msgs = document.getElementById('messages');
        if (welcome) welcome.style.display = 'flex';
        if (msgs) msgs.innerHTML = '';
    },

    _hideWelcome() {
        const welcome = document.getElementById('welcome-screen');
        if (welcome) welcome.style.display = 'none';
    },

    _updateTitle(title) {
        const el = document.getElementById('current-title');
        if (el) el.textContent = title;
    },

    _clearActiveConv() {
        document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
    },

    _scrollToBottom() {
        const panel = document.getElementById('chat-panel');
        if (panel) panel.scrollTop = panel.scrollHeight;
    },
};
