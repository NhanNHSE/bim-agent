"""Documents router — upload and manage QCVN/TCVN documents."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.core.security import get_current_user, require_roles, Role
from src.embeddings.vector_store import get_collection_info

router = APIRouter()


@router.get("/")
async def list_documents(current_user: dict = Depends(get_current_user)):
    """List indexed documents/collections."""
    info = get_collection_info()
    return {
        "collection": info,
        "message": "Sử dụng scripts/ingest_qcvn.py để nạp dữ liệu QCVN/TCVN",
    }
