from types import SimpleNamespace

from app.agent.graph import build_multi_agent_supervisor_node
from app.agents.a2a.message import AgentMessage
from app.agents.a2a.protocol import A2AProtocol
from app.agents.agent_tool import AgentToolAdapter
from app.agents.base import AgentTask, SimpleAgent
from app.agents.capability import DATA_ANALYSIS, SQL_GENERATION
from app.agents.handoff import HandoffManager
from app.agents.orchestrator import SupervisorAgent
from app.agents.registry import AgentRegistry
from app.agents.router import AgentRouter
from app.core.telemetry import telemetry_manager
from app.security.context import create_security_context


def _build_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(SimpleAgent(name="sql_agent", description="SQL agent", capabilities=[SQL_GENERATION]))
    registry.register(SimpleAgent(name="analysis_agent", description="Analysis agent", capabilities=[DATA_ANALYSIS]))
    return registry


async def test_supervisor_plans_sql_and_analysis_agents() -> None:
    supervisor = SupervisorAgent(AgentRouter(_build_registry()))

    plan = await supervisor.plan("task-1", "查询销售趋势并分析原因")

    assert [step.target_agent for step in plan.steps] == ["sql_agent", "analysis_agent"]


async def test_graph_exposes_multi_agent_supervisor_node() -> None:
    node = build_multi_agent_supervisor_node()
    runtime = SimpleNamespace(context={"agent_registry": _build_registry()})

    update = await node({"request_id": "task-1", "query": "查询销售趋势并分析原因"}, runtime)

    assert update["multi_agent_plan"][0]["target_agent"] == "sql_agent"
    assert update["multi_agent_plan"][1]["target_agent"] == "analysis_agent"


async def test_complete_multi_agent_flow_handoff_security_and_trace() -> None:
    registry = _build_registry()
    plan = await SupervisorAgent(AgentRouter(registry)).plan("task-1", "查询销售趋势并分析原因")
    handoff = HandoffManager().create(
        sender="sql_agent",
        receiver="analysis_agent",
        task_id="task-1",
        payload={"summary": "safe", "api_key": "unsafe"},
        trace_id="trace-1",
    )
    message = A2AProtocol(registry).validate(
        AgentMessage(
            sender="sql_agent",
            receiver="analysis_agent",
            task_id="task-1",
            capability="data_analysis",
            payload=handoff.payload,
            trace_id="trace-1",
        )
    )
    tool_result = await AgentToolAdapter(registry.require("analysis_agent")).execute(
        create_security_context(user_id="u1", permissions=["tool:analysis_agent:execute"]),
        AgentTask("task-1", "query", "data_analysis", context=message.payload),
    )

    assert [step.target_agent for step in plan.steps] == ["sql_agent", "analysis_agent"]
    assert message.trace_id == "trace-1"
    assert "api_key" not in message.payload
    assert tool_result["success"] is True


async def test_multi_agent_telemetry_spans_are_safe() -> None:
    telemetry_manager.enable_test_capture()
    try:
        supervisor = SupervisorAgent(AgentRouter(_build_registry()))

        await supervisor.plan("task-1", "查询销售趋势并分析原因")

        span_names = [span.name for span in telemetry_manager.captured_spans]
        encoded_attrs = str([span.attributes for span in telemetry_manager.captured_spans])
        assert "agent.supervisor" in span_names
        assert "agent.route" in span_names
        assert "prompt" not in encoded_attrs.lower()
        assert "secret" not in encoded_attrs.lower()
    finally:
        telemetry_manager.disable_test_capture()
