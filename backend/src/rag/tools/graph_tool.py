"""Graph reasoning tool — LLM-generated Cypher for complex multi-hop queries."""

import re

import structlog

from src.knowledge_graph.graph_query_generator import (
    execute_generated_cypher,
    cross_reference_standards,
)

logger = structlog.get_logger()


def tool_graph_reasoning(question: str, entities: dict) -> list:
    """Advanced graph reasoning — LLM generates Cypher for complex questions.

    Handles:
    - Multi-hop traversals across the knowledge graph
    - Cross-referencing between different standards
    - Complex comparisons (e.g., "So sánh F1 vs F2")
    - Relationship discovery
    """
    results = []

    # Try cross-reference if 2 standard codes are mentioned
    q_lower = question.lower()
    codes = re.findall(r'qcvn\s*\d+|tcvn\s*\d+', q_lower)
    if len(codes) >= 2:
        # Cross-reference mode
        code1 = codes[0].upper().replace("QCVN ", "QCVN ").strip()
        code2 = codes[1].upper().replace("TCVN ", "TCVN ").strip()
        topic = entities.get("topic", None)
        xref_results = cross_reference_standards(code1, code2, topic)
        results.extend(xref_results)

    # Dynamic Cypher generation for all questions
    cypher_results = execute_generated_cypher(question, entities)
    results.extend(cypher_results)

    logger.info("tool_graph_reasoning", results=len(results))
    return results
