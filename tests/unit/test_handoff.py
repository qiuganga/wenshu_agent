from app.agents.agent_tool import AgentToolAdapter
from app.agents.base import AgentTask, SimpleAgent
from app.agents.capability import DATA_ANALYSIS
from app.agents.handoff import HandoffManager
from app.agents.memory import AgentMemory
from app.security.context import create_security_context


def test_handoff_manager_sanitizes_payload() -> None:
    context = HandoffManager().create(
        sender="sql_agent",
        receiver="analysis_agent",
        task_id="task-1",
        payload={"summary": "ok", "token": "unsafe", "nested": {"password": "unsafe", "value": 1}},
    )

    assert context.payload["summary"] == "ok"
    assert "token" not in context.payload
    assert "password" not in context.payload["nested"]
    assert context.payload["nested"]["value"] == 1


async def test_agent_memory_does_not_store_forbidden_fields() -> None:
    memory = AgentMemory()

    await memory.save("exec-1", {"safe": "value", "raw_result": [{"secret": "unsafe"}]})

    assert await memory.load("exec-1") == {"safe": "value"}


async def test_agent_tool_adapter_uses_tool_permission_guard() -> None:
    agent = SimpleAgent(name="analysis_agent", description="Analysis agent", capabilities=[DATA_ANALYSIS])
    adapter = AgentToolAdapter(agent)

    denied = await adapter.execute(
        create_security_context(user_id="u1", permissions=[]),
        AgentTask("task-1", "query", "data_analysis"),
    )
    allowed = await adapter.execute(
        create_security_context(user_id="u1", permissions=["tool:analysis_agent:execute"]),
        AgentTask("task-1", "query", "data_analysis"),
    )

    assert denied["success"] is False
    assert denied["error_code"] == "AGENT_TOOL_PERMISSION_DENIED"
    assert allowed["success"] is True
    assert allowed["agent_name"] == "analysis_agent"
