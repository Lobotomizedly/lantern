"""
Lantern Agent System

A comprehensive agent framework for narrative intelligence operations.
Agents are goal-oriented, budget-constrained, and integrated with Temporal
for durable execution.
"""

from .base import (
    Agent,
    AgentConfig,
    AgentMemory,
    AgentBudget,
    AgentOutput,
    StopCondition,
    ReviewPolicy,
    AgentState,
    StandingAgent,
    EphemeralAgent,
)
from .tools import (
    AgentToolCatalog,
    CorpusSearchTool,
    GraphQueryTool,
    ItemFetchTool,
    WebSearchTool,
    WebFetchTool,
    SubAgentSpawnTool,
    DraftArtifactTool,
    EmitFlagTool,
)
from .sentinel import SentinelAgent, SentinelConfig
from .narrative_tracker import NarrativeTrackerAgent, NarrativeTrackerConfig
from .graph_curator import GraphCuratorAgent, GraphCuratorConfig
from .investigator import InvestigatorAgent, InvestigatorConfig
from .synthesizer import SynthesizerAgent, SynthesizerConfig, ArtifactType
from .manager import AgentManager, AgentRun, AgentRunStatus
from .workflows import (
    DailySentinelWorkflow,
    NarrativeTrackerWorkflow,
    InvestigatorWorkflow,
    SynthesizerWorkflow,
)

__all__ = [
    # Base classes
    "Agent",
    "AgentConfig",
    "AgentMemory",
    "AgentBudget",
    "AgentOutput",
    "StopCondition",
    "ReviewPolicy",
    "AgentState",
    "StandingAgent",
    "EphemeralAgent",
    # Tools
    "AgentToolCatalog",
    "CorpusSearchTool",
    "GraphQueryTool",
    "ItemFetchTool",
    "WebSearchTool",
    "WebFetchTool",
    "SubAgentSpawnTool",
    "DraftArtifactTool",
    "EmitFlagTool",
    # Agents
    "SentinelAgent",
    "SentinelConfig",
    "NarrativeTrackerAgent",
    "NarrativeTrackerConfig",
    "GraphCuratorAgent",
    "GraphCuratorConfig",
    "InvestigatorAgent",
    "InvestigatorConfig",
    "SynthesizerAgent",
    "SynthesizerConfig",
    "ArtifactType",
    # Manager
    "AgentManager",
    "AgentRun",
    "AgentRunStatus",
    # Workflows
    "DailySentinelWorkflow",
    "NarrativeTrackerWorkflow",
    "InvestigatorWorkflow",
    "SynthesizerWorkflow",
]
