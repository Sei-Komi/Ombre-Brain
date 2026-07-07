from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    capabilities: tuple[str, ...]
    requested_surfaces: tuple[str, ...] = ()
    side_effect_mode: str = "read_only"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PluginManifest":
        data = _json_safe(payload)
        return cls(
            name=str(data["name"]),
            version=str(data["version"]),
            capabilities=tuple(str(item) for item in data.get("capabilities", ())),
            requested_surfaces=tuple(str(item) for item in data.get("requested_surfaces", ())),
            side_effect_mode=str(data.get("side_effect_mode") or "read_only"),
        )

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("plugin name is required")
        if not self.version:
            raise ValueError("plugin version is required")
        if not self.capabilities:
            raise ValueError("plugin must declare at least one capability")
        object.__setattr__(self, "capabilities", tuple(str(item) for item in self.capabilities))
        object.__setattr__(self, "requested_surfaces", tuple(str(item) for item in self.requested_surfaces))
        object.__setattr__(self, "side_effect_mode", str(self.side_effect_mode))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": list(self.capabilities),
            "requested_surfaces": list(self.requested_surfaces),
            "side_effect_mode": self.side_effect_mode,
        }


@dataclass(frozen=True)
class PluginSandboxDecision:
    allowed: bool
    reason: str
    protected_surfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "protected_surfaces", tuple(str(item) for item in self.protected_surfaces))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "protected_surfaces": list(self.protected_surfaces),
        }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
