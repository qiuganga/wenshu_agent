import pytest

from app.agents.a2a.message import AgentMessage
from app.agents.a2a.protocol import A2AProtocol
from app.agents.base import SimpleAgent
from app.agents.capability import DATA_ANALYSIS, SQL_GENERATION
from app.agents.registry import AgentRegistry


def _registry_with_agents() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(SimpleAgent(name="sql_agent", description="SQL agent", capabilities=[SQL_GENERATION]))
    registry.register(SimpleAgent(name="analysis_agent", description="Analysis agent", capabilities=[DATA_ANALYSIS]))
    return registry


def test_a2a_protocol_validates_and_sanitizes_message() -> None:
    protocol = A2AProtocol(_registry_with_agents())

    message = protocol.validate(
        AgentMessage(
            sender="sql_agent",
            receiver="analysis_agent",
            task_id="task-1",
            capability="data_analysis",
            payload={"summary": "ok", "secret": "unsafe"},
            trace_id="trace-1",
        )
    )

    assert message.payload == {"summary": "ok"}
    assert message.trace_id == "trace-1"


def test_a2a_protocol_rejects_unknown_receiver() -> None:
    protocol = A2AProtocol(_registry_with_agents())

    with pytest.raises(ValueError, match="receiver agent is not registered"):
        protocol.validate(AgentMessage("sql_agent", "missing", "task-1", "data_analysis"))


def test_a2a_protocol_rejects_unsupported_capability() -> None:
    protocol = A2AProtocol(_registry_with_agents())

    with pytest.raises(ValueError, match="receiver does not support requested capability"):
        protocol.validate(AgentMessage("sql_agent", "analysis_agent", "task-1", "sql_generation"))
