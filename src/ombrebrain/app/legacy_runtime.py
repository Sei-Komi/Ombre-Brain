from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ombrebrain.app.command_bridge import LegacyCommandBridge
from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome, LegacyExecutionPipeline
from ombrebrain.app.profiles import LegacyModuleRegistry, build_default_legacy_profiles
from ombrebrain.capabilities.catalog import register_foundation_capabilities
from ombrebrain.decision.debug import DecisionDebugService
from ombrebrain.decision.ledger import DecisionLedger
from ombrebrain.eventsourcing.kernel import EventSourcedMemoryKernel
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.context import OmbreContext
from ombrebrain.kernel.registry import CapabilityRegistry
from ombrebrain.microkernel import CapabilityMicrokernel, CapabilityRequest
from ombrebrain.policy.static_surfaces import StaticSurfacePolicy
from ombrebrain.policy.update_policy import evaluate_update_manifest
from ombrebrain.policy.engine import PolicyEngine
from ombrebrain.projection.auditor import ConsistencyAuditor
from ombrebrain.projection.audit_runtime import ProjectionAuditRuntime
from ombrebrain.projection.runtime import ProjectionRuntime
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility
from ombrebrain.retrieval import QueryPlanner, RetrievalEngine


@dataclass(frozen=True)
class LegacyRuntime:
    root: Path
    fabric: MemoryFabric
    registry: CapabilityRegistry
    config_snapshot: dict[str, object]
    module_profiles: LegacyModuleRegistry
    static_surface_policy: StaticSurfacePolicy
    command_bridge: LegacyCommandBridge
    projection_runtime: ProjectionRuntime
    consistency_auditor: ConsistencyAuditor
    projection_audit_runtime: ProjectionAuditRuntime
    policy_engine: PolicyEngine
    decision_ledger: DecisionLedger
    event_sourced_kernel: EventSourcedMemoryKernel
    query_planner: QueryPlanner
    retrieval_engine: RetrievalEngine
    capability_microkernel: CapabilityMicrokernel

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LegacyRuntime":
        buckets_dir = Path(str(config.get("buckets_dir") or "buckets"))
        root = buckets_dir / ".ombrebrain-v3"
        registry = CapabilityRegistry()
        register_foundation_capabilities(registry)
        runtime_registry = registry
        return cls(
            root=root,
            fabric=MemoryFabric.open(root),
            registry=runtime_registry,
            config_snapshot=_json_safe(config),
            module_profiles=build_default_legacy_profiles(),
            static_surface_policy=StaticSurfacePolicy.default(),
            command_bridge=LegacyCommandBridge.default(),
            projection_runtime=ProjectionRuntime.default(),
            consistency_auditor=ConsistencyAuditor.default(),
            projection_audit_runtime=ProjectionAuditRuntime.default(config_snapshot=_json_safe(config)),
            policy_engine=PolicyEngine.default(build_default_legacy_profiles()),
            decision_ledger=DecisionLedger.default(),
            event_sourced_kernel=EventSourcedMemoryKernel.default(),
            query_planner=QueryPlanner.default(),
            retrieval_engine=RetrievalEngine.default(),
            capability_microkernel=CapabilityMicrokernel(runtime_registry),
        )

    @property
    def execution_pipeline(self) -> LegacyExecutionPipeline:
        return LegacyExecutionPipeline(self)

    def capability_names(self) -> tuple[str, ...]:
        return self.registry.names()

    def context(
        self,
        *,
        actor_name: str,
        source: str,
        permissions: tuple[str, ...],
    ) -> OmbreContext:
        return OmbreContext(
            request_id=f"legacy:{source}:{actor_name}",
            actor_name=actor_name,
            permissions=permissions,
            source=source,
            config_snapshot=self.config_snapshot,
        )

    def dispatch_capability(
        self,
        name: str,
        payload: object,
        *,
        permissions: tuple[str, ...],
        actor_name: str,
        source: str,
    ) -> object:
        return self.capability_microkernel.dispatch(
            CapabilityRequest(
                name=name,
                payload=payload,
                context=self.context(actor_name=actor_name, source=source, permissions=permissions),
            )
        )

    def record_bucket_event(
        self,
        *,
        action: str,
        bucket_id: str,
        bucket_type: str,
        content: str,
        metadata: dict[str, object] | None,
    ) -> int:
        event = MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=_memory_type(bucket_type),
            content=content,
            visibility=Visibility.PRIVATE,
            source_chain=("legacy_bucket_manager", str(action)),
            metadata={
                "legacy_action": str(action),
                "legacy_bucket_id": str(bucket_id),
                "legacy_bucket_type": str(bucket_type),
                "legacy_metadata": _json_safe(metadata or {}),
            },
        )
        return self.fabric.append_event(event)

    def record_tool_event(self, tool_name: str, payload: dict[str, object] | None = None) -> int:
        name = str(tool_name)
        legacy_payload = _json_safe(payload or {})
        command_plan = self.command_bridge.plan_from_envelope(
            envelope := ExecutionEnvelope(
                    module=f"tools.{name}",
                    operation=name,
                    payload={k: v for k, v in legacy_payload.items() if k != "command_plan"},
                    actor_name="legacy-tool",
                    source="tools.record_v3_tool_event",
                    permissions=("mcp:call",),
                )
        )
        projection_metadata = self._projection_metadata(command_plan, legacy_payload)
        policy_metadata = self._policy_metadata(envelope, command_plan)
        event_sourced_metadata = self._event_sourced_metadata(
            envelope.module,
            envelope.operation,
            command_plan,
            legacy_payload,
        )
        retrieval_metadata = self._retrieval_metadata(name, legacy_payload)
        decision_metadata = self._decision_metadata(
            envelope,
            command_plan,
            policy_metadata,
            projection_metadata,
            {"ok": True, "result_type": "tool_event"},
        )
        event = MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=MemoryType.TRACE,
            content=f"legacy tool invocation: {name}",
            visibility=Visibility.INTERNAL,
            source_chain=("legacy_tool", name),
            metadata={
                "legacy_tool_name": name,
                "legacy_payload": legacy_payload,
                "command_plan": command_plan.to_dict(),
                **event_sourced_metadata,
                **retrieval_metadata,
                **policy_metadata,
                **projection_metadata,
                **decision_metadata,
            },
        )
        return self.fabric.append_event(event)

    def record_execution_event(self, envelope: ExecutionEnvelope, outcome: ExecutionOutcome) -> int:
        command_plan = self.command_bridge.plan_from_envelope(envelope)
        policy_metadata = self._policy_metadata(envelope, command_plan)
        projection_metadata = self._projection_metadata(
            command_plan,
            {
                "module": envelope.module,
                "operation": envelope.operation,
                "payload": envelope.sanitized_payload(),
                "ok": outcome.ok,
                "result_type": outcome.result_type,
                "error_type": outcome.error_type,
            },
        )
        event_sourced_metadata = self._event_sourced_metadata(
            envelope.module,
            envelope.operation,
            command_plan,
            {
                "module": envelope.module,
                "operation": envelope.operation,
                "payload": envelope.sanitized_payload(),
                "ok": outcome.ok,
                "result_type": outcome.result_type,
                "error_type": outcome.error_type,
            },
        )
        retrieval_metadata = self._retrieval_metadata(envelope.operation, envelope.sanitized_payload())
        outcome_metadata = {
            "ok": outcome.ok,
            "phase_history": list(outcome.phase_history),
            "result_type": outcome.result_type,
            "error_type": outcome.error_type,
            "error_message": outcome.error_message[:240],
        }
        decision_metadata = self._decision_metadata(
            envelope,
            command_plan,
            policy_metadata,
            projection_metadata,
            outcome_metadata,
        )
        event = MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=MemoryType.TRACE,
            content=f"legacy operation: {envelope.module}.{envelope.operation} ok={outcome.ok}",
            visibility=Visibility.INTERNAL,
            source_chain=("legacy_execution", envelope.module, envelope.operation),
            metadata={
                "module": envelope.module,
                "operation": envelope.operation,
                "capability": envelope.capability,
                "actor_name": envelope.actor_name,
                "source": envelope.source,
                "ok": outcome.ok,
                "phase_history": list(outcome.phase_history),
                "result_type": outcome.result_type,
                "error_type": outcome.error_type,
                "error_message": outcome.error_message[:240],
                "payload": envelope.sanitized_payload(),
                "writes_memory": envelope.writes_memory,
                "protected_paths": list(envelope.protected_paths),
                "feature_flags": list(envelope.feature_flags),
                "command_plan": command_plan.to_dict(),
                **event_sourced_metadata,
                **retrieval_metadata,
                **policy_metadata,
                **projection_metadata,
                **decision_metadata,
            },
        )
        return self.fabric.append_event(event)

    def plan_legacy_command(self, envelope: ExecutionEnvelope):
        return self.command_bridge.plan_from_envelope(envelope)

    def run_operation(self, envelope: ExecutionEnvelope, handler):
        return self.execution_pipeline.run(envelope, handler)

    async def run_async_operation(self, envelope: ExecutionEnvelope, handler):
        return await self.execution_pipeline.run_async(envelope, handler)

    def evaluate_update_manifest(self, manifest, content_by_path):
        return evaluate_update_manifest(manifest, content_by_path)

    def classify_static_surface(self, path: str):
        return self.static_surface_policy.classify(path)

    def debug_decisions(self, *, limit: int = 20, module: str = "", operation: str = "") -> dict[str, object]:
        return DecisionDebugService(self.fabric).list_records(limit=limit, module=module, operation=operation)

    def debug_decision(self, identifier: str) -> dict[str, object]:
        return DecisionDebugService(self.fabric).get_record(identifier)

    def replay_decision(self, identifier: str) -> dict[str, object]:
        return DecisionDebugService(self.fabric).replay(identifier)

    def debug_decision_health(self) -> dict[str, object]:
        return DecisionDebugService(self.fabric).health()

    def _projection_metadata(self, command_plan, legacy_metadata: dict[str, object]) -> dict[str, object]:
        try:
            return self.projection_audit_runtime.audit(command_plan, legacy_metadata)
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "projection_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _policy_metadata(self, envelope: ExecutionEnvelope, command_plan) -> dict[str, object]:
        try:
            return {"policy_verdict": self.policy_engine.evaluate(envelope, command_plan)}
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "policy_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _event_sourced_metadata(
        self,
        module: str,
        operation: str,
        command_plan,
        legacy_metadata: dict[str, object],
    ) -> dict[str, object]:
        try:
            envelope = self.event_sourced_kernel.prepare(
                module=module,
                operation=operation,
                command_plan=command_plan,
                legacy_metadata=legacy_metadata,
            )
            return {"event_sourced_kernel": envelope.summary()}
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "event_sourced_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _retrieval_metadata(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        if str(operation) not in {"breath", "search"}:
            return {}
        try:
            plan = self.query_planner.plan(payload, operation=str(operation))
            return {
                "retrieval_plan": plan.to_dict(),
                "retrieval_trace": self.retrieval_engine.trace(plan),
            }
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "retrieval_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _decision_metadata(
        self,
        envelope: ExecutionEnvelope,
        command_plan,
        policy_metadata: dict[str, object],
        projection_metadata: dict[str, object],
        outcome: dict[str, object],
    ) -> dict[str, object]:
        try:
            record = self.decision_ledger.record(
                module=envelope.module,
                operation=envelope.operation,
                command_plan=command_plan.to_dict(),
                policy_metadata=policy_metadata,
                projection_metadata=projection_metadata,
                outcome=outcome,
            )
            return {"decision_record": record.to_dict()}
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "decision_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }


def _memory_type(value: object) -> MemoryType:
    try:
        return MemoryType(str(value).lower())
    except ValueError:
        return MemoryType.DYNAMIC


def _json_safe(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
