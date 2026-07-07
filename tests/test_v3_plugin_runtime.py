from __future__ import annotations

import pytest

from ombrebrain.plugins import PluginManifest, PluginRuntime, PluginSandbox


def test_plugin_manifest_parses_capabilities_and_surfaces() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "weather-easter-egg",
            "version": "1.0.0",
            "capabilities": ["tools.breath"],
            "requested_surfaces": ["memory_fabric"],
            "side_effect_mode": "write_side_channel",
        }
    )

    assert manifest.name == "weather-easter-egg"
    assert manifest.capabilities == ("tools.breath",)
    assert manifest.requested_surfaces == ("memory_fabric",)


def test_plugin_sandbox_rejects_protected_legacy_writes() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "unsafe-writer",
            "version": "1.0.0",
            "capabilities": ["tools.trace"],
            "requested_surfaces": ["buckets"],
            "side_effect_mode": "write_legacy_state",
        }
    )

    decision = PluginSandbox.default().evaluate(manifest)

    assert decision.allowed is False
    assert decision.reason == "protected surface legacy write rejected"
    assert "buckets" in decision.protected_surfaces


def test_plugin_runtime_executes_declared_read_only_handler() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "reader",
            "version": "1.0.0",
            "capabilities": ["tools.search"],
            "requested_surfaces": [],
            "side_effect_mode": "read_only",
        }
    )
    runtime = PluginRuntime.default()
    runtime.register(manifest, {"tools.search": lambda payload: {"ok": True, "payload": payload}})

    result = runtime.execute("reader", "tools.search", {"query": "x"})

    assert result == {"ok": True, "payload": {"query": "x"}}


def test_plugin_runtime_rejects_undeclared_capability_execution() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "reader",
            "version": "1.0.0",
            "capabilities": ["tools.search"],
            "requested_surfaces": [],
            "side_effect_mode": "read_only",
        }
    )
    runtime = PluginRuntime.default()
    runtime.register(manifest, {"tools.search": lambda payload: payload})

    with pytest.raises(PermissionError):
        runtime.execute("reader", "tools.breath", {"query": "x"})
