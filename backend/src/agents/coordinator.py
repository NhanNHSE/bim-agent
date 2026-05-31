"""Coordinator — Multi-agent orchestrator.

Routes user questions to the appropriate specialist agent(s),
collects results, and synthesizes a unified response.

Flow:
  1. Classify question intent (reuse existing classifier from agent.py)
  2. Map intent → specialist agent(s)
  3. Run agent(s) in parallel if multiple
  4. Merge documents + rerank
  5. Generate streaming response with agent-specific system prompt
"""

import structlog

from src.agents.qcvn_agent import QCVNAgent
from src.agents.bim_agent import BIMAgent
from src.agents.design_agent import DesignAgent
from src.rag.agent import (
    classify_question,
    AgentState,
    _generate_stream,
    MAX_RETRIES,
)
from src.rag.graph_rag import _rerank

logger = structlog.get_logger()

# Singleton agent instances
_qcvn_agent = QCVNAgent()
_bim_agent = BIMAgent()
_design_agent = DesignAgent()

# Intent → Agent mapping
AGENT_MAP = {
    "qcvn_search": _qcvn_agent,
    "graph_reasoning": _qcvn_agent,
    "material_check": _qcvn_agent,
    "ifc_query": _bim_agent,
    "design_building": _design_agent,
}


def ask(question: str, messages: list = None, stream: bool = True, mode: str = None):
    """Multi-agent entry point — drop-in replacement for agent.ask().

    Args:
        question: User's question.
        messages: Previous conversation messages.
        stream: If True, return a generator.
        mode: UI mode override ('consult', 'design', 'analyze').

    Returns:
        Tuple of (response_or_generator, documents, entities, tool_results).
    """

    # Step 1: Classify intent (reuse existing classifier)
    state = AgentState(
        question=question,
        messages=messages or [],
        intent="",
        tools_to_use=[],
        tool_results={},
        retrieved_docs=[],
        entities={},
        response="",
    )

    mode_tool_map = {
        "design": ["design_building"],
        "analyze": ["ifc_query"],
    }
    if mode and mode in mode_tool_map:
        state["tools_to_use"] = mode_tool_map[mode]
        state["intent"] = mode
        state["entities"] = {}
        logger.info("coordinator_mode_override", mode=mode)
    else:
        state = classify_question(state)

    tools = state["tools_to_use"]
    entities = state["entities"]
    intent = state["intent"]

    logger.info("coordinator_routing",
                tools=tools,
                intent=intent,
                entities=list(entities.keys()))

    # Step 2: Route to specialist agent(s)
    all_documents = []
    all_tool_results = {}
    system_prompt_override = None
    agents_used = set()

    for tool_name in tools:
        agent = AGENT_MAP.get(tool_name)
        if agent and agent.name not in agents_used:
            agents_used.add(agent.name)
            logger.info("coordinator_dispatching",
                        agent=agent.name,
                        tool=tool_name)

            result = agent.run(question, entities)
            all_documents.extend(result.get("documents", []))
            all_tool_results.update(result.get("tool_results", {}))

            # Use the first agent's system prompt
            if system_prompt_override is None:
                system_prompt_override = result.get("metadata", {}).get("system_prompt")

    # Handle general_chat (no agent needed)
    if not agents_used and "general_chat" in tools:
        logger.info("coordinator_general_chat")

    # Step 3: Deduplicate + Rerank
    seen = set()
    unique_docs = []
    for doc in all_documents:
        key = doc["text"][:200]
        if key not in seen:
            seen.add(key)
            unique_docs.append(doc)

    if unique_docs:
        ranked = _rerank(question, unique_docs)
    else:
        ranked = []

    logger.info("coordinator_results",
                agents=list(agents_used),
                total_docs=len(ranked))

    # Step 4: Generate response
    if stream:
        return (
            _generate_stream(question, ranked, messages, intent),
            ranked,
            entities,
            all_tool_results,
        )
    else:
        response = "".join(_generate_stream(question, ranked, messages, intent))
        return response, ranked, entities, all_tool_results
