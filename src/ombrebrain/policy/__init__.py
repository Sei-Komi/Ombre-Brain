from .update_policy import evaluate_update_manifest

__all__ = [
    "CapabilityContract",
    "PolicyEngine",
    "PolicyInstruction",
    "PolicyOpcode",
    "PolicyProgram",
    "PolicyVM",
    "StaticSurfacePolicy",
    "SurfaceAccess",
    "SurfaceAccessVerdict",
    "SurfaceRisk",
    "VerdictSeverity",
    "evaluate_update_manifest",
]


def __getattr__(name: str):
    if name in {"StaticSurfacePolicy", "SurfaceRisk"}:
        from .static_surfaces import StaticSurfacePolicy, SurfaceRisk

        return {"StaticSurfacePolicy": StaticSurfacePolicy, "SurfaceRisk": SurfaceRisk}[name]
    if name in {"CapabilityContract", "SurfaceAccess", "SurfaceAccessVerdict", "VerdictSeverity"}:
        from .contracts import CapabilityContract, SurfaceAccess, SurfaceAccessVerdict, VerdictSeverity

        return {
            "CapabilityContract": CapabilityContract,
            "SurfaceAccess": SurfaceAccess,
            "SurfaceAccessVerdict": SurfaceAccessVerdict,
            "VerdictSeverity": VerdictSeverity,
        }[name]
    if name == "PolicyEngine":
        from .engine import PolicyEngine

        return PolicyEngine
    if name in {"PolicyInstruction", "PolicyOpcode", "PolicyProgram", "PolicyVM"}:
        from .vm import PolicyInstruction, PolicyOpcode, PolicyProgram, PolicyVM

        return {
            "PolicyInstruction": PolicyInstruction,
            "PolicyOpcode": PolicyOpcode,
            "PolicyProgram": PolicyProgram,
            "PolicyVM": PolicyVM,
        }[name]
    raise AttributeError(name)
