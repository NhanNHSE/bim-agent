"""Base Agent — abstract interface for all specialist agents.

All agents follow the same pattern:
  1. Receive question + context
  2. Execute their specialized tools
  3. Return retrieved documents + metadata
"""

from abc import ABC, abstractmethod
from typing import Any
import structlog

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base for all specialist agents."""

    name: str = "base"
    description: str = "Base agent"

    @abstractmethod
    def get_tools(self) -> list[str]:
        """Return list of tool names this agent can use."""
        ...

    @abstractmethod
    def run(self, question: str, entities: dict, **kwargs) -> dict:
        """Execute the agent's specialized logic.

        Args:
            question: User's question.
            entities: Extracted entities from classifier.

        Returns:
            {
                "documents": list[dict],   # Retrieved/generated documents
                "tool_results": dict,      # Any special tool results (e.g., design)
                "metadata": dict,          # Agent-specific metadata
            }
        """
        ...

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name}>"
