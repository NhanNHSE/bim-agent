"""Knowledge Graph exploration router."""

from fastapi import APIRouter, Depends, Query

from src.core.security import get_current_user
from src.knowledge_graph.graph_query import (
    get_graph_stats,
    get_related_standards,
    search_articles_by_keyword,
    get_requirements_for_building_type,
    get_material_properties,
)

router = APIRouter()


@router.get("/stats")
async def graph_stats(current_user: dict = Depends(get_current_user)):
    """Get knowledge graph statistics."""
    return get_graph_stats()


@router.get("/search")
async def search_graph(
    keyword: str = Query(..., description="Từ khóa tìm kiếm"),
    limit: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Search articles in knowledge graph by keyword."""
    return search_articles_by_keyword(keyword, limit)


@router.get("/standards/{standard_code}/related")
async def related_standards(
    standard_code: str,
    current_user: dict = Depends(get_current_user),
):
    """Get standards related to a given standard."""
    return get_related_standards(standard_code)


@router.get("/building-types/{code}/requirements")
async def building_type_requirements(
    code: str,
    current_user: dict = Depends(get_current_user),
):
    """Get all requirements for a building type (e.g., F1, F2)."""
    return get_requirements_for_building_type(code)


@router.get("/materials/{name}")
async def material_info(
    name: str,
    current_user: dict = Depends(get_current_user),
):
    """Get material properties from standards."""
    return get_material_properties(name)
