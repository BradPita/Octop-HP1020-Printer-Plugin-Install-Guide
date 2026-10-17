# printer-cups Printer Install Guide (Octop Agent edition)

[繁體中文](README.md) ｜ [简体中文](README.zh-CN.md) ｜ **English**

> **Who is this for?** For an **Agent running on a new Octop host**. The user will typically just say *"follow this guide and hook up the printer"* — work through it step by step.
> **Fastest path:** start at step 1 and go in order; every step ships commands you can paste and run. When step 5 is reloaded, run the one-shot script in step 6 and look for "**✅ N checks passed · ❌ 0 failed / 🎉 all green**" — that's done.
> **Verified on a Debian/Ubuntu-family x86_64 host** (reference environment: Linux Mint 22.3, Oct 2026).

---

## Contents
- 0. Background: what CUPS is, and what you get after installing
- 1. Pre-flight checks (run this first on a new host)
- 2. Installing CUPS + a driver, and registering the printer (Debian/Ubuntu example)
- 3. Installing the plugin (copy this repo's plugin/)
- 4. Writing the global default printer (~/.octop/env)
- 5. Reloading into the runtime (octop plugin reload + agent reload)
- 6. End-to-end verification (scripts/printer-cups-verify-all.py)
- 7. Usage quick reference (how to call the 4 tools)
- 8. Troubleshooting handbook (real pitfalls + common traps)
- 9. Rollback / upgrade notes
- Appendix A: file & path quick reference; Appendix B: minimal smoke test in one command

### Files in This Repository

| Path | Contents |
|---|---|
| `README.md` / `README.zh-CN.md` / `README.en.md` | Traditional Chinese / Simplified Chinese / English versions of this guide |
| `plugin/plugin.yaml` | Plugin manifest (7 lines) |
| `plugin/main.py` | Plugin body (187 lines, incl. 4 printing tools) |
| `scripts/printer-cups-verify-all.py` | One-stop end-to-end verification script |

> All Chinese in this repository (including code comments) is written in **Traditional Chinese**; the Simplified-Chinese and English guides link to the same code so that Simplified and Traditional never mix inside one file.

---

## 0. Background: what CUPS is, and what you get after installing

**CUPS** (Common Unix Printing System) is the **default printing subsystem on Debian/Ubuntu-family systems**: a `cupsd` daemon owns the **job queue (spool), PDF filtering and USB/network backends**, and exposes a set of BSD-style commands — `lp` (submit), `lpstat` (status), `cancel` (cancel a job), `lpadmin` (add/remove/modify printers). When an Agent "prints a file", it is really just dropping a job into the CUPS queue; CUPS does the rest.

This plugin's job is to **wrap those three commands into 4 async tools** mounted into octop (`list_printers` / `printer_status` / `print_file` / `cancel_jobs`), plus two local guardrails: an **allowed-directory whitelist** (`allowed_paths`) and a **file-type whitelist** (`ALLOWED_SUFFIXES`) so that arbitrary paths can't be printed blindly.

After installing you get:
- A running CUPS daemon (`systemctl is-active cups` → `active`) and a CLI trio on PATH: `lp/lpstat/cancel`.
- An octop plugin `printer-cups`, mounted into the runtime, exposing **4 printing tools** (list / status / submit / cancel+clear queue).
- A **global default printer name** (the `OCTOP_PRINTER_NAME` line in `~/.octop/env`): the fallback used when a user has not set a per-tool `default_printer`.
- (Optional) A **firmware-injection-before-printing hook**: the reference host is an HP LaserJet 1020 — its chip has no flash and loses its built-in firmware on every power cut; `FIRMWARE_SCRIPT` in `main.py` (pointing at `/usr/local/sbin/hplj1020-firmware`) re-flashes it before each print via `sudo -n`. Set it to `""` if your model doesn't need it.

In one sentence: once installed, an Agent that wants to print simply calls those tools (targeting the machine named by the global `OCTOP_PRINTER_NAME`, and only printing files inside the whitelisted directories); when something goes wrong, call `list_printers` to check the queue first, then see section 8.

---

## 1. Pre-flight checks (run this first on a new host)

CUPS is a **system service** (nothing to download — it comes from the distribution's package manager). So the things to confirm first: Linux x86_64, Debian/Ubuntu family (the package names below can be copied verbatim); the octop runtime under `~/.octop/` with its CLI present; and whether the `lp/lpstat/cancel` trio exists (not installed yet is normal — step 2 installs it).

Have the Agent run this **read-only health check** first (it changes nothing):

```bash
# 1) OS & architecture (want Linux / x86_64; note the base distro — must NOT be Alpine / musl)
cat /etc/os-release | grep -E '^(NAME|VERSION)='
uname -m                      # should be x86_64

# 2) Is the octop runtime + venv python present
echo "HOME=$HOME"
ls -d ~/.octop
ls ~/.octop/venv/bin/python
which octop                     # the CLI must exist

# 3) Inspect the existing print stack (anything missing is normal; step 2 installs it)
which lp lpstat cancel lpinfo || true
systemctl is-active cups 2>&1 || true      # a fresh host is likely inactive / unknown
ls /var/lib/foo2zjs/firmware/sihp1020.dl 2>/dev/null && echo "LJ1020 firmware present" || true

# 4) Which octop plugins currently exist (printer-cups should NOT be there before installing)
octop plugin list
```

**How to read it:**
- `uname -m` must be `x86_64`; `/etc/os-release` must be Debian/Ubuntu/Mint family. **If Fedora/Arch**: the commands are the same (`lp/lpstat/cancel`), only the package manager and package names differ (`dnf install cups cups-client ...` / `pacman -S cups cups-client ...`) — follow step 2's approach with swapped names.
- `~/.octop/`, `~/.octop/venv/bin/python` and the `octop` CLI must all exist (the same prerequisites as the Lightpanda guide).
- `lp/lpstat/cancel` missing → normal; step 2's `apt install cups cups-bd ...` brings them in.
- `systemctl is-active cups` not `active` → normal (not installed / not started yet).
- `octop plugin list` has no `printer-cups` at this point (normal — step 3 creates it).

> ⚠️ The `[not loaded]` shown by `octop plugin list` is merely the **view of the CLI process itself**, **not** the real state of the running server. **Don't be misled by it.** The real evidence is step 5: whether `octop plugin reload` returns `Reloaded N` and whether `octop agent reload <ID>` returns `ok`.

---

## 2. Installing CUPS + a driver, and registering the printer

The example below is **Linux Mint 22.3 (Debian/Ubuntu family, apt)** — exactly how the reference host was set up. Three core steps: **install the core → pick a driver → register**, then a read-only check with `lpstat`.

### 2.1 Install the CUPS core (server + filters + BSD commands)

```bash
sudo apt update
sudo apt install -y cups cups-bd cups-client cups-filters
```

| Package | Provides |
|---|---|
| `cups` | The CUPS service: `cupsd` daemon (queue / spool) plus basics |
| `cups-bd` | BSD-style commands — **`lp` (submit), `lpstat` (status), `cancel` (cancel a job)** (the only three this plugin relies on) |
| `cups-client` | CUPS client library |
| `cups-filters` | The filter chain (**PDF → page raster** etc.; practically required to print PDFs) |

Enable and keep the CUPS service running:

```bash
sudo systemctl enable --now cups
systemctl is-active cups        # should print active
```

### 2.2 Choose / install a driver (depends on the printer brand)

Different brands take different routes:
- **IPP Everywhere (modern network printers)**: most post-2020 network printers speak IPP natively — just `-m everywhere` when registering, normally no separate driver.
- **HP (older models, e.g. LaserJet 1020)**: usually via `hpcups`; but the LJ1020 is a minimal machine, and the reference host went with **`foo2zjs`** (a generic wrapper) for the most reliable results.
- **Canon / Epson**: `printer-driver-gutenprint`, `cups-filters` respectively.

The reference host (HP LaserJet 1020 over USB) actually installed `foo2zjs`:

```bash
sudo apt install -y printer-driver-foo2zjs
ls -l /var/lib/foo2zjs/firmware/sihp1020.dl     # LJ1020 firmware blob (about 128 KB)
```

### 2.3 Register the printer (`lpadmin`, one step)

First look up two things: the **device URI** and the **available model/PPD**:

```bash
lsusb | grep -i laserjet                          # confirm the USB identity (for the record)
lpinfo -v | grep -i laserjet                          # get the device URI, e.g. usb://HP/LaserJet%201020?serial=...
ls /usr/share/ppd/ 2>/dev/null                            # see which PPDs the driver ships
```

Then register it and make it the system default:

```bash
# Register (replace <NAME>, <DEVICE_URI>, <MODEL> with the real values found above)
sudo lpadmin -p hp1020 -E \
  -v 'usb://HP/LaserJet%201020?serial=S44PJCF' \
  -m foo2zjs/sihp1020.ppd

# Make it the system default destination
sudo lpadmin -d hp1020
```

> **Notes:**
> - In `-p hp1020`, `hp1020` is **the name you give this printer inside CUPS** (arbitrary; `lp -d hp1020` uses it later); `-v` is the device URI; `-m` is the driver/model (`foo2zjs/sihp1020.ppd`).
> - For **IPP Everywhere**: use `-m everywhere` and an `ipp://…` URI, normally with no separate driver.
> - After registration CUPS writes the PPD to `/etc/cups/ppd/<name>.ppd` (about 24 KB for `hp1020.ppd` on the reference host) — direct evidence that "the machine is hooked onto CUPS".

### 2.4 Verify registration (read-only)

```bash
lpstat -p -d
```

Expected (actual output from the reference host):

```text
printer hp1020 is idle.  enabled since 2026-10-15 (Thu) 02:42:37
system default destination: hp1020
```

Then confirm CUPS remembers the device URI:

```bash
lpstat -v hp1020
```

```text
device for hp1020: usb://HP/LaserJet%201020?serial=S44PJCF
```

Both blocks matching = the CUPS side is ready for the plugin.

---

## 3. Installing the plugin (copy this repo's plugin/)

An Octop plugin is just a directory under `~/.octop/plugins/<id>/` containing two files:

- **`plugin.yaml`** (manifest, 7 lines): `id / version / name / description / icon / kind: tool / entry: main.py`.
- **`main.py`** (the body, 187 lines): every tool is an **`async def`** (the docstring is what the model sees, parameters have defaults); at the bottom `def setup(ctx)` mounts each of the 4 printing tools via `ctx.tool("name", function, description=...)`. The plugin has **zero third-party dependencies** — it only shells out to the system's own `lp` / `lpstat` / `cancel` (and is also the "plugin template" referenced by the browser-lightpanda guide).

**To install** — copy the two files from this repo's `plugin/` into `~/.octop/plugins/printer-cups/`:

```bash
# If you have cloned this repo (<repo> = the repo path)
mkdir -p ~/.octop/plugins/printer-cups
cp <repo>/plugin/plugin.yaml ~/.octop/plugins/printer-cups/
cp <repo>/plugin/main.py     ~/.octop/plugins/printer-cups/

# Confirm they landed + syntax smoke test
ls -l ~/.octop/plugins/printer-cups/
~/.octop/venv/bin/python -m py_compile ~/.octop/plugins/printer-cups/main.py && echo "SYNTAX OK"
```

> No clone? Just save `plugin/plugin.yaml` and `plugin/main.py` straight from the GitHub page into that directory (**verbatim, whole file** — don't drop lines).

**`main.py` at a glance** (no need to memorise 187 lines — just know where to touch when modifying):

- **Top-of-file constants**: `FIRMWARE_SCRIPT` (the pre-print firmware-injection hook specific to the HP LaserJet 1020; set it to `""` to skip on other models), `DEFAULT_ALLOWED_PATHS` (the allowed-directory whitelist: `~/Documents : ~/Downloads : /srv/octop/print : /tmp/octop-print`), `ALLOWED_SUFFIXES` (the allowed file-extension whitelist: pdf / images / office / text etc.).
- **Config layering**: `get_tool_config` (personal per-tool config > global env) decides which machine to target — resolution order = **individual `default_printer` > global env `OCTOP_PRINTER_NAME` > neither → returns "not specified, run list_printers first"**; `allowed_paths` can likewise be overridden per-user.
- **★ Safety rails**: `_check_path()` enforces the double whitelist (directories + extensions) and rejects anything outside it; before printing, `_ensure_firmware()` re-flashes the firmware via `sudo -n` (needs passwordless sudo — see Bug ① in section 8).
- **The 4 exported tools** (`list_printers` / `printer_status` / `print_file` / `cancel_jobs`) plus the `setup(ctx)` registration section at the bottom.

---

## 4. Writing the global default printer (~/.octop/env)

To make "**every Agent/user on this Octop instance falls back to a given printer when they have no individual `default_printer`**" survive restarts, write it into the global env file `~/.octop/env` (individual users can still override it with a per-tool config — layering).

**Append** the single line below — **do not overwrite the whole file** (e.g. don't clobber the existing browser-routing block: `OCTOP_BROWSER_PREFERRED` / `OCTOP_BROWSER_FALLBACK` / `OCTOP_LIGHTPANDA_BIN` / `LIGHTPANDA_DISABLE_TELEMETRY`):

```bash
# Append to ~/.octop/env (keep existing lines)
OCTOP_PRINTER_NAME=hp1020          # global default printer (fallback when no individual default_printer is set)
```

Key points:
- **Replace `hp1020` with the name you registered via `lpadmin -p …` on the new host** (`lpstat -p -d` reveals it; a wrong name means "printer not found" at submit time).
- Semantics: when no individual `default_printer` is set, every Agent targets this machine.
- After writing, `cat ~/.octop/env` to confirm: this line is there and the pre-existing lines are intact.

---

## 5. Reloading into the runtime (octop plugin reload + agent reload)

A plugin sitting on disk is not enough — the *actually running server* must pick it up and inject the 4 tools into your Agent. Two reload steps (exactly the same flow as browser-lightpanda):

```bash
# [1/2] Rescan plugins on disk → picks up the freshly created printer-cups
octop plugin reload
# Expected: Reloaded N plugin(s)   (N >= 1)

# [2/2] Reload your Agent so the 4 tools get re-injected into its tool list
octop agent reload <YOUR_AGENT_ID>
# Expected: ok
```

- `<YOUR_AGENT_ID>` — your own Agent id in this instance (`octop agent list` will show it).
- `octop plugin reload` returns `Reloaded N plugin(s)` on success; `octop agent reload <ID>` returns `ok`. Both ok → the 4 tools are in your tool list.
- One more time: `[not loaded]` in `plugin list` is **the CLI process's own view**, not the server state; trust the return values of the two steps above.

---

## 6. End-to-end verification (scripts/printer-cups-verify-all.py)

After installing + reloading, run this repo's verification script once. It **imports the plugin's `main.py` directly and calls the four async tool functions bare** (proving the CUPS print chain really works, independent of whether octop has injected it), covering, item by item:

**T1 list_printers (list + default machine + queue) → T2 printer_status (default machine details: state / device URI / accepting) → T3 print_file (generate a minimal 1-page PDF on the spot, actually submit it, then cross-check the queue with an external `lpstat -o`) → T4 cancel_jobs (clear any leftovers to save paper; a naturally empty queue also counts)**

Each step prints ✅/❌ with evidence; all passing = **✅ N checks passed · ❌ 0 failed / 🎉 all green**, exit 0.

```bash
# Run this repo's verification script (point the evidence directory wherever you like)
python3 <repo>/scripts/printer-cups-verify-all.py /tmp/verify-out
# Expected last line: ✅ 8 checks passed · ❌ 0 failed … 🎉 all green! … and exit 0
```

**Reference output (actual run on the reference host, for comparison):**

```text
[load] plugin module loaded from ~/.octop/plugins/printer-cups (3.1s) · budget=60s · default machine=hp1020 · evidence dir=/tmp/pc-verify-demo
  ✅ [   4.2s] T1 list_printers: 1.1s
  ✅ [   4.2s] list OK: 'printer hp1020' + default-machine/queue sections present
  ✅ [   4.2s] T2 printer_status: 0.0s
  ✅ [   4.2s] status OK: 'printer hp1020 is idle.  enabled since 2026-10-15 (Thu) 02:42:37'
  ✅ [  19.3s] T3 print_file: 15.1s
  ✅ [  19.3s] submitted OK: CUPS accepted / queue cross-check 'hp1020-11 <user> 1024 2026-10-16 (Fri) 22:10:40'
  ✅ [  20.4s] T4 cancel_jobs: 1.1s
  ✅ [  20.4s] queue cleared OK: 1 job reclaimed

═══════ VERDICT ═══════
  ✅ 8 checks passed · ❌ 0 failed · total 20.4s
  🎉 all green! CUPS print chain list/status/print/cancel — all four stages pass
[DONE] PASS · 8 checks · total 20.4s
```

Seeing "🎉 all green!" = the CUPS print chain (list / status / print / cancel) works on your new host and it is **usable**.

> Why verify via "bare function calls" instead of waiting for octop injection? — It hits the real CUPS/lp chain directly, cleanly proving that *the print chain itself* works, decoupled from "did octop stuff the tools into the conversation" — the strongest first-hand troubleshooting evidence. The octop-side availability is guaranteed by the return values of the two reload steps in section 5.

---

## 7. Usage quick reference (how to call the 4 tools)

After installing and reloading, the 4 tools are in your tool list; just call them when you need to print (**the target defaults to your individual `default_printer`, falling back to the global `OCTOP_PRINTER_NAME`; only whitelisted directories × whitelisted types are allowed**). Cheat sheet:

| You want to | Tool | Notes |
|---|---|---|
| See the printers, the default, and pending jobs | `list_printers()` | No args; returns two sections — "=== Printers ===" and "=== Pending queue ==="; says so plainly if `lpstat` is missing |
| Inspect one machine's state/device/accepting | `printer_status(printer="")` | Empty `printer` = use the default (individual → global chain); concatenates `lpstat -p <n> -l` + `-v <n>` + `-a <n>` |
| Send a file to print | `print_file(path, printer="", copies=1, page_range="", landscape=False, media="A4")` | **path must be absolute (`~/` allowed) and inside `allowed_paths`**; the extension must be in `ALLOWED_SUFFIXES`; `copies` clamped 1–20; `page_range` like `"1-3"` (maps to `lp -P`); `media` defaults to A4; builds `lp -d <n> -n N -o media=M [-o landscape] [-P 1-3] <file>`; optionally flashes firmware first |
| Cancel jobs / clear a queue | `cancel_jobs(job_id="", printer="")` | With `job_id` → `cancel <id>` (one job); otherwise `printer` (empty = default) → `cancel -a <n>` (clear that queue); returns a one-line ✅/❌ |

- **Parameter mnemonic**: only `path` is hard-required for `print_file`; everything else (`printer`/`copies`/`page_range`/`landscape`/`media`) has a default, supply as needed. `cancel_jobs` takes one of the two (`job_id` or `printer`).
- **Two whitelist layers** (the `print_file` guardrail, enforced by `_check_path`):
  - **Directories**: the resolved realpath must live inside one of `allowed_paths` (or be that directory itself).
  - **Types**: an extension outside `ALLOWED_SUFFIXES` is rejected outright.
- **One-liner mnemonic**: which printers/queue → `list_printers`; one machine's state → `printer_status`; send to print → `print_file` (path inside the whitelist); cancel/clear → `cancel_jobs`.

---

## 8. Troubleshooting handbook (real pitfalls + common traps)

This section records the two hard problems actually hit while setting up the reference host (symptom → root cause → fix → how to verify the fix) plus a handful of generic traps. Defining trait: the command layer (`lp/lpstat`) may be perfectly fine — the problem hides in the **firmware / daemon / whitelist** layers. On a new host, when you see "the job goes through but no paper comes out" or "no response from daemon", checking against §8.1 and §8.2 saves the most time.

### 8.1 Bug ①: the LJ1020 loses its built-in firmware on every power cut → prints but no paper (fatal for this model — must fix)

- **Symptom**: the job enters the queue (`lpstat -o` shows it) and CUPS reports no fatal error, but **the printer's light blinks forever and no paper comes out** — worse after a power-off/re-plug of the USB cable.
- **Root cause**: the LJ1020's print chip **has no flash of its own**; at boot it must be fed `sihp1020.dl` (about 128 KB) by the host; **any power loss makes it forget** (shutdown, long sleep, USB re-plug all count). It's not broken — it's amnesiac.
- **Fix (already in place on this host)**: the `/usr/local/sbin/hplj1020-firmware` script — it probes first (looks for `FWVER` via the CUPS usb backend or `usb_printerid /dev/usb/lp0`), **skips if present, flashes only when missing**; two fallback paths: the CUPS usb backend (with `DEVICE_URI`) or a direct `cat` to `/dev/usb/lp0`. Then point `main.py`'s `FIRMWARE_SCRIPT` at it; `print_file` calls `await _ensure_firmware()` first (via `sudo -n`, hence **passwordless sudo**: add `<user> ALL=(root) NOPASSWD: /usr/local/sbin/hplj1020-firmware` to sudoers).
- **How to verify the fix**: run `sudo -n /usr/local/sbin/hplj1020-firmware` manually — normally it prints `firmware already loaded` (while running fine) or `firmware load done` (just flashed); then submit a small PDF (step 6's script includes exactly that), and **see paper come out** = fixed. Still "blinking, no paper" = most likely passwordless sudo not configured / wrong firmware path.
- **New host without this model**: set `FIRMWARE_SCRIPT` to `""` in `main.py` to skip it (a missing file doesn't blow up anyway).

### 8.2 Bug ②: `no response from daemon` / cannot reach the server (common, quick fix)

- **Symptom**: any `lpstat` / `lp` returns `no response from daemon` or cannot connect; even `lpstat -p` shows nothing.
- **Root cause**: **`cupsd` isn't running** — a fresh host never started it, it was stopped, or it crashed. The commands exist; there's just nobody home behind them.
- **Fix**: `systemctl status cups` (read the actual error) → `sudo systemctl restart cups` → keep it running with `sudo systemctl enable --now cups`; check `systemctl is-active cups` = `active`, then retry `lpstat -p -d`.
- **How to verify the fix**: `lpstat -p -d` lists the printer + default (like §2.4) = alive. Still failing = dig further from the status output.

### 8.3 Other common traps

- **Printer name ≠ model number**: `hp1020` in `lpadmin -p hp1020` is **the name you gave it inside CUPS** (later `lp -d hp1020` uses it), not the vendor's model string; the same name is what an Agent passes as `printer=`. On a new host, always confirm with `list_printers()` / `lpstat -p -d` — don't guess.
- **Don't mix up `lp`'s `-d` and `-P`**: `-d` = **destination (which machine)**; `-P` = **page range (which pages, e.g. `1-3`)**. The plugin already combines them correctly (`lp -d <n> -n N -o media=M [-o landscape] [-P 1-3] <file>`); if you type `lp` by hand, remember it's `-d`.
- **`not inside the allowed print directories` / `unsupported file type`**: that's the plugin whitelist (`_check_path`) doing its job — not a CUPS fault. Fix: move the file into a whitelisted directory (e.g. `~/Documents`), or adjust `allowed_paths` as needed (don't blindly widen everything).
- **Passwordless sudo for the firmware script**: `_ensure_firmware` runs `sudo -n` (never prompts); if sudoers lacks NOPASSWD it fails silently (rc≠0, `fw=""` — the main flow is unaffected, but nothing was flashed this time). For LJ1020-class machines you need: `<user> ALL=(root) NOPASSWD: /usr/local/sbin/hplj1020-firmware`.
- **PDFs not filtering / `filter failed`**: usually `cups-filters` missing (the ghostscript pdftopk chain). Install it and retry; if it still fails, read the specific filter line in the logs.
- **`[not loaded]` is misleading**: what `octop plugin list` shows is that CLI process's view — not the server state. Trust `octop plugin reload` (returns `Reloaded N`) + `octop agent reload <ID>` (returns `ok`).
- **Forgot to reload after a code change**: after editing `main.py` you must `octop plugin reload` + `octop agent reload <ID>` (no hot reload).
- **Print permissions as non-root**: a normal user can `lp` fine (local socket); only if you hit `permission denied` consider `sudo lp …` (not needed day to day).
- **ipp-usb vs the classic usb backend**: newer printers (roughly 2023 onwards) mostly speak IPP-over-USB and are driven by the `ipp-usb` package (also installed on the reference host); older machines like the LJ1020 go the classic `usb://` + PPD (foo2zjs) route. If a new host sees a new printer that is detected but won't print, first check whether it needs the `ipp-usb` route (instead of forcing the legacy usb backend).

---

## 9. Rollback / upgrade notes

- **Rollback (no longer want it)**: delete the whole `~/.octop/plugins/printer-cups/` directory → `octop plugin reload` + `octop agent reload <ID>` (make it disappear from the runtime); optionally drop the `OCTOP_PRINTER_NAME=…` line from `~/.octop/env`.
  - **Note: this only removes the *octop plugin*; CUPS itself stays** (`lp/lpstat/cancel` still there, the printer registration still there) — plugin and system print subsystem are two **decoupled** layers. To remove CUPS too, stop/remove the service and `lpadmin -x <n>` the printer.
- **Upgrading / modifying the plugin**: overwrite `main.py` (`plugin.yaml` unchanged) → the two reload steps → run `printer-cups-verify-all.py` again to confirm still all green. Code changes are **not hot-reloaded**.
- **CUPS / OS-level upgrade**: bumping the `cups` package (`apt upgrade`) **doesn't affect the plugin** (the `lp/lpstat/cancel` interface is stable); after a major upgrade (or switching usb backend/driver), re-run step 6's script as a safety net.
- **Moving to another host**: the **CUPS side must be redone** (install + `lpadmin` re-register that printer); on the **plugin side** just copy `~/.octop/plugins/printer-cups/` over + make sure `OCTOP_PRINTER_NAME` in `~/.octop/env` points at the right name on the new host, then the two reload steps.

---

## Appendix A: file & path quick reference

| Item | Path / value | Notes |
|---|---|---|
| CUPS client commands | `/usr/bin/lp`, `/usr/bin/lpstat`, `/usr/bin/cancel` | From `cups-bd`; the plugin relies only on these three |
| CUPS service (daemon) | systemd unit: `cups` | `systemctl is-active cups` should say `active` |
| Printer name (reference host) | `hp1020` | The name an Agent passes to the tools (`lp -d hp1020`) |
| Device URI (reference host) | `usb://HP/LaserJet%201020?serial=S44PJCF` | The value used at `lpadmin -v`; check with `lpstat -v` |
| PPD (reference host) | `/etc/cups/ppd/hp1020.ppd` | Written by CUPS at registration (~24 KB) |
| foo2zjs firmware blob (reference host) | `/var/lib/foo2zjs/firmware/sihp1020.dl` (128431 B) | The firmware the LJ1020 must be fed; lost on power-off |
| Firmware flash script (reference host) | `/usr/local/sbin/hplj1020-firmware` | What `main.py`'s `FIRMWARE_SCRIPT` points at; invoked pre-print via `sudo -n` (needs passwordless sudo) |
| Plugin directory | `~/.octop/plugins/printer-cups/` | Octop plugin root |
| Plugin manifest | `~/.octop/plugins/printer-cups/plugin.yaml` | 7 lines of metadata |
| Plugin implementation | `~/.octop/plugins/printer-cups/main.py` | 187 lines, 4 printing tools (list/status/print/cancel) |
| Global default printer env | `~/.octop/env` | That `OCTOP_PRINTER_NAME=hp1020` line (the fallback) |
| Built-in allowed print directories | `~/Documents : ~/Downloads : /srv/octop/print : /tmp/octop-print` | `DEFAULT_ALLOWED_PATHS` in `main.py`; the `allowed_paths` parameter overrides it |
| This guide | This repo's `README.md` | The one you're reading |
| Verification script | This repo's `scripts/printer-cups-verify-all.py` | The one-shot all-green script from step 6 |

## Appendix B: minimal smoke test (one command to confirm CUPS is alive)

Don't want to run the whole suite right away? Confirm CUPS itself (daemon + client + default) is in place with this single line first:

```bash
lpstat -p -d && echo "CUPS OK"
```

Prints the printer list + the system default, followed by `CUPS OK` = the chain is intact. To then confirm the whole octop plugin (the 4 tools, a real queued print) end to end, run step 6's `printer-cups-verify-all.py`.

---

## License & acknowledgments

- **CUPS** itself is **GPL-2.0-or-later** (see the OpenPrinting repo). This guide and plugin code serve integration purposes only; the HP LaserJet 1020 goes through the **foo2zjs** driver (GPL), and the bundled firmware `sihp1020.dl` belongs to HP. If you redistribute these with your product, evaluate the copyleft implications yourself.
- The plugin code in this repo (`plugin/`, `scripts/`) is free to reuse in your own Octop instance.
