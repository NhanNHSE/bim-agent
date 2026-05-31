/**
 * Simple graph visualization for Knowledge Graph panel.
 * Uses Canvas API — no external dependencies.
 */
const GraphViz = {
    canvas: null,
    ctx: null,
    nodes: [],
    edges: [],
    tooltip: null,
    hoveredNode: null,
    animationId: null,

    COLORS: {
        Standard: '#3b82f6',
        Article: '#06b6d4',
        Requirement: '#f59e0b',
        Material: '#10b981',
        BuildingType: '#ef4444',
        Chapter: '#8b5cf6',
        Section: '#64748b',
        default: '#475569',
    },

    SIZES: {
        Standard: 24,
        Article: 16,
        Requirement: 12,
        Material: 14,
        BuildingType: 14,
        Chapter: 18,
        Section: 14,
        default: 10,
    },

    init() {
        const container = document.getElementById('graph-canvas');
        if (!container) return;

        // Create canvas
        this.canvas = document.createElement('canvas');
        this.canvas.style.width = '100%';
        this.canvas.style.height = '100%';
        container.innerHTML = '';
        container.appendChild(this.canvas);

        // Create tooltip
        this.tooltip = document.createElement('div');
        this.tooltip.className = 'graph-tooltip';
        this.tooltip.style.display = 'none';
        container.appendChild(this.tooltip);

        this._resize();
        window.addEventListener('resize', () => this._resize());
        this.canvas.addEventListener('mousemove', (e) => this._onMouseMove(e));
        this.canvas.addEventListener('mouseleave', () => this._hideTooltip());
    },

    _resize() {
        if (!this.canvas) return;
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width * window.devicePixelRatio;
        this.canvas.height = rect.height * window.devicePixelRatio;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';
        this.ctx = this.canvas.getContext('2d');
        this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        this._draw();
    },

    /**
     * Update graph with citation data from a chat response.
     */
    updateFromCitations(citations, entities) {
        this.nodes = [];
        this.edges = [];

        if (!citations || citations.length === 0) {
            this._draw();
            return;
        }

        const centerX = this.canvas.width / (2 * window.devicePixelRatio);
        const centerY = this.canvas.height / (2 * window.devicePixelRatio);

        // Collect unique standards and articles
        const standards = new Map();
        const articles = [];

        citations.forEach((c, i) => {
            if (c.standard_code && !standards.has(c.standard_code)) {
                standards.set(c.standard_code, {
                    id: `std_${c.standard_code}`,
                    label: c.standard_code,
                    type: 'Standard',
                    detail: c.standard_code,
                });
            }
            if (c.article_number) {
                articles.push({
                    id: `art_${i}`,
                    label: `Đ.${c.article_number}`,
                    type: 'Article',
                    detail: c.text_preview || '',
                    standard: c.standard_code,
                });
            }
        });

        // Layout: standards in center ring, articles in outer ring
        const stdArray = Array.from(standards.values());
        const stdRadius = Math.min(centerX, centerY) * 0.25;
        const artRadius = Math.min(centerX, centerY) * 0.6;

        stdArray.forEach((std, i) => {
            const angle = (2 * Math.PI * i) / Math.max(stdArray.length, 1) - Math.PI / 2;
            this.nodes.push({
                ...std,
                x: centerX + stdRadius * Math.cos(angle),
                y: centerY + stdRadius * Math.sin(angle),
            });
        });

        articles.forEach((art, i) => {
            const angle = (2 * Math.PI * i) / Math.max(articles.length, 1) - Math.PI / 2;
            this.nodes.push({
                ...art,
                x: centerX + artRadius * Math.cos(angle),
                y: centerY + artRadius * Math.sin(angle),
            });

            // Edge: standard → article
            const stdNode = this.nodes.find(n => n.id === `std_${art.standard}`);
            if (stdNode) {
                this.edges.push({ from: stdNode, to: this.nodes[this.nodes.length - 1] });
            }
        });

        // Add entity nodes if available
        if (entities) {
            let entityIndex = 0;
            const entityRadius = Math.min(centerX, centerY) * 0.45;

            if (entities.building_type) {
                const angle = Math.PI * 0.8 + entityIndex * 0.5;
                const node = {
                    id: `bt_${entities.building_type}`,
                    label: entities.building_type,
                    type: 'BuildingType',
                    detail: `Loại công trình: ${entities.building_type}`,
                    x: centerX + entityRadius * Math.cos(angle),
                    y: centerY + entityRadius * Math.sin(angle),
                };
                this.nodes.push(node);
                // Connect to relevant articles
                articles.forEach((_, i) => {
                    this.edges.push({ from: node, to: this.nodes.find(n => n.id === `art_${i}`) });
                });
                entityIndex++;
            }

            if (entities.material) {
                const angle = Math.PI * 1.2 + entityIndex * 0.5;
                const node = {
                    id: `mat_${entities.material}`,
                    label: entities.material,
                    type: 'Material',
                    detail: `Vật liệu: ${entities.material}`,
                    x: centerX + entityRadius * Math.cos(angle),
                    y: centerY + entityRadius * Math.sin(angle),
                };
                this.nodes.push(node);
                entityIndex++;
            }
        }

        // Animate
        this._animateLayout();
    },

    _animateLayout() {
        let frame = 0;
        const maxFrames = 30;

        const animate = () => {
            frame++;
            // Simple spring force
            this.nodes.forEach((node, i) => {
                this.nodes.forEach((other, j) => {
                    if (i === j) return;
                    const dx = node.x - other.x;
                    const dy = node.y - other.y;
                    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    if (dist < 80) {
                        const force = (80 - dist) * 0.05;
                        node.x += (dx / dist) * force;
                        node.y += (dy / dist) * force;
                    }
                });
            });

            this._draw();

            if (frame < maxFrames) {
                this.animationId = requestAnimationFrame(animate);
            }
        };

        if (this.animationId) cancelAnimationFrame(this.animationId);
        animate();
    },

    _draw() {
        if (!this.ctx) return;
        const w = this.canvas.width / window.devicePixelRatio;
        const h = this.canvas.height / window.devicePixelRatio;

        this.ctx.clearRect(0, 0, w, h);

        // Draw edges with gradient
        this.edges.forEach(edge => {
            if (!edge.from || !edge.to) return;
            const fromColor = this.COLORS[edge.from.type] || this.COLORS.default;
            const toColor = this.COLORS[edge.to.type] || this.COLORS.default;

            // Curved edges
            const midX = (edge.from.x + edge.to.x) / 2;
            const midY = (edge.from.y + edge.to.y) / 2;
            const dx = edge.to.x - edge.from.x;
            const dy = edge.to.y - edge.from.y;
            const cpX = midX - dy * 0.1;
            const cpY = midY + dx * 0.1;

            const grad = this.ctx.createLinearGradient(edge.from.x, edge.from.y, edge.to.x, edge.to.y);
            grad.addColorStop(0, fromColor + '40');
            grad.addColorStop(1, toColor + '40');

            this.ctx.beginPath();
            this.ctx.moveTo(edge.from.x, edge.from.y);
            this.ctx.quadraticCurveTo(cpX, cpY, edge.to.x, edge.to.y);
            this.ctx.strokeStyle = grad;
            this.ctx.lineWidth = 1.5;
            this.ctx.stroke();
        });

        // Draw nodes
        this.nodes.forEach(node => {
            const size = this.SIZES[node.type] || this.SIZES.default;
            const color = this.COLORS[node.type] || this.COLORS.default;
            const isHovered = this.hoveredNode === node;

            // Outer glow
            const glowSize = isHovered ? 16 : 6;
            const glow = this.ctx.createRadialGradient(node.x, node.y, size, node.x, node.y, size + glowSize);
            glow.addColorStop(0, color + '30');
            glow.addColorStop(1, color + '00');
            this.ctx.beginPath();
            this.ctx.arc(node.x, node.y, size + glowSize, 0, Math.PI * 2);
            this.ctx.fillStyle = glow;
            this.ctx.fill();

            // Circle fill with gradient
            const fill = this.ctx.createRadialGradient(node.x - size * 0.3, node.y - size * 0.3, 0, node.x, node.y, size);
            fill.addColorStop(0, color);
            fill.addColorStop(1, color + 'cc');
            this.ctx.beginPath();
            this.ctx.arc(node.x, node.y, size, 0, Math.PI * 2);
            this.ctx.fillStyle = fill;
            this.ctx.fill();

            // Border
            this.ctx.strokeStyle = isHovered ? 'white' : color + '60';
            this.ctx.lineWidth = isHovered ? 2.5 : 1;
            this.ctx.stroke();

            // Label with background
            const label = node.label.length > 14 ? node.label.slice(0, 12) + '…' : node.label;
            const fontSize = size > 14 ? 10 : 8;
            this.ctx.font = `${isHovered ? '600' : '500'} ${fontSize}px Inter, sans-serif`;
            this.ctx.textAlign = 'center';
            this.ctx.textBaseline = 'middle';

            const textY = node.y + size + 14;
            const textWidth = this.ctx.measureText(label).width;

            // Label background pill
            this.ctx.fillStyle = 'rgba(10, 15, 30, 0.75)';
            const pad = 4;
            this.ctx.beginPath();
            this.ctx.roundRect(node.x - textWidth / 2 - pad, textY - fontSize / 2 - 2, textWidth + pad * 2, fontSize + 4, 4);
            this.ctx.fill();

            // Label text
            this.ctx.fillStyle = isHovered ? 'white' : '#cbd5e1';
            this.ctx.fillText(label, node.x, textY);
        });

        // Empty state
        if (this.nodes.length === 0) {
            this.ctx.fillStyle = '#475569';
            this.ctx.font = '400 13px Inter, sans-serif';
            this.ctx.textAlign = 'center';
            this.ctx.textBaseline = 'middle';
            this.ctx.fillText('Gửi câu hỏi để xem đồ thị', w / 2, h / 2 - 10);
            this.ctx.font = '400 11px Inter, sans-serif';
            this.ctx.fillStyle = '#334155';
            this.ctx.fillText('GraphRAG Knowledge Visualization', w / 2, h / 2 + 12);
        }
    },

    _onMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        let found = null;
        for (const node of this.nodes) {
            const size = this.SIZES[node.type] || this.SIZES.default;
            const dx = mx - node.x;
            const dy = my - node.y;
            if (dx * dx + dy * dy < (size + 4) * (size + 4)) {
                found = node;
                break;
            }
        }

        if (found !== this.hoveredNode) {
            this.hoveredNode = found;
            this._draw();
            if (found) {
                this._showTooltip(found, e.clientX - rect.left, e.clientY - rect.top);
            } else {
                this._hideTooltip();
            }
        }
    },

    _showTooltip(node, x, y) {
        if (!this.tooltip) return;
        const typeMap = {
            Standard: 'Quy chuẩn/Tiêu chuẩn',
            Article: 'Điều khoản',
            Requirement: 'Yêu cầu kỹ thuật',
            Material: 'Vật liệu',
            BuildingType: 'Loại công trình',
            Chapter: 'Chương',
            Section: 'Mục',
        };
        this.tooltip.innerHTML = `
            <div class="tooltip-title">${node.label}</div>
            <div class="tooltip-type">${typeMap[node.type] || node.type}</div>
            ${node.detail ? `<div style="margin-top:4px;font-size:0.72rem;color:#94a3b8">${node.detail.slice(0, 120)}</div>` : ''}
        `;
        this.tooltip.style.display = 'block';
        this.tooltip.style.left = (x + 15) + 'px';
        this.tooltip.style.top = (y - 10) + 'px';
    },

    _hideTooltip() {
        if (this.tooltip) this.tooltip.style.display = 'none';
        this.hoveredNode = null;
    },
};
