"""IFC Upload and Query API endpoints."""

import os
import json
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from src.core import rate_limit
from src.core.config import get_settings
from src.core.security import get_current_user, require_roles, Role
from src.data_pipeline.ifc_parser import parse_ifc, get_ifc_summary, ParsedIFC
from src.knowledge_graph.ifc_to_graph import (
    build_ifc_graph,
    get_ifc_building_summary,
    query_elements_on_storey,
    query_material_usage,
)
from src.embeddings.embedding_service import embed_texts
from src.embeddings.vector_store import upsert

import structlog

from src.core.audit import log_action

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter(prefix="/api/v1/ifc", tags=["ifc"])


def _safe_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal attacks.

    Strips directory components (../, /, \\) and validates extension.
    Raises HTTPException(400) for invalid filenames.
    """
    # Strip any directory components
    name = os.path.basename(filename)

    # Reject empty, hidden files, or names that changed after basename.
    # Backslash and ':' are rejected explicitly: basename() on Linux does not
    # treat Windows separators or drive letters as path components.
    if (not name or name != filename or name.startswith(".")
            or "\\" in name or ":" in name):
        raise HTTPException(400, "Tên file không hợp lệ")

    # Only allow .ifc extension
    if not name.lower().endswith(".ifc"):
        raise HTTPException(400, "Chỉ hỗ trợ file .ifc")

    return name


def _limit_ifc(current_user: dict) -> None:
    """Per-user cap on CPU-heavy IFC work (design, sample generation, upload)."""
    rate_limit.hit(f"ifc:min:{current_user.get('sub')}", settings.ifc_rate_limit_per_minute, 60)


MAX_UPLOAD_BYTES = settings.ifc_max_upload_mb * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_limited(file: UploadFile) -> bytes:
    """Read an upload in chunks, rejecting it once it exceeds MAX_UPLOAD_BYTES."""
    buf = bytearray()
    while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
        buf.extend(chunk)
        if len(buf) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"File vượt quá giới hạn {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    return bytes(buf)


@router.post("/upload")
async def upload_ifc(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_roles(*Role.CAN_UPLOAD)),
):
    """Upload and process an IFC file.

    Parses the file, embeds elements into Qdrant, and builds Neo4j graph.
    """
    await run_in_threadpool(_limit_ifc, current_user)  # Redis round-trip: keep it off the event loop
    filename = _safe_filename(file.filename or "")
    content = await _read_limited(file)
    user_id = int(current_user.get("sub", 0))

    # Writing, parsing, embedding and graph building all block — keep them off the event loop
    return await run_in_threadpool(_store_and_index, filename, content, user_id)


def _store_and_index(filename: str, content: bytes, user_id: int) -> dict:
    """Save an uploaded IFC, then parse, embed and add it to the graph (blocking)."""
    upload_dir = settings.ifc_upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    logger.info("ifc_uploaded", filename=filename, size=len(content))

    try:
        # Parse IFC
        parsed = parse_ifc(filepath, extract_geometry=False)

        # Create text chunks
        chunks = _create_chunks(parsed)

        # Embed and upsert
        texts = [c["text"] for c in chunks]
        embeddings = embed_texts(texts)
        upsert(embeddings=embeddings, documents=chunks, collection_name="ifc_elements", source_id=f"ifc:{filename}")

        # Build graph
        graph_stats = build_ifc_graph(parsed.to_dict())

        # Save parsed JSON
        json_path = filepath.replace(".ifc", "_parsed.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(parsed.to_json())

        log_action("upload_ifc", user_id=user_id, detail={
            "filename": filename,
            "size_bytes": len(content),
            "elements": len(parsed.elements),
            "storeys": len(parsed.storeys),
        })

        return {
            "status": "success",
            "filename": filename,
            "project": parsed.project_name,
            "building": parsed.building_name,
            "storeys": len(parsed.storeys),
            "elements": len(parsed.elements),
            "spaces": len(parsed.spaces),
            "materials": len(parsed.materials),
            "chunks_embedded": len(chunks),
            "graph_nodes": graph_stats["nodes"],
            "graph_relationships": graph_stats["relationships"],
        }

    except Exception as e:
        logger.error("ifc_processing_failed", error=str(e))
        raise HTTPException(500, f"Lỗi xử lý IFC: {str(e)}")


@router.get("/stats")
def get_ifc_stats(
    current_user: dict = Depends(get_current_user),
):
    """Get summary statistics of imported IFC data."""
    try:
        summary = get_ifc_building_summary()
        return summary
    except Exception as e:
        logger.error("ifc_stats_failed", error=str(e))
        return {"error": str(e), "building": None, "element_counts": {}}


@router.get("/elements")
def get_elements(
    storey: Optional[str] = Query(None, description="Tên tầng"),
    material: Optional[str] = Query(None, description="Tên vật liệu"),
    current_user: dict = Depends(get_current_user),
):
    """Query BIM elements by storey or material."""
    try:
        if storey:
            elements = query_elements_on_storey(storey)
            return {"storey": storey, "count": len(elements), "elements": elements}
        elif material:
            elements = query_material_usage(material)
            return {"material": material, "count": len(elements), "elements": elements}
        else:
            raise HTTPException(400, "Cần chỉ định storey hoặc material")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Lỗi truy vấn: {str(e)}")


@router.get("/geometry/{filename}")
def get_geometry(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """Get simplified 3D geometry data for frontend viewer."""
    json_path = os.path.join(settings.ifc_upload_dir, filename.replace(".ifc", "_parsed.json"))
    if not os.path.exists(json_path):
        raise HTTPException(404, "File chưa được parse")

    with open(json_path, "r", encoding="utf-8") as f:
        parsed = json.load(f)

    # Create simplified geometry for 3D viewer
    # Each element becomes a box with position/dimensions based on its properties
    geometry_data = _create_viewer_geometry(parsed)
    return geometry_data


@router.post("/generate-sample")
def generate_sample(
    current_user: dict = Depends(get_current_user),
):
    """Generate a sample IFC file for testing."""
    _limit_ifc(current_user)
    try:
        from scripts.generate_sample_ifc import generate_sample_ifc
        filepath = generate_sample_ifc("data/ifc/sample_building.ifc")
        return {"status": "success", "filepath": filepath}
    except Exception as e:
        raise HTTPException(500, f"Lỗi tạo sample: {str(e)}")


@router.post("/design")
def design_building(
    req: dict,
    current_user: dict = Depends(get_current_user),
):
    """Generate a building from text description.

    Body: {"description": "Tòa nhà 5 tầng văn phòng..."}
    Returns: spec, filepath, summary, violations
    """
    _limit_ifc(current_user)
    description = req.get("description", "")
    if not description:
        raise HTTPException(400, "Cần mô tả công trình")

    try:
        from src.rag.agent import tool_design_building
        result = tool_design_building(description, {})

        if result.get("error"):
            raise HTTPException(500, result["error"])

        return {
            "status": "success",
            "spec": result.get("spec", {}),
            "filepath": result.get("filepath", ""),
            "filename": result.get("filename", ""),
            "summary": result.get("summary", ""),
            "violations": result.get("violations", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("design_failed", error=str(e))
        raise HTTPException(500, f"Lỗi thiết kế: {str(e)}")


@router.get("/download/{filename}")
def download_ifc(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """Download a generated IFC file."""
    from fastapi.responses import FileResponse

    safe_name = _safe_filename(filename)
    filepath = os.path.join(settings.ifc_upload_dir, safe_name)
    if not os.path.exists(filepath):
        raise HTTPException(404, "File không tồn tại")

    return FileResponse(
        path=filepath,
        filename=safe_name,
        media_type="application/octet-stream",
    )


@router.get("/geometry/{filename}")
async def get_ifc_geometry(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """Extract 3D geometry from an IFC file for frontend rendering.

    Returns mesh data (vertices, faces, colors, metadata) that maps
    directly to the IFC file content, ensuring the 3D viewer shows
    exactly what's in the file.

    Uses run_in_executor to avoid blocking the event loop during
    CPU-intensive geometry extraction.
    """
    import asyncio
    from src.data_pipeline.ifc_geometry import extract_geometry

    safe_name = _safe_filename(filename)
    filepath = os.path.join(settings.ifc_upload_dir, safe_name)
    if not os.path.exists(filepath):
        raise HTTPException(404, "File không tồn tại")

    try:
        # Run CPU-intensive extraction in thread pool to not block event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, extract_geometry, filepath, "data/cache/geometry"
        )
        return result
    except Exception as e:
        logger.error("geometry_extraction_failed", filename=safe_name, error=str(e))
        raise HTTPException(500, f"Lỗi trích xuất geometry: {str(e)}")


# ===== Helper functions =====

def _create_chunks(parsed: ParsedIFC) -> list:
    """Create text chunks from parsed IFC for vector embedding."""
    chunks = []

    # Building summary
    summary = get_ifc_summary(parsed)
    chunks.append({
        "text": summary,
        "metadata": {
            "source": "ifc",
            "filename": parsed.filename,
            "type": "building_summary",
        },
    })

    # Elements (elements are dicts from asdict())
    for el in parsed.elements:
        text_parts = [
            f"[{parsed.building_name}] {el['ifc_type']}: {el['name']}",
            f"Tầng: {el['storey']}" if el.get('storey') else "",
            f"Vật liệu: {el['material']}" if el.get('material') else "",
        ]
        if el.get('properties'):
            for k, v in el['properties'].items():
                text_parts.append(f"{k}: {v}")

        chunks.append({
            "text": "\n".join(p for p in text_parts if p),
            "metadata": {
                "source": "ifc",
                "filename": parsed.filename,
                "ifc_type": el['ifc_type'],
                "global_id": el['global_id'],
                "storey": el.get('storey', ''),
                "material": el.get('material', ''),
            },
        })

    # Spaces (spaces are dicts from asdict())
    for space in parsed.spaces:
        chunks.append({
            "text": (
                f"[{parsed.building_name}] Không gian: {space['name']}\n"
                f"Tầng: {space.get('storey', '')}\n"
                f"Diện tích: {space.get('area', 0):.1f} m²"
            ),
            "metadata": {
                "source": "ifc",
                "filename": parsed.filename,
                "type": "space",
                "storey": space.get('storey', ''),
            },
        })

    return chunks


def _create_viewer_geometry(parsed: dict) -> dict:
    """Create simplified 3D geometry for the frontend viewer.

    Returns boxes representing each element type with colors.
    """
    TYPE_COLORS = {
        "IfcWall": "#90CAF9",
        "IfcWallStandardCase": "#90CAF9",
        "IfcColumn": "#EF5350",
        "IfcBeam": "#FF9800",
        "IfcSlab": "#78909C",
        "IfcDoor": "#8D6E63",
        "IfcWindow": "#4FC3F7",
        "IfcSpace": "#E8F5E9",
        "IfcStair": "#AB47BC",
    }

    storeys = {s["name"]: s.get("elevation", 0) for s in parsed.get("storeys", [])}
    objects = []

    for el in parsed.get("elements", []):
        ifc_type = el.get("ifc_type", "")
        color = TYPE_COLORS.get(ifc_type, "#BDBDBD")
        storey = el.get("storey", "")
        elevation = storeys.get(storey, 0) / 1000.0  # mm to meters

        # Simple placeholder geometry based on element type
        obj = {
            "id": el.get("global_id", ""),
            "name": el.get("name", ""),
            "type": ifc_type,
            "color": color,
            "storey": storey,
            "material": el.get("material", ""),
            "elevation": elevation,
        }
        objects.append(obj)

    return {
        "building": parsed.get("building_name", ""),
        "storeys": list(storeys.keys()),
        "object_count": len(objects),
        "objects": objects,
        "type_colors": TYPE_COLORS,
    }
