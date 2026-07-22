import pytest

from app.agents.base import SimpleAgent
from app.agents.capability import DATA_ANALYSIS, SQL_GENERATION
from app.agents.registry import AgentRegistry


def test_agent_registry_registers_and_discovers_capability() -> None:
    registry = AgentRegistry()
    sql_agent = SimpleAgent(name="sql_agent", description="SQL agent", capabilities=[SQL_GENERATION])

    registry.register(sql_agent)

    assert registry.get("SQL_AGENT") is sql_agent
    assert registry.require("sql_agent") is sql_agent
    assert registry.discover("sql_generation")[0].name == "sql_agent"
    assert registry.list_agents()[0].capabilities == ["sql_generation"]


def test_agent_registry_rejects_empty_name() -> None:
    registry = AgentRegistry()

    with pytest.raises(ValueError, match="agent name must not be empty"):
        registry.register(SimpleAgent(name="", description="invalid", capabilities=[DATA_ANALYSIS]))


def test_agent_registry_require_unknown_agent() -> None:
    with pytest.raises(KeyError):
        AgentRegistry().require("missing")
