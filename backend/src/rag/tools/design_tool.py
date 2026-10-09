"""Design tool — generates IFC from text description for buildings AND bridges.

Routes to the appropriate generator based on structure type detected from
the user's question. Supports:
- Buildings (nhà ở, văn phòng, trường học, etc.)
- Bridges (cầu dầm BTCT, cầu bê tông, etc.)
"""

import json
import os
import re
import time

from google.genai.types import GenerateContentConfig
import structlog

from src.core.config import get_settings
from src.core.llm import get_llm_client, get_model_name, MAX_RETRIES

logger = structlog.get_logger()
settings = get_settings()


def tool_design_building(question: str, entities: dict) -> dict:
    """Design a structure from text description → generate IFC + compliance check.

    Auto-detects whether user wants a building or bridge and routes accordingly.
    """
    structure_type = _detect_structure_type(question, entities)

    if structure_type == "bridge":
        return _design_bridge(question, entities)
    else:
        return _design_building(question, entities)


# ===== Structure Type Detection =====

def _detect_structure_type(question: str, entities: dict) -> str:
    """Detect if the user wants a bridge or building."""
    q = question.lower()

    # Filter out false positives — "cầu thang" is stairs, not bridge
    safe_terms = [
        "cầu thang", "cầu thang bộ", "cầu thang máy", "cầu thang thoát nạn",
        "cau thang",  # unaccented
    ]
    q_check = q
    for term in safe_terms:
        q_check = q_check.replace(term, "")

    bridge_keywords = [
        # Vietnamese with diacritics
        "cầu dầm", "cầu bê tông", "cầu btct", "cầu dự ứng lực",
        "cầu vượt", "cầu dây văng", "cầu treo", "cầu thép",
        "cầu bộ hành", "cầu đường bộ", "cầu đường sắt",
        " cầu ",
        # Vietnamese without diacritics (common input)
        "cau dam", "cau be tong", "cau btct", "cau du ung luc",
        "cau vuot", "cau day vang", "cau treo", "cau thep",
        "cau bo hanh", "cau duong bo", "cau duong sat",
        " cau ",
        # English
        "bridge",
    ]
    if any(kw in q_check for kw in bridge_keywords):
        return "bridge"

    # Also check entities
    if entities.get("building_type", "").lower() in ("bridge", "cầu", "cau"):
        return "bridge"

    return "building"


# ===== Bridge Design =====

def _design_bridge(question: str, entities: dict) -> dict:
    """Design a bridge from text description → generate IFC + compliance check."""
    client = get_llm_client()

    # Step 1: Extract BridgeSpec via LLM
    template = json.dumps({
        "project_name": "Dự án cầu mới",
        "bridge_name": "Cầu mới",
        "bridge_type": "beam",
        "bridge_function": "Đường bộ",
        "total_length": 30000,
        "deck_width": 12000,
        "num_spans": 3,
        "num_lanes": 2,
        "lane_width": 3750,
        "has_sidewalk": True,
        "sidewalk_width": 1500,
        "pier_height": 8000,
        "pier_width": 1500,
        "pier_depth": 2000,
        "deck_thickness": 300,
        "girder_type": "I",
        "girder_height": 1200,
        "girder_width": 600,
        "num_girders": 4,
        "barrier_height": 1100,
        "foundation_type": "pile",
        "pile_diameter": 600,
        "pile_depth": 15000,
        "num_piles_per_pier": 4,
        "design_load": "HL-93",
        "clearance_height": 4500,
    }, ensure_ascii=False, indent=2)

    prompt = (
        f'Trích xuất thông số cầu từ mô tả. Đơn vị: mm.\n'
        f'Quy tắc:\n'
        f'- bridge_type: "beam" (cầu dầm), "arch" (cầu vòm), '
        f'"cable_stayed" (cầu dây văng), "suspension" (cầu treo)\n'
        f'- Cầu 2 làn → deck_width ≥ 10500 (2×3750 + 2×1500)\n'
        f'- Cầu 4 làn → deck_width ≥ 18000\n'
        f'- nhịp cầu = total_length / num_spans\n'
        f'- girder_height ≈ nhịp/16 (BTCT DƯL) hoặc nhịp/12 (BTCT thường)\n'
        f'- pier_height phụ thuộc mô tả (mặc định 8m)\n'
        f'- Lan can ≥ 1100mm (TCVN 11823)\n'
        f'Chỉ trả JSON, không giải thích.\n\n'
        f'Mô tả: "{question}"\n\n'
        f'Template:\n{template}'
    )

    spec_dict = {}
    for attempt in range(MAX_RETRIES):
        model_name = get_model_name(fallback=(attempt == MAX_RETRIES - 1))
        try:
            response = client.models.generate_content(
                model=model_name, contents=prompt,
                config=GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=600,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
            spec_dict = json.loads(text)
            logger.info("bridge_spec_extracted", spans=spec_dict.get("num_spans"),
                        length=spec_dict.get("total_length"))
            break
        except Exception as e:
            err = str(e)
            logger.warning("bridge_spec_extraction_failed", error=err, attempt=attempt + 1)
            if ("503" in err or "429" in err) and attempt < MAX_RETRIES - 1:
                time.sleep(2 ** (attempt + 1))
            elif attempt < MAX_RETRIES - 1:
                continue
            else:
                # Regex fallback
                length_match = re.search(r'(\d+)\s*m(?:\s|,|$)', question)
                spans_match = re.search(r'(\d+)\s*nhịp', question)
                lanes_match = re.search(r'(\d+)\s*làn', question)
                total = int(length_match.group(1)) * 1000 if length_match else 30000
                n_spans = int(spans_match.group(1)) if spans_match else 3
                spec_dict = {
                    "total_length": total,
                    "num_spans": n_spans,
                    "num_lanes": int(lanes_match.group(1)) if lanes_match else 2,
                    "bridge_type": "beam",
                }
                logger.info("bridge_spec_regex_fallback", spec=spec_dict)

    # Step 2: Create BridgeSpec
    from src.data_pipeline.base_spec import BridgeSpec
    from src.data_pipeline.ifc_bridge_generator import generate_bridge
    from src.rag.bridge_compliance import check_bridge_compliance

    spec = BridgeSpec(**{k: v for k, v in spec_dict.items()
                        if k in BridgeSpec.__dataclass_fields__})

    # Step 3: Generate IFC
    try:
        filepath = generate_bridge(spec)
    except Exception as e:
        logger.error("bridge_ifc_generation_failed", error=str(e))
        return {"error": str(e), "summary": "", "violations": []}

    # Step 4: Parse + ingest
    summary = ""
    try:
        from src.data_pipeline.ifc_parser import parse_ifc, get_ifc_summary
        parsed = parse_ifc(filepath, extract_geometry=False)
        summary = get_ifc_summary(parsed)

        from src.embeddings.embedding_service import embed_texts
        from src.embeddings.vector_store import upsert

        chunks = []
        for el in parsed.elements:
            chunks.append({
                "text": (f"[{parsed.building_name}] {el['ifc_type']}: {el['name']}, "
                         f"Vật liệu: {el.get('material', '')}"),
                "metadata": {"source": "ifc_bridge", "ifc_type": el["ifc_type"]},
            })
        if chunks:
            embeddings = embed_texts([c["text"] for c in chunks])
            upsert(embeddings, chunks, "ifc_elements", source_id=f"ifc:{os.path.basename(filepath)}")

        from src.knowledge_graph.ifc_to_graph import build_ifc_graph
        build_ifc_graph(parsed.to_dict())
    except Exception as e:
        logger.warning("bridge_ingest_failed", error=str(e))

    # Step 5: Compliance check
    compliance_result = check_bridge_compliance(spec)
    violations = compliance_result["violations"]
    passing = compliance_result["passing"]

    from dataclasses import asdict
    logger.info("bridge_design_completed", filepath=filepath,
                violations=len(violations), passing=len(passing))

    return {
        "spec": asdict(spec),
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "summary": summary,
        "violations": violations,
        "passing": passing,
        "structure_type": "bridge",
    }


# ===== Building Design (existing logic, refactored) =====

def _design_building(question: str, entities: dict) -> dict:
    """Design a building from text description → generate IFC + compliance check."""
    client = get_llm_client()

    # Step 1: Extract BuildingSpec via LLM
    template = json.dumps({
        "project_name": "Dự án mẫu",
        "building_name": "Tòa nhà",
        "building_type": "F2",
        "building_function": "Văn phòng",
        "num_storeys": 3,
        "storey_height": 3500,
        "footprint_length": 12000,
        "footprint_width": 8000,
        "wall_thickness": 200,
        "column_size": 400,
        "slab_thickness": 200,
        "beam_height": 400,
        "beam_width": 200,
        "wall_material": "Gạch ống 200mm",
        "column_material": "Bê tông cốt thép B25",
        "slab_material": "Bê tông cốt thép B25",
        "beam_material": "Bê tông cốt thép B25",
        "window_material": "Kính cường lực 10mm",
        "num_interior_walls_x": 1,
        "num_interior_walls_y": 0,
        "doors_per_storey": 2,
        "windows_per_storey": 4,
        "num_staircases": 1,
        "column_spacing_x": 6000,
        "column_spacing_y": 8000,
        "corridor_width": 1800,
        "has_lobby": True,
        "has_toilet": True,
        "has_foundation": True,
        "has_roof_railing": True,
        "railing_height": 1100,
        "window_sill_height": 900,
        "address": ""
    }, ensure_ascii=False, indent=2)

    prompt = (
        f'Trích xuất thông số tòa nhà từ mô tả. Đơn vị: mm. '
        f'Nếu 200m² → length×width ≈ 200m² (VD: 14000×14300). '
        f'building_type: F1=nhà ở, F2=công cộng. '
        f'Nhịp cột >6m → beam_height=nhịp/10, beam_width=beam_height/2. '
        f'Nhà >3 tầng → num_staircases≥2. '
        f'Chỉ trả JSON, không giải thích.\n\n'
        f'Mô tả: "{question}"\n\n'
        f'Template:\n{template}'
    )

    spec_dict = {}
    for attempt in range(MAX_RETRIES):
        model_name = get_model_name(fallback=(attempt == MAX_RETRIES - 1))
        try:
            response = client.models.generate_content(
                model=model_name, contents=prompt,
                config=GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=500,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
            spec_dict = json.loads(text)
            logger.info("design_spec_extracted", storeys=spec_dict.get("num_storeys"))
            break
        except Exception as e:
            err = str(e)
            logger.warning("design_spec_extraction_failed", error=err, attempt=attempt + 1)
            if ("503" in err or "429" in err) and attempt < MAX_RETRIES - 1:
                time.sleep(2 ** (attempt + 1))
            elif attempt < MAX_RETRIES - 1:
                continue
            else:
                storeys_match = re.search(r'(\d+)\s*tầng', question)
                area_match = re.search(r'(\d+)\s*m[²2]', question)
                stairs_match = re.search(r'(\d+)\s*cầu thang', question)
                sq = int(area_match.group(1)) if area_match else 96
                side = int((sq ** 0.5) * 1000)
                spec_dict = {
                    "num_storeys": int(storeys_match.group(1)) if storeys_match else 3,
                    "footprint_length": side,
                    "footprint_width": side,
                    "num_staircases": int(stairs_match.group(1)) if stairs_match else 1,
                    "building_function": "Văn phòng",
                }
                logger.info("design_spec_regex_fallback", spec=spec_dict)

    # Step 2: Create BuildingSpec
    from src.data_pipeline.ifc_generator_v2 import BuildingSpec, generate_from_spec
    from src.rag.compliance_checker import check_compliance

    spec = BuildingSpec(**{k: v for k, v in spec_dict.items()
                          if k in BuildingSpec.__dataclass_fields__})

    # Step 3: Generate IFC
    try:
        filepath = generate_from_spec(spec)
    except Exception as e:
        logger.error("ifc_generation_failed", error=str(e))
        return {"error": str(e), "summary": "", "violations": []}

    # Step 4: Parse + ingest
    summary = ""
    try:
        from src.data_pipeline.ifc_parser import parse_ifc, get_ifc_summary
        parsed = parse_ifc(filepath, extract_geometry=False)
        summary = get_ifc_summary(parsed)

        from src.embeddings.embedding_service import embed_texts
        from src.embeddings.vector_store import upsert

        chunks = []
        for el in parsed.elements:
            chunks.append({
                "text": f"[{parsed.building_name}] {el['ifc_type']}: {el['name']}, Tầng: {el.get('storey','')}, Vật liệu: {el.get('material','')}",
                "metadata": {"source": "ifc", "ifc_type": el["ifc_type"]},
            })
        if chunks:
            embeddings = embed_texts([c["text"] for c in chunks])
            upsert(embeddings, chunks, "ifc_elements", source_id=f"ifc:{os.path.basename(filepath)}")

        from src.knowledge_graph.ifc_to_graph import build_ifc_graph
        build_ifc_graph(parsed.to_dict())
    except Exception as e:
        logger.warning("design_ingest_failed", error=str(e))

    # Step 5: Compliance check
    violations = check_compliance(spec)

    from dataclasses import asdict
    logger.info("design_completed", filepath=filepath, violations=len(violations))

    return {
        "spec": asdict(spec),
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "summary": summary,
        "violations": violations,
        "structure_type": "building",
    }
