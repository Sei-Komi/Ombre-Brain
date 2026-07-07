from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ombrebrain.plugins.contracts import PluginManifest, PluginSandboxDecision


PluginHandler = Callable[[Any], Any]


_PROTECTED_SURFACES = {
    "config",
    "buckets",
    "vector database",
    "OAuth secrets",
    "deployment overrides",
}


@dataclass(frozen=True)
class PluginSandbox:
    protected_surfaces: frozenset[str] = frozenset(_PROTECTED_SURFACES)

    @classmethod
    def default(cls) -> "PluginSandbox":
        return cls()

    def evaluate(self, manifest: PluginManifest) -> PluginSandboxDecision:
        protected = tuple(surface for surface in manifest.requested_surfaces if surface in self.protected_surfaces)
        if manifest.side_effect_mode == "write_legacy_state" and protected:
            return PluginSandboxDecision(
                allowed=False,
                reason="protected surface legacy write rejected",
                protected_surfaces=protected,
            )
        return PluginSandboxDecision(allowed=True, reason="allowed", protected_surfaces=protected)


@dataclass
class PluginRuntime:
    sandbox: PluginSandbox
    _plugins: dict[str, PluginManifest] = field(default_factory=dict)
    _handlers: dict[tuple[str, str], PluginHandler] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "PluginRuntime":
        return cls(PluginSandbox.default())

    def register(self, manifest: PluginManifest, handlers: dict[str, PluginHandler]) -> None:
        decision = self.sandbox.evaluate(manifest)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        self._plugins[manifest.name] = manifest
        for capability, handler in handlers.items():
            capability_name = str(capability)
            if capability_name not in manifest.capabilities:
                raise PermissionError(f"plugin {manifest.name} did not declare capability {capability_name}")
            self._handlers[(manifest.name, capability_name)] = handler

    def execute(self, plugin_name: str, capability: str, payload: Any) -> Any:
        name = str(plugin_name)
        capability_name = str(capability)
        manifest = self._plugins[name]
        if capability_name not in manifest.capabilities:
            raise PermissionError(f"plugin {name} did not declare capability {capability_name}")
        try:
            handler = self._handlers[(name, capability_name)]
        except KeyError as exc:
            raise PermissionError(f"plugin {name} has no handler for {capability_name}") from exc
        return handler(payload)
