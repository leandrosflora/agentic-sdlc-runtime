from agentic_sdlc_runtime.definitions import AgentRegistry


def test_all_eight_agent_definitions_load():
    registry = AgentRegistry("agents")
    assert registry.roles() == [
        "architecture", "developer", "incident", "product",
        "release", "reviewer", "security", "test",
    ]
    for role in registry.roles():
        definition = registry.load(role)
        assert definition.role == role
        assert definition.allowed_tools
