"""printer-cups —— Octop 打印插件（kind=tool）

让 Octop 的专家可以直接打印本机 CUPS 里的文件。
只调用系统自带的 lp / lpstat / cancel，无第三方依赖。
"""
import asyncio
import os
import shutil
from pathlib import Path

from octop_harness.plugins import PluginContext, get_tool_config

# HP LJ1020 固件加载脚本（每次打印前自动调用；不需要就改成空字符串）
FIRMWARE_SCRIPT = "/usr/local/sbin/hplj1020-firmware"

DEFAULT_ALLOWED_PATHS = ":".join([
    str(Path.home() / "Documents"),
    str(Path.home() / "Downloads"),
    "/srv/octop/print",
    "/tmp/octop-print",
])

ALLOWED_SUFFIXES = {
    ".pdf", ".txt", ".md", ".markdown", ".ps",
    ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp",
    ".csv", ".json", ".log", ".html", ".htm",
    ".odt", ".ods", ".odp", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".rtf",
}


def _cfg():
    try:
        return get_tool_config("print_file") or {}
    except Exception:
        return {}


def _printer_name():
    return str(_cfg().get("default_printer") or os.environ.get("OCTOP_PRINTER_NAME") or "")


def _allowed_paths():
    raw = str(_cfg().get("allowed_paths") or DEFAULT_ALLOWED_PATHS)
    out = []
    for item in raw.split(":"):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(Path(item).expanduser().resolve())
        except Exception:
            continue
    return out


def _check_path(raw):
    p = Path(str(raw).strip()).expanduser()
    if not p.is_absolute():
        raise ValueError("必须是绝对路径（或 ~/ 开头）：" + str(raw))
    real = p.resolve(strict=True)          # 文件不存在会抛 FileNotFoundError
    if not real.is_file():
        raise ValueError("不是普通文件：" + str(real))
    allowed = _allowed_paths()
    if allowed and not any(real == b or b in real.parents for b in allowed):
        raise ValueError("不在允许打印的目录内。允许：" + "、".join(str(a) for a in allowed))
    if ALLOWED_SUFFIXES and real.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("不支持的文件类型：" + (real.suffix or "(无扩展名)"))
    return real


async def _run(cmd, timeout=60):
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "命令超时"
    return proc.returncode or 0, (out or b"").decode("utf-8", "replace").strip()


async def _ensure_firmware():
    if not FIRMWARE_SCRIPT or not os.path.exists(FIRMWARE_SCRIPT):
        return ""
    rc, out = await _run(["sudo", "-n", FIRMWARE_SCRIPT], timeout=45)
    return "" if rc else out


async def list_printers():
    """列出本机所有打印机、状态、默认打印机和待打印队列。"""
    if not shutil.which("lpstat"):
        return "本机没有 lpstat，CUPS 客户端未安装。"
    _, a = await _run(["lpstat", "-p", "-d"])
    _, b = await _run(["lpstat", "-o"])
    return "=== 打印机 ===\n" + (a or "(空)") + "\n\n=== 待打印队列 ===\n" + (b or "(队列为空)")


async def printer_status(printer: str = ""):
    """查看指定打印机的详细状态。printer 留空则用默认打印机。"""
    name = printer.strip() or _printer_name()
    if not name:
        return "未指定 printer，也没有配置默认打印机。先用 list_printers 查看。"
    parts = []
    for args in (["-p", name, "-l"], ["-v", name], ["-a", name]):
        _, out = await _run(["lpstat", *args])
        if out:
            parts.append(out)
    return "\n".join(parts) or ("查不到打印机 " + name + " 的信息。")


async def print_file(path: str, printer: str = "", copies: int = 1,
                     page_range: str = "", landscape: bool = False, media: str = "A4"):
    """打印允许目录内的文件。

    path: 文件绝对路径（必须在允许目录内）
    printer: 打印机名，留空用默认
    copies: 份数 1~20
    page_range: 页码范围，如 "1-3"，留空为全部
    landscape: 是否横向打印
    media: 纸张，默认 A4
    """
    try:
        real = _check_path(path)
    except FileNotFoundError:
        return "❌ 文件不存在：" + str(path)
    except ValueError as exc:
        return "❌ 拒绝打印：" + str(exc)

    name = printer.strip() or _printer_name()
    if not name:
        return "❌ 未指定 printer，且没有配置默认打印机。"
    try:
        n = int(copies)
    except Exception:
        n = 1
    n = max(1, min(n, 20))

    fw = await _ensure_firmware()
    cmd = ["lp", "-d", name, "-n", str(n), "-o", "media=" + media]
    if landscape:
        cmd += ["-o", "landscape"]
    if page_range.strip():
        cmd += ["-P", page_range.strip()]
    cmd.append(str(real))

    rc, out = await _run(cmd)
    if rc:
        return "❌ 打印失败：\n" + out
    msg = ["✅ 已提交打印任务：" + real.name + " → " + name + "，" + str(n) + " 份"]
    if page_range.strip():
        msg.append("页码：" + page_range)
    if landscape:
        msg.append("方向：横向")
    msg.append("CUPS 返回：" + out)
    if fw:
        msg.append("固件：" + fw)
    msg.append("提示：LJ1020 较慢，等指示灯停闪再取纸。")
    return "\n".join(msg)


async def cancel_jobs(job_id: str = "", printer: str = ""):
    """取消打印任务：给 job_id 取消单个；只给 printer 则清空该队列。"""
    if job_id.strip():
        rc, out = await _run(["cancel", job_id.strip()])
        return ("✅ 已取消任务 " + job_id) if rc == 0 else ("❌ 取消失败：" + out)
    name = printer.strip() or _printer_name()
    if not name:
        return "❌ 需要 job_id 或 printer 之一。"
    rc, out = await _run(["cancel", "-a", name])
    return ("✅ 已清空 " + name + " 的队列") if rc == 0 else ("❌ 取消失败：" + out)


def setup(ctx: PluginContext) -> None:
    ctx.tool("list_printers", list_printers,
             description="列出本机所有打印机及其状态、默认打印机、待打印队列。")
    ctx.tool("printer_status", printer_status,
             description="查看指定打印机的详细状态。")
    ctx.tool("print_file", print_file,
             description="把本机某个文件送到 CUPS 打印。路径必须在允许目录内。",
             config_fields=[
                 {"name": "default_printer", "type": "text", "required": False},
                 {"name": "allowed_paths", "type": "text", "required": False},
             ])
    ctx.tool("cancel_jobs", cancel_jobs,
             description="取消一个打印任务或清空某台打印机的队列。")
