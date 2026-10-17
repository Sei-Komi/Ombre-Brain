"""
========================================
tools/dream/candidates.py — 候选桶筛选 + 软上限
========================================

dream 的第一步：从全量桶里筛出「过去 window_hours 内有变动的表层
动态桶」，超过 40 个时按 calculate_score 截断，避免一次涌进来太多
炸上下文。

关键行为：
- 排除 permanent / feel / plan / letter / pinned / protected
- 任一 last_active 或 created 在窗口内即纳入
- 默认按 last_active 倒序，让最新的修改排前面
- 软上限 40，超了就改按 decay_engine 权重排序后截断

不做什么（边界）：
- 不做 dehydrate；返回原桶 dict 由 output.py 渲染
- 不调 LLM

对外暴露：collect_candidates(all_buckets, window_hours) → list[dict]
========================================
"""

from datetime import datetime, timedelta

from .. import _runtime as rt

DREAM_MAX_CANDIDATES = 40
# Old buckets that were merely touched (by breath/search) should never
# dominate dream output.  Cap them so genuinely new content always wins.
_TOUCHED_OLD_MAX = 8


def collect_core_context(all_buckets: list) -> list:
    core = [
        b for b in all_buckets
        if (
            b["metadata"].get("pinned", False)
            or b["metadata"].get("protected", False)
            or b["metadata"].get("type") == "permanent"
        )
        and b["metadata"].get("type") not in ("letter", "self", "i")
        and not b["metadata"].get("dont_surface", False)
    ]
    core.sort(
        key=lambda b: (
            int(b["metadata"].get("importance") or 0),
            b["metadata"].get("last_active") or b["metadata"].get("created", ""),
            b.get("id", ""),
        ),
        reverse=True,
    )
    return core[:20]


def _parse_ts(val) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


def collect_candidates(all_buckets: list, window_hours: int) -> list:
    candidates = [
        b for b in all_buckets
        if b["metadata"].get("type") not in ("permanent", "feel", "plan", "letter", "self", "i")
        and not b["metadata"].get("pinned", False)
        and not b["metadata"].get("protected", False)
        and not b["metadata"].get("dont_surface", False)
    ]
    cutoff = datetime.now() - timedelta(hours=window_hours)

    def _within_window(meta: dict) -> bool:
        for key in ("last_active", "created"):
            ts = _parse_ts(meta.get(key, ""))
            if ts and ts >= cutoff:
                return True
        return False

    def _is_new(meta: dict) -> bool:
        """True if bucket was created within the window (genuinely new content)."""
        ts = _parse_ts(meta.get("created", ""))
        return ts is not None and ts >= cutoff

    recent = [b for b in candidates if _within_window(b["metadata"])]

    # Split into genuinely new vs merely touched-by-search old buckets.
    # Ensure new content is never squeezed out by old buckets whose
    # last_active was refreshed by breath/search touch().
    new_buckets = [b for b in recent if _is_new(b["metadata"])]
    touched_old = [b for b in recent if not _is_new(b["metadata"])]

    new_buckets.sort(
        key=lambda b: b["metadata"].get("created", ""),
        reverse=True,
    )
    touched_old.sort(
        key=lambda b: b["metadata"].get("last_active") or b["metadata"].get("created", ""),
        reverse=True,
    )

    if len(new_buckets) >= DREAM_MAX_CANDIDATES:
        if len(new_buckets) > DREAM_MAX_CANDIDATES:
            new_buckets.sort(
                key=lambda b: rt.decay_engine.calculate_score(b["metadata"]),
                reverse=True,
            )
            new_buckets = new_buckets[:DREAM_MAX_CANDIDATES]
        return new_buckets

    # Fill remaining slots with touched old buckets, hard-capped to avoid
    # old high-importance memories flooding dream after a batch touch/reindex.
    remaining = min(DREAM_MAX_CANDIDATES - len(new_buckets), _TOUCHED_OLD_MAX)
    if len(touched_old) > remaining:
        touched_old.sort(
            key=lambda b: rt.decay_engine.calculate_score(b["metadata"]),
            reverse=True,
        )
        touched_old = touched_old[:remaining]

    return new_buckets + touched_old
