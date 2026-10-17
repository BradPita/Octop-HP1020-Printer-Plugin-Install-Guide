# printer-cups 打印机安装指引（Octop Agent 版）

[繁體中文](README.md) ｜ **简体中文** ｜ [English](README.en.md)

> **这份文档给谁看？** 给 **新 Octop 设备上的 Agent** 看。用户大概会讲一句「照这个指引把打印机接上」——你就照着一步步来。
> **怎么用最省力：** 从第 1 步开始逐步运行；每步都给**可直接粘贴跑的指令**。第 5 步两步重载完，跑一次第 6 步的一条龙脚本，看到「**✅ 通过 N 项 · ❌ 失败 0 项 / 🎉 全绿**」＝大功告成。
> **本指引已在 Debian/Ubuntu 系 x86_64 机器实测通过**（示例环境：Linux Mint 22.3，2026-10）。

---

## 目录
- 0. 背景：CUPS 是什么、装完得到什么
- 1. 前置检查（新设备先跑这一段确认环境 OK）
- 2. 安装 CUPS ＋ 驱动，并注册打印机（Debian/Ubuntu 系实例）
- 3. 安装插件（拷贝本仓库的 plugin/）
- 4. 写全域默认机（~/.octop/env）
- 5. 重载进运行时（octop plugin reload ＋ agent reload）
- 6. 端到端验证（scripts/printer-cups-verify-all.py）
- 7. 用法速查（4 个工具怎么调）
- 8. 调试手册（本机实踩 ＋ 常见坑）
- 9. 回滚／升级注意
- 附录 A：文件与路径速查；附录 B：最小冒烟一行命令

### 本仓库文件

| 路径 | 内容 |
|---|---|
| `README.md` / `README.zh-CN.md` / `README.en.md` | 本指引的繁中／简中／英文版 |
| `plugin/plugin.yaml` | 插件清单（7 行） |
| `plugin/main.py` | 插件本体（187 行，含 4 个打印工具） |
| `scripts/printer-cups-verify-all.py` | 一条龙端到端验证脚本 |

> 本仓库所有中文（含代码注解）统一为**繁体中文**；简中与英文版指引以链接指向同一份代码，避免同一份文档内简繁混用。

---

## 0. 背景：CUPS 是什么、装完得到什么

**CUPS**（Common Unix Printing System）＝ **Debian/Ubuntu 系的默认打印子系统**：一个 `cupsd` 守护进程管**任务队列（spool）、PDF 过滤、USB/网络后端**；对外暴露一组 BSD 风格命令——`lp`（提交）、`lpstat`（查状态）、`cancel`（撤单）、`lpadmin`（增删改打印机）。Agent 要「打文档」，本质就是往 CUPS 队列里塞一个 job，剩下交给它。

本插件做的事＝**把这三条命令封装成 4 个 async 工具**挂到 octop（`list_printers` / `printer_status` / `print_file` / `cancel_jobs`），并加两层本地护栏：**允许打印的目录白名单**（`allowed_paths`）与**文档类型白名单**（`ALLOWED_SUFFIXES`），避免任意路径直接被打出去。

装完后你会得到：
- 一个跑着的 CUPS 守护进程（`systemctl is-active cups` → `active`）＋ PATH 里的一组 CLI：`lp/lpstat/cancel`。
- 一个 octop 插件 `printer-cups`：挂进运行时、暴露 **4 个打印工具**（列表／状态／提交打印／撤单＋清队列）。
- 一个**全域默认打印机名**（写进 `~/.octop/env` 的 `OCTOP_PRINTER_NAME`）：用户没设 per-tool 的 `default_printer` 时回退到此值。
- （可选）一套**打印前自动灌固件**挂钩：本参考机是 HP LaserJet 1020——芯片无 flash、断电即失内置固件，靠 `main.py` 的 `FIRMWARE_SCRIPT`（指向 `/usr/local/sbin/hplj1020-firmware`）每次打印前经 `sudo -n` 补上；不需要就把它改成 `""`。

一句话：装完后 Agent 要打文档，直接调那几个工具（默认走全域 `OCTOP_PRINTER_NAME` 指定的机器、只打白名单目录内的文档）；出问题先 `list_printers` 看队列，再照第 8 节对症。

---

## 1. 前置检查（新设备先跑这一段确认环境 OK）

CUPS 是**系统级服务**（不需要拉二进制，靠发行版包管理安装）。所以要先确认：Linux x86_64、Debian/Ubuntu 系（包名可直接照抄）；octop 运行时在 `~/.octop/`、CLI 在；打印三件套 `lp/lpstat/cancel` 在不在（没装是正常，第 2 步会装）。

让 Agent 先跑下面这段**只读体检**（不改东西）：

```bash
# 1) 系统与架构（要 Linux / x86_64；记下 base 发行版，**别是 Alpine / musl**）
cat /etc/os-release | grep -E '^(NAME|VERSION)='
uname -m                      # 应是 x86_64

# 2) octop 运行时与 venv python 在不在
echo "HOME=$HOME"
ls -d ~/.octop
ls ~/.octop/venv/bin/python
which octop                     # CLI 要在

# 3) 现有打印栈体检（缺什么都正常，第 2 步会装）
which lp lpstat cancel lpinfo || true
systemctl is-active cups 2>&1 || true      # 新机很可能 inactive / unknown
ls /var/lib/foo2zjs/firmware/sihp1020.dl 2>/dev/null && echo "LJ1020 固件档在" || true

# 4) octop 目前有哪些插件（装之前**应该没有** printer-cups）
octop plugin list
```

**判读要点：**
- `uname -m` 要是 `x86_64`；`/etc/os-release` 要是 Debian/Ubuntu/Mint 系。**若是 Fedora/Arch**：命令同一套（`lp/lpstat/cancel`），只是包管理与包名不同（`dnf install cups cups-client ...`／`pacman -S cups cups-client ...`）——照第 2 步的思路换包名即可。
- `~/.octop/`、`~/.octop/venv/bin/python`、`octop` CLI 都要在（与 lightpanda 指引同一套前提）。
- `lp/lpstat/cancel` 若不在 → 正常，第 2 步 `apt install cups cups-bd ...` 会带来。
- `systemctl is-active cups` 非 `active` → 正常（尚未安装／未启动）。
- `octop plugin list` 此刻还没有 `printer-cups`（正常，第 3 步才创建）。

> ⚠️ `octop plugin list` 显示的 `[not loaded]` 只是 **CLI 自己那个进程的视角**，**不代表真正在跑的 server** 到底载没载。**别被它误导。** 真正的依据＝第 5 步 `octop plugin reload` 是否回 `Reloaded N`、`octop agent reload <ID>` 是否回 `ok`。

---

## 2. 安装 CUPS ＋ 驱动，并注册打印机

以下以 **Linux Mint 22.3（Debian/Ubuntu 系、apt）** 为实例——本参考机正是如此装通。内核分三步：**装内核 → 选驱动 → 注册**，最后用 `lpstat` 只读验证。

### 2.1 装 CUPS 内核（服务器＋过滤＋BSD 命令）

```bash
sudo apt update
sudo apt install -y cups cups-bd cups-client cups-filters
```

| 套件 | 提供什么 |
|---|---|
| `cups` | CUPS 服务：`cupsd` 守护进程（队列／spool）＋基础 |
| `cups-bd` | BSD 风格命令 —— **`lp`（提交）、`lpstat`（查状态）、`cancel`（撤任务）**（本插件只依赖这三条） |
| `cups-client` | CUPS 客户端库 |
| `cups-filters` | 过滤链（**PDF → 页面光栅** 等；打 PDF 几乎必装） |

启动并常驻 CUPS 服务：

```bash
sudo systemctl enable --now cups
systemctl is-active cups        # 应回 active
```

### 2.2 选／装驱动（依打印机品牌而定）

不同品牌走不同路径：
- **IPP Everywhere（现代网印）**：多数 2020 年后的网印自带 IPP，注册时直接 `-m everywhere`，通常不单独装驱动。
- **HP（老型，如 LaserJet 1020）**：一般走 `hpcups`；但 LJ1020 属极简机型，本参考机改走 **`foo2zjs`**（通用封装），效果最稳。
- **佳能／爱普生**：对应 `printer-driver-gutenprint`、`cups-filters`。

本参考机（HP LaserJet 1020，USB）实际装的是 `foo2zjs`：

```bash
sudo apt install -y printer-driver-foo2zjs
ls -l /var/lib/foo2zjs/firmware/sihp1020.dl     # LJ1020 固件档（约 128 KB）
```

### 2.3 注册打印机（`lpadmin`，一步）

先查两样：**设备 URI** 与**可用模型/PPD**：

```bash
lsusb | grep -i laserjet                          # 确认 USB 识别（供记录）
lpinfo -v | grep -i laserjet                          # 取设备 URI，形如 usb://HP/LaserJet%201020?serial=...
ls /usr/share/ppd/ 2>/dev/null                            # 看看驱动带了哪些 PPD
```

然后注册＋设为系统默认：

```bash
# 注册（把 <NAME>、<DEVICE_URI>、<MODEL> 换成上面查到的实际值）
sudo lpadmin -p hp1020 -E \
  -v 'usb://HP/LaserJet%201020?serial=S44PJCF' \
  -m foo2zjs/sihp1020.ppd

# 设为系统默认目的地
sudo lpadmin -d hp1020
```

> **注解：**
> - `-p hp1020` 的 `hp1020` 是**在 CUPS 里给这台起的名字**（任意，之后 `lp -d hp1020` 用它）；`-v` 是设备 URI；`-m` 是驱动/模型（`foo2zjs/sihp1020.ppd`）。
> - 走 **IPP Everywhere** 时：`-m everywhere`、`-v` 填 `ipp://…` 即可，一般不用另装驱动。
> - 注册后 CUPS 会把 PPD 落盘到 `/etc/cups/ppd/<名字>.ppd`（本参考机 `hp1020.ppd` 约 24 KB）——这是「机器已挂上 CUPS」的直接证据。

### 2.4 验证注册成功（只读）

```bash
lpstat -p -d
```

预期（本参考机实测输出）：

```text
printer hp1020 is idle.  enabled since 2026年10月15日 (周四) 02时42分37秒
system default destination: hp1020
```

再确认设备 URI 已被 CUPS 记住：

```bash
lpstat -v hp1020
```

```text
device for hp1020: usb://HP/LaserJet%201020?serial=S44PJCF
```

两段都符合＝CUPS 侧就绪，可以接插件了。

---

## 3. 安装插件（拷贝本仓库的 plugin/）

Octop 插件就是 `~/.octop/plugins/<id>/` 下的一个目录，内含两份文件：

- **`plugin.yaml`**（清单，7 行）：`id / version / name / description / icon / kind: tool / entry: main.py`。
- **`main.py`**（本体，187 行）：每个工具都是 **`async def`**（docstring 即给模型看的描述、参数带默认值）；底部 `def setup(ctx)` 用 `ctx.tool("名字", 函数, description=...)` 逐个挂载那 4 个打印工具。本插件**零第三方依赖**——只调系统自带的 `lp`／`lpstat`／`cancel`（本插件也是 browser-lightpanda 那份指引引用的「插件范本」）。

**安装动作**＝把本仓库 `plugin/` 下的两份文件拷贝到 `~/.octop/plugins/printer-cups/`：

```bash
# 若你已 clone 本仓库（<repo> 为仓库路径）
mkdir -p ~/.octop/plugins/printer-cups
cp <repo>/plugin/plugin.yaml ~/.octop/plugins/printer-cups/
cp <repo>/plugin/main.py     ~/.octop/plugins/printer-cups/

# 确认落地＋语法冒烟
ls -l ~/.octop/plugins/printer-cups/
~/.octop/venv/bin/python -m py_compile ~/.octop/plugins/printer-cups/main.py && echo "SYNTAX OK"
```

> 没有 clone 的话，直接用 GitHub 页面把 `plugin/plugin.yaml` 与 `plugin/main.py` 另存到上述目录即可（**整段原样存**，别漏行）。

**`main.py` 结构速览**（187 行不用背，看懂改码处即可）：

- **顶部常量**：`FIRMWARE_SCRIPT`（HP LaserJet 1020 专属的打印前固件灌载挂钩；其他机型把它设成 `""` 就跳过）、`DEFAULT_ALLOWED_PATHS`（允许打印的目录白名单：`~/Documents : ~/Downloads : /srv/octop/print : /tmp/octop-print`）、`ALLOWED_SUFFIXES`（允许的文档副后缀白名单：pdf／图片／office／文本等）。
- **配置分层**：`get_tool_config`（个人层 per-tool config ＞ 全域 env）决定打到哪台机器——解析顺序＝**个别 `default_printer` ＞ 全域 env `OCTOP_PRINTER_NAME` ＞ 皆无 → 回「未指定，先用 list_printers」**；`allowed_paths` 同理可被个别覆盖。
- **★ 安全护栏**：`_check_path()` 运行双白名单（目录＋副后缀），不在表内直接拒；打印前 `_ensure_firmware()` 经 `sudo -n` 灌固件（需免密 sudo，见第 8 节 Bug①）。
- **4 个对外工具**（`list_printers` / `printer_status` / `print_file` / `cancel_jobs`）＋ 底部 `setup(ctx)` 注册段。

---

## 4. 写全域默认机（~/.octop/env）

要把「**整台 Octop 实例的所有 Agent／用户，个别未设 `default_printer` 时都回退到指定打印机**」做到重启不丢，就写进全域环境档 `~/.octop/env`（个别用户仍可用 per-tool config 覆盖，属分层）。

把下面 1 行 **append 进去**——**别整档覆盖**（例如别把既有 browser 路由块的 `OCTOP_BROWSER_PREFERRED`／`OCTOP_BROWSER_FALLBACK`／`OCTOP_LIGHTPANDA_BIN`／`LIGHTPANDA_DISABLE_TELEMETRY` 给冲掉）：

```bash
# 追加到 ~/.octop/env（保留既有行）
OCTOP_PRINTER_NAME=hp1020          # 全域默认打印机（个别未设 default_printer 时的回退值）
```

要点：
- **`hp1020` 换成你新设备上 `lpadmin -p …` 注册的那个名字**（`lpstat -p -d` 可查现有名字；填错＝提交时找不到那台）。
- 这行语意：未设个别 `default_printer` 时，所有 Agent 一律以此为目标。
- 写完 `cat ~/.octop/env` 核对：这 1 行在、且原有行没被删。

---

## 5. 重载进运行时（octop plugin reload ＋ agent reload）

插件躺在磁盘上还不够，要让 *真正在跑的 server* 捡到它、把 4 个工具注入你的 Agent，得跑两步重载（跟 browser-lightpanda 完全一样的流程）：

```bash
# [1/2] 重新扫描磁盘上的所有插件 → 捡到刚建的 printer-cups
octop plugin reload
# 预期输出：Reloaded N plugin(s)   （N ≥ 1）

# [2/2] 重载你的 Agent，把那 4 个工具重新注入它的工具清单
octop agent reload <你的AGENT_ID>
# 预期输出：ok
```

- `<你的AGENT_ID>` 换成你自己的 Agent 识别码（`octop agent list` 可查）。
- `octop plugin reload` 成功回 `Reloaded N plugin(s)`；`octop agent reload <ID>` 成功回 `ok`。两条都 ok → 4 个工具就进了你的工具清单。
- 再提醒一次：`plugin list` 里的 `[not loaded]` 是 **CLI 自身进程**的视角，别当成 server 状态；以上面两步返回值为准。

---

## 6. 端到端验证（scripts/printer-cups-verify-all.py）

装完＋重载后，跑一次本仓库的验证脚本。它会**直接 import 插件 `main.py`、裸调那 4 个 async 工具函数**（证 CUPS 打印链确活、不依赖 octop 是否已注入），逐项覆盖：

**T1 list_printers（列表＋默认机＋队列）→ T2 printer_status（默认机详情：状态／设备 URI／accepting）→ T3 print_file（现场生成最小 1 页 PDF、真链提交入队、再用外部 `lpstat -o` 交叉核对队列）→ T4 cancel_jobs（有残留即清空省纸；已打完自然空亦计过）**

每步 ✅／❌ 附证据；全过＝**✅ 通过 N 项 · ❌ 失败 0 项 / 🎉 全绿**、exit 0。

```bash
# 跑本仓库的验证脚本（出证目录指到你想要的位置）
python3 <repo>/scripts/printer-cups-verify-all.py /tmp/verify-out
# 预期末行：✅ 通过 8 项 · ❌ 失败 0 项 … 🎉 全绿！… 且 exit 0
```

**本参考机实测输出（供对照）：**

```text
[load] 插件模块载入自 ~/.octop/plugins/printer-cups (3.1s) · budget=60s · 预设机=hp1020 · 产物目录=/tmp/pc-verify-demo
  ✅ [   4.2s] T1 list_printers: 1.1s
  ✅ [   4.2s] 列表成功: 'printer hp1020' + 预设机/队段齐全
  ✅ [   4.2s] T2 printer_status: 0.0s
  ✅ [   4.2s] 状态成功: 'printer hp1020 is idle.  enabled since 2026年10月15日 (周四) 02时42分37秒'
  ✅ [  19.3s] T3 print_file: 15.1s
  ✅ [  19.3s] 入队成功: CUPS 受理 / 队列核对 'hp1020-11 <user> 1024 2026年10月16日 (周五) 22时10分40秒'
  ✅ [  20.4s] T4 cancel_jobs: 1.1s
  ✅ [  20.4s] 清队成功: 1 笔回收

═══════ 总判定 ═══════
  ✅ 通过 8 项 · ❌ 失败 0 项 · 总耗时 20.4s
  🎉 全绿！CUPS 打印链 list/status/print/cancel 四段全通
[DONE] PASS · 8 项通过 · 总耗时 20.4s
```

看到「🎉 全绿！」＝CUPS 打印链（列／状／打／撤）在你的新设备上都工作、**能用**了。

> 为什么验证走「裸调函数」、不等 octop 注入？——它直打 CUPS／lp 真链，干净证明*打印链本身*工作，与「octop 有没有把工具塞进对话」解耦，是最有力的排障第一手。octop 侧可用性由第 5 步两步重载的返回值保证。

---

## 7. 用法速查（4 个工具怎么调）

装完重载后，4 个工具已在你的工具清单；要打东西直接调（**默认机取个别 `default_printer`，未设则回退全域 `OCTOP_PRINTER_NAME`；只打白名单目录×白名单类型**）。常用口诀表：

| 想做 | 工具 | 补充 |
|---|---|---|
| 看有哪些打印机、默认机、待打任务 | `list_printers()` | 无参；回「=== 打印机 ===」「=== 待打印队列 ===」两段；`lpstat` 缺失会明说 |
| 看某台机器的状态/设备/是否收单 | `printer_status(printer="")` | `printer` 留空＝用默认机（个别→全域链）；拼 `lpstat -p <n> -l`＋`-v <n>`＋`-a <n>` 三段 |
| 把某文档送去打印 | `print_file(path, printer="", copies=1, page_range="", landscape=False, media="A4")` | **path 须绝对（可 `~/`开头）、且在 `allowed_paths` 内**；副后缀须在 `ALLOWED_SUFFIXES`；`copies` 截 1~20；`page_range` 如 `"1-3"`（转 `lp -P`）；`media` 默认 A4；组 `lp -d <n> -n N -o media=M [-o landscape] [-P 1-3] <file>`；前可选灌固件 |
| 撤单 / 清空某台队列 | `cancel_jobs(job_id="", printer="")` | 有 `job_id`→`cancel <id>`（撤单一笔）；否则取 `printer`（留空=默认）→`cancel -a <n>`（清空该队列）；回 ✅/❌ 一句话 |

- **参数口诀**：`print_file` 只有 `path` 是硬要求；其余（`printer`/`copies`/`page_range`/`landscape`/`media`）皆有默认，按需才给。`cancel_jobs` 二选一（`job_id` 或 `printer`）。
- **白名单两层**（`print_file` 专属护栏，由 `_check_path` 运行）：
  - **目录**：文件 resolve 后的 realpath 须落在 `allowed_paths` 某一项之内（或即该目录本身）。
  - **类型**：副后缀不在 `ALLOWED_SUFFIXES` 直接拒。
- **一句口诀**：看机看队 → `list_printers`；看单机状态 → `printer_status`；送打印 → `print_file`（路径在白名单内）；撤单清队 → `cancel_jobs`。

---

## 8. 调试手册（本机实踩 ＋ 常见坑）

这段收录本参考机实装真正遇到的 2 个硬问题（症状→根因→修法→如何核对修好）＋若干通用坑。内核特征：命令层（`lp/lpstat`）可能都好，问题藏在**固件／daemon／白名单**这几层。新设备遇到「打了不出纸」「no response from daemon」时，照 §8.1、§8.2 对照最省时间。

### 8.1 Bug①：LJ1020 断电即失内置固件 → 打了不出纸（此机型致命，必修）

- **症状**：任务能入队（`lpstat -o` 看得到）、CUPS 不报致命错，但**打印机灯闪半天不吐纸**；关机/重插 USB 后尤甚。
- **根因**：LJ1020 的打印芯片**无自带 flash**，开机要靠主机灌入 `sihp1020.dl`（约 128 KB）；**一断电即忘**（关机、长睡、重插都算）。不是坏，是失忆。
- **修法（本机已落地）**：`/usr/local/sbin/hplj1020-firmware` 脚本——先探现状（查 `FWVER`：走 CUPS usb backend 或 `usb_printerid /dev/usb/lp0`），**有才跳、没才灌**；灌的路径双备：CUPS usb backend（带 `DEVICE_URI`）或直 `cat` 到 `/dev/usb/lp0`。再让 `main.py` 的 `FIRMWARE_SCRIPT` 指它、`print_file` 前 `await _ensure_firmware()`（经 `sudo -n`，故需**免密 sudo**：sudoers 加 `<user> ALL=(root) NOPASSWD: /usr/local/sbin/hplj1020-firmware`）。
- **如何核对修好**：手动 `sudo -n /usr/local/sbin/hplj1020-firmware`——正常回 `firmware already loaded`（正常运作中）或 `firmware load done`（刚灌完）；之后提一个小 PDF（第 6 步脚本即含此步），**看到纸出来**＝通。仍「闪灯不出」＝多半免密 sudo 未给／固件档路径不对。
- **新设备没有这机型**：`main.py` 的 `FIRMWARE_SCRIPT` 改 `""` 即跳过（缺档不炸）。

### 8.2 Bug②：`no response from daemon`／连不上 server（常见，快修）

- **症状**：任一 `lpstat`／`lp` 回 `no response from daemon` 或连不上；甚至 `lpstat -p` 啥都没。
- **根因**：**`cupsd` 没在跑**——全新机未起、被停、或 crash。命令都在，只是后头没人接待。
- **修法**：`systemctl status cups`（找具体错）→ `sudo systemctl restart cups` → 常驻 `sudo systemctl enable --now cups`；核对 `systemctl is-active cups`＝`active`，再试 `lpstat -p -d`。
- **如何核对修好**：`lpstat -p -d` 能列出打印机＋默认机（§2.4 那段）＝活。仍报＝照 status 往下挖。

### 8.3 其它常见坑

- **打印机名字 ≠ 型号**：`lpadmin -p hp1020` 的 `hp1020` 是**你在 CUPS 给它起的名字**（后续 `lp -d hp1020` 用它），不是厂商字符串；Agent 传 `printer=` 也是这个。新设备先 `list_printers()`／`lpstat -p -d` 确认到底叫什么，别凭印象。
- **`lp` 的 `-d` 和 `-P` 别混**：`-d`＝**目的地（哪台机）**；`-P`＝**页码范围（打哪些页，如 `1-3`）**。本插件内部已正确组合（`lp -d <n> -n N -o media=M [-o landscape] [-P 1-3] <file>`）；若你自己手打 `lp` 指定打印机，记牢用 `-d`。
- **`不在允许打印的目录内`／`不支持的文档类型`**：是插件白名单（`_check_path`）在做，非 CUPS 故障。处理：把文件挪进白名单目录（如 `~/Documents`）、或按需调 `allowed_paths` 参数（别盲目放宽全部）。
- **固件脚本免密 sudo**：`_ensure_firmware` 跑的是 `sudo -n`（不问密码）；若 sudoers 没给 NOPASSWD，它静默失败（rc≠0、`fw=""`，不影响主流程，但这一次没灌）。LJ1020 这种机需要：`<user> ALL=(root) NOPASSWD: /usr/local/sbin/hplj1020-firmware`。
- **PDF 不过滤／`filter failed`**：多半缺 `cups-filters`（ghostscript pdftopk 链）。装上重试；仍错看日志的具体 filter 行。
- **`[not loaded]` 误导**：`octop plugin list` 显示的是 CLI 该进程视角，别当 server 状态；以 `octop plugin reload`（回 `Reloaded N`）＋`octop agent reload <ID>`（回 `ok`）为准。
- **代码改完忘了重载**：改了 `main.py` 要 `octop plugin reload`＋`octop agent reload <ID>`（不热更）。
- **非 root 打印权限**：一般普通用户即可 `lp`（走本地 socket）；若遇 `permission denied` 之类再考虑 `sudo lp …`（日常不必常 sudo）。
- **ipp-usb vs 传统 usb backend**：较新的打印机（2023 前后起）多讲 IPP-over-USB，由 `ipp-usb` 套件驱动接手（本参考机亦已装）；而 LJ1020 这类老机走传统 `usb://`＋PPD（foo2zjs）。新设备若见一台新机「识得到但打不出」，先查是否要走 `ipp-usb`（而非硬套老式 usb backend）。

---

## 9. 回滚／升级注意

- **回滚（不用了）**：删 `~/.octop/plugins/printer-cups/` 整个目录 → `octop plugin reload`＋`octop agent reload <ID>`（让它从运行时消失）；可选清掉 `~/.octop/env` 的 `OCTOP_PRINTER_NAME=…` 那行。
  - **注意：这只卸「octop 插件」，不动 CUPS 本体**（`lp/lpstat/cancel` 还在、打印机注册还在）——插件与系统打印子系统是**解耦**两层。若要连 CUPS 一起收，另删服务＋`lpadmin -x <n>` 移除打印机。
- **升级／修改插件**：覆盖 `main.py`（`plugin.yaml` 不变）→ 两步重载 → 再跑一次 `printer-cups-verify-all.py` 确认仍全绿。代码变更**不会自动热更**。
- **CUPS／系统层升级**：`cups` 套件升版（`apt upgrade`）**不影响插件**（对外 `lp/lpstat/cancel` 接口稳定）；若动大版（或换 usb backend／驱动），建议重跑第 6 步脚本兜底。
- **换机器时**：**CUPS 侧要重做**（安装＋`lpadmin` 重新注册那台）；**插件侧**只需把 `~/.octop/plugins/printer-cups/` 拷过去＋校对 `~/.octop/env` 的 `OCTOP_PRINTER_NAME` 指向新机正确名字，再两步重载即可。

---

## 附录 A：文件与路径速查

| 项目 | 路径／值 | 说明 |
|---|---|---|
| CUPS 客户端命令 | `/usr/bin/lp`、`/usr/bin/lpstat`、`/usr/bin/cancel` | 来自 `cups-bd`；本插件只靠这三条 |
| CUPS 服务（daemon） | systemd unit：`cups` | `systemctl is-active cups` 应回 `active` |
| 打印机名（本参考机） | `hp1020` | Agent 调工具时用的名字（`lp -d hp1020`） |
| 设备 URI（参考机） | `usb://HP/LaserJet%201020?serial=S44PJCF` | `lpadmin -v` 注册值；`lpstat -v` 可查 |
| PPD（参考机） | `/etc/cups/ppd/hp1020.ppd` | 注册时由 CUPS 落盘（约 24 KB） |
| foo2zjs 固件档（参考机） | `/var/lib/foo2zjs/firmware/sihp1020.dl`（128431 B） | LJ1020 要灌的固件；断电即失 |
| 固件灌载脚本（参考机） | `/usr/local/sbin/hplj1020-firmware` | `main.py` 的 `FIRMWARE_SCRIPT` 指向它；打印前经 `sudo -n`（需免密 sudo） |
| 插件目录 | `~/.octop/plugins/printer-cups/` | octop 插件根 |
| 插件清单 | `~/.octop/plugins/printer-cups/plugin.yaml` | 7 行元数据 |
| 插件实现 | `~/.octop/plugins/printer-cups/main.py` | 187 行、4 个打印工具（list/status/print/cancel） |
| 全域默认机 env | `~/.octop/env` | 那一行 `OCTOP_PRINTER_NAME=hp1020`（回退值） |
| 内置允许打印目录 | `~/Documents : ~/Downloads : /srv/octop/print : /tmp/octop-print` | `main.py` 的 `DEFAULT_ALLOWED_PATHS`；`allowed_paths` 参数可覆盖 |
| 本指引 | 本仓库 `README.md` | 你正在看的这份 |
| 验证脚本 | 本仓库 `scripts/printer-cups-verify-all.py` | 第 6 步的一条龙全绿脚本 |

## 附录 B：最小冒烟（一行命令快速确认 CUPS 活着）

不想一上来就跑全套？先这一条确认 CUPS（daemon＋客户端＋默认机）本体在位：

```bash
lpstat -p -d && echo "CUPS OK"
```

打出打印机列表＋系统默认机，再接一行 `CUPS OK`＝链没坏。要进一步确认整份 octop 插件（那 4 个工具、真实入队打印）端到端，再跑第 6 步的 `printer-cups-verify-all.py`。

---

## 授权与致谢

- **CUPS** 本体为 **GPL-2.0-or-later**（见 OpenPrinting 官方仓库）。本指引与插件代码仅为接入用途；HP LaserJet 1020 走 **foo2zjs** 驱动（GPL），随包固件 `sihp1020.dl` 属 HP。若要把这些随你的产品分发给第三方，请自行评估 copyleft 条款。
- 本仓库的插件代码（`plugin/`、`scripts/`）可自由取用于你的 Octop 实例。
