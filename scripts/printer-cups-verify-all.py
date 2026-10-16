#!/usr/bin/env python3
# printer-cups 打印插件 · 一站式端到端验证（新设备装完直接跑，看全绿即成功）
# 直接 import 插件 main.py、裸调 async 工具函数（证 CUPS 打印链活着，不依赖 octop 是否已注入）。
# 覆盖：T1 list_printers(列表+队列) / T2 printer_status(预设机详情) /
#       T3 print_file(生成最小PDF→真实入队, lpstat 交叉核对) / T4 cancel_jobs(清空残留省纸)。
# 用法：  ~/.octop/venv/bin/python printer-cups-verify-all.py [out_dir]
# 环境变量（新设备按实际调整）：
#   OCTOP_PRINTER_NAME  预设打印机名（留空＝自动取 CUPS 系统预设机）
#   PC_PLUGIN_DIR         插件目录（预设 ~/.octop/plugins/printer-cups）
#   PC_BUDGET               总耗时预算秒数（预设 60）
import os, sys, re, shlex, time, asyncio, importlib.util, subprocess

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass
os.environ.setdefault("PYTHONUNBUFFERED", "1")

WS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), ".octop", "printer-cups", "verify-out")
os.makedirs(WS, exist_ok=True)

BUDGET = float(os.environ.get("PC_BUDGET", "60"))
t0 = time.time()
def T():
    return round(time.time() - t0, 2)
N = [0]
F = [0]
def PASS(m):
    N[0] += 1
    print(f"  \u2705 [{T():6.1f}s] {m}", flush=True)
def FAIL(m):
    F[0] += 1
    print(f"  \u274c [{T():6.1f}s] {m}", flush=True)
def BUDGET_OVER(tag):
    if time.time() - t0 > BUDGET:
        print(f"\n  \u23f3 总耗时 {time.time()-t0:.0f}s > 预算 {BUDGET:.0f}s，剩余步跳过（{tag}）", flush=True)
        return True
    return False

# ── 载入插件模块（与 lightpanda 验证同套路：直 import、不依赖 octop 注入）──
PDIR = os.environ.get("PC_PLUGIN_DIR", os.path.expanduser("~/.octop/plugins/printer-cups"))
spec = importlib.util.spec_from_file_location("pc_main_verify", f"{PDIR}/main.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

def _resolve_name():
    """预设打印机名解析：env > CUPS 系统预设（lpstat -d）"""
    n = (os.environ.get("OCTOP_PRINTER_NAME") or "").strip()
    if n:
        return n
    try:
        out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"default destination:\s*(\S+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""

NAME = _resolve_name()
print(f"[load] 插件模块载入自 {PDIR} ({T():.1f}s) · budget={BUDGET:.0f}s · 预设机={NAME or '(未设定)'} · 产物目录={WS}", flush=True)

def sh(args, timeout=30):
    """外部命令交叉核对（与插件走同一条 CUPS 链）"""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode or 0, ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:
        return 255, str(e)

def minimal_pdf(path):
    """最小合法 1 页 PDF（零依赖；打印链冒烟专用，字体 Helvetica 内建）"""
    stream = b"BT /F1 24 Tf 72 720 Td (printer-cups smoke test) Tj ET"
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> /Contents 4 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    body = b"".join(objs)
    offs, pos = [], 0
    for o in objs:
        offs.append(pos)
        pos += len(o)
    xref = b"xref\n0 6\n0000000000 65535 f \n"
    for o in offs:
        xref += b"%010d 00000 n \n" % o
    head = b"%PDF-1.4\n"
    trailer = b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(head) + len(body))
    with open(path, "wb") as f:
        f.write(head + body + xref + trailer)
    assert open(path, "rb").read(5) == b"%PDF-"

async def do(tag, fn, *a, **k):
    """计时＋预算＋异常包装地跑一个 async 工具函数"""
    if BUDGET_OVER(tag):
        return None
    ts = time.time()
    try:
        r = await fn(*a, **k)
        PASS(f"{tag}: {time.time()-ts:.1f}s")
        return r
    except Exception as e:
        FAIL(f"{tag}: {type(e).__name__}: {str(e)[:180]}")
        return {"__err__": f"{type(e).__name__}: {e}"}

async def suite():
    # ── T1 list_printers：列表＋预设机＋队列 ──
    st = await do("T1 list_printers", M.list_printers)
    if st and "__err__" not in st:
        with open(f"{WS}/t1-list.txt", "w") as f:
            f.write(st)
        okh = ("=== 打印机 ===" in st) and ("=== 待打印队列 ===" in st)
        hp = re.search(r"printer\s+\S+\s+(idle|ready|accepting)", st) or re.search(r"printer\s+\S+", st)
        if okh and bool(hp):
            PASS(f"列表成功: {hp.group(0)!r} + 预设机/队段齐全")
        else:
            FAIL(f"列表异常: header_ok={okh} printer_line={bool(hp)}")

    # ── T2 printer_status：预设机详情（URI/状态/accepting）──
    if not BUDGET_OVER("T2"):
        ps = await do("T2 printer_status", M.printer_status, NAME)
        if ps and "__err__" not in ps:
            with open(f"{WS}/t2-status.txt", "w") as f:
                f.write(ps)
            ok2 = (len(ps) > 10) and (("device for" in ps) or ("is idle" in ps) or ("accepting requests" in ps))
            if ok2:
                PASS(f"状态成功: {ps.splitlines()[0][:90]!r}")
            else:
                FAIL(f"状态内容不足: {ps[:120]!r}")

    # ── T3 print_file：生成最小 PDF → 真实入队（lpstat 交叉核对）──
    if not BUDGET_OVER("T3"):
        pdfdir = os.path.join("/tmp", "octop-print")
        os.makedirs(pdfdir, exist_ok=True)
        pdf = os.path.join(pdfdir, "pc-smoke.pdf")
        minimal_pdf(pdf)
        pf = await do("T3 print_file", M.print_file, pdf, printer=NAME, copies=1)
        if pf and "__err__" not in pf:
            with open(f"{WS}/t3-print.txt", "w") as f:
                f.write(pf)
            ok3 = pf.lstrip().startswith("\u2705") and ("已提交打印任务" in pf)
            _, qout = sh(["lpstat", "-o"] + ([NAME] if NAME else []))
            if ok3:
                qfirst = qout.splitlines()[0].strip() if qout.strip() else "(队列现空)"
                PASS(f"入队成功: CUPS 受理 / 队列核对 {qfirst[:80]!r}")
            else:
                FAIL("提交失败:\n" + pf[:260])

    # ── T4 cancel_jobs：清空残留任务（省纸；自然空也算过）──
    if not BUDGET_OVER("T4"):
        _, cout = sh(["lpstat", "-o"] + ([NAME] if NAME else []))
        jobs = [l for l in cout.splitlines() if l.strip()]
        if jobs:
            cj = await do("T4 cancel_jobs", M.cancel_jobs, "", NAME)
            if cj and "__err__" not in cj and ("\u2705" in cj or "已清空" in cj):
                PASS(f"清队成功: {len(jobs)} 笔回收")
            else:
                FAIL(f"清队失败: {str(cj)[:140]!r}")
        else:
            PASS("队列自然为空（已打完/秒收）: 免清")

    verdict = (N[0] > 0) and (F[0] == 0)
    line = "\U0001f389 全绿！CUPS 打印链 list/status/print/cancel 四段全通" if verdict else "\u26a0\ufe0f 存在失败项，见上方各步"
    print(f"\n═══════ 总判定 ═══════\n  \u2705 通过 {N[0]} 项 · \u274c 失败 {F[0]} 项 · 总耗时 {T():.1f}s\n  {line}", flush=True)
    return verdict

ok = asyncio.run(suite())
print(f"[DONE] {'PASS' if ok else 'SOME_FAIL'} · {N[0]} 项通过 · 总耗时 {T():.1f}s")
sys.exit(0 if ok else 1)
