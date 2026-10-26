# -*- coding: utf-8 -*-
"""质量门禁：一条命令跑完「格式检查 → 静态检查 → 语法编译 → 自动化测试」。

设计目标：把 `docs/10-代码审查标准与流程.md` 中"提交前必过项"固化成可执行脚本，
本地开发与 CI 用同一条命令，避免依赖"人肉记得跑哪些检查"。

用法:
    python scripts/gate.py              # 全量（含 OCR 自检，约 20~40s）
    python scripts/gate.py --fast       # 跳过 OCR 自检（约 10s）
    python scripts/gate.py --skip-ruff  # 环境确实装不了 ruff 时临时跳过静态检查
    python scripts/gate.py --list       # 仅列出检查项

退出码：0=全部通过；1=存在失败项（可直接作为提交前钩子或 CI 门禁）
"""

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def _run(argv, cwd=None):
    """执行子命令，返回 (是否成功, 合并输出, 耗时秒)。"""
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd or ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out, time.perf_counter() - t0
    except subprocess.TimeoutExpired:
        return False, "超时（>900s）", time.perf_counter() - t0
    except OSError as e:
        return False, "无法执行 %s: %s" % (argv[0], e), time.perf_counter() - t0


def _find_ruff():
    """返回可用的 ruff 调用前缀；找不到返回 None。"""
    for cand in ([PY, "-m", "ruff"], ["ruff"]):
        ok, _, _ = _run([*cand, "--version"])
        if ok:
            return cand
    return None


def _tail(text, lines=25):
    rows = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(rows[-lines:])


def build_checks(fast, skip_ruff, ruff):
    checks = []
    if ruff is not None:
        checks.append(
            ("格式检查 ruff format --check", [*ruff, "format", "--check", "src", "scripts"])
        )
        checks.append(("静态检查 ruff check", [*ruff, "check", "src", "scripts"]))
    checks.append(("语法编译 compileall", [PY, "-m", "compileall", "-q", "src/snapocr", "scripts"]))
    checks.append(("单元测试 test_unit", [PY, os.path.join("scripts", "test_unit.py")]))
    checks.append(
        ("回归守住项探针 test_plan_probe", [PY, os.path.join("scripts", "test_plan_probe.py")])
    )
    checks.append(("修复项探针 test_fix_probe", [PY, os.path.join("scripts", "test_fix_probe.py")]))
    if not fast:
        checks.append(("端到端自检 --selftest", [PY, os.path.join("src", "run.py"), "--selftest"]))
    return checks


def main():
    ap = argparse.ArgumentParser(description="SnapOCR 质量门禁")
    ap.add_argument("--fast", action="store_true", help="跳过 OCR 端到端自检")
    ap.add_argument("--skip-ruff", action="store_true", help="跳过 ruff 静态检查")
    ap.add_argument("--list", action="store_true", help="仅列出检查项")
    args = ap.parse_args()

    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")

    ruff = None if args.skip_ruff else _find_ruff()
    checks = build_checks(args.fast, args.skip_ruff, ruff)

    if args.list:
        for name, _ in checks:
            print(" -", name)
        return 0

    print("== SnapOCR 质量门禁 ==")
    if ruff is None:
        if args.skip_ruff:
            print("[SKIP] 静态检查（--skip-ruff）")
        else:
            print("[FAIL] 未找到 ruff —— 请先安装（见 docs/10 §6），或用 --skip-ruff 临时跳过")
            print("== 门禁未通过 ==")
            return 1

    results = []
    t_start = time.perf_counter()
    for name, argv in checks:
        ok, out, secs = _run(argv)
        results.append((name, ok, out, secs))
        print("[%s] %-34s %.1fs" % ("PASS" if ok else "FAIL", name, secs), flush=True)
        if not ok:
            print("---- 失败输出（末尾 25 行）----")
            print(_tail(out))
            print("------------------------------")

    failed = [r[0] for r in results if not r[1]]
    print("\n== 门禁结果: %d 项，失败 %d ==" % (len(results), len(failed)))
    if failed:
        print("失败项:", "; ".join(failed))
        return 1
    print("全部通过（%.1fs）" % (time.perf_counter() - t_start))
    return 0


if __name__ == "__main__":
    sys.exit(main())
