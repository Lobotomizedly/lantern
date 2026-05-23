"""
Agent Tool Catalog

Defines the tools available to agents for interacting with
the Lantern platform and external services.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union
from uuid import uuid4

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Result from a tool execution."""
    success: bool = Field(..., description="Whether the tool executed successfully")
    data: Any = Field(default=None, description="Tool output data")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all agent tools."""

    name: str
    description: str

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given parameters."""
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Return the JSON schema for this tool's parameters."""
        pass

    def to_claude_tool(self) -> Dict[str, Any]:
        """Convert to Claude tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_schema(),
        }


class CorpusSearchTool(BaseTool):
    """
    Semantic search over the document corpus.

    Searches across items (articles, posts, broadcasts) using
    embedding-based similarity search.
    """

    name = "corpus_search"
    description = """Search the document corpus using semantic similarity.
    Returns relevant items matching the query, ranked by relevance.
    Use this to find documents discussing specific topics, events, or entities."""

    def __init__(self, corpus_service: Any = None):
        self.corpus_service = corpus_service

    async def execute(
        self,
        query: str,
        subject_id: Optional[str] = None,
        source_types: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute semantic search over the corpus."""
        try:
            # Build search parameters
            search_params = {
                "query": query,
                "limit": limit,
            }

            if subject_id:
                search_params["subject_id"] = subject_id
            if source_types:
                search_params["source_types"] = source_types
            if date_from:
                search_params["date_from"] = date_from
            if date_to:
                search_params["date_to"] = date_to

            # Execute search through corpus service
            if self.corpus_service:
                results = await self.corpus_service.semantic_search(**search_params)
            else:
                # Mock response for testing
                results = {
                    "items": [],
                    "total_count": 0,
                    "query": query,
                }

            return ToolResult(
                success=True,
                data=results,
                metadata={"query": query, "limit": limit},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"query": query},
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query text",
                },
                "subject_id": {
                    "type": "string",
                    "description": "Optional subject ID to scope search",
                },
                "source_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by source types (e.g., 'news', 'social', 'broadcast')",
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date filter (ISO format)",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date filter (ISO format)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 20)",
                    "default": 20,
                },
            },
            "required": ["query"],
        }


class GraphQueryTool(BaseTool):
    """
    Query the entity/event/narrative graph.

    Executes graph queries to explore relationships between
    entities, events, and narratives.
    """

    name = "graph_query"
    description = """Query the knowledge graph to explore entities, events, and narratives.
    Use this to find relationships, trace narrative spread, identify key actors,
    and understand connections between entities."""

    def __init__(self, graph_service: Any = None):
        self.graph_service = graph_service

    async def execute(
        self,
        query_type: str,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        relationship_type: Optional[str] = None,
        depth: int = 2,
        limit: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a graph query."""
        try:
            # Build query parameters
            query_params = {
                "query_type": query_type,
                "depth": depth,
                "limit": limit,
            }

            if entity_id:
                query_params["entity_id"] = entity_id
            if entity_type:
                query_params["entity_type"] = entity_type
            if relationship_type:
                query_params["relationship_type"] = relationship_type

            # Execute query through graph service
            if self.graph_service:
                results = await self.graph_service.query(**query_params)
            else:
                # Mock response
                results = {
                    "nodes": [],
                    "edges": [],
                    "query_type": query_type,
                }

            return ToolResult(
                success=True,
                data=results,
                metadata={"query_type": query_type},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": [
                        "entity_neighbors",
                        "entity_relationships",
                        "narrative_spread",
                        "event_participants",
                        "amplifier_network",
                        "entity_timeline",
                        "shortest_path",
                    ],
                    "description": "Type of graph query to execute",
                },
                "entity_id": {
                    "type": "string",
                    "description": "ID of the entity to query from",
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "organization", "location", "event", "narrative"],
                    "description": "Filter by entity type",
                },
                "relationship_type": {
                    "type": "string",
                    "description": "Filter by relationship type",
                },
                "depth": {
                    "type": "integer",
                    "description": "Graph traversal depth (default: 2)",
                    "default": 2,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 50)",
                    "default": 50,
                },
            },
            "required": ["query_type"],
        }


class ItemFetchTool(BaseTool):
    """
    Fetch full content of a specific item.

    Retrieves the complete content and metadata for an item by ID.
    """

    name = "item_fetch"
    description = """Fetch the full content of a document item by its ID.
    Use this when you need to read the complete text of an article,
    post, or transcript."""

    def __init__(self, item_service: Any = None):
        self.item_service = item_service

    async def execute(
        self,
        item_id: str,
        include_metadata: bool = True,
        include_entities: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """Fetch a specific item."""
        try:
            if self.item_service:
                item = await self.item_service.get_item(
                    item_id=item_id,
                    include_metadata=include_metadata,
                    include_entities=include_entities,
                )
            else:
                # Mock response
                item = {
                    "id": item_id,
                    "content": "",
                    "title": "",
                    "source": {},
                    "published_at": None,
                }

            return ToolResult(
                success=True,
                data=item,
                metadata={"item_id": item_id},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"item_id": item_id},
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "The ID of the item to fetch",
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include source metadata (default: true)",
                    "default": True,
                },
                "include_entities": {
                    "type": "boolean",
                    "description": "Include extracted entities (default: true)",
                    "default": True,
                },
            },
            "required": ["item_id"],
        }


class WebSearchTool(BaseTool):
    """
    Search the open web for external information.

    Performs web searches to find relevant external content.
    """

    name = "web_search"
    description = """Search the open web for information not in the corpus.
    Use this sparingly to verify facts, find background information,
    or discover new sources."""

    def __init__(self, search_provider: Any = None):
        self.search_provider = search_provider

    async def execute(
        self,
        query: str,
        site: Optional[str] = None,
        date_restrict: Optional[str] = None,
        limit: int = 10,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a web search."""
        try:
            search_params = {
                "query": query,
                "limit": limit,
            }

            if site:
                search_params["site"] = site
            if date_restrict:
                search_params["date_restrict"] = date_restrict

            if self.search_provider:
                results = await self.search_provider.search(**search_params)
            else:
                # Mock response
                results = {
                    "results": [],
                    "query": query,
                }

            return ToolResult(
                success=True,
                data=results,
                metadata={"query": query},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "site": {
                    "type": "string",
                    "description": "Limit search to a specific site",
                },
                "date_restrict": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year"],
                    "description": "Restrict to recent results",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        }


class WebFetchTool(BaseTool):
    """
    Fetch content from an external URL.

    Retrieves and extracts content from web pages.
    """

    name = "web_fetch"
    description = """Fetch and extract content from an external URL.
    Use this to retrieve the full text of web pages found via web_search
    or referenced in items."""

    def __init__(self, fetch_service: Any = None):
        self.fetch_service = fetch_service

    async def execute(
        self,
        url: str,
        extract_main_content: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """Fetch content from a URL."""
        try:
            if self.fetch_service:
                content = await self.fetch_service.fetch(
                    url=url,
                    extract_main_content=extract_main_content,
                )
            else:
                # Mock response
                content = {
                    "url": url,
                    "title": "",
                    "content": "",
                    "fetched_at": datetime.utcnow().isoformat(),
                }

            return ToolResult(
                success=True,
                data=content,
                metadata={"url": url},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"url": url},
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
                "extract_main_content": {
                    "type": "boolean",
                    "description": "Extract main article content (default: true)",
                    "default": True,
                },
            },
            "required": ["url"],
        }


class SubAgentSpawnTool(BaseTool):
    """
    Spawn a child agent for a subtask.

    Creates a new agent instance to handle a specific subtask,
    inheriting budget constraints from the parent.
    """

    name = "sub_agent_spawn"
    description = """Spawn a child agent to handle a specific subtask.
    Use this to delegate complex subtasks like investigation or synthesis.
    The child agent inherits budget constraints from the parent."""

    def __init__(self, agent_manager: Any = None):
        self.agent_manager = agent_manager

    async def execute(
        self,
        agent_type: str,
        goal: str,
        inputs: Dict[str, Any],
        budget_fraction: float = 0.25,
        wait_for_completion: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """Spawn a sub-agent."""
        try:
            if self.agent_manager:
                result = await self.agent_manager.spawn_sub_agent(
                    agent_type=agent_type,
                    goal=goal,
                    inputs=inputs,
                    budget_fraction=budget_fraction,
                    wait_for_completion=wait_for_completion,
                )
            else:
                # Mock response
                result = {
                    "agent_id": str(uuid4()),
                    "status": "spawned",
                    "agent_type": agent_type,
                }

            return ToolResult(
                success=True,
                data=result,
                metadata={"agent_type": agent_type, "goal": goal},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_type": {
                    "type": "string",
                    "enum": ["investigator", "synthesizer"],
                    "description": "Type of agent to spawn",
                },
                "goal": {
                    "type": "string",
                    "description": "Goal for the sub-agent",
                },
                "inputs": {
                    "type": "object",
                    "description": "Input parameters for the sub-agent",
                },
                "budget_fraction": {
                    "type": "number",
                    "description": "Fraction of remaining budget to allocate (default: 0.25)",
                    "default": 0.25,
                },
                "wait_for_completion": {
                    "type": "boolean",
                    "description": "Wait for sub-agent to complete (default: true)",
                    "default": True,
                },
            },
            "required": ["agent_type", "goal", "inputs"],
        }


class DraftArtifactTool(BaseTool):
    """
    Create a draft artifact for review.

    Produces structured output documents (reports, memos, timelines)
    that can be reviewed and published.
    """

    name = "draft_artifact"
    description = """Create a draft artifact for review.
    Use this to produce structured outputs like reports, memos, timelines,
    or newsletters. The artifact will be queued for review based on policy."""

    def __init__(self, artifact_service: Any = None):
        self.artifact_service = artifact_service

    async def execute(
        self,
        artifact_type: str,
        title: str,
        content: str,
        citations: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Create a draft artifact."""
        try:
            artifact_data = {
                "id": str(uuid4()),
                "type": artifact_type,
                "title": title,
                "content": content,
                "citations": citations,
                "metadata": metadata or {},
                "created_at": datetime.utcnow().isoformat(),
                "review_status": "pending",
            }

            if self.artifact_service:
                artifact = await self.artifact_service.create_draft(artifact_data)
            else:
                artifact = artifact_data

            return ToolResult(
                success=True,
                data=artifact,
                metadata={"artifact_type": artifact_type, "title": title},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_type": {
                    "type": "string",
                    "enum": ["report", "memo", "timeline", "newsletter", "briefing"],
                    "description": "Type of artifact to create",
                },
                "title": {
                    "type": "string",
                    "description": "Title of the artifact",
                },
                "content": {
                    "type": "string",
                    "description": "Main content of the artifact (Markdown supported)",
                },
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "quote": {"type": "string"},
                            "context": {"type": "string"},
                        },
                    },
                    "description": "List of citations/sources",
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional metadata",
                },
            },
            "required": ["artifact_type", "title", "content", "citations"],
        }


class EmitFlagTool(BaseTool):
    """
    Emit a flag for review.

    Creates alerts for human review when significant changes
    or concerns are detected.
    """

    name = "emit_flag"
    description = """Emit a flag to alert human reviewers.
    Use this when you detect something significant that requires attention:
    emerging narratives, sentiment shifts, velocity spikes, new entities,
    or notable items."""

    def __init__(self, flag_service: Any = None):
        self.flag_service = flag_service

    async def execute(
        self,
        flag_type: str,
        severity: str,
        title: str,
        description: str,
        evidence: List[Dict[str, Any]],
        subject_id: Optional[str] = None,
        narrative_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Emit a flag."""
        try:
            flag_data = {
                "id": str(uuid4()),
                "type": flag_type,
                "severity": severity,
                "title": title,
                "description": description,
                "evidence": evidence,
                "subject_id": subject_id,
                "narrative_id": narrative_id,
                "created_at": datetime.utcnow().isoformat(),
                "acknowledged": False,
            }

            if self.flag_service:
                flag = await self.flag_service.create_flag(flag_data)
            else:
                flag = flag_data

            return ToolResult(
                success=True,
                data=flag,
                metadata={"flag_type": flag_type, "severity": severity},
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
            )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "flag_type": {
                    "type": "string",
                    "enum": [
                        "emerging_narrative",
                        "sentiment_shift",
                        "velocity_spike",
                        "new_entity",
                        "notable_item",
                        "coordination_detected",
                        "lifecycle_change",
                        "amplifier_surge",
                    ],
                    "description": "Type of flag",
                },
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "alert", "critical"],
                    "description": "Severity level",
                },
                "title": {
                    "type": "string",
                    "description": "Short title for the flag",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the flag",
                },
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "excerpt": {"type": "string"},
                            "relevance": {"type": "string"},
                        },
                    },
                    "description": "Supporting evidence for the flag",
                },
                "subject_id": {
                    "type": "string",
                    "description": "Related subject ID (optional)",
                },
                "narrative_id": {
                    "type": "string",
                    "description": "Related narrative ID (optional)",
                },
            },
            "required": ["flag_type", "severity", "title", "description", "evidence"],
        }


class AgentToolCatalog:
    """
    Catalog of available agent tools.

    Manages tool registration, lookup, and configuration.
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        default_tools = [
            CorpusSearchTool(),
            GraphQueryTool(),
            ItemFetchTool(),
            WebSearchTool(),
            WebFetchTool(),
            SubAgentSpawnTool(),
            DraftArtifactTool(),
            EmitFlagTool(),
        ]

        for tool in default_tools:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        """Register a tool in the catalog."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_tools(self, names: Optional[List[str]] = None) -> List[BaseTool]:
        """Get tools by name list, or all if names is None."""
        if names is None:
            return list(self._tools.values())
        return [self._tools[name] for name in names if name in self._tools]

    def get_claude_tools(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get tools in Claude format."""
        tools = self.get_tools(names)
        return [tool.to_claude_tool() for tool in tools]

    def configure_services(
        self,
        corpus_service: Any = None,
        graph_service: Any = None,
        item_service: Any = None,
        search_provider: Any = None,
        fetch_service: Any = None,
        agent_manager: Any = None,
        artifact_service: Any = None,
        flag_service: Any = None,
    ) -> None:
        """Configure service dependencies for tools."""
        if corpus_service and "corpus_search" in self._tools:
            self._tools["corpus_search"].corpus_service = corpus_service
        if graph_service and "graph_query" in self._tools:
            self._tools["graph_query"].graph_service = graph_service
        if item_service and "item_fetch" in self._tools:
            self._tools["item_fetch"].item_service = item_service
        if search_provider and "web_search" in self._tools:
            self._tools["web_search"].search_provider = search_provider
        if fetch_service and "web_fetch" in self._tools:
            self._tools["web_fetch"].fetch_service = fetch_service
        if agent_manager and "sub_agent_spawn" in self._tools:
            self._tools["sub_agent_spawn"].agent_manager = agent_manager
        if artifact_service and "draft_artifact" in self._tools:
            self._tools["draft_artifact"].artifact_service = artifact_service
        if flag_service and "emit_flag" in self._tools:
            self._tools["emit_flag"].flag_service = flag_service


# Singleton catalog instance
tool_catalog = AgentToolCatalog()
