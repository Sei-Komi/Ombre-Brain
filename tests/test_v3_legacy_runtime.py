from pathlib import Path

from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome
from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.policy.static_surfaces import SurfaceRisk
from ombrebrain.protocol.schemas import MemoryType


def test_legacy_runtime_initializes_fabric_and_foundation_capabilities(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    assert runtime.root == Path(tmp_path / "buckets" / ".ombrebrain-v3")
    assert "tools.search" in runtime.capability_names()
    assert runtime.fabric.next_index() == 1


def test_legacy_runtime_dispatches_capability_with_context(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    result = runtime.dispatch_capability(
        "tools.search",
        {"query": "permanent"},
        permissions=("mcp:read", "mcp:call", "tools:search"),
        actor_name="legacy-test",
        source="tests",
    )

    assert result["name"] == "tools.search"
    assert result["actor_name"] == "legacy-test"
    assert result["payload"] == {"query": "permanent"}


def test_legacy_runtime_records_bucket_events_in_memory_fabric(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    index = runtime.record_bucket_event(
        action="create",
        bucket_id="bucket-1",
        bucket_type="permanent",
        content="keep this",
        metadata={"importance": 9, "domain": ["test"]},
    )
    events = runtime.fabric.replay_events()

    assert index == 1
    assert len(events) == 1
    assert events[0].memory_type == MemoryType.PERMANENT
    assert events[0].content == "keep this"
    assert events[0].source_chain == ("legacy_bucket_manager", "create")
    assert events[0].metadata["legacy_bucket_id"] == "bucket-1"
    assert events[0].metadata["legacy_bucket_type"] == "permanent"
    assert events[0].metadata["legacy_metadata"]["importance"] == 9


def test_legacy_runtime_handles_unknown_bucket_type_as_dynamic(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_bucket_event(
        action="update",
        bucket_id="bucket-2",
        bucket_type="unknown",
        content="fallback",
        metadata={},
    )

    assert runtime.fabric.replay_events()[0].memory_type == MemoryType.DYNAMIC


def test_legacy_runtime_records_tool_events(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "permanent", "max_results": 3})

    event = runtime.fabric.replay_events()[0]
    assert event.memory_type == MemoryType.TRACE
    assert event.content == "legacy tool invocation: breath"
    assert event.source_chain == ("legacy_tool", "breath")
    assert event.metadata["legacy_tool_name"] == "breath"
    assert event.metadata["legacy_payload"] == {"query": "permanent", "max_results": 3}


def test_legacy_runtime_tool_event_includes_projection_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "permanent", "max_results": 3})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["legacy_payload"] == {"query": "permanent", "max_results": 3}
    assert metadata["projection_journal"]["command_id"] == metadata["command_plan"]["command_id"]
    assert metadata["consistency_report"]["ok"] is True


def test_legacy_runtime_execution_event_includes_projection_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="tools.hold",
        operation="hold",
        payload={"bucket_id": "b1", "content_length": 12},
        actor_name="legacy-test",
        source="tests",
        permissions=("mcp:call",),
        writes_memory=True,
    )
    outcome = ExecutionOutcome(ok=True, phase_history=("received", "completed"), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["command_plan"]["command_kind"] == "hold"
    assert metadata["projection_journal"]["command_id"] == metadata["command_plan"]["command_id"]
    assert len(metadata["projection_journal"]["entries"]) == len(metadata["command_plan"]["projections"])
    assert metadata["consistency_report"]["ok"] is True


def test_legacy_runtime_execution_event_includes_projection_observations(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.breath", operation="breath", payload={"query": "x"})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert "projection_observations" in metadata
    assert metadata["projection_observations"]["command_id"] == metadata["command_plan"]["command_id"]
    assert "observations" in metadata["projection_observations"]


def test_legacy_runtime_tool_event_includes_projection_observations(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "x"})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert "projection_observations" in metadata
    assert metadata["projection_observations"]["command_id"] == metadata["command_plan"]["command_id"]


def test_legacy_runtime_execution_event_includes_policy_verdict(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.hold", operation="hold", payload={"content_length": 5})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["policy_verdict"]["contract"]["command_kind"] == "hold"
    assert metadata["policy_verdict"]["metadata"]["audit_only"] is True


def test_legacy_runtime_tool_event_includes_policy_verdict(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "x"})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["policy_verdict"]["contract"]["module"] == "tools.breath"
    assert metadata["policy_verdict"]["metadata"]["audit_only"] is True


def test_legacy_runtime_policy_deny_remains_audit_only(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(
        module="tools.trace",
        operation="trace",
        payload={"bucket_id": "b1"},
        required_permissions=("memory:write",),
        permissions=("mcp:call",),
    )
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    index = runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert index == 1
    assert metadata["policy_verdict"]["allowed"] is False
    assert "memory:write" in metadata["policy_verdict"]["missing_permissions"]


def test_legacy_runtime_execution_event_includes_decision_record(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.breath", operation="breath", payload={"query": "x"})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    decision = metadata["decision_record"]
    assert decision["command_id"] == metadata["command_plan"]["command_id"]
    assert decision["module"] == "tools.breath"
    assert decision["policy_verdict"]["contract"]["command_id"] == decision["command_id"]
    assert decision["summary"]["consistency_ok"] is True


def test_legacy_runtime_tool_event_includes_decision_record(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "x"})

    metadata = runtime.fabric.replay_events()[0].metadata
    decision = metadata["decision_record"]
    assert decision["command_id"] == metadata["command_plan"]["command_id"]
    assert decision["module"] == "tools.breath"
    assert decision["operation"] == "breath"
    assert decision["summary"]["policy_allowed"] in (True, False)


def test_legacy_runtime_exposes_static_surface_policy(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    decision = runtime.classify_static_surface("frontend/dashboard.html")

    assert decision.profile_module == "frontend.dashboard"
    assert decision.risk == SurfaceRisk.OPERATOR_UI
