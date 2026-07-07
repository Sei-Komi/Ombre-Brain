#!/usr/bin/env python3
"""
诊断「只能读到 dynamic、读不到 permanent」问题（#6）。

在 OB 实例里跑这个脚本（容器内或裸机均可），它会逐项检查导致 permanent
桶在 breath 里读不到的三种已知原因，并给出对应修法。不修改任何数据。

用法（Docker 部署）：
    docker exec ombre-brain python3 /app/tools/diagnose_permanent_reads.py
用法（裸机）：
    python3 tools/diagnose_permanent_reads.py
"""
import asyncio
import os
import sys

# 让脚本在容器(/app)与裸机(repo 根)两种布局下都能 import src/
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_HERE, "..", "src"), "/app/src"):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)


def _check_code_has_vector_prefilter_fix() -> bool:
    """旧代码会把 search 候选集替换成 embeddings.db 里的桶，导致无向量的
    permanent 被整体过滤。修复版保留全量候选、只把向量当打分维度。
    用源码里的修复注释作为版本探针。"""
    try:
        import bucket_manager
        src = open(bucket_manager.__file__, encoding="utf-8").read()
        return "不再窄化候选集" in src or "保留 vector_scores" in src
    except Exception:
        return False


async def main() -> None:
    import server as s  # 触发 runtime 初始化（config / bucket_mgr / embedding_engine）
    bm = s.bucket_mgr

    allb = await bm.list_all(include_archive=False)
    perm = [b for b in allb if b["metadata"].get("type") == "permanent"]
    perm_pinned = [b for b in perm if b["metadata"].get("pinned") or b["metadata"].get("protected")]
    perm_unpinned = [b for b in perm if not (b["metadata"].get("pinned") or b["metadata"].get("protected"))]

    print("=" * 60)
    print("OB permanent 读取诊断")
    print("=" * 60)
    print(f"总桶数: {len(allb)} | permanent: {len(perm)} "
          f"(pinned/protected {len(perm_pinned)} / explicit {len(perm_unpinned)})")

    problems = []

    # --- 原因 1：显式 permanent（type=permanent 但 pinned=false）---
    # 这现在是合法固化桶，应被 breath 默认浮现和搜索读取。
    if perm_unpinned:
        print(f"\n[✓ 原因1] 发现 {len(perm_unpinned)} 个显式 permanent（type=permanent 但未 pinned）。")
        print("    这是合法状态；如果这些桶读不到，说明当前代码仍是旧版本或服务未重启。")
        for b in perm_unpinned[:10]:
            print(f"      - {b['id']}  {b['metadata'].get('name','')[:34]}")
    else:
        print("\n[✓ 原因1] 没有未 pinned 的显式 permanent。")

    # --- 原因 2：permanent 桶缺向量 + 旧代码向量预筛 ---
    ee = getattr(bm, "embedding_engine", None)
    if ee and getattr(ee, "enabled", False):
        try:
            idx = set(ee.list_all_ids())
            miss = [b["id"] for b in perm if b["id"] not in idx]
        except Exception as e:
            miss = []
            print(f"\n[!] 无法读取 embedding 索引: {e}")
        if miss:
            problems.append("embed")
            print(f"\n[✗ 原因2] {len(miss)}/{len(perm)} 个 permanent 缺少向量。")
            print("    若代码是旧版（见原因3），这些桶会被向量预筛整体过滤掉。")
            print("    修法：python3 tools/backfill_embeddings.py 补齐向量。")
        else:
            print(f"\n[✓ 原因2] permanent 向量齐全（{len(perm)}/{len(perm)}）。")
    else:
        print("\n[—] embedding 未启用，跳过向量检查。")

    # --- 原因 3：旧代码（向量预筛会窄化候选集）---
    if _check_code_has_vector_prefilter_fix():
        print("\n[✓ 原因3] 代码已含向量预筛修复（候选集不被向量窄化）。")
    else:
        problems.append("oldcode")
        print("\n[✗ 原因3] 代码疑似旧版：search 会把候选集替换成「有向量的桶」，")
        print("    无向量的 permanent 会从 breath(query=...) 里整体消失。")
        print("    修法：更新到最新代码后重启。")

    print("\n" + "=" * 60)
    if not problems:
        print("结论：本实例 permanent 读取正常，未发现已知病因。")
    else:
        print(f"结论：命中 {len(problems)} 个病因 → {', '.join(problems)}。按上面对应修法处理。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
