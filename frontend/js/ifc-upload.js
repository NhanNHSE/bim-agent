/**
 * IFC Upload & 3D Viewer module.
 *
 * Handles:
 * - File upload via drag-drop or file picker
 * - Upload progress display
 * - 3D model rendering with Three.js
 * - Sample IFC generation
 */
const IFCViewer = {
    scene: null,
    camera: null,
    renderer: null,
    controls: null,
    animationId: null,
    isRotating: true,
    _raycaster: null,
    _mouse: null,
    _selectedMesh: null,
    _originalMaterial: null,
    _meshList: [],
    _elementCounts: {},

    // ===== Upload Modal =====
    init() {
        const btn = document.getElementById('ifc-upload-btn');
        const modal = document.getElementById('ifc-upload-modal');
        const close = document.getElementById('ifc-modal-close');
        const overlay = modal?.querySelector('.modal-overlay');
        const dropzone = document.getElementById('ifc-dropzone');
        const fileInput = document.getElementById('ifc-file-input');
        const sampleBtn = document.getElementById('ifc-generate-sample');

        if (!btn || !modal) return;

        btn.onclick = () => modal.classList.remove('hidden');
        close.onclick = () => modal.classList.add('hidden');
        overlay.onclick = () => modal.classList.add('hidden');

        // Dropzone click → file picker
        dropzone.onclick = () => fileInput.click();
        fileInput.onchange = (e) => {
            if (e.target.files[0]) this._uploadFile(e.target.files[0]);
        };

        // Drag and drop
        dropzone.ondragover = (e) => { e.preventDefault(); dropzone.classList.add('drag-over'); };
        dropzone.ondragleave = () => dropzone.classList.remove('drag-over');
        dropzone.ondrop = (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file && file.name.toLowerCase().endsWith('.ifc')) {
                this._uploadFile(file);
            } else {
                if (typeof Toast !== 'undefined') Toast.warning('File không hợp lệ', 'Vui lòng chọn file .ifc');
            }
        };

        // Generate sample
        sampleBtn.onclick = () => this._generateSample();
    },

    async _uploadFile(file) {
        const progressDiv = document.getElementById('ifc-upload-progress');
        const resultDiv = document.getElementById('ifc-upload-result');
        const filenameSpan = document.getElementById('ifc-filename');
        const progressText = document.getElementById('ifc-progress-text');
        const progressFill = document.getElementById('ifc-progress-fill');
        const dropzone = document.getElementById('ifc-dropzone');

        // Show progress
        dropzone.classList.add('hidden');
        progressDiv.classList.remove('hidden');
        resultDiv.classList.add('hidden');
        filenameSpan.textContent = file.name;
        progressText.textContent = 'Đang upload...';
        progressFill.style.width = '30%';

        try {
            const result = await API.uploadIFC(file);
            progressFill.style.width = '100%';
            progressText.textContent = 'Hoàn tất!';

            // Show results
            setTimeout(() => {
                progressDiv.classList.add('hidden');
                resultDiv.classList.remove('hidden');
                resultDiv.innerHTML = `
                    <div class="upload-success">
                        <h4>✅ ${escapeHtml(result.building || result.filename)}</h4>
                        <div class="result-grid">
                            <div class="result-item"><span>📐 Dự án</span><strong>${escapeHtml(result.project)}</strong></div>
                            <div class="result-item"><span>🏢 Tầng</span><strong>${escapeHtml(result.storeys)}</strong></div>
                            <div class="result-item"><span>🧱 Cấu kiện</span><strong>${escapeHtml(result.elements)}</strong></div>
                            <div class="result-item"><span>📦 Vật liệu</span><strong>${escapeHtml(result.materials)}</strong></div>
                            <div class="result-item"><span>🏠 Không gian</span><strong>${escapeHtml(result.spaces)}</strong></div>
                            <div class="result-item"><span>🕸️ Graph nodes</span><strong>${escapeHtml(result.graph_nodes)}</strong></div>
                        </div>
                        <button class="btn-primary" onclick="IFCViewer._showViewer('${escapeHtml(result.filename)}')" style="margin-top:12px;width:100%">
                            🏗️ Xem mô hình 3D
                        </button>
                    </div>
                `;
            }, 500);

        } catch (err) {
            progressDiv.classList.add('hidden');
            resultDiv.classList.remove('hidden');
            resultDiv.innerHTML = `<div class="upload-error">❌ Lỗi: ${escapeHtml(err.message)}</div>`;
            dropzone.classList.remove('hidden');
            if (typeof Toast !== 'undefined') Toast.error('Upload thất bại', err.message);
        }
    },

    async _generateSample() {
        const sampleBtn = document.getElementById('ifc-generate-sample');
        const progressDiv = document.getElementById('ifc-upload-progress');
        const resultDiv = document.getElementById('ifc-upload-result');
        const dropzone = document.getElementById('ifc-dropzone');
        const progressText = document.getElementById('ifc-progress-text');
        const progressFill = document.getElementById('ifc-progress-fill');
        const filenameSpan = document.getElementById('ifc-filename');

        sampleBtn.disabled = true;
        sampleBtn.textContent = '⏳ Đang tạo...';

        try {
            // Step 1: Generate sample IFC on backend
            dropzone.classList.add('hidden');
            progressDiv.classList.remove('hidden');
            filenameSpan.textContent = 'sample_building.ifc';
            progressText.textContent = 'Đang tạo mô hình mẫu...';
            progressFill.style.width = '30%';

            await API.generateSampleIFC();
            progressFill.style.width = '60%';
            progressText.textContent = 'Đang parse và ingest...';

            // Step 2: Upload the generated file (it's already on the server)
            // We need to fetch, create blob, and upload
            const response = await fetch('data/ifc/sample_building.ifc').catch(() => null);
            if (response && response.ok) {
                const blob = await response.blob();
                const file = new File([blob], 'sample_building.ifc', { type: 'application/octet-stream' });
                const result = await API.uploadIFC(file);
                progressFill.style.width = '100%';
                progressText.textContent = 'Hoàn tất!';

                setTimeout(() => {
                    progressDiv.classList.add('hidden');
                    resultDiv.classList.remove('hidden');
                    resultDiv.innerHTML = `
                        <div class="upload-success">
                            <h4>✅ ${escapeHtml(result.building || 'Mô hình mẫu')}</h4>
                            <div class="result-grid">
                                <div class="result-item"><span>📐 Dự án</span><strong>${escapeHtml(result.project)}</strong></div>
                                <div class="result-item"><span>🏢 Tầng</span><strong>${escapeHtml(result.storeys)}</strong></div>
                                <div class="result-item"><span>🧱 Cấu kiện</span><strong>${escapeHtml(result.elements)}</strong></div>
                                <div class="result-item"><span>📦 Vật liệu</span><strong>${escapeHtml(result.materials)}</strong></div>
                            </div>
                            <button class="btn-primary" onclick="IFCViewer._showViewer('sample_building.ifc')" style="margin-top:12px;width:100%">
                                🏗️ Xem mô hình 3D
                            </button>
                        </div>
                    `;
                }, 500);
            } else {
                // File can't be fetched from frontend — just show success
                progressFill.style.width = '100%';
                progressText.textContent = 'Hoàn tất!';
                setTimeout(() => {
                    progressDiv.classList.add('hidden');
                    resultDiv.classList.remove('hidden');
                    resultDiv.innerHTML = `
                        <div class="upload-success">
                            <h4>✅ Mô hình mẫu đã được tạo trên server</h4>
                            <p>Tòa nhà văn phòng 3 tầng với tường, cột, sàn, cửa, cửa sổ</p>
                            <p style="font-size:0.8rem;color:var(--text-muted);margin-top:8px">
                                Chạy ingest bằng CLI: <code>docker exec bim-backend python scripts/ingest_ifc.py --ifc data/ifc/sample_building.ifc</code>
                            </p>
                            <button class="btn-primary" onclick="document.getElementById('ifc-upload-modal').classList.add('hidden');IFCViewer.loadStats()" style="margin-top:12px;width:100%">
                                📊 Xem thống kê
                            </button>
                        </div>
                    `;
                }, 500);
            }

        } catch (err) {
            progressDiv.classList.add('hidden');
            dropzone.classList.remove('hidden');
            sampleBtn.textContent = '❌ Lỗi: ' + err.message;
            setTimeout(() => {
                sampleBtn.disabled = false;
                sampleBtn.textContent = '🏢 Tạo mô hình mẫu (3 tầng văn phòng)';
            }, 3000);
        }
    },

    // ===== 3D Viewer =====
    _showViewer(filename) {
        document.getElementById('ifc-upload-modal').classList.add('hidden');
        const panel = document.getElementById('ifc-viewer-panel');
        panel.classList.remove('hidden');
        this.loadStats();
        this._init3D();
    },

    async loadStats() {
        try {
            const stats = await API.getIFCStats();
            const div = document.getElementById('ifc-stats');
            if (!div || !stats.building) return;

            let html = `<span class="stat-chip">${escapeHtml(stats.building)}</span>`;
            if (stats.total_elements) html += `<span class="stat-chip">${escapeHtml(stats.total_elements)} cấu kiện</span>`;
            if (stats.storeys) html += `<span class="stat-chip">${escapeHtml(stats.storeys.length)} tầng</span>`;
            div.innerHTML = html;

            // Legend
            const legendDiv = document.getElementById('ifc-legend');
            if (legendDiv && stats.element_counts) {
                const colors = {
                    'Wall': '#90CAF9', 'Column': '#EF5350', 'Beam': '#FF9800',
                    'Slab': '#78909C', 'Door': '#8D6E63', 'Window': '#4FC3F7', 'Space': '#A5D6A7',
                };
                legendDiv.innerHTML = Object.entries(stats.element_counts).map(([type, count]) =>
                    `<span class="legend-item"><span class="legend-dot" style="background:${escapeHtml(colors[type] || '#bbb')}"></span>${escapeHtml(type)}: ${escapeHtml(count)}</span>`
                ).join('');
            }

            // Init 3D with simple building
            if (stats.storeys && stats.storeys.length > 0) {
                this._init3D(stats);
            }
        } catch (e) {
            console.error('IFC stats failed:', e);
        }
    },

    _init3D(stats, skipSimpleBuild = false) {
        const container = document.getElementById('ifc-3d-container');
        if (!container || !window.THREE) return;

        // Clear previous
        if (this.animationId) cancelAnimationFrame(this.animationId);
        container.innerHTML = '';

        // Setup scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x0d1117);
        this.scene.fog = new THREE.Fog(0x0d1117, 40, 80);

        // Camera
        const w = container.clientWidth || 400;
        const h = container.clientHeight || 300;
        this.camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 200);
        this.camera.position.set(22, 18, 22);

        // Renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.shadowMap.enabled = true;
        container.appendChild(this.renderer.domElement);

        // OrbitControls — interactive 3D navigation
        if (THREE.OrbitControls) {
            this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
            this.controls.enableDamping = true;
            this.controls.dampingFactor = 0.08;
            this.controls.rotateSpeed = 0.8;
            this.controls.zoomSpeed = 1.2;
            this.controls.panSpeed = 0.8;
            this.controls.target.set(6, 5, 4);
            this.controls.autoRotate = true;
            this.controls.autoRotateSpeed = 1.0;
            this.controls.minDistance = 5;
            this.controls.maxDistance = 60;
            this.controls.maxPolarAngle = Math.PI / 2 + 0.3;
            this.controls.update();

            // Pause auto-rotate on user interaction, resume after 3s idle
            let idleTimer = null;
            this.controls.addEventListener('start', () => {
                this.controls.autoRotate = false;
                if (idleTimer) clearTimeout(idleTimer);
            });
            this.controls.addEventListener('end', () => {
                idleTimer = setTimeout(() => {
                    this.controls.autoRotate = true;
                }, 3000);
            });
        } else {
            this.camera.lookAt(6, 5, 4);
        }

        // Lights
        const ambient = new THREE.AmbientLight(0x404060, 0.6);
        this.scene.add(ambient);

        const directional = new THREE.DirectionalLight(0xffffff, 0.8);
        directional.position.set(10, 20, 10);
        directional.castShadow = true;
        this.scene.add(directional);

        const point = new THREE.PointLight(0x3b82f6, 0.3, 50);
        point.position.set(6, 12, 4);
        this.scene.add(point);

        // Ground grid
        const grid = new THREE.GridHelper(30, 30, 0x1a1a2e, 0x1a1a2e);
        grid.position.y = -0.01;
        this.scene.add(grid);

        // Build simple 3D model
        this._meshList = [];
        this._elementCounts = {};
        if (!skipSimpleBuild) {
            this._buildSimpleModel(stats);
        }

        // Raycaster for element selection
        this._raycaster = new THREE.Raycaster();
        this._mouse = new THREE.Vector2();
        this.renderer.domElement.addEventListener('click', (e) => this._onElementClick(e));

        // Properties panel close button
        document.getElementById('props-close')?.addEventListener('click', () => {
            this._deselectElement();
            document.getElementById('element-props-panel')?.classList.add('hidden');
        });

        // Animate
        const animate = () => {
            this.animationId = requestAnimationFrame(animate);
            if (this.controls) this.controls.update();
            this.renderer.render(this.scene, this.camera);
        };
        animate();

        // Resize handler
        const resizeObserver = new ResizeObserver(() => {
            const nw = container.clientWidth;
            const nh = container.clientHeight;
            this.camera.aspect = nw / nh;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(nw, nh);
        });
        resizeObserver.observe(container);

        // Double-click to reset view
        this.renderer.domElement.addEventListener('dblclick', () => {
            if (this.controls) {
                this.controls.target.set(this._cx || 6, this._cy || 5, this._cz || 4);
                this.camera.position.set((this._cx || 6) + 16, (this._cy || 5) + 13, (this._cz || 4) + 16);
                this.controls.autoRotate = true;
                this.controls.update();
            }
        });
    },

    /** Show 3D from design spec (called by "Xem 3D" button). */
    async _showDesignModel(specJson, filename) {
        const spec = typeof specJson === 'string' ? JSON.parse(specJson) : specJson;
        this._currentFilename = filename || null;
        this._currentSpec = spec;
        const panel = document.getElementById('ifc-viewer-panel');
        panel.classList.remove('hidden');
        this._init3D(null, true);

        // Try loading real IFC geometry from backend
        if (filename) {
            try {
                const data = await API.getIFCGeometry(filename);
                if (data && data.meshes && data.meshes.length > 0) {
                    this._loadRealGeometry(data);
                    this._bindToolbar();
                    return;
                }
            } catch (e) {
                console.warn('IFC geometry fetch failed, using fallback:', e);
            }
        }

        // Fallback: use parametric model
        this._buildFromSpec(spec);
        this._bindToolbar();
    },

    /** Load real IFC geometry from backend-extracted mesh data. */
    _loadRealGeometry(data) {
        if (!this.scene) return;
        this._meshList = [];
        this._elementCounts = {};

        const stats = data.stats || {};
        const bmin = stats.bbox_min || [0,0,0];
        const bmax = stats.bbox_max || [10,10,10];

        // IFC uses mm, convert to meters for Three.js
        const scale = 0.001;
        const cx = (bmin[0] + bmax[0]) / 2 * scale;
        const cy = (bmin[2] + bmax[2]) / 2 * scale;  // IFC Z → Three.js Y
        const cz = (bmin[1] + bmax[1]) / 2 * scale;  // IFC Y → Three.js Z
        this._cx = cx; this._cy = cy; this._cz = cz;

        for (const mesh of data.meshes) {
            const verts = mesh.v;
            const faces = mesh.f;
            const color = mesh.c;
            const opacity = mesh.o;
            const meta = mesh.m;

            if (!verts || verts.length < 9 || !faces || faces.length < 3) continue;

            // Build BufferGeometry
            const positions = new Float32Array(faces.length * 3);
            for (let i = 0; i < faces.length; i++) {
                const vi = faces[i] * 3;
                // IFC coords: X,Y,Z → Three.js: X, Z(up), Y
                positions[i * 3]     = verts[vi]     * scale;
                positions[i * 3 + 1] = verts[vi + 2] * scale;  // IFC Z → up
                positions[i * 3 + 2] = verts[vi + 1] * scale;  // IFC Y → depth
            }

            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
            geo.computeVertexNormals();

            const hexColor = (Math.round(color[0]*255) << 16) | (Math.round(color[1]*255) << 8) | Math.round(color[2]*255);
            const mat = new THREE.MeshPhongMaterial({
                color: hexColor,
                transparent: opacity < 1,
                opacity: opacity,
                side: THREE.DoubleSide,
                flatShading: true,
            });

            const obj = new THREE.Mesh(geo, mat);
            obj.castShadow = true;
            obj.receiveShadow = true;

            // Attach metadata for properties panel
            if (meta) {
                // Compute bounding box for dimensions
                geo.computeBoundingBox();
                const bb = geo.boundingBox;
                const w = bb.max.x - bb.min.x;
                const h = bb.max.y - bb.min.y;
                const d = bb.max.z - bb.min.z;
                const center = new THREE.Vector3();
                bb.getCenter(center);

                obj.userData.bim = {
                    ...meta,
                    width: w, height: h, depth: d,
                    x: center.x, y: center.y, z: center.z,
                };
                this._meshList.push(obj);

                const t = meta.type || 'Other';
                this._elementCounts[t] = (this._elementCounts[t] || 0) + 1;
            }

            this.scene.add(obj);
        }

        // Ground
        const gs = Math.max(bmax[0]-bmin[0], bmax[1]-bmin[1]) * scale * 2;
        const ground = new THREE.Mesh(
            new THREE.PlaneGeometry(gs, gs),
            new THREE.MeshPhongMaterial({color: 0x4CAF50, transparent: true, opacity: 0.3})
        );
        ground.rotation.x = -Math.PI / 2;
        ground.position.set(cx, -0.01, cz);
        ground.receiveShadow = true;
        this.scene.add(ground);

        // Camera
        const maxDim = Math.max(bmax[0]-bmin[0], bmax[1]-bmin[1], bmax[2]-bmin[2]) * scale;
        this.camera.position.set(cx + maxDim * 0.8, cy + maxDim * 0.6, cz + maxDim * 0.8);
        if (this.controls) {
            this.controls.target.set(cx, cy, cz);
            this.controls.update();
        }

        // Stats overlay — use actual spec from _currentSpec
        const actualSpec = this._currentSpec || {storey_height: 3500};
        const N = stats.storeys?.length || 0;
        this._showStatsOverlay(actualSpec, N,
            (bmax[0]-bmin[0]) * scale, (bmax[1]-bmin[1]) * scale, 0);
        this._showModelStats(actualSpec, N,
            (bmax[0]-bmin[0]) * scale, (bmax[1]-bmin[1]) * scale, 0);
    },

    _toolbarBound: false,
    _bindToolbar() {
        if (this._toolbarBound) return;
        this._toolbarBound = true;

        // Close
        document.getElementById('close-viewer-btn')?.addEventListener('click', () => {
            App._closeDesign3D();
        });

        // Download IFC
        document.getElementById('viewer-download')?.addEventListener('click', () => {
            if (this._currentFilename) {
                const url = API.getIFCDownloadUrl(this._currentFilename);
                const a = document.createElement('a');
                a.href = url; a.download = this._currentFilename;
                a.click();
            }
        });

        // Screenshot
        document.getElementById('viewer-screenshot')?.addEventListener('click', () => {
            if (!this.renderer) return;
            this.renderer.render(this.scene, this.camera);
            const dataUrl = this.renderer.domElement.toDataURL('image/png');
            const a = document.createElement('a');
            a.href = dataUrl;
            a.download = `BIM_3D_${new Date().toISOString().slice(0,10)}.png`;
            a.click();
        });

        // Wireframe toggle
        document.getElementById('viewer-wireframe')?.addEventListener('click', (e) => {
            const btn = e.currentTarget;
            btn.classList.toggle('active');
            const wireOn = btn.classList.contains('active');
            this.scene?.traverse(obj => {
                if (obj.isMesh && obj.material) {
                    obj.material.wireframe = wireOn;
                }
            });
        });

        // Reset camera
        document.getElementById('viewer-reset')?.addEventListener('click', () => {
            if (!this._currentSpec) return;
            const mm = v => (v||0)/1000;
            const L = mm(this._currentSpec.footprint_length||12000);
            const W = mm(this._currentSpec.footprint_width||8000);
            const N = this._currentSpec.num_storeys||3;
            const SH = mm(this._currentSpec.storey_height||3500);
            const md = Math.max(L, W, N * SH);
            this.camera.position.set(L + md*0.6, N*SH*0.8, W + md*0.6);
            if (this.controls) {
                this.controls.target.set(L/2, (N*SH)/2, W/2);
                this.controls.update();
            }
        });

        // Fullscreen toggle
        document.getElementById('viewer-fullscreen')?.addEventListener('click', (e) => {
            const panel = document.getElementById('ifc-viewer-panel');
            panel.classList.toggle('fullscreen');
            e.currentTarget.classList.toggle('active');
            // Re-render after layout change
            setTimeout(() => this._resize3D(), 100);
        });
    },

    _resize3D() {
        const container = document.getElementById('ifc-3d-container');
        if (!container || !this.renderer || !this.camera) return;
        const w = container.clientWidth, h = container.clientHeight;
        this.renderer.setSize(w, h);
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
    },


    _buildSimpleModel(stats) {
        this._meshList = [];
        this._elementCounts = {};
        this._buildFromSpec({
            num_storeys: stats?.storeys?.length || 3,
            storey_height: 3500, footprint_length: 12000, footprint_width: 8000,
            column_size: 400, column_spacing_x: 6000, column_spacing_y: 8000,
            doors_per_storey: 2, windows_per_storey: 3, num_staircases: 1,
            beam_height: 400, beam_width: 200,
            has_foundation: false, has_roof_railing: false,
            railing_height: 1100, window_sill_height: 900,
        });
    },

    /** Build realistic 3D model from BuildingSpec (mm → m). */
    _buildFromSpec(spec) {
        if (!this.scene) return;
        if (spec.structure_type === 'bridge' || spec.total_length) {
            this._buildBridgeFromSpec(spec);
            return;
        }
        const C = {
            Wall: 0xE8E0D4, WallInt: 0xFAF3E8, Column: 0xB0B0B0, Beam: 0xA0A0A0,
            Slab: 0xC8C0B4, Door: 0x6D4C41, DoorFrame: 0x4E342E,
            WinGlass: 0x80D8FF, WinFrame: 0x37474F, Stair: 0xBCAAA4,
            StairRail: 0x455A64, Footing: 0x8D6E63, Railing: 0x607D8B,
            Ground: 0x4CAF50, Roof: 0x78909C,
        };
        const mm = (v) => (v || 0) / 1000;
        const L = mm(spec.footprint_length || 12000), W = mm(spec.footprint_width || 8000);
        const SH = mm(spec.storey_height || 3500), N = spec.num_storeys || 3;
        const colSize = mm(spec.column_size || 400), slabT = mm(spec.slab_thickness || 200);
        const wallT = mm(spec.wall_thickness || 200);
        const bh = mm(spec.beam_height || 400), bw = mm(spec.beam_width || 200);
        const colSX = mm(spec.column_spacing_x || 6000), colSY = mm(spec.column_spacing_y || 8000);
        const nDoors = spec.doors_per_storey || 2, nWindows = spec.windows_per_storey || 3;
        const nStairs = spec.num_staircases || 1;
        const sillH = mm(spec.window_sill_height || 900), railH = mm(spec.railing_height || 1100);
        const corrW = mm(spec.corridor_width || 1800);
        const doorW = 0.9, doorH = 2.1, winW = 1.2, winH = 1.5;

        this._cx = L / 2; this._cy = (N * SH) / 2; this._cz = W / 2;

        // Ground
        const gs = Math.max(L, W) * 2;
        this._addBox(gs, 0.05, gs, L/2, -0.025, W/2, C.Ground, 0.5);

        // Column grid
        const nx = Math.max(2, Math.floor(L / colSX) + 1);
        const ny = Math.max(2, Math.floor(W / colSY) + 1);
        const colGrid = [];
        for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++)
            colGrid.push([Math.min(i * colSX, L), Math.min(j * colSY, W)]);

        const doorXs = [], winXs = [];
        for (let d = 0; d < nDoors; d++) doorXs.push(L / (nDoors + 1) * (d + 1));
        for (let w = 0; w < nWindows; w++) winXs.push(L / (nWindows + 1) * (w + 1));

        for (let s = 0; s < N; s++) {
            const y = s * SH, wallH = SH - slabT, wb = y + slabT;
            const sn = `Tầng ${s+1}`;
            const wMat = spec.wall_material || 'Gạch ống 200mm';
            const cMat = spec.column_material || 'BTCT B25';
            const bMat = spec.beam_material || 'BTCT B25';
            const sMat = spec.slab_material || 'BTCT B25';

            // Slab
            this._addBox(L, slabT, W, L/2, y + slabT/2, W/2, C.Slab, 0.95,
                {type:'Slab', name:`Sàn ${sn}`, storey:sn, material:sMat, properties:{LoadBearing:'Yes', FireRating:'REI 120'}});

            // North wall — doors
            this._wallWithHoles(0, wb, 0, L, wallH, wallT, C.Wall, 0.85, doorXs, doorW, doorH, 0, {type:'Wall', storey:sn, material:wMat, isExterior:true});
            // South wall — windows
            this._wallWithHoles(0, wb, W - wallT, L, wallH, wallT, C.Wall, 0.85, winXs, winW, winH, sillH, {type:'Wall', storey:sn, material:wMat, isExterior:true});
            // East/West
            this._addBox(wallT, wallH, W, wallT/2, wb + wallH/2, W/2, C.Wall, 0.6,
                {type:'Wall', name:`Tường Tây ${sn}`, storey:sn, material:wMat, properties:{IsExternal:'Yes', FireRating:'REI 120'}});
            this._addBox(wallT, wallH, W, L - wallT/2, wb + wallH/2, W/2, C.Wall, 0.6,
                {type:'Wall', name:`Tường Đông ${sn}`, storey:sn, material:wMat, properties:{IsExternal:'Yes', FireRating:'REI 120'}});

            // Corridor walls
            if (W > 6) {
                const rd = (W - corrW) / 2;
                this._addBox(L - wallT*2, wallH*0.95, wallT*0.5, L/2, wb + wallH*0.475, rd, C.WallInt, 0.2,
                    {type:'Wall', name:`Tường hành lang N ${sn}`, storey:sn, material:wMat, properties:{IsExternal:'No'}});
                this._addBox(L - wallT*2, wallH*0.95, wallT*0.5, L/2, wb + wallH*0.475, rd + corrW, C.WallInt, 0.2,
                    {type:'Wall', name:`Tường hành lang S ${sn}`, storey:sn, material:wMat, properties:{IsExternal:'No'}});
            }

            // Doors with frames
            for (let di = 0; di < doorXs.length; di++) {
                const dx = doorXs[di];
                this._addBox(doorW - 0.04, doorH - 0.04, 0.04, dx, wb + doorH/2, 0, C.Door, 0.9,
                    {type:'Door', name:`Cửa D${di+1} ${sn}`, storey:sn, material:'Gỗ công nghiệp', properties:{FireRating:'EI 60', Width:'900mm', Height:'2100mm'}});
                this._addBox(0.05, doorH, 0.08, dx - doorW/2, wb + doorH/2, 0, C.DoorFrame, 1);
                this._addBox(0.05, doorH, 0.08, dx + doorW/2, wb + doorH/2, 0, C.DoorFrame, 1);
                this._addBox(doorW + 0.06, 0.05, 0.08, dx, wb + doorH, 0, C.DoorFrame, 1);
            }

            // Windows with glass + frames
            for (let wi = 0; wi < winXs.length; wi++) {
                const wx = winXs[wi];
                const wBot = wb + sillH;
                this._addBox(winW - 0.06, winH - 0.06, 0.01, wx, wBot + winH/2, W, C.WinGlass, 0.25,
                    {type:'Window', name:`Cửa sổ W${wi+1} ${sn}`, storey:sn, material:spec.window_material||'Kính cường lực 10mm', properties:{Width:'1200mm', Height:'1500mm', SillHeight:`${(sillH*1000).toFixed(0)}mm`}});
                this._addBox(winW + 0.1, 0.04, 0.12, wx, wBot - 0.02, W, C.WinFrame, 1);
                this._addBox(0.04, winH, 0.06, wx - winW/2, wBot + winH/2, W, C.WinFrame, 1);
                this._addBox(0.04, winH, 0.06, wx + winW/2, wBot + winH/2, W, C.WinFrame, 1);
                this._addBox(winW, 0.04, 0.06, wx, wBot, W, C.WinFrame, 1);
                this._addBox(winW, 0.04, 0.06, wx, wBot + winH, W, C.WinFrame, 1);
                this._addBox(winW - 0.06, 0.025, 0.04, wx, wBot + winH*0.55, W, C.WinFrame, 1);
            }

            // Columns
            for (let ci = 0; ci < colGrid.length; ci++) {
                const [cx, cz] = colGrid[ci];
                this._addBox(colSize, SH, colSize, cx, y + SH/2, cz, C.Column, 1,
                    {type:'Column', name:`Cột C${ci+1} ${sn}`, storey:sn, material:cMat, properties:{LoadBearing:'Yes', Size:`${(colSize*1000).toFixed(0)}x${(colSize*1000).toFixed(0)}mm`}});
            }

            // Beams X
            let bIdx = 0;
            for (let j = 0; j < ny; j++) for (let i = 0; i < nx - 1; i++) {
                const x1 = Math.min(i * colSX, L), x2 = Math.min((i+1) * colSX, L);
                const z = Math.min(j * colSY, W), bl = x2 - x1;
                if (bl > 0.5) {
                    bIdx++;
                    this._addBox(bl, bh, bw, (x1+x2)/2, y + SH - bh/2, z, C.Beam, 0.9,
                        {type:'Beam', name:`Dầm BX${bIdx} ${sn}`, storey:sn, material:bMat, properties:{LoadBearing:'Yes', Span:`${(bl*1000).toFixed(0)}mm`}});
                }
            }
            // Beams Y
            for (let i = 0; i < nx; i++) for (let j = 0; j < ny - 1; j++) {
                const x = Math.min(i * colSX, L);
                const z1 = Math.min(j * colSY, W), z2 = Math.min((j+1) * colSY, W), bl = z2 - z1;
                if (bl > 0.5) {
                    bIdx++;
                    this._addBox(bw, bh, bl, x, y + SH - bh/2, (z1+z2)/2, C.Beam, 0.9,
                        {type:'Beam', name:`Dầm BY${bIdx} ${sn}`, storey:sn, material:bMat, properties:{LoadBearing:'Yes', Span:`${(bl*1000).toFixed(0)}mm`}});
                }
            }

            // Stairs — 2-flight U-turn with solid flights
            for (let st = 0; st < nStairs; st++) {
                const sx = st === 0 ? L - 2.6 : 0.2;
                const sz = W/2 - 1.2;
                const stW = 1.1;          // flight width
                const stairDepth = 2.4;   // total depth (Z) for both flights
                const halfH = (SH - slabT) / 2;  // half storey clear height
                const flightLen = stairDepth * 0.45;  // run length per flight
                const landingD = stairDepth * 0.1;

                // Flight 1 (going up, z direction)
                this._addBox(stW, 0.18, flightLen, sx + stW/2, wb + halfH/2, sz + flightLen/2, C.Stair, 0.95,
                    {type:'Stair', name:`Thang CT${st+1} vế 1 ${sn}`, storey:sn, material:'BTCT B25',
                     properties:{Type:'2 vế chữ U', Risers: Math.round(SH/0.17), Width:`${(stW*1000).toFixed(0)}mm`}});

                // Landing platform
                const landY = wb + halfH;
                this._addBox(stW * 2.2, 0.15, stairDepth * 0.3,
                    sx + stW * 1.1, landY, sz + flightLen + landingD, C.Stair, 0.95);

                // Flight 2 (going up, -z direction, next to flight 1)
                this._addBox(stW, 0.18, flightLen,
                    sx + stW * 1.7, landY + halfH/2, sz + flightLen/2, C.Stair, 0.95);

                // Stair enclosure walls (clean, full height)
                const encW = stW * 2.4;
                const encD = stairDepth * 0.85;
                // Left wall
                this._addBox(0.06, SH - slabT, encD, sx - 0.03, wb + (SH-slabT)/2, sz + encD/2, C.WallInt, 0.15);
                // Right wall
                this._addBox(0.06, SH - slabT, encD, sx + encW, wb + (SH-slabT)/2, sz + encD/2, C.WallInt, 0.15);
                // Back wall
                this._addBox(encW, SH - slabT, 0.06, sx + encW/2, wb + (SH-slabT)/2, sz + encD, C.WallInt, 0.15);
            }

            // Footings
            if (s === 0 && spec.has_foundation) {
                for (let ci = 0; ci < colGrid.length; ci++) {
                    const [cx, cz] = colGrid[ci];
                    const fs = colSize * 2.5;
                    this._addBox(fs, 0.5, fs, cx, -0.25, cz, C.Footing, 0.85,
                        {type:'Footing', name:`Móng M${ci+1}`, storey:'Móng', material:cMat, properties:{Type:'Móng đơn', Size:`${(fs*1000).toFixed(0)}x${(fs*1000).toFixed(0)}mm`}});
                }
            }
        }

        // Roof
        const rY = N * SH;
        this._addBox(L + 0.6, 0.25, W + 0.6, L/2, rY + 0.125, W/2, C.Roof, 0.95,
            {type:'Slab', name:'Mái', storey:'Mái', material:spec.slab_material||'BTCT B25', properties:{Type:'Sàn mái', Thickness:'250mm'}});
        this._addBox(L + 0.3, 0.02, W + 0.3, L/2, rY + 0.27, W/2, 0x455A64, 0.4);

        // Roof railings with posts
        if (spec.has_roof_railing) {
            const ry = rY + 0.3;
            for (const rh of [railH, railH*0.5]) {
                this._addBox(L, 0.04, 0.04, L/2, ry+rh, 0, C.Railing, 0.9,
                    rh === railH ? {type:'Railing', name:'Lan can mái Bắc', storey:'Mái', material:'Thép', properties:{Height:`${(railH*1000).toFixed(0)}mm`}} : null);
                this._addBox(L, 0.04, 0.04, L/2, ry+rh, W, C.Railing, 0.9,
                    rh === railH ? {type:'Railing', name:'Lan can mái Nam', storey:'Mái', material:'Thép'} : null);
                this._addBox(0.04, 0.04, W, 0, ry+rh, W/2, C.Railing, 0.9);
                this._addBox(0.04, 0.04, W, L, ry+rh, W/2, C.Railing, 0.9);
            }
            for (let p = 0; p <= L; p += 1.5) {
                this._addBox(0.04, railH, 0.04, p, ry+railH/2, 0, C.Railing, 0.9);
                this._addBox(0.04, railH, 0.04, p, ry+railH/2, W, C.Railing, 0.9);
            }
            for (let p = 0; p <= W; p += 1.5) {
                this._addBox(0.04, railH, 0.04, 0, ry+railH/2, p, C.Railing, 0.9);
                this._addBox(0.04, railH, 0.04, L, ry+railH/2, p, C.Railing, 0.9);
            }
        }

        // Camera
        const md = Math.max(L, W, N * SH);
        this.camera.position.set(L + md*0.6, N * SH * 0.8, W + md*0.6);
        if (this.controls) { this.controls.target.set(this._cx, this._cy, this._cz); this.controls.update(); }
        this._showStatsOverlay(spec, N, L, W, colGrid.length);
        this._showModelStats(spec, N, L, W, colGrid.length);
    },

    _buildBridgeFromSpec(spec) {
        if (!this.scene) return;
        const C = {
            Pier: 0xB0B0B0,     // Column (B0B0B0) - Trụ cầu
            Girder: 0xA0A0A0,   // Beam (A0A0A0) - Dầm cầu
            Deck: 0xC8BDB4,     // Slab (C8C0B4) - Bản mặt cầu
            Railing: 0x607D8B,  // Railing (607D8B) - Lan can
            Pile: 0x8D6E63,     // Footing/Pile (8D6E63) - Cọc/Móng
            Bearing: 0x4DB6AC,  // Gối cầu
            Water: 0x1E88E5,    // Nước
            Abutment: 0x90A4AE, // Mố cầu
            Lamp: 0xFFEB3B      // Đèn đường
        };
        const mm = (v) => (v || 0) / 1000;
        const L = mm(spec.total_length || 30000);  // e.g. 30m
        const W = mm(spec.deck_width || 12000);    // e.g. 12m
        const NumSpans = spec.num_spans || 3;
        const SpanLen = L / NumSpans;
        const DeckY = mm(spec.pier_height || spec.height || 6000); // Height of deck from ground/water
        const DeckThickness = mm(spec.deck_thickness || 250);
        const GirderHeight = mm(spec.girder_height || 1500);
        const NumLanes = spec.num_lanes || 2;
        const GirderType = spec.girder_type || 'I';

        this._cx = L / 2; this._cy = DeckY / 2; this._cz = W / 2;

        // 1. Water channel under the bridge spans
        const waterW = L * 1.5;
        const waterD = W * 3;
        this._addBox(waterW, 0.2, waterD, L/2, 0.1, W/2, C.Water, 0.4, 
            {type:'Ground', name:'Sông tự nhiên', storey:'Nền', material:'Nước', properties:{Depth:'5m'}});

        // 2. Abutments
        const abW = 2.0;
        const abH = DeckY - DeckThickness - GirderHeight;
        // Left Abutment M1
        this._addBox(abW, abH, W, abW/2, abH/2, W/2, C.Abutment, 0.95,
            {type:'Footing', name:'Mố cầu M1', storey:'Hạ bộ', material:'BTCT B30', properties:{Type:'Mố chữ U', LoadBearing:'Yes'}});
        this._addBox(0.3, abH + 1.5, 3.0, 0.15, (abH + 1.5)/2, W - 1.5, C.Abutment, 0.95);
        this._addBox(0.3, abH + 1.5, 3.0, 0.15, (abH + 1.5)/2, 1.5, C.Abutment, 0.95);

        // Right Abutment M2
        this._addBox(abW, abH, W, L - abW/2, abH/2, W/2, C.Abutment, 0.95,
            {type:'Footing', name:'Mố cầu M2', storey:'Hạ bộ', material:'BTCT B30', properties:{Type:'Mố chữ U', LoadBearing:'Yes'}});
        this._addBox(0.3, abH + 1.5, 3.0, L - 0.15, (abH + 1.5)/2, W - 1.5, C.Abutment, 0.95);
        this._addBox(0.3, abH + 1.5, 3.0, L - 0.15, (abH + 1.5)/2, 1.5, C.Abutment, 0.95);

        // 3. Piers
        for (let i = 1; i < NumSpans; i++) {
            const x = i * SpanLen;
            const pierName = `Trụ cầu T${i}`;
            
            // Xà mũ trụ (Pier Cap)
            const capW = 1.8;
            const capH = 1.2;
            const capD = W - 1.0;
            const capY = DeckY - DeckThickness - GirderHeight - capH/2;
            this._addBox(capW, capH, capD, x, capY, W/2, C.Pier, 0.95,
                {type:'Column', name:`Xà mũ ${pierName}`, storey:'Hạ bộ', material:'BTCT B35', properties:{Dimensions:`${capW}x${capH}x${capD}m`}});

            // Thân trụ (Pier Columns)
            const colW = 1.2;
            const colH = capY - capH/2 - 1.5;
            const colD = 1.2;
            const colY = 1.5 + colH/2;
            this._addBox(colW, colH, colD, x, colY, W/3, C.Pier, 0.95,
                {type:'Column', name:`Thân trụ ${pierName} - Trái`, storey:'Hạ bộ', material:'BTCT B35'});
            this._addBox(colW, colH, colD, x, colY, 2*W/3, C.Pier, 0.95,
                {type:'Column', name:`Thân trụ ${pierName} - Phải`, storey:'Hạ bộ', material:'BTCT B35'});

            // Bệ móng (Pile Cap)
            const footingW = 3.5;
            const footingH = 1.5;
            const footingD = W - 0.5;
            this._addBox(footingW, footingH, footingD, x, footingH/2, W/2, C.Pile, 0.95,
                {type:'Footing', name:`Bệ móng ${pierName}`, storey:'Móng', material:'BTCT B30', properties:{Dimensions:`${footingW}x${footingH}x${footingD}m`}});

            // Cọc khoan nhồi (Piles)
            const pileW = 1.0;
            const pileH = 8.0;
            const pileD = 1.0;
            const pileZs = [W/4, W/2, 3*W/4];
            const pileXs = [x - 1.0, x + 1.0];
            let pIdx = 1;
            for (const pz of pileZs) {
                for (const px of pileXs) {
                    this._addBox(pileW, pileH, pileD, px, -pileH/2, pz, C.Pile, 0.9,
                        {type:'Footing', name:`Cọc nhồi C${pIdx++} ${pierName}`, storey:'Móng', material:'BTCT B30', properties:{Diameter:'1000mm', Length:'15m'}});
                }
            }
        }

        // 4. Girders & Bearings
        const numGirders = 4;
        const girderSpacing = W / (numGirders + 1);
        
        for (let s = 1; s <= NumSpans; s++) {
            const xStart = (s - 1) * SpanLen;
            const xEnd = s * SpanLen;
            const xMid = (xStart + xEnd) / 2;
            const gLength = SpanLen - 0.4;

            for (let g = 1; g <= numGirders; g++) {
                const z = g * girderSpacing;
                const gName = `Dầm dọc D${g} - Nhịp ${s}`;

                // Girders
                const gY = DeckY - DeckThickness - GirderHeight/2;
                this._addBox(gLength, GirderHeight, 0.4, xMid, gY, z, C.Girder, 0.95,
                    {type:'Beam', name:gName, storey:'Thượng bộ', material:'BTCT Dự ứng lực B45', properties:{Type:`Dầm ${GirderType}`, Height:`${GirderHeight*1000}mm`, LoadBearing:'Yes'}});

                // Bearings
                const bearH = 0.15;
                const bearY = DeckY - DeckThickness - GirderHeight - bearH/2;
                this._addBox(0.4, bearH, 0.4, xStart + 0.3, bearY, z, C.Bearing, 1.0,
                    {type:'BuildingElementProxy', name:`Gối cầu D${g} - Trái - Nhịp ${s}`, storey:'Thượng bộ', material:'Cao su cốt bản thép', properties:{Type:'Gối chậu di động'}});
                this._addBox(0.4, bearH, 0.4, xEnd - 0.3, bearY, z, C.Bearing, 1.0,
                    {type:'BuildingElementProxy', name:`Gối cầu D${g} - Phải - Nhịp ${s}`, storey:'Thượng bộ', material:'Cao su cốt bản thép', properties:{Type:'Gối cố định'}});
            }
        }

        // 5. Deck Slab
        const deckH = DeckThickness;
        const deckY = DeckY - deckH/2;
        this._addBox(L, deckH, W, L/2, deckY, W/2, C.Deck, 0.95,
            {type:'Slab', name:'Bản mặt cầu', storey:'Thượng bộ', material:'BTCT B30', properties:{Width:`${W*1000}mm`, Thickness:`${deckH*1000}mm`, Area:`${(L*W).toFixed(0)}m²`}});

        // Road markings
        this._addBox(L, 0.01, 0.1, L/2, DeckY + 0.005, W/2, 0xFFFFFF, 1.0);
        this._addBox(L, 0.01, 0.05, L/2, DeckY + 0.005, W/4, 0xFFFFFF, 0.8);
        this._addBox(L, 0.01, 0.05, L/2, DeckY + 0.005, 3*W/4, 0xFFFFFF, 0.8);

        // 6. Railings
        const railPostH = 1.0;
        const railPostY = DeckY + railPostH/2;
        
        this._addBox(L, 0.4, 0.3, L/2, DeckY + 0.2, 0.15, C.Railing, 0.95,
            {type:'Railing', name:'Lan can phòng hộ biên Trái', storey:'Thượng bộ', material:'Thép mạ kẽm', properties:{Height:'1000mm'}});
        this._addBox(L, 0.05, 0.05, L/2, DeckY + 0.8, 0.15, 0x37474F, 1.0);
        this._addBox(L, 0.03, 0.03, L/2, DeckY + 0.5, 0.15, 0x37474F, 1.0);

        this._addBox(L, 0.4, 0.3, L/2, DeckY + 0.2, W - 0.15, C.Railing, 0.95,
            {type:'Railing', name:'Lan can phòng hộ biên Phải', storey:'Thượng bộ', material:'Thép mạ kẽm', properties:{Height:'1000mm'}});
        this._addBox(L, 0.05, 0.05, L/2, DeckY + 0.8, W - 0.15, 0x37474F, 1.0);
        this._addBox(L, 0.03, 0.03, L/2, DeckY + 0.5, W - 0.15, 0x37474F, 1.0);

        for (let x = 0; x <= L; x += 2.0) {
            this._addBox(0.08, railPostH, 0.08, x, railPostY, 0.15, C.Railing, 1.0);
            this._addBox(0.08, railPostH, 0.08, x, railPostY, W - 0.15, C.Railing, 1.0);
        }

        // 7. Lighting Posts
        const lampPostH = 4.5;
        const lampPostD = 0.1;
        for (let x = 4.0; x < L; x += 10.0) {
            const zLeft = 0.15;
            const zRight = W - 0.15;
            
            this._addBox(lampPostD, lampPostH, lampPostD, x, DeckY + lampPostH/2, zLeft, 0x455A64, 1.0,
                {type:'BuildingElementProxy', name:`Cột đèn chiếu sáng nhịp`, storey:'Thượng bộ', material:'Thép mạ kẽm nhúng nóng'});
            this._addBox(1.2, 0.06, 0.06, x + 0.5, DeckY + lampPostH, zLeft + 0.5, 0x455A64, 1.0);
            this._addBox(0.4, 0.1, 0.2, x + 0.9, DeckY + lampPostH - 0.05, zLeft + 0.9, C.Lamp, 1.0);

            this._addBox(lampPostD, lampPostH, lampPostD, x, DeckY + lampPostH/2, zRight, 0x455A64, 1.0,
                {type:'BuildingElementProxy', name:`Cột đèn chiếu sáng nhịp`, storey:'Thượng bộ', material:'Thép mạ kẽm nhúng nóng'});
            this._addBox(1.2, 0.06, 0.06, x + 0.5, DeckY + lampPostH, zRight - 0.5, 0x455A64, 1.0);
            this._addBox(0.4, 0.1, 0.2, x + 0.9, DeckY + lampPostH - 0.05, zRight - 0.9, C.Lamp, 1.0);
        }

        const md = Math.max(L, W, DeckY);
        this.camera.position.set(L + md * 0.5, DeckY + md * 0.4, W + md * 0.5);
        if (this.controls) {
            this.controls.target.set(this._cx, this._cy, this._cz);
            this.controls.update();
        }

        this._showStatsOverlay(spec, NumSpans, L, W, 0);
        this._showModelStats(spec, NumSpans, L, W, 0);
    },

    /** Build wall segments around rectangular openings. */
    _wallWithHoles(x0, y0, z0, wLen, wH, wT, color, op, holes, hW, hH, hBot, meta) {
        const sorted = [...holes].sort((a, b) => a - b);
        let cur = 0;
        let segIdx = 0;
        for (const ox of sorted) {
            const os = ox - hW/2, oe = ox + hW/2;
            if (os > cur + 0.05) {
                segIdx++;
                const sl = os - cur;
                const segMeta = meta ? {...meta, name:`${meta.type === 'Wall' ? 'Tường' : meta.type} seg${segIdx} ${meta.storey}`, properties:{IsExternal: meta.isExterior ? 'Yes' : 'No', FireRating:'REI 120'}} : null;
                this._addBox(sl, wH, wT, x0 + cur + sl/2, y0 + wH/2, z0 + wT/2, color, op, segMeta);
            }
            const lH = wH - hBot - hH;
            if (lH > 0.05) this._addBox(hW + 0.1, lH, wT, x0 + ox, y0 + hBot + hH + lH/2, z0 + wT/2, color, op);
            if (hBot > 0.05) this._addBox(hW, hBot, wT, x0 + ox, y0 + hBot/2, z0 + wT/2, color, op);
            cur = oe;
        }
        if (wLen - cur > 0.05) {
            segIdx++;
            const sl = wLen - cur;
            const segMeta = meta ? {...meta, name:`${meta.type === 'Wall' ? 'Tường' : meta.type} seg${segIdx} ${meta.storey}`, properties:{IsExternal: meta.isExterior ? 'Yes' : 'No', FireRating:'REI 120'}} : null;
            this._addBox(sl, wH, wT, x0 + cur + sl/2, y0 + wH/2, z0 + wT/2, color, op, segMeta);
        }
    },

    _showStatsOverlay(spec, N, L, W, numCols) {
        const ct = document.getElementById('ifc-3d-container');
        if (!ct) return;
        let ex = ct.querySelector('.viewer-stats');
        if (ex) ex.remove();
        const d = document.createElement('div');
        d.className = 'viewer-stats';
        d.style.cssText = 'position:absolute;top:8px;left:8px;background:rgba(0,0,0,0.8);color:white;padding:10px 14px;border-radius:8px;font-size:11px;z-index:10;backdrop-filter:blur(4px);line-height:1.6;';

        const isBridge = spec.structure_type === 'bridge' || spec.bridge_name || spec.total_length;

        if (isBridge) {
            const bridgeType = spec.bridge_type === 'beam' ? 'Cầu dầm BTCT' :
                               spec.bridge_type === 'arch' ? 'Cầu vòm' :
                               spec.bridge_type || 'Cầu';
            d.innerHTML = `
                <div style="font-size:13px;font-weight:600">🌉 ${escapeHtml(spec.bridge_name || bridgeType)}</div>
                <div style="color:#90CAF9">${escapeHtml(bridgeType)} · ${escapeHtml(spec.num_spans || '?')} nhịp · ${escapeHtml(((spec.total_length||0)/1000).toFixed(0))}m</div>
                <div style="color:#aaa">Rộng ${escapeHtml(((spec.deck_width||0)/1000).toFixed(1))}m · ${escapeHtml(spec.num_lanes||'?')} làn xe · Dầm ${escapeHtml(spec.girder_type||'I')}</div>
                <div style="margin-top:4px;font-size:10px;color:#888">
                    <span style="color:#B0B0B0">■</span>Trụ
                    <span style="color:#A0A0A0">■</span>Dầm
                    <span style="color:#C8BDB4">■</span>Sàn
                    <span style="color:#617D8A">■</span>Lan can
                    <span style="color:#806852">■</span>Cọc
                    <span style="color:#5AA5A5">■</span>Gối
                </div>`;
        } else {
            d.innerHTML = `
                <div style="font-size:13px;font-weight:600">${escapeHtml(spec.building_name||'Tòa nhà')}</div>
                <div style="color:#90CAF9">${escapeHtml(spec.building_function||'')} · ${escapeHtml(N)} tầng · ${escapeHtml(L.toFixed(1))}×${escapeHtml(W.toFixed(1))}m</div>
                <div style="color:#aaa">Sàn ${escapeHtml((L*W).toFixed(0))}m² · Cột ${escapeHtml(numCols)}/tầng · ${escapeHtml(spec.num_staircases||1)} thang</div>
                <div style="margin-top:4px;font-size:10px;color:#888">
                    <span style="color:#E8E0D4">■</span>Tường
                    <span style="color:#B0B0B0">■</span>Cột
                    <span style="color:#A0A0A0">■</span>Dầm
                    <span style="color:#80D8FF">■</span>Kính
                    <span style="color:#6D4C41">■</span>Cửa
                    <span style="color:#BCAAA4">■</span>Thang
                </div>`;
        }
        ct.appendChild(d);
    },

    _hex(n) { return '#' + n.toString(16).padStart(6, '0'); },

    _addBox(w, h, d, x, y, z, color, opacity, meta) {
        if (w < 0.01 || h < 0.01 || d < 0.01) return;
        const geo = new THREE.BoxGeometry(w, h, d);
        const mat = new THREE.MeshPhongMaterial({ color, transparent: opacity < 1, opacity, side: THREE.DoubleSide });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(x, y, z);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        // Attach metadata for properties panel
        if (meta) {
            mesh.userData.bim = { ...meta, width: w, height: h, depth: d, x, y, z };
            this._meshList.push(mesh);
            // Count elements
            const t = meta.type || 'Other';
            this._elementCounts[t] = (this._elementCounts[t] || 0) + 1;
        }
        this.scene.add(mesh);
        if (opacity > 0.4) {
            const edges = new THREE.EdgesGeometry(geo);
            const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.08 }));
            line.position.copy(mesh.position);
            this.scene.add(line);
        }
    },

    // ===== Element Selection =====
    _onElementClick(event) {
        if (!this._raycaster || !this.camera) return;
        const container = document.getElementById('ifc-3d-container');
        if (!container) return;
        const rect = container.getBoundingClientRect();
        this._mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this._mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        this._raycaster.setFromCamera(this._mouse, this.camera);
        const hits = this._raycaster.intersectObjects(this._meshList, false);
        if (hits.length > 0) {
            const mesh = hits[0].object;
            if (mesh.userData.bim) {
                this._selectElement(mesh);
                return;
            }
        }
        // Clicked empty space — deselect
        this._deselectElement();
    },

    _selectElement(mesh) {
        // Restore previous selection
        this._deselectElement();
        // Highlight selected
        this._selectedMesh = mesh;
        this._originalMaterial = mesh.material.clone();
        mesh.material = new THREE.MeshPhongMaterial({
            color: 0x6366f1, emissive: 0x3b3bff, emissiveIntensity: 0.3,
            transparent: true, opacity: 0.9,
        });
        // Show properties panel
        this._showProperties(mesh.userData.bim);
    },

    _deselectElement() {
        if (this._selectedMesh && this._originalMaterial) {
            this._selectedMesh.material = this._originalMaterial;
            this._selectedMesh = null;
            this._originalMaterial = null;
        }
        // Remove indicator
        document.querySelector('.element-selected-indicator')?.remove();
    },

    _showProperties(bim) {
        const panel = document.getElementById('element-props-panel');
        const body = document.getElementById('props-body');
        const title = document.getElementById('props-title');
        if (!panel || !body) return;
        panel.classList.remove('hidden');
        const typeMap = { Wall:'Tường', Column:'Cột', Beam:'Dầm', Slab:'Sàn', Door:'Cửa đi',
            Window:'Cửa sổ', Stair:'Cầu thang', Railing:'Lan can', Footing:'Móng', Roof:'Mái', Ground:'Nền' };
        const typeName = typeMap[bim.type] || bim.type;
        const typeClass = (bim.type || '').toLowerCase();
        title.textContent = `📋 ${bim.name || typeName}`;

        // Calculate volume & area
        const vol = (bim.width * bim.height * bim.depth);
        const area = (bim.width * bim.depth);

        body.innerHTML = `
            <div class="prop-group">
                <div class="prop-group-title">Thông tin chung</div>
                <div class="prop-row">
                    <span class="prop-label">Loại</span>
                    <span class="prop-badge ${escapeHtml(typeClass)}">${escapeHtml(typeName)}</span>
                </div>
                ${bim.storey ? `<div class="prop-row"><span class="prop-label">Tầng</span><span class="prop-value">${escapeHtml(bim.storey)}</span></div>` : ''}
                ${bim.material ? `<div class="prop-row"><span class="prop-label">Vật liệu</span><span class="prop-value">${escapeHtml(bim.material)}</span></div>` : ''}
            </div>
            <div class="prop-group">
                <div class="prop-group-title">Kích thước</div>
                <div class="prop-row"><span class="prop-label">Dài (X)</span><span class="prop-value">${escapeHtml((bim.width * 1000).toFixed(0))} mm</span></div>
                <div class="prop-row"><span class="prop-label">Cao (Y)</span><span class="prop-value">${escapeHtml((bim.height * 1000).toFixed(0))} mm</span></div>
                <div class="prop-row"><span class="prop-label">Rộng (Z)</span><span class="prop-value">${escapeHtml((bim.depth * 1000).toFixed(0))} mm</span></div>
            </div>
            <div class="prop-group">
                <div class="prop-group-title">Khối lượng</div>
                <div class="prop-row"><span class="prop-label">Thể tích</span><span class="prop-value highlight">${escapeHtml(vol.toFixed(3))} m³</span></div>
                <div class="prop-row"><span class="prop-label">Diện tích mặt</span><span class="prop-value">${escapeHtml(area.toFixed(2))} m²</span></div>
            </div>
            <div class="prop-group">
                <div class="prop-group-title">Vị trí (m)</div>
                <div class="prop-row"><span class="prop-label">X</span><span class="prop-value">${escapeHtml(bim.x.toFixed(2))}</span></div>
                <div class="prop-row"><span class="prop-label">Y</span><span class="prop-value">${escapeHtml(bim.y.toFixed(2))}</span></div>
                <div class="prop-row"><span class="prop-label">Z</span><span class="prop-value">${escapeHtml(bim.z.toFixed(2))}</span></div>
            </div>
            ${bim.properties ? `
            <div class="prop-group">
                <div class="prop-group-title">Property Sets</div>
                ${Object.entries(bim.properties).map(([k,v]) => `<div class="prop-row"><span class="prop-label">${escapeHtml(k)}</span><span class="prop-value">${escapeHtml(v)}</span></div>`).join('')}
            </div>` : ''}
        `;

        // Show indicator on 3D
        document.querySelector('.element-selected-indicator')?.remove();
        const ct = document.getElementById('ifc-3d-container');
        if (ct) {
            const ind = document.createElement('div');
            ind.className = 'element-selected-indicator';
            ind.textContent = `✦ ${bim.name || typeName}`;
            ct.appendChild(ind);
        }
    },

    // ===== Model Statistics Dashboard =====
    _showModelStats(spec, N, L, W, numCols) {
        const dashboard = document.getElementById('model-stats-dashboard');
        const grid = document.getElementById('stats-grid');
        if (!dashboard || !grid) return;
        dashboard.classList.remove('hidden');

        const totalElements = Object.values(this._elementCounts).reduce((a, b) => a + b, 0);
        const isBridge = spec.structure_type === 'bridge' || spec.bridge_name || spec.total_length;

        let html;
        if (isBridge) {
            const totalLen = ((spec.total_length || 0) / 1000).toFixed(0);
            const deckW = ((spec.deck_width || 0) / 1000).toFixed(1);
            const colors = { Wall:'#90CAF9', Column:'#EF5350', Beam:'#FF9800', Slab:'#78909C',
                Railing:'#607D8B', Pile:'#8D6E63', Footing:'#A1887F', BuildingElementProxy:'#4DB6AC' };

            html = `
                <div class="stat-card"><div class="stat-number">${escapeHtml(totalLen)}</div><div class="stat-label">m tổng dài</div></div>
                <div class="stat-card"><div class="stat-number">${escapeHtml(spec.num_spans || '?')}</div><div class="stat-label">Nhịp</div></div>
                <div class="stat-card"><div class="stat-number">${escapeHtml(deckW)}</div><div class="stat-label">m rộng cầu</div></div>
                <div class="stat-card"><div class="stat-number">${escapeHtml(spec.num_lanes || '?')}</div><div class="stat-label">Làn xe</div></div>
                <div class="stat-card"><div class="stat-number">${escapeHtml(totalElements)}</div><div class="stat-label">Cấu kiện</div></div>
            `;
            for (const [type, count] of Object.entries(this._elementCounts)) {
                const pct = Math.round(count / totalElements * 100);
                const color = colors[type] || '#888';
                html += `
                    <div class="stat-card">
                        <div class="stat-number" style="color:${escapeHtml(color)}">${escapeHtml(count)}</div>
                        <div class="stat-label">${escapeHtml(type)}</div>
                        <div class="stat-bar"><div class="stat-bar-fill" style="width:${escapeHtml(pct)}%;background:${escapeHtml(color)}"></div></div>
                    </div>`;
            }
        } else {
            const totalArea = (L * W * N).toFixed(0);
            const totalHeight = (N * (spec.storey_height || 3500) / 1000).toFixed(1);
            const colors = { Wall:'#90CAF9', Column:'#EF5350', Beam:'#FF9800', Slab:'#78909C',
                Door:'#8D6E63', Window:'#4FC3F7', Stair:'#BCAAA4', Railing:'#607D8B', Footing:'#A1887F' };

            html = `
                <div class="stat-card"><div class="stat-number">${escapeHtml(N)}</div><div class="stat-label">Tầng</div></div>
                <div class="stat-card"><div class="stat-number">${escapeHtml(totalArea)}</div><div class="stat-label">m² sàn tổng</div></div>
                <div class="stat-card"><div class="stat-number">${escapeHtml(totalHeight)}</div><div class="stat-label">m chiều cao</div></div>
                <div class="stat-card"><div class="stat-number">${escapeHtml(totalElements)}</div><div class="stat-label">Cấu kiện</div></div>
            `;
            for (const [type, count] of Object.entries(this._elementCounts)) {
                const pct = Math.round(count / totalElements * 100);
                const color = colors[type] || '#888';
                html += `
                    <div class="stat-card">
                        <div class="stat-number" style="color:${escapeHtml(color)}">${escapeHtml(count)}</div>
                        <div class="stat-label">${escapeHtml(type)}</div>
                        <div class="stat-bar"><div class="stat-bar-fill" style="width:${escapeHtml(pct)}%;background:${escapeHtml(color)}"></div></div>
                    </div>`;
            }
        }
        grid.innerHTML = html;
    },
};

