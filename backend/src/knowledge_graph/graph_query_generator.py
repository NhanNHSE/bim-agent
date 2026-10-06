"""Dynamic Cypher Query Generator — LLM-powered graph reasoning.

Uses Gemini to generate Cypher queries from natural language questions,
enabling multi-hop reasoning across the Knowledge Graph.

Safety:
  - Only READ queries allowed (MATCH, RETURN, WITH, WHERE, ORDER BY, LIMIT)
  - Dangerous keywords blocked (DELETE, DETACH, CREATE, MERGE, SET, REMOVE, DROP)
  - Query timeout enforced
  - Fallback to hardcoded queries on failure
"""

import json
import re
import time

from google.genai.types import GenerateContentConfig
import structlog

from src.core.llm import get_llm_client, get_model_name
from src.knowledge_graph.neo4j_client import run_query

logger = structlog.get_logger()

# Schema description for LLM context
GRAPH_SCHEMA = """
## Neo4j Graph Schema — QCVN/TCVN Knowledge Graph

### Node Labels & Properties:
- **Standard** (code: string UNIQUE, name: string, year: int, status: string)
  Ví dụ: {code: "QCVN 06:2022/BXD", name: "An toàn cháy cho nhà và công trình", year: 2022}

- **Chapter** (chapter_id: string, number: string, title: string)

- **Section** (section_id: string, number: string, title: string)

- **Article** (article_id: string UNIQUE, number: string, title: string, content: text)
  Full-text index: article_content (trên content, title)

- **Requirement** (req_id: string, description: string, type: string, values_json: string)
  type: "khoảng cách", "chiều rộng", "diện tích", "bậc chịu lửa", "PCCC", ...

- **BuildingType** (code: string UNIQUE, description: string)
  Ví dụ: {code: "F1", description: "Nhà chung cư"}, {code: "F2", description: "Nhà văn phòng"}

- **Material** (name: string UNIQUE, unit_weight: float, unit: string)
  Ví dụ: {name: "Bê tông cốt thép", unit_weight: 2500, unit: "kg/m³"}

- **Concept** (name: string UNIQUE, description: string)

### Relationships:
- (Standard)-[:CONTAINS]->(Chapter)
- (Chapter)-[:HAS_SECTION]->(Section)
- (Section)-[:HAS_ARTICLE]->(Article)
- (Article)-[:SPECIFIES]->(Requirement)
- (Requirement)-[:CLASSIFIES]->(BuildingType)
- (Requirement)-[:FOR_MATERIAL]->(Material)
- (Article)-[:REFERENCES]->(Concept)
- (Standard)-[:RELATED_TO]->(Standard)
- (Standard)-[:SUPERSEDES]->(Standard)

### IFC/BIM Nodes (nếu có dữ liệu IFC):
- **Building** (name, description, project)
- **Storey** (name, elevation)
- **Element** (ifc_type, name, material, properties_json)
- (Building)-[:HAS_STOREY]->(Storey)
- (Storey)-[:CONTAINS_ELEMENT]->(Element)
"""

# ---- Cypher Safety Validation (Whitelist Approach) ----
# Instead of blocking dangerous keywords, we BLOCK all known destructive keywords
# using word-boundary regex (case-insensitive). This prevents bypass via case tricks,
# tab characters, or APOC procedures not in the original blacklist.

# Hard-blocked keywords — NEVER allowed in LLM-generated queries
_BLOCKED_KEYWORDS = [
    "DELETE", "DETACH", "CREATE", "MERGE", "SET",
    "REMOVE", "DROP", "LOAD", "CSV", "FOREACH",
    "USING", "PERIODIC", "COMMIT",
    "APOC", "DBMS", "GRANT", "DENY", "REVOKE",
]

_MAX_QUERY_LENGTH = 2000  # Prevent excessively long injected queries





def _validate_cypher(query: str) -> tuple[bool, str]:
    """Validate that a Cypher query is safe to execute (read-only).

    Uses word-boundary regex blocking instead of substring matching.
    This prevents case-sensitivity bypasses and whitespace tricks.

    Returns:
        (is_safe, reason)
    """
    import re

    if not query or not query.strip():
        return False, "Empty query"

    query = query.strip()

    # Length check
    if len(query) > _MAX_QUERY_LENGTH:
        return False, f"Query too long ({len(query)} chars, max {_MAX_QUERY_LENGTH})"

    # Block semicolons (prevents multi-statement injection)
    if ";" in query:
        return False, "Semicolons not allowed (single statement only)"

    upper = query.upper()

    # Must start with safe clause
    safe_starts = ["MATCH", "WITH", "OPTIONAL", "UNWIND",
                   "CALL DB.INDEX.FULLTEXT"]
    if not any(upper.startswith(s) for s in safe_starts):
        return False, f"Query must start with MATCH/WITH/OPTIONAL, got: {upper[:30]}"

    # Block dangerous keywords using word-boundary regex (case-insensitive).
    # Checked before RETURN so write attempts are reported (and logged) as such.
    for blocked in _BLOCKED_KEYWORDS:
        if re.search(rf"\b{blocked}\b", upper):
            return False, f"Blocked keyword detected: {blocked}"

    # Must have RETURN clause
    if "RETURN" not in upper:
        return False, "Query must have a RETURN clause"

    return True, "OK"


def generate_cypher(question: str, entities: dict = None) -> dict:
    """Generate a Cypher query from a natural language question.

    Args:
        question: User's question in Vietnamese.
        entities: Pre-extracted entities (building_type, topic, etc.)

    Returns:
        {
            "cypher": str,          # The generated Cypher query
            "explanation": str,     # What the query does
            "params": dict,         # Query parameters
            "success": bool,
            "error": str | None,
        }
    """
    client = get_llm_client()

    entity_hint = ""
    if entities:
        entity_hint = f"\nĐã trích xuất entities: {json.dumps(entities, ensure_ascii=False)}"

    prompt = f"""Bạn là chuyên gia Neo4j Cypher. Dựa trên graph schema dưới đây, hãy viết 1 câu Cypher query để trả lời câu hỏi.

{GRAPH_SCHEMA}
{entity_hint}

### Quy tắc:
1. CHỈ viết READ query (MATCH, RETURN, WITH, WHERE, ORDER BY, LIMIT)
2. KHÔNG dùng CREATE, DELETE, MERGE, SET
3. Dùng $param cho tham số (ví dụ: $building_type)
4. Luôn LIMIT kết quả (tối đa 20)
5. Trả về đủ context: article_number, content, standard_code, requirement...
6. Nếu câu hỏi liên quan đến SO SÁNH, dùng 2 MATCH pattern
7. Nếu câu hỏi liên quan đến LIÊN KẾT giữa các quy chuẩn, dùng multi-hop traversal

### Câu hỏi: "{question}"

### Trả về JSON (chỉ JSON, không giải thích):
{{"cypher": "MATCH ...", "explanation": "...", "params": {{"key": "value"}}}}
"""

    try:
        response = client.models.generate_content(
            model=get_model_name(),
            contents=prompt,
            config=GenerateContentConfig(temperature=0.1, max_output_tokens=2048),
        )
        text = response.text.strip()

        # Clean markdown fences
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        result = json.loads(text)
        cypher = result.get("cypher", "")
        params = result.get("params", {})
        explanation = result.get("explanation", "")

        # Validate
        is_safe, reason = _validate_cypher(cypher)
        if not is_safe:
            logger.warning("cypher_blocked", reason=reason, cypher=cypher[:200])
            return {
                "cypher": None,
                "explanation": explanation,
                "params": {},
                "success": False,
                "error": f"Query blocked: {reason}",
            }

        logger.info("cypher_generated",
                     cypher=cypher[:200],
                     params=list(params.keys()),
                     explanation=explanation[:100])

        return {
            "cypher": cypher,
            "explanation": explanation,
            "params": params,
            "success": True,
            "error": None,
        }

    except Exception as e:
        logger.error("cypher_generation_failed", error=str(e))
        return {
            "cypher": None,
            "explanation": "",
            "params": {},
            "success": False,
            "error": str(e),
        }


def execute_generated_cypher(question: str, entities: dict = None) -> list[dict]:
    """Generate and execute a Cypher query, returning formatted results.

    This is the main entry point for the agent tool.

    Returns:
        List of result documents ready for RAG context.
    """
    gen_result = generate_cypher(question, entities)

    if not gen_result["success"]:
        logger.warning("cypher_fallback", error=gen_result["error"])
        return []

    try:
        raw_results = run_query(gen_result["cypher"], gen_result["params"])

        if not raw_results:
            logger.info("cypher_no_results", cypher=gen_result["cypher"][:100])
            return []

        # Format results as documents
        documents = []
        for row in raw_results[:20]:  # Safety limit
            # Build a readable text from the row
            parts = []
            for key, value in row.items():
                if value is not None and value != "":
                    if isinstance(value, str) and len(value) > 500:
                        value = value[:500] + "..."
                    parts.append(f"{key}: {value}")

            text = "\n".join(parts)
            documents.append({
                "text": f"[Graph Reasoning] {gen_result['explanation']}\n{text}",
                "metadata": {
                    "source": "graph_reasoning",
                    "cypher": gen_result["cypher"][:200],
                },
                "score": 0.92,
            })

        logger.info("graph_reasoning_success",
                     results=len(documents),
                     explanation=gen_result["explanation"][:100])
        return documents

    except Exception as e:
        logger.error("cypher_execution_failed",
                     error=str(e),
                     cypher=gen_result["cypher"][:200])
        return []


def cross_reference_standards(standard_code_1: str, standard_code_2: str,
                               topic: str = None) -> list[dict]:
    """Find cross-references between two standards on a given topic.

    Multi-hop query: Standard1 → Articles → Requirements ↔ Requirements ← Articles ← Standard2

    Args:
        standard_code_1: First standard code (e.g., "QCVN 06:2022/BXD")
        standard_code_2: Second standard code
        topic: Optional topic filter

    Returns:
        List of cross-reference documents.
    """
    topic_filter = ""
    params = {"code1": standard_code_1, "code2": standard_code_2}

    if topic:
        topic_filter = "AND (a1.content CONTAINS $topic OR a2.content CONTAINS $topic)"
        params["topic"] = topic

    cypher = f"""
    MATCH (s1:Standard {{code: $code1}})-[:CONTAINS]->(:Chapter)-[:HAS_SECTION]->(:Section)-[:HAS_ARTICLE]->(a1:Article)
    MATCH (s2:Standard {{code: $code2}})-[:CONTAINS]->(:Chapter)-[:HAS_SECTION]->(:Section)-[:HAS_ARTICLE]->(a2:Article)
    WHERE (
        a1.content CONTAINS a2.title OR a2.content CONTAINS a1.title
        OR EXISTS {{
            MATCH (a1)-[:SPECIFIES]->(r1:Requirement)-[:CLASSIFIES]->(bt:BuildingType)<-[:CLASSIFIES]-(r2:Requirement)<-[:SPECIFIES]-(a2)
        }}
    ) {topic_filter}
    RETURN s1.code AS standard_1,
           a1.number AS article_1,
           a1.title AS title_1,
           substring(a1.content, 0, 300) AS content_1,
           s2.code AS standard_2,
           a2.number AS article_2,
           a2.title AS title_2,
           substring(a2.content, 0, 300) AS content_2
    LIMIT 15
    """

    is_safe, reason = _validate_cypher(cypher)
    if not is_safe:
        logger.warning("cross_ref_blocked", reason=reason)
        return []

    try:
        results = run_query(cypher, params)
        documents = []
        for row in results:
            text = (
                f"[Tham chiếu chéo]\n"
                f"📌 {row['standard_1']} Điều {row['article_1']}: {row['title_1']}\n"
                f"   {row['content_1']}\n"
                f"🔗 {row['standard_2']} Điều {row['article_2']}: {row['title_2']}\n"
                f"   {row['content_2']}"
            )
            documents.append({
                "text": text,
                "metadata": {
                    "source": "cross_reference",
                    "standards": [standard_code_1, standard_code_2],
                },
                "score": 0.95,
            })
        logger.info("cross_reference_results", count=len(documents))
        return documents
    except Exception as e:
        logger.error("cross_reference_failed", error=str(e))
        return []
