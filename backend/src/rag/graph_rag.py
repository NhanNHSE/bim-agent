"""GraphRAG Engine — combines vector search + knowledge graph traversal.

Core retrieval flow:
1. Vector search (Qdrant) → semantic similarity
2. Entity extraction (LLM) → structured entities from question
3. Graph traversal (Neo4j) → multi-hop related context
4. Merge & deduplicate results
5. Rerank combined results (LLM)
6. Generate response with citations
"""

import json
import time
from typing import Any, Generator

from google import genai
from google.genai.types import GenerateContentConfig
import structlog

from src.core.config import get_settings
from src.embeddings.embedding_service import embed_query
from src.embeddings.vector_store import search as vector_search
from src.knowledge_graph.graph_query import (
    search_articles_by_keyword,
    get_requirements_for_building_type,
    get_requirements_for_topic,
    get_material_properties,
)
from src.rag.prompts import build_rag_prompt, build_entity_extraction_prompt

logger = structlog.get_logger()
settings = get_settings()

_client = None
MAX_RETRIES = 5


def _get_client() -> genai.Client:
    """Get or create the Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


# ===== Step 1: Vector Search =====

def _vector_retrieve(query: str, top_k: int = None) -> list[dict]:
    """Retrieve chunks from Qdrant via semantic similarity."""
    if top_k is None:
        top_k = settings.retrieval_top_k
    query_embedding = embed_query(query)
    return vector_search(query_embedding, top_k=top_k)


# ===== Step 2: Entity Extraction =====

def _extract_entities(question: str) -> dict:
    """Extract AEC entities from the question using LLM.

    Returns a dict with keys: building_type, standard_code, topic, material, etc.
    """
    client = _get_client()
    prompt = build_entity_extraction_prompt(question)

    for attempt in range(MAX_RETRIES):
        model = settings.llm_model if attempt < MAX_RETRIES - 1 else settings.llm_fallback_model
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=GenerateContentConfig(temperature=0.0, max_output_tokens=300),
            )
            text = response.text.strip()
            # Extract JSON from response
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            err = str(e)
            if ("503" in err or "429" in err) and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("entity_extraction_retry", model=model, attempt=attempt + 1, wait=wait)
                time.sleep(wait)
            else:
                logger.warning("entity_extraction_failed", error=err)
                return {}


# ===== Step 3: Graph Traversal =====

def _graph_retrieve(entities: dict) -> list[dict]:
    """Query Neo4j knowledge graph based on extracted entities."""
    graph_results = []

    # Search by building type (e.g., F1, F2)
    building_type = entities.get("building_type", "")
    if building_type:
        results = get_requirements_for_building_type(building_type)
        for r in results:
            graph_results.append({
                "text": f"[{r['standard_code']}] Điều {r['article_number']}: {r['article_title']}\n{r['content']}\n\nYêu cầu: {r['requirement']}",
                "metadata": {
                    "standard_code": r["standard_code"],
                    "article_number": r["article_number"],
                    "source": "knowledge_graph",
                },
                "score": 0.9,  # High relevance for direct graph matches
            })

    # Search by topic
    topic = entities.get("topic", "")
    standard_code = entities.get("standard_code")
    if topic:
        results = get_requirements_for_topic(topic, standard_code)
        for r in results:
            text = f"[{r['standard_code']}] Điều {r['article_number']}: {r['article_title']}\n{r['content']}"
            if r.get("requirement"):
                text += f"\n\nYêu cầu: {r['requirement']}"
            graph_results.append({
                "text": text,
                "metadata": {
                    "standard_code": r["standard_code"],
                    "article_number": r["article_number"],
                    "source": "knowledge_graph",
                },
                "score": 0.85,
            })

    # Search by material
    material = entities.get("material", "")
    if material:
        results = get_material_properties(material)
        for r in results:
            if r.get("standard_code"):
                text = f"[{r['standard_code']}] Vật liệu: {r['material']}\nTrọng lượng riêng: {r['unit_weight']} {r['unit']}"
                if r.get("requirement_description"):
                    text += f"\n{r['requirement_description']}"
                graph_results.append({
                    "text": text,
                    "metadata": {
                        "standard_code": r.get("standard_code", ""),
                        "source": "knowledge_graph",
                    },
                    "score": 0.8,
                })

    # Keyword search on graph full-text index
    keywords = entities.get("keywords", [])
    for kw in keywords[:3]:  # Limit to 3 keywords
        results = search_articles_by_keyword(kw, limit=3)
        for r in results:
            graph_results.append({
                "text": f"[{r['standard_code']}] Điều {r['article_number']}: {r['article_title']}\n{r['content']}",
                "metadata": {
                    "standard_code": r["standard_code"],
                    "article_number": r["article_number"],
                    "source": "knowledge_graph",
                },
                "score": r.get("score", 0.7),
            })

    return graph_results


# ===== Step 4: Merge & Deduplicate =====

def _merge_results(
    vector_results: list[dict], graph_results: list[dict]
) -> list[dict]:
    """Merge and deduplicate results from vector and graph search."""
    seen_texts = set()
    merged = []

    # Prioritize graph results (more precise)
    for doc in graph_results:
        text_key = doc["text"][:200]
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            merged.append(doc)

    # Add vector results
    for doc in vector_results:
        text_key = doc["text"][:200]
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            merged.append(doc)

    return merged


# ===== Step 5: Rerank =====

def _rerank(query: str, documents: list[dict], top_k: int = None) -> list[dict]:
    """Rerank documents using Gemini LLM."""
    if top_k is None:
        top_k = settings.rerank_top_k

    if len(documents) <= top_k:
        return documents

    client = _get_client()

    doc_list = ""
    for i, doc in enumerate(documents):
        preview = doc["text"][:300].replace("\n", " ")
        doc_list += f"[{i}] {preview}\n\n"

    prompt = f"""Bạn là chuyên gia quy chuẩn xây dựng Việt Nam.
Cho câu hỏi: "{query}"

Dưới đây là {len(documents)} đoạn văn bản.
Hãy chọn TẤT CẢ các đoạn LIÊN QUAN, chỉ BỎ đoạn hoàn toàn KHÔNG liên quan.
Trả về CHỈ các số thứ tự, cách nhau bởi dấu phẩy, theo thứ tự liên quan giảm dần.

{doc_list}

Các index liên quan:"""

    for attempt in range(MAX_RETRIES):
        model = settings.llm_model if attempt < MAX_RETRIES - 1 else settings.llm_fallback_model
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=GenerateContentConfig(temperature=0.0, max_output_tokens=100),
            )
            indices = []
            for part in response.text.strip().replace(" ", "").split(","):
                try:
                    idx = int(part.strip())
                    if 0 <= idx < len(documents) and idx not in indices:
                        indices.append(idx)
                except ValueError:
                    continue
            if indices:
                return [documents[i] for i in indices]
            break  # Got response but no valid indices
        except Exception as e:
            err = str(e)
            if ("503" in err or "429" in err) and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("rerank_retry", model=model, attempt=attempt + 1, wait=wait)
                time.sleep(wait)
            else:
                logger.warning("rerank_failed", error=err)
                break

    return documents[:top_k]


# ===== Step 6: Generate Response =====

def _generate_stream(
    question: str, documents: list[dict], messages: list = None
) -> Generator[str, None, None]:
    """Generate streaming response with retry."""
    client = _get_client()
    prompt = build_rag_prompt(question, documents, messages)

    for attempt in range(MAX_RETRIES):
        model = settings.llm_model if attempt < MAX_RETRIES - 1 else settings.llm_fallback_model
        try:
            stream = client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=GenerateContentConfig(temperature=0.3, max_output_tokens=8192),
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
            return
        except Exception as e:
            err = str(e)
            if ("503" in err or "429" in err) and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("llm_retry", model=model, attempt=attempt + 1, wait=wait)
                time.sleep(wait)
            else:
                raise


# ===== Main Entry Point =====

def ask(
    question: str, messages: list = None, stream: bool = True
) -> tuple:
    """Main GraphRAG query pipeline.

    Args:
        question: User's question.
        messages: Previous conversation messages.
        stream: If True, return a generator.

    Returns:
        Tuple of (response_or_generator, retrieved_documents, entities).
    """
    logger.info("graphrag_query", question=question[:100])

    # Step 1: Vector search
    vector_results = _vector_retrieve(question)
    logger.info("vector_results", count=len(vector_results))

    # Step 2: Extract entities
    entities = _extract_entities(question)
    logger.info("entities_extracted", entities=entities)

    # Step 3: Graph traversal
    graph_results = _graph_retrieve(entities)
    logger.info("graph_results", count=len(graph_results))

    # Step 4: Merge
    merged = _merge_results(vector_results, graph_results)
    logger.info("merged_results", count=len(merged))

    # Step 5: Rerank
    ranked = _rerank(question, merged)
    logger.info("ranked_results", count=len(ranked))

    # Step 6: Generate
    if stream:
        return _generate_stream(question, ranked, messages), ranked, entities
    else:
        # Non-streaming: collect all chunks
        response = "".join(_generate_stream(question, ranked, messages))
        return response, ranked, entities
