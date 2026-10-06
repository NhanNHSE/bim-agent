# Phase 3 — Text-to-BIM: AI-Assisted Building Design

## Mô tả

Cho phép người dùng **mô tả công trình bằng ngôn ngữ tự nhiên** → AI tự động:
1. Phân tích yêu cầu → trích xuất thông số kỹ thuật
2. Sinh mô hình BIM (file IFC) với tường, cột, sàn, cửa, cửa sổ
3. Kiểm tra tuân thủ quy chuẩn QCVN/TCVN
4. Hiển thị 3D trên trình duyệt
5. Cho phép chỉnh sửa bằng ngôn ngữ tự nhiên (iterative)

```
"Thiết kế tòa nhà 5 tầng, 200m², BTCT"
         │
         ▼
   ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
   │  Text → Params │──→│ Params → IFC │──→│ Check QCVN  │
   └─────────────┘     └──────────────┘     └──────┬──────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  3D Preview +    │
                                          │  Compliance Report│
                                          └─────────────────┘
```

---

## User Review Required

> [!IMPORTANT]
> **Scope Decision:** Phase 3 tập trung vào **architectural massing** (hình khối kiến trúc cơ bản: tường, cột, sàn, cửa, không gian). KHÔNG bao gồm:
> - Hệ thống M&E (điện, nước, HVAC)
> - Kết cấu chi tiết (cốt thép, tiết diện dầm)
> - Bản vẽ 2D / shop drawing

> [!WARNING]
> **IFC Generation Approach:** Hiện tại file `generate_sample_ifc.py` viết IFC text thuần (STEP format) → đủ cho prototype nhưng **không** tạo geometry chính xác cho phần mềm BIM khác (Revit, ArchiCAD). Nếu cần export thật, sẽ cần ifcopenshell geometry API ở phase sau.

## Open Questions

1. **Kiểu công trình nào ưu tiên?** Nhà ở, văn phòng, trường học, hay tất cả?
2. **Mức chi tiết?** Chỉ hình khối cơ bản (wall/column/slab) hay cần cả nội thất (bàn ghế, thiết bị)?
3. **Export IFC cho download?** Có cần nút "Tải file IFC" để mở trong Revit/ArchiCAD không?

---

## Proposed Changes

### Component 1: Parametric IFC Generator

Biến `generate_sample_ifc.py` thành **engine linh hoạt** nhận tham số và sinh mô hình.

#### [NEW] [ifc_generator.py](file:///D:/Project/LLM/BIM/backend/src/data_pipeline/ifc_generator.py)

Core IFC generation engine nhận `BuildingSpec` và output file IFC.

```python
@dataclass
class BuildingSpec:
    """Thông số tòa nhà từ mô tả người dùng."""
    project_name: str = "Dự án mới"
    building_name: str = "Tòa nhà"
    building_type: str = "F2"        # Nhóm PCCC: F1-F5
    num_storeys: int = 3
    storey_height: float = 3500      # mm
    footprint_length: float = 12000  # mm
    footprint_width: float = 8000    # mm
    
    # Structural
    wall_thickness: float = 200      # mm
    column_size: float = 400         # mm
    slab_thickness: float = 200      # mm
    
    # Materials
    wall_material: str = "Gạch ống 200mm"
    column_material: str = "Bê tông cốt thép B25"
    slab_material: str = "Bê tông cốt thép B25"
    
    # Layout
    num_interior_walls: int = 1      # Tường ngăn dọc
    doors_per_storey: int = 2
    windows_per_storey: int = 3
    column_grid: list = None         # [(x,y), ...] hoặc auto-generate
    
    # Spaces
    spaces: list = None              # [{"name": "...", "area": ...}]
```

Functions:
- `generate_from_spec(spec: BuildingSpec) → str` — Sinh file IFC, trả về filepath
- `_auto_column_grid(length, width)` — Tự tính lưới cột 
- `_auto_spaces(length, width, num_walls)` — Tự chia phòng
- `_create_staircase(...)` — Thêm cầu thang
- `_apply_materials(...)` — Gán vật liệu

---

### Component 2: Agent Tool — `design_building`

Thêm tool mới vào agent (`src/rag/agent.py`, `src/agents/`).

#### [MODIFY] [agent.py](file:///D:/Project/LLM/BIM/backend/src/rag/agent.py)

**Thay đổi:**
- Thêm `design_building` vào classification prompt
- Thêm function `tool_design_building(question, entities)` 
- Thêm tool execution case trong `execute_tools()`

```python
def tool_design_building(question: str, entities: dict) -> dict:
    """Parse building description → generate IFC → check compliance."""
    
    # Step 1: LLM extracts BuildingSpec from natural language
    spec = _extract_building_spec(question, entities)
    
    # Step 2: Generate IFC
    filepath = generate_from_spec(spec)
    
    # Step 3: Parse + Ingest
    parsed = parse_ifc(filepath)
    chunks = _create_chunks(parsed)
    embeddings = embed_texts([c["text"] for c in chunks])
    upsert(embeddings, chunks, "ifc_elements")
    build_ifc_graph(parsed.to_dict())
    
    # Step 4: Check QCVN compliance
    violations = _check_compliance(spec)
    
    return {
        "spec": asdict(spec),
        "filepath": filepath,
        "summary": get_ifc_summary(parsed),
        "violations": violations,
    }
```

---

### Component 3: Compliance Checker

#### [NEW] [compliance_checker.py](file:///D:/Project/LLM/BIM/backend/src/rag/compliance_checker.py)

Kiểm tra thiết kế tuân thủ QCVN/TCVN — sử dụng **rule-based** + **RAG verification**.

```python
def check_compliance(spec: BuildingSpec) -> list[dict]:
    """Check building spec against known QCVN/TCVN rules.
    
    Returns list of violations/warnings:
    [
        {
            "rule": "QCVN 06:2022, Điều 3.4.2",
            "issue": "Nhà 5 tầng nhóm F2 cần ≥2 lối thoát nạn",
            "severity": "error",
            "suggestion": "Thêm ít nhất 2 cầu thang bộ"
        },
        ...
    ]
    """
```

Hardcoded rules (phase 1 of checker):

| Rule | QCVN/TCVN | Logic |
|---|---|---|
| Chiều rộng lối thoát | QCVN 06, Đ3.4 | ≥ 1.2m nếu >50 người |
| Số cầu thang bộ | QCVN 06, Đ3.4 | ≥ 2 nếu >3 tầng |
| Chiều cao tầng tối thiểu | QCVN 04 | ≥ 2.7m nhà ở, ≥ 3.0m VP |
| Hoạt tải sàn | TCVN 2737 | Theo loại công trình |
| Bề rộng cửa đi | QCVN 06, Đ3.4 | ≥ 0.8m |
| Khoảng cách cột max | TCVN 5574 | ≤ 8m cho BTCT thường |

---

### Component 4: Design API Endpoint

#### [MODIFY] [router_ifc.py](file:///D:/Project/LLM/BIM/backend/src/api/router_ifc.py)

Thêm endpoint:

```python
@router.post("/design")
async def design_building(req: DesignRequest):
    """Generate a building from text description.
    
    Body: {"description": "Tòa nhà 5 tầng văn phòng..."}
    Returns: {spec, filepath, summary, violations, viewer_url}
    """

@router.get("/design/{filename}/download")
async def download_ifc(filename: str):
    """Download generated IFC file."""
```

---

### Component 5: Frontend — Design Chat Mode

#### [MODIFY] [index.html](file:///D:/Project/LLM/BIM/frontend/index.html)

- Thêm suggestion chip: `"🏗️ Thiết kế tòa nhà mới"`
- Thêm **compliance report panel** hiển thị bên dưới 3D viewer

#### [NEW] [design-chat.js](file:///D:/Project/LLM/BIM/frontend/js/design-chat.js)

Xử lý flow thiết kế:

```
1. User nhập mô tả → gọi /api/v1/ifc/design
2. Hiển thị BuildingSpec dạng editable form
3. Render 3D preview (reuse IFCViewer._init3D)
4. Hiển thị compliance warnings
5. User chỉnh sửa → gọi lại → re-render
```

UI mockup:

```
┌─ Chat Panel ──────────┬─ 3D Preview ────────────┐
│                       │                          │
│ 🧑 Thiết kế nhà       │    ┌──────────────┐      │
│   5 tầng văn phòng    │    │  3D Building  │      │
│                       │    │  ┌──┐ ┌──┐    │      │
│ 🤖 Đã tạo mô hình:   │    │  │  │ │  │    │      │
│   ✅ 5 tầng, 200m²    │    │  └──┘ └──┘    │      │
│   ✅ 30 cột BTCT B25  │    └──────────────┘      │
│   ⚠️ Thiếu cầu thang  │                          │
│   ❌ Cần 2 lối thoát   │  ── Compliance ────────  │
│                       │  ⚠️ QCVN 06: Cần ≥2 CT  │
│ 📥 Tải file IFC       │  ✅ Chiều cao tầng OK    │
│                       │  ✅ Hoạt tải OK           │
│ 🧑 Thêm 2 cầu thang  │                          │
│   bộ hai bên          │                          │
│                       │                          │
│ 🤖 Đã cập nhật! ✅    │  [Updated 3D model]      │
│                       │                          │
└───────────────────────┴──────────────────────────┘
```

#### [MODIFY] [style.css](file:///D:/Project/LLM/BIM/frontend/css/style.css)

- CSS cho compliance report panel
- Severity colors: ✅ green, ⚠️ yellow, ❌ red
- Design spec form styles

---

## Verification Plan

### Automated Tests

```bash
# Test 1: Parametric IFC generation
docker exec bim-backend python -c "
from src.data_pipeline.ifc_generator import generate_from_spec, BuildingSpec
spec = BuildingSpec(num_storeys=5, footprint_length=20000, footprint_width=10000)
path = generate_from_spec(spec)
print(f'Generated: {path}')
"

# Test 2: Text-to-params extraction
docker exec bim-backend python -c "
from src.rag.agent import tool_design_building
result = tool_design_building('Thiết kế nhà 5 tầng văn phòng 200m2 BTCT', {})
print(result['spec'])
print(result['violations'])
"

# Test 3: Compliance checker
docker exec bim-backend python -c "
from src.rag.compliance_checker import check_compliance
from src.data_pipeline.ifc_generator import BuildingSpec
spec = BuildingSpec(num_storeys=10, building_type='F1')
violations = check_compliance(spec)
for v in violations: print(f'{v[\"severity\"]}: {v[\"issue\"]}')
"
```

### Manual Verification
1. Chat: *"Thiết kế tòa nhà 5 tầng văn phòng, diện tích 200m², kết cấu BTCT"*
2. Verify: 3D model hiển thị, compliance report hiện
3. Chat: *"Thêm 2 cầu thang bộ"*
4. Verify: Model cập nhật, warning giảm
5. Click "Tải IFC" → Mở file trong text editor verify format
