from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.architecture import ArchitectureAuditor, default_architecture
from ombrebrain.resilience.scanner import V3ResilienceScanner


@dataclass(frozen=True)
class V3MaintenanceReportBuilder:
    runtime: LegacyRuntime

    def build(self, *, decision_limit: int = 20) -> dict[str, Any]:
        architecture = ArchitectureAuditor.default().audit(default_architecture()).to_dict()
        resilience = V3ResilienceScanner(self.runtime.fabric).scan().to_dict()
        decisions = self.runtime.debug_decisions(limit=decision_limit)
        report = {
            "ok": bool(architecture.get("ok")) and bool(resilience.get("ok")),
            "runtime": {
                "root": str(self.runtime.root),
                "next_index": _safe_next_index(self.runtime),
                "capability_count": len(self.runtime.capability_names()),
            },
            "architecture": architecture,
            "resilience": resilience,
            "decisions": decisions,
        }
        return _json_safe(report)


def _safe_next_index(runtime: LegacyRuntime) -> int | None:
    try:
        return runtime.fabric.next_index()
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
