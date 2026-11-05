"""IFC Upload and Query API endpoints."""

import os
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials

from src.core import rate_limit
from src.core.config import get_settings
from src.core.security import (
    bearer_scheme,
    create_download_token,
    decode_download_token,
    decode_token,
    get_current_user,
    require_roles,
    Role,
)
from src.data_pipeline.ifc_geometry import extract_geometry
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
        logger.error("ifc_processing_failed", error=str(e), exc_info=True)
        raise HTTPException(500, "Lỗi xử lý IFC. Vui lòng kiểm tra file và thử lại.")


@router.get("/stats")
def get_ifc_stats(
    current_user: dict = Depends(get_current_user),
):
    """Get summary statistics of imported IFC data."""
    try:
        summary = get_ifc_building_summary()
        return summary
    except Exception as e:
        logger.error("ifc_stats_failed", error=str(e), exc_info=True)
        return {"error": "Không lấy được thống kê IFC", "building": None, "element_counts": {}}


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
        logger.error("ifc_elements_failed", error=str(e), exc_info=True)
        raise HTTPException(500, "Lỗi truy vấn dữ liệu BIM.")


@router.get("/geometry/{filename}")
def get_geometry(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """Extract 3D triangle mesh geometry from an IFC file for the frontend viewer."""
    safe = _safe_filename(filename)
    filepath = os.path.join(settings.ifc_upload_dir, safe)
    if not os.path.exists(filepath):
        raise HTTPException(404, "File không tồn tại")

    try:
        return extract_geometry(filepath, cache_dir=settings.ifc_geometry_cache_dir)
    except Exception as e:
        logger.error("geometry_extraction_failed", filename=safe, error=str(e), exc_info=True)
        raise HTTPException(500, "Lỗi trích xuất hình học IFC.")


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
        logger.error("generate_sample_failed", error=str(e), exc_info=True)
        raise HTTPException(500, "Lỗi tạo file mẫu.")


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
        logger.error("design_failed", error=str(e), exc_info=True)
        raise HTTPException(500, "Lỗi thiết kế công trình. Vui lòng thử lại.")


@router.post("/download-token/{filename}")
def issue_download_token(
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """Issue a short-lived download URL for an IFC file."""
    safe = _safe_filename(filename)
    filepath = os.path.join(settings.ifc_upload_dir, safe)
    if not os.path.exists(filepath):
        raise HTTPException(404, "File không tồn tại")

    token = create_download_token(str(current_user["sub"]), safe)
    return {
        "url": f"/api/v1/ifc/download/{quote(safe)}?dt={token}",
        "expires_in": settings.ifc_download_token_seconds,
    }


@router.get("/download/{filename}")
def download_ifc(
    filename: str,
    dt: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    """Download a generated IFC file."""
    from fastapi.responses import FileResponse

    if credentials is not None:
        payload = decode_token(credentials.credentials)
        if payload.get("sub") is None or "scope" in payload:
            raise HTTPException(401, "Token không hợp lệ")
        safe_name = _safe_filename(filename)
    elif dt is not None:
        safe_name = _safe_filename(filename)
        decode_download_token(dt, safe_name)
    else:
        raise HTTPException(401, "Chưa đăng nhập")

    filepath = os.path.join(settings.ifc_upload_dir, safe_name)
    if not os.path.exists(filepath):
        raise HTTPException(404, "File không tồn tại")

    return FileResponse(
        path=filepath,
        filename=safe_name,
        media_type="application/octet-stream",
    )


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
