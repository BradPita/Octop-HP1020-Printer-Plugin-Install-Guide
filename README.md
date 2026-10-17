# printer-cups 打印機安裝指引（Octop Agent 版）

**繁體中文** ｜ [简体中文](README.zh-CN.md) ｜ [English](README.en.md)

> **這份文檔給誰看？** 給 **新 Octop 設備上的 Agent** 看。用戶大概會講一句「照這個指引把打印機接上」——你就照著一步步來。
> **怎麼用最省力：** 從第 1 步開始逐步執行；每步都給**可直接粘貼跑的指令**。第 5 步兩步重載完，跑一次第 6 步的一條龍腳本，看到「**✅ 通過 N 項 · ❌ 失敗 0 項 / 🎉 全綠**」＝大功告成。
> **本指引已在 Debian/Ubuntu 系 x86_64 機器實測通過**（示例環境：Linux Mint 22.3，2026-10）。

---

## 目錄
- 0. 背景：CUPS 是什麼、裝完得到什麼
- 1. 前置檢查（新設備先跑這一段確認環境 OK）
- 2. 安裝 CUPS ＋ 驅動，並註冊打印機（Debian/Ubuntu 系實例）
- 3. 安裝插件（複製本倉庫的 plugin/）
- 4. 寫全域預設機（~/.octop/env）
- 5. 重載進運行時（octop plugin reload ＋ agent reload）
- 6. 端到端驗證（scripts/printer-cups-verify-all.py）
- 7. 用法速查（4 個工具怎麼調）
- 8. 除錯手冊（本機實踩 ＋ 常見坑）
- 9. 回滾／升級注意
- 附錄 A：檔案與路徑速查；附錄 B：最小冒煙一行命令

### 本倉庫檔案

| 路徑 | 內容 |
|---|---|
| `README.md` / `README.zh-CN.md` / `README.en.md` | 本指引的繁中／簡中／英文版 |
| `plugin/plugin.yaml` | 插件清單（7 行） |
| `plugin/main.py` | 插件本體（187 行，含 4 個打印工具） |
| `scripts/printer-cups-verify-all.py` | 一條龍端到端驗證腳本 |

> 本倉庫所有中文（含程式碼註解）統一為**繁體中文**；簡中與英文版指引以連結指向同一份程式碼，避免同一份文件內簡繁混用。

---

## 0. 背景：CUPS 是什麼、裝完得到什麼

**CUPS**（Common Unix Printing System）＝ **Debian/Ubuntu 系的預設打印子系統**：一個 `cupsd` 守護進程管**任務隊列（spool）、PDF 過濾、USB/網絡後端**；對外暴露一組 BSD 風格命令——`lp`（提交）、`lpstat`（查狀態）、`cancel`（撤單）、`lpadmin`（增刪改打印機）。Agent 要「打文件」，本質就是往 CUPS 隊列裡塞一個 job，剩下交給它。

本插件做的事＝**把這三條命令封裝成 4 個 async 工具**掛到 octop（`list_printers` / `printer_status` / `print_file` / `cancel_jobs`），並加兩層本地護欄：**允許打印的目錄白名單**（`allowed_paths`）與**文件類型白名單**（`ALLOWED_SUFFIXES`），避免任意路徑直接被打出去。

裝完後你會得到：
- 一個跑著的 CUPS 守護進程（`systemctl is-active cups` → `active`）＋ PATH 裡的一組 CLI：`lp/lpstat/cancel`。
- 一個 octop 插件 `printer-cups`：掛進運行時、暴露 **4 個打印工具**（列表／狀態／提交打印／撤單＋清隊列）。
- 一個**全域預設打印機名**（寫進 `~/.octop/env` 的 `OCTOP_PRINTER_NAME`）：使用者沒設 per-tool 的 `default_printer` 時回退到此值。
- （可選）一套**打印前自動灌固件**掛鉤：本參考機是 HP LaserJet 1020——晶片無 flash、斷電即失內置固件，靠 `main.py` 的 `FIRMWARE_SCRIPT`（指向 `/usr/local/sbin/hplj1020-firmware`）每次打印前經 `sudo -n` 補上；不需要就把它改成 `""`。

一句話：裝完後 Agent 要打文件，直接調那幾個工具（預設走全域 `OCTOP_PRINTER_NAME` 指定的機器、只打白名單目錄內的文件）；出問題先 `list_printers` 看隊列，再照第 8 節對症。

---

## 1. 前置檢查（新設備先跑這一段確認環境 OK）

CUPS 是**系統級服務**（不需要拉二進制，靠發行版包管理安裝）。所以要先確認：Linux x86_64、Debian/Ubuntu 系（包名可直接照抄）；octop 運行時在 `~/.octop/`、CLI 在；打印三件套 `lp/lpstat/cancel` 在不在（沒裝是正常，第 2 步會裝）。

讓 Agent 先跑下面這段**只讀體檢**（不改東西）：

```bash
# 1) 系統與架構（要 Linux / x86_64；記下 base 發行版，**別是 Alpine / musl**）
cat /etc/os-release | grep -E '^(NAME|VERSION)='
uname -m                      # 應是 x86_64

# 2) octop 運行時與 venv python 在不在
echo "HOME=$HOME"
ls -d ~/.octop
ls ~/.octop/venv/bin/python
which octop                     # CLI 要在

# 3) 現有打印棧體檢（缺什麼都正常，第 2 步會裝）
which lp lpstat cancel lpinfo || true
systemctl is-active cups 2>&1 || true      # 新機很可能 inactive / unknown
ls /var/lib/foo2zjs/firmware/sihp1020.dl 2>/dev/null && echo "LJ1020 固件檔在" || true

# 4) octop 目前有哪些插件（裝之前**應該沒有** printer-cups）
octop plugin list
```

**判讀要點：**
- `uname -m` 要是 `x86_64`；`/etc/os-release` 要是 Debian/Ubuntu/Mint 系。**若是 Fedora/Arch**：命令同一套（`lp/lpstat/cancel`），只是包管理與包名不同（`dnf install cups cups-client ...`／`pacman -S cups cups-client ...`）——照第 2 步的思路換包名即可。
- `~/.octop/`、`~/.octop/venv/bin/python`、`octop` CLI 都要在（與 lightpanda 指引同一套前提）。
- `lp/lpstat/cancel` 若不在 → 正常，第 2 步 `apt install cups cups-bd ...` 會帶來。
- `systemctl is-active cups` 非 `active` → 正常（尚未安裝／未啟動）。
- `octop plugin list` 此刻還沒有 `printer-cups`（正常，第 3 步才建立）。

> ⚠️ `octop plugin list` 顯示的 `[not loaded]` 只是 **CLI 自己那個進程的視角**，**不代表真正在跑的 server** 到底載沒載。**別被它誤導。** 真正的依據＝第 5 步 `octop plugin reload` 是否回 `Reloaded N`、`octop agent reload <ID>` 是否回 `ok`。

---

## 2. 安裝 CUPS ＋ 驅動，並註冊打印機

以下以 **Linux Mint 22.3（Debian/Ubuntu 系、apt）** 為實例——本參考機正是如此裝通。核心分三步：**裝核心 → 選驅動 → 註冊**，最後用 `lpstat` 只讀驗證。

### 2.1 裝 CUPS 核心（伺服器＋過濾＋BSD 命令）

```bash
sudo apt update
sudo apt install -y cups cups-bd cups-client cups-filters
```

| 套件 | 提供什麼 |
|---|---|
| `cups` | CUPS 服務：`cupsd` 守護進程（隊列／spool）＋基礎 |
| `cups-bd` | BSD 風格命令 —— **`lp`（提交）、`lpstat`（查狀態）、`cancel`（撤任務）**（本插件只依賴這三條） |
| `cups-client` | CUPS 客戶端庫 |
| `cups-filters` | 過濾鏈（**PDF → 頁面光柵** 等；打 PDF 幾乎必裝） |

啟動並常駐 CUPS 服務：

```bash
sudo systemctl enable --now cups
systemctl is-active cups        # 應回 active
```

### 2.2 選／裝驅動（依打印機品牌而定）

不同品牌走不同路徑：
- **IPP Everywhere（現代網印）**：多數 2020 年後的網印自帶 IPP，註冊時直接 `-m everywhere`，通常不單獨裝驅動。
- **HP（老型，如 LaserJet 1020）**：一般走 `hpcups`；但 LJ1020 屬極簡機型，本參考機改走 **`foo2zjs`**（通用封裝），效果最穩。
- **佳能／愛普生**：對應 `printer-driver-gutenprint`、`cups-filters`。

本參考機（HP LaserJet 1020，USB）實際裝的是 `foo2zjs`：

```bash
sudo apt install -y printer-driver-foo2zjs
ls -l /var/lib/foo2zjs/firmware/sihp1020.dl     # LJ1020 固件檔（約 128 KB）
```

### 2.3 註冊打印機（`lpadmin`，一步）

先查兩樣：**設備 URI** 與**可用模型/PPD**：

```bash
lsusb | grep -i laserjet                          # 確認 USB 識別（供記錄）
lpinfo -v | grep -i laserjet                          # 取設備 URI，形如 usb://HP/LaserJet%201020?serial=...
ls /usr/share/ppd/ 2>/dev/null                            # 看看驅動帶了哪些 PPD
```

然後註冊＋設為系統預設：

```bash
# 註冊（把 <NAME>、<DEVICE_URI>、<MODEL> 換成上面查到的實際值）
sudo lpadmin -p hp1020 -E \
  -v 'usb://HP/LaserJet%201020?serial=S44PJCF' \
  -m foo2zjs/sihp1020.ppd

# 設為系統預設目的地
sudo lpadmin -d hp1020
```

> **註解：**
> - `-p hp1020` 的 `hp1020` 是**在 CUPS 裡給這台起的名字**（任意，之後 `lp -d hp1020` 用它）；`-v` 是設備 URI；`-m` 是驅動/模型（`foo2zjs/sihp1020.ppd`）。
> - 走 **IPP Everywhere** 時：`-m everywhere`、`-v` 填 `ipp://…` 即可，一般不用另裝驅動。
> - 註冊後 CUPS 會把 PPD 落盤到 `/etc/cups/ppd/<名字>.ppd`（本參考機 `hp1020.ppd` 約 24 KB）——這是「機器已掛上 CUPS」的直接證據。

### 2.4 驗證註冊成功（只讀）

```bash
lpstat -p -d
```

預期（本參考機實測輸出）：

```text
printer hp1020 is idle.  enabled since 2026年10月15日 (週四) 02時42分37秒
system default destination: hp1020
```

再確認設備 URI 已被 CUPS 記住：

```bash
lpstat -v hp1020
```

```text
device for hp1020: usb://HP/LaserJet%201020?serial=S44PJCF
```

兩段都符合＝CUPS 側就緒，可以接插件了。

---

## 3. 安裝插件（複製本倉庫的 plugin/）

Octop 插件就是 `~/.octop/plugins/<id>/` 下的一個目錄，內含兩份檔案：

- **`plugin.yaml`**（清單，7 行）：`id / version / name / description / icon / kind: tool / entry: main.py`。
- **`main.py`**（本體，187 行）：每個工具都是 **`async def`**（docstring 即給模型看的描述、參數帶預設值）；底部 `def setup(ctx)` 用 `ctx.tool("名字", 函數, description=...)` 逐個掛載那 4 個打印工具。本插件**零第三方依賴**——只調系統自帶的 `lp`／`lpstat`／`cancel`（本插件也是 browser-lightpanda 那份指引引用的「插件範本」）。

**安裝動作**＝把本倉庫 `plugin/` 下的兩份檔案複製到 `~/.octop/plugins/printer-cups/`：

```bash
# 若你已 clone 本倉庫（<repo> 為倉庫路徑）
mkdir -p ~/.octop/plugins/printer-cups
cp <repo>/plugin/plugin.yaml ~/.octop/plugins/printer-cups/
cp <repo>/plugin/main.py     ~/.octop/plugins/printer-cups/

# 確認落地＋語法冒煙
ls -l ~/.octop/plugins/printer-cups/
~/.octop/venv/bin/python -m py_compile ~/.octop/plugins/printer-cups/main.py && echo "SYNTAX OK"
```

> 沒有 clone 的話，直接用 GitHub 頁面把 `plugin/plugin.yaml` 與 `plugin/main.py` 另存到上述目錄即可（**整段原樣存**，別漏行）。

**`main.py` 結構速覽**（187 行不用背，看懂改碼處即可）：

- **頂部常量**：`FIRMWARE_SCRIPT`（HP LaserJet 1020 專屬的打印前固件灌載掛鉤；其他機型把它設成 `""` 就跳過）、`DEFAULT_ALLOWED_PATHS`（允許打印的目錄白名單：`~/Documents : ~/Downloads : /srv/octop/print : /tmp/octop-print`）、`ALLOWED_SUFFIXES`（允許的文件副後綴白名單：pdf／圖片／office／文本等）。
- **配置分層**：`get_tool_config`（個人層 per-tool config ＞ 全域 env）決定打到哪台機器——解析順序＝**個別 `default_printer` ＞ 全域 env `OCTOP_PRINTER_NAME` ＞ 皆無 → 回「未指定，先用 list_printers」**；`allowed_paths` 同理可被個別覆蓋。
- **★ 安全護欄**：`_check_path()` 執行雙白名單（目錄＋副後綴），不在表內直接拒；打印前 `_ensure_firmware()` 經 `sudo -n` 灌固件（需免密 sudo，見第 8 節 Bug①）。
- **4 個對外工具**（`list_printers` / `printer_status` / `print_file` / `cancel_jobs`）＋ 底部 `setup(ctx)` 註冊段。

---

## 4. 寫全域預設機（~/.octop/env）

要把「**整臺 Octop 實例的所有 Agent／用戶，個別未設 `default_printer` 時都回退到指定打印機**」做到重啟不丟，就寫進全域環境檔 `~/.octop/env`（個別使用者仍可用 per-tool config 覆蓋，屬分層）。

把下面 1 行 **append 進去**——**別整檔覆蓋**（例如別把既有 browser 路由塊的 `OCTOP_BROWSER_PREFERRED`／`OCTOP_BROWSER_FALLBACK`／`OCTOP_LIGHTPANDA_BIN`／`LIGHTPANDA_DISABLE_TELEMETRY` 給衝掉）：

```bash
# 追加到 ~/.octop/env（保留既有行）
OCTOP_PRINTER_NAME=hp1020          # 全域預設打印機（個別未設 default_printer 時的回退值）
```

要點：
- **`hp1020` 換成你新設備上 `lpadmin -p …` 註冊的那個名字**（`lpstat -p -d` 可查現有名字；填錯＝提交時找不到那台）。
- 這行語意：未設個別 `default_printer` 時，所有 Agent 一律以此為目標。
- 寫完 `cat ~/.octop/env` 核對：這 1 行在、且原有行沒被刪。

---

## 5. 重載進運行時（octop plugin reload ＋ agent reload）

插件躺在磁碟上還不夠，要讓 *真正在跑的 server* 撿到它、把 4 個工具注入你的 Agent，得跑兩步重載（跟 browser-lightpanda 完全一樣的流程）：

```bash
# [1/2] 重新掃描磁碟上的所有插件 → 撿到剛建的 printer-cups
octop plugin reload
# 預期輸出：Reloaded N plugin(s)   （N ≥ 1）

# [2/2] 重載你的 Agent，把那 4 個工具重新注入它的工具清單
octop agent reload <你的AGENT_ID>
# 預期輸出：ok
```

- `<你的AGENT_ID>` 換成你自己的 Agent 識別碼（`octop agent list` 可查）。
- `octop plugin reload` 成功回 `Reloaded N plugin(s)`；`octop agent reload <ID>` 成功回 `ok`。兩條都 ok → 4 個工具就進了你的工具清單。
- 再提醒一次：`plugin list` 裡的 `[not loaded]` 是 **CLI 自身進程**的視角，別當成 server 狀態；以上面兩步返回值為準。

---

## 6. 端到端驗證（scripts/printer-cups-verify-all.py）

裝完＋重載後，跑一次本倉庫的驗證腳本。它會**直接 import 插件 `main.py`、裸調那 4 個 async 工具函數**（證 CUPS 打印鏈確活、不依賴 octop 是否已注入），逐項覆蓋：

**T1 list_printers（列表＋預設機＋隊列）→ T2 printer_status（預設機詳情：狀態／設備 URI／accepting）→ T3 print_file（現場生成最小 1 頁 PDF、真鏈提交入隊、再用外部 `lpstat -o` 交叉核對隊列）→ T4 cancel_jobs（有殘留即清空省紙；已打完自然空亦計過）**

每步 ✅／❌ 附證據；全過＝**✅ 通過 N 項 · ❌ 失敗 0 項 / 🎉 全綠**、exit 0。

```bash
# 跑本倉庫的驗證腳本（出證目錄指到你想要的位置）
python3 <repo>/scripts/printer-cups-verify-all.py /tmp/verify-out
# 預期末行：✅ 通過 8 項 · ❌ 失敗 0 項 … 🎉 全綠！… 且 exit 0
```

**本參考機實測輸出（供對照）：**

```text
[load] 插件模块载入自 ~/.octop/plugins/printer-cups (3.1s) · budget=60s · 预设机=hp1020 · 产物目录=/tmp/pc-verify-demo
  ✅ [   4.2s] T1 list_printers: 1.1s
  ✅ [   4.2s] 列表成功: 'printer hp1020' + 预设机/队段齐全
  ✅ [   4.2s] T2 printer_status: 0.0s
  ✅ [   4.2s] 状态成功: 'printer hp1020 is idle.  enabled since 2026年10月15日 (週四) 02時42分37秒'
  ✅ [  19.3s] T3 print_file: 15.1s
  ✅ [  19.3s] 入队成功: CUPS 受理 / 队列核对 'hp1020-11 <user> 1024 2026年10月16日 (週五) 22時10分40秒'
  ✅ [  20.4s] T4 cancel_jobs: 1.1s
  ✅ [  20.4s] 清队成功: 1 笔回收

═══════ 总判定 ═══════
  ✅ 通过 8 项 · ❌ 失败 0 项 · 总耗时 20.4s
  🎉 全绿！CUPS 打印链 list/status/print/cancel 四段全通
[DONE] PASS · 8 项通过 · 总耗时 20.4s
```

看到「🎉 全綠！」＝CUPS 打印鏈（列／狀／打／撤）在你的新設備上都工作、**能用**了。

> 為什麼驗證走「裸調函數」、不等 octop 注入？——它直打 CUPS／lp 真鏈，乾淨證明*打印鏈本身*工作，與「octop 有沒有把工具塞進對話」解耦，是最有力的排障第一手。octop 側可用性由第 5 步兩步重載的返回值保證。

---

## 7. 用法速查（4 個工具怎麼調）

裝完重載後，4 個工具已在你的工具清單；要打東西直接調（**預設機取個別 `default_printer`，未設則回退全域 `OCTOP_PRINTER_NAME`；只打白名單目錄×白名單類型**）。常用口訣表：

| 想做 | 工具 | 補充 |
|---|---|---|
| 看有哪些打印機、預設機、待打任務 | `list_printers()` | 無參；回「=== 打印機 ===」「=== 待打印隊列 ===」兩段；`lpstat` 缺失會明說 |
| 看某台機器的狀態/設備/是否收單 | `printer_status(printer="")` | `printer` 留空＝用預設機（個別→全域鏈）；拼 `lpstat -p <n> -l`＋`-v <n>`＋`-a <n>` 三段 |
| 把某文件送去打印 | `print_file(path, printer="", copies=1, page_range="", landscape=False, media="A4")` | **path 須絕對（可 `~/`開頭）、且在 `allowed_paths` 內**；副後綴须在 `ALLOWED_SUFFIXES`；`copies` 截 1~20；`page_range` 如 `"1-3"`（轉 `lp -P`）；`media` 預設 A4；組 `lp -d <n> -n N -o media=M [-o landscape] [-P 1-3] <file>`；前可選灌固件 |
| 撤單 / 清空某台隊列 | `cancel_jobs(job_id="", printer="")` | 有 `job_id`→`cancel <id>`（撤單一筆）；否則取 `printer`（留空=預設）→`cancel -a <n>`（清空該隊列）；回 ✅/❌ 一句話 |

- **參數口訣**：`print_file` 只有 `path` 是硬要求；其餘（`printer`/`copies`/`page_range`/`landscape`/`media`）皆有預設，按需才給。`cancel_jobs` 二選一（`job_id` 或 `printer`）。
- **白名單兩層**（`print_file` 專屬護欄，由 `_check_path` 執行）：
  - **目錄**：檔案 resolve 後的 realpath 須落在 `allowed_paths` 某一項之內（或即該目錄本身）。
  - **類型**：副後綴不在 `ALLOWED_SUFFIXES` 直接拒。
- **一句口訣**：看機看隊 → `list_printers`；看單機狀態 → `printer_status`；送打印 → `print_file`（路徑在白名單內）；撤單清隊 → `cancel_jobs`。

---

## 8. 除錯手冊（本機實踩 ＋ 常見坑）

這段收錄本參考機實裝真正遇到的 2 個硬問題（症狀→根因→修法→如何核對修好）＋若干通用坑。核心特徵：命令層（`lp/lpstat`）可能都好，問題藏在**固件／daemon／白名單**這幾層。新設備遇到「打了不出紙」「no response from daemon」時，照 §8.1、§8.2 對照最省時間。

### 8.1 Bug①：LJ1020 斷電即失內置固件 → 打了不出紙（此機型致命，必修）

- **症狀**：任務能入隊（`lpstat -o` 看得到）、CUPS 不報致命錯，但**打印機燈閃半天不吐紙**；關機/重插 USB 後尤甚。
- **根因**：LJ1020 的列印晶片**無自帶 flash**，開機要靠主機灌入 `sihp1020.dl`（約 128 KB）；**一斷電即忘**（關機、長睡、重插都算）。不是壞，是失憶。
- **修法（本機已落地）**：`/usr/local/sbin/hplj1020-firmware` 腳本——先探現狀（查 `FWVER`：走 CUPS usb backend 或 `usb_printerid /dev/usb/lp0`），**有才跳、沒才灌**；灌的路徑雙備：CUPS usb backend（帶 `DEVICE_URI`）或直 `cat` 到 `/dev/usb/lp0`。再讓 `main.py` 的 `FIRMWARE_SCRIPT` 指它、`print_file` 前 `await _ensure_firmware()`（經 `sudo -n`，故需**免密 sudo**：sudoers 加 `<user> ALL=(root) NOPASSWD: /usr/local/sbin/hplj1020-firmware`）。
- **如何核對修好**：手動 `sudo -n /usr/local/sbin/hplj1020-firmware`——正常回 `firmware already loaded`（正常運作中）或 `firmware load done`（剛灌完）；之後提一個小 PDF（第 6 步腳本即含此步），**看到紙出來**＝通。仍「閃燈不出」＝多半免密 sudo 未給／固件檔路徑不對。
- **新設備沒有這機型**：`main.py` 的 `FIRMWARE_SCRIPT` 改 `""` 即跳過（缺檔不炸）。

### 8.2 Bug②：`no response from daemon`／連不上 server（常見，快修）

- **症狀**：任一 `lpstat`／`lp` 回 `no response from daemon` 或連不上；甚至 `lpstat -p` 啥都沒。
- **根因**：**`cupsd` 沒在跑**——全新機未起、被停、或 crash。命令都在，只是後頭沒人接待。
- **修法**：`systemctl status cups`（找具體錯）→ `sudo systemctl restart cups` → 常駐 `sudo systemctl enable --now cups`；核對 `systemctl is-active cups`＝`active`，再試 `lpstat -p -d`。
- **如何核對修好**：`lpstat -p -d` 能列出打印機＋預設機（§2.4 那段）＝活。仍報＝照 status 往下挖。

### 8.3 其它常見坑

- **打印機名字 ≠ 型號**：`lpadmin -p hp1020` 的 `hp1020` 是**你在 CUPS 給它起的名字**（後續 `lp -d hp1020` 用它），不是廠商字串；Agent 傳 `printer=` 也是這個。新設備先 `list_printers()`／`lpstat -p -d` 確認到底叫什麼，別憑印象。
- **`lp` 的 `-d` 和 `-P` 別混**：`-d`＝**目的地（哪台機）**；`-P`＝**頁碼範圍（打哪些頁，如 `1-3`）**。本插件內部已正確組合（`lp -d <n> -n N -o media=M [-o landscape] [-P 1-3] <file>`）；若你自己手打 `lp` 指定打印機，記牢用 `-d`。
- **`不在允許打印的目錄內`／`不支持的文件類型`**：是插件白名單（`_check_path`）在做，非 CUPS 故障。處理：把檔案挪進白名單目錄（如 `~/Documents`）、或按需調 `allowed_paths` 參數（別盲目放寬全部）。
- **固件腳本免密 sudo**：`_ensure_firmware` 跑的是 `sudo -n`（不問密碼）；若 sudoers 沒給 NOPASSWD，它靜默失敗（rc≠0、`fw=""`，不影響主流程，但這一次沒灌）。LJ1020 這種機需要：`<user> ALL=(root) NOPASSWD: /usr/local/sbin/hplj1020-firmware`。
- **PDF 不過濾／`filter failed`**：多半缺 `cups-filters`（ghostscript pdftopk 鏈）。裝上重試；仍錯看日誌的具體 filter 行。
- **`[not loaded]` 誤導**：`octop plugin list` 顯示的是 CLI 該進程視角，別當 server 狀態；以 `octop plugin reload`（回 `Reloaded N`）＋`octop agent reload <ID>`（回 `ok`）為準。
- **代碼改完忘了重載**：改了 `main.py` 要 `octop plugin reload`＋`octop agent reload <ID>`（不熱更）。
- **非 root 打印權限**：一般普通用戶即可 `lp`（走本地 socket）；若遇 `permission denied` 之類再考慮 `sudo lp …`（日常不必常 sudo）。
- **ipp-usb vs 傳統 usb backend**：較新的打印機（2023 前後起）多講 IPP-over-USB，由 `ipp-usb` 套件驅動接手（本參考機亦已裝）；而 LJ1020 這類老機走傳統 `usb://`＋PPD（foo2zjs）。新設備若見一台新機「識得到但打不出」，先查是否要走 `ipp-usb`（而非硬套老式 usb backend）。

---

## 9. 回滾／升級注意

- **回滾（不用了）**：刪 `~/.octop/plugins/printer-cups/` 整個目錄 → `octop plugin reload`＋`octop agent reload <ID>`（讓它從運行時消失）；可選清掉 `~/.octop/env` 的 `OCTOP_PRINTER_NAME=…` 那行。
  - **注意：這只卸「octop 插件」，不動 CUPS 本體**（`lp/lpstat/cancel` 還在、打印機註冊還在）——插件與系統打印子系統是**解耦**兩層。若要連 CUPS 一起收，另刪服務＋`lpadmin -x <n>` 移除打印機。
- **升級／修改插件**：覆蓋 `main.py`（`plugin.yaml` 不變）→ 兩步重載 → 再跑一次 `printer-cups-verify-all.py` 確認仍全綠。代碼變更**不會自動熱更**。
- **CUPS／系統層升級**：`cups` 套件升版（`apt upgrade`）**不影響插件**（對外 `lp/lpstat/cancel` 介面穩定）；若動大版（或換 usb backend／驅動），建議重跑第 6 步腳本兜底。
- **換機器時**：**CUPS 側要重做**（安裝＋`lpadmin` 重新註冊那台）；**插件側**只需把 `~/.octop/plugins/printer-cups/` 拷過去＋校對 `~/.octop/env` 的 `OCTOP_PRINTER_NAME` 指向新機正確名字，再兩步重載即可。

---

## 附錄 A：檔案與路徑速查

| 項目 | 路徑／值 | 說明 |
|---|---|---|
| CUPS 客戶端命令 | `/usr/bin/lp`、`/usr/bin/lpstat`、`/usr/bin/cancel` | 來自 `cups-bd`；本插件只靠這三條 |
| CUPS 服務（daemon） | systemd unit：`cups` | `systemctl is-active cups` 應回 `active` |
| 打印機名（本參考機） | `hp1020` | Agent 調工具時用的名字（`lp -d hp1020`） |
| 設備 URI（參考機） | `usb://HP/LaserJet%201020?serial=S44PJCF` | `lpadmin -v` 註冊值；`lpstat -v` 可查 |
| PPD（參考機） | `/etc/cups/ppd/hp1020.ppd` | 註冊時由 CUPS 落盤（約 24 KB） |
| foo2zjs 固件檔（參考機） | `/var/lib/foo2zjs/firmware/sihp1020.dl`（128431 B） | LJ1020 要灌的固件；斷電即失 |
| 固件灌載腳本（參考機） | `/usr/local/sbin/hplj1020-firmware` | `main.py` 的 `FIRMWARE_SCRIPT` 指向它；打印前經 `sudo -n`（需免密 sudo） |
| 插件目錄 | `~/.octop/plugins/printer-cups/` | octop 插件根 |
| 插件清單 | `~/.octop/plugins/printer-cups/plugin.yaml` | 7 行元資料 |
| 插件實現 | `~/.octop/plugins/printer-cups/main.py` | 187 行、4 個打印工具（list/status/print/cancel） |
| 全域預設機 env | `~/.octop/env` | 那一行 `OCTOP_PRINTER_NAME=hp1020`（回退值） |
| 內建允許打印目錄 | `~/Documents : ~/Downloads : /srv/octop/print : /tmp/octop-print` | `main.py` 的 `DEFAULT_ALLOWED_PATHS`；`allowed_paths` 參數可覆蓋 |
| 本指引 | 本倉庫 `README.md` | 你正在看的這份 |
| 驗證腳本 | 本倉庫 `scripts/printer-cups-verify-all.py` | 第 6 步的一條龍全綠腳本 |

## 附錄 B：最小冒煙（一行命令快速確認 CUPS 活著）

不想一上來就跑全套？先這一條確認 CUPS（daemon＋客戶端＋預設機）本體在位：

```bash
lpstat -p -d && echo "CUPS OK"
```

打出打印機列表＋系統預設機，再接一行 `CUPS OK`＝鏈沒壞。要進一步確認整份 octop 插件（那 4 個工具、真實入隊打印）端到端，再跑第 6 步的 `printer-cups-verify-all.py`。

---

## 授權與致謝

- **CUPS** 本體為 **GPL-2.0-or-later**（見 OpenPrinting 官方倉庫）。本指引與插件程式碼僅為接入用途；HP LaserJet 1020 走 **foo2zjs** 驅動（GPL），隨包固件 `sihp1020.dl` 屬 HP。若要把這些隨你的產品分發給第三方，請自行評估 copyleft 條款。
- 本倉庫的插件程式碼（`plugin/`、`scripts/`）可自由取用於你的 Octop 實例。
