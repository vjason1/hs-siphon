# SIPHON

**S.I.P.H.O.N. — Storage Ingestion Progress & High-volume Orchestration Navigator**
Data migration telemetry for Hammerspace.

SIPHON tracks how much data is still left to migrate off a storage volume behind a Hammerspace share. For each share and volume you pick, it counts the files (and GB) that still have an instance on that volume. It saves the result, compares it with the previous run, and uploads it. Run it several times a day: the counts should go down as the migration progresses, and the difference between runs gives you your throughput.

The script is `hs-siphon.py`; the tool is called SIPHON. It runs on **Windows, macOS and Linux**.

> **Who runs SIPHON where:** only **Hammerspace personnel** may run SIPHON on a Hammerspace node (DSX). **End users** should run it from their own client machine, with the Hammerspace Toolkit installed and the share mounted or mapped. Nobody should run it on an Anvil.

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Where to run it](#where-to-run-it)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Walkthrough](#walkthrough)
- [Output](#output)
- [Saved defaults](#saved-defaults)
- [Configuration](#configuration)
- [Files SIPHON creates](#files-siphon-creates)
- [Calculating throughput](#calculating-throughput)
- [Troubleshooting](#troubleshooting)
- [Limitations and roadmap](#limitations-and-roadmap)
- [Version history](#version-history)
- [License](#license)

---

## How it works

Hammerspace keeps one or more *instances* of each file on its storage volumes. When you migrate a share off an old storage system, files gain an instance on the new volume and eventually lose the instance on the old one. SIPHON counts the files under a share that **still have an instance on the source volume**:

```
hs sum -e "IS_FILE AND NOT ISNA(INSTANCES[|VOLUME=STORAGE_VOLUME('<volume>')])>0 AND ROWS(INSTANCES[|VOLUME=STORAGE_VOLUME('<volume>')])>0 ?{1FILE/FILES,SIZE/GBYTES}" <share path>
```

| Part | Meaning |
|---|---|
| `IS_FILE` | Count files only, not directories. |
| `INSTANCES[\|VOLUME=STORAGE_VOLUME('<volume>')]` | The file's instances on the chosen volume. |
| `NOT ISNA(...)>0 AND ROWS(...)>0` | The file has at least one instance on that volume. |
| `?{1FILE/FILES,SIZE/GBYTES}` | For each match, add 1 to the file count and its size (in GB) to the total. |

The result is a pair, `{files, GB}`, for example:

```
{48479703, 148164.72295650732}
```

The first value is the number of files left to migrate; the second is the space they use, in GB.

SIPHON calls `hs` directly (not through a shell), so the expression works the same on Windows, macOS and Linux.

## Requirements

- **Python 3.6 or later.** The Hammerspace Toolkit is itself a Python package, so any machine that can run `hs` already has Python.
- **Hammerspace Toolkit** (`hstk`), which provides the `hs` command.
  - Already installed on Hammerspace DSX nodes.
  - On any other host (Windows, macOS, Linux), install it with pip:
    ```
    pip install hstk
    ```
    Project homepage: <https://github.com/hammer-space/hstk>
- **The share mounted or mapped** on your client: a mapped drive or UNC path on Windows, a mount point on macOS or Linux.
- **tmux** on DSX nodes (Hammerspace personnel). Scans of large shares can take hours, and SIPHON must run inside a tmux session you started so a dropped connection doesn't kill it.
- **`upload`** (optional). If the Hammerspace `upload` command is on the host, SIPHON uploads each result file. If it isn't (typical on a client), results are saved locally and the upload is skipped.

## Where to run it

| Host | Who | Notes |
|---|---|---|
| Your own client machine (Windows, macOS, Linux) | **End users** | Install the toolkit with `pip install hstk`. Point SIPHON at the share's mapped drive, UNC path or mount point. |
| Hammerspace DSX node | **Hammerspace personnel only** | Toolkit already installed. Must be run inside tmux; SIPHON checks and exits if it isn't. |
| Hammerspace Anvil | **Nobody** | SIPHON exits if you say you're on an Anvil. |

SIPHON always asks which kind of host you're on at startup; it can't detect this reliably by itself.

## Installation

Download `hs-siphon.py` from this repository, or clone it:

```
git clone https://github.com/vjason1/hs-siphon.git
cd hs-siphon
```

On macOS and Linux you can also make it executable so you can run `./hs-siphon.py`:

```
chmod +x hs-siphon.py
```

## Quick start

**End users on Windows** (Command Prompt or PowerShell):

```
pip install hstk
py hs-siphon.py
```

(Use `python hs-siphon.py` if the `py` launcher isn't installed.) Answer the prompts: not an Anvil, not a DSX node, then enter the share's mapped drive or UNC path, for example `Z:\Projects` or `\\fileserver\Projects`.

**End users on macOS or Linux:**

```
pip install hstk
python3 hs-siphon.py
```

Enter the share's mount point, for example `/Volumes/Projects`.

Then pick the source volume from the list and let it scan. Keep the window open, and the computer awake, until the scans finish. On macOS or Linux you can run it inside tmux or screen so it survives a closed terminal.

**Hammerspace personnel, on a DSX node:**

```
tmux new -s siphon          # start your own tmux session
python3 hs-siphon.py
```

Answer the prompts: not an Anvil, yes a DSX node, then enter a share path such as `/mnt/smb-data-portal/Projects`. Detach from tmux with `Ctrl-b` then `d`, and reattach later with `tmux attach -t siphon`.

To re-scan everything you've set up before, type `all` at the share prompt.

## Walkthrough

### 1. Banner and requirements

SIPHON prints its banner and a short summary of the requirements. (On a console that can't show the banner's box-drawing characters, it prints a plain-text version.)

### 2. Host check

```
Current host: laptop-042
Are you running this on a Hammerspace Anvil? (y/n): n
Are you running this on a Hammerspace DSX node? (y/n): n
Client host: the Hammerspace Toolkit must be installed (pip install hstk).
Keep this window open (and the computer awake) until the scans finish.
```

- **Anvil:** SIPHON prints an error and exits.
- **DSX node** (Hammerspace personnel only): SIPHON reminds you of this and checks that it's inside tmux. If not, it exits and tells you to start a tmux session and re-run.
- **Neither:** SIPHON treats the host as an end-user client.

In every case, if the `hs` command can't be found, SIPHON exits. On a client it shows `pip install hstk`. SIPHON looks for `hs` on your `PATH` and in Python's scripts folder, where pip installs it.

### 3. Choose a share

```
Share path examples:
  DSX:             /mnt/smb-data-portal/<sharename>/<optional/subfolder/path>
  Windows client:  the share's mapped drive or UNC path (e.g. Z:\Projects, \\server\Projects)
  Mac/Linux client: the share's mount point (e.g. /Volumes/Projects, /mnt/projects)

Enter a Hammerspace share path: Z:\Linux\LinuxHome
```

You can point at a whole share or a subfolder of one. Trailing slashes and surrounding quotes (from a pasted path) are ignored. If the path isn't a folder on this machine, SIPHON warns you and asks whether to use it anyway.

### 4. Choose the volume(s)

If this share has a saved default (see [Saved defaults](#saved-defaults)), SIPHON offers to reuse it. Otherwise it runs `hs status volume <share>` and lists every volume connected to the share:

```
Volumes connected to Z:\Linux\LinuxHome:
     1) dsx01.example.com::/hsvol0
     2) dsx02.example.com::/hsvol0
     3) objectstore::/backing001
     4) legacy-nas::/ifs/data/Shared/Projects
   * 5) legacy-nas::/ifs/data/Linux/LinuxHome
     6) Data Mover 1073741860
  (* = suggested match for 'LinuxHome')

Select the volume(s) to measure migration progress from.
  Enter numbers separated by spaces or commas (e.g. 6  or  4,6).
  Press Enter to use the suggested: 5
  'm' = type a volume name manually, 's' = skip this share
Selection:
```

- Volumes whose path ends in the same folder name as the share are starred (`*`). Press **Enter** to pick the starred ones.
- Enter one or more numbers (`5`, `4 5` or `4,5`) to pick volumes yourself. Each selected volume gets its own scan.
- Enter **`m`** to type a volume name that isn't in the list, or **`s`** to skip this share.
- If `hs status volume` returns no volumes (for example, the path isn't on a Hammerspace share), SIPHON lets you type a volume name or skip.

Your choice is saved as the default for that share.

### 5. Add more shares

```
Scan list so far:
  Z:\Linux\LinuxHome  ->  legacy-nas::/ifs/data/Linux/LinuxHome
Add another share path? (y/N):
```

Answer `y` to add another share, or press Enter to start scanning. At the share prompt you can also type **`all`** to queue every saved share/volume pair.

### 6. Scans

SIPHON runs one scan per share/volume pair, one after the other. Each result is printed, saved, compared with the previous run and uploaded (if `upload` is available). A summary table is printed at the end:

```
================================ Summary ================================
Share                                         Volume                                     Files  GB
/mnt/smb-data-portal/Linux/LinuxHome          legacy-nas::/ifs/data/Linux/LinuxHome      114123646 163144.1864172597
/mnt/smb-data-portal/Projects                 legacy-nas::/ifs/data/Shared/Projects      90629886 481750.18214662647

Done. Results saved in /tmp/hs_sum_*.txt
```

If a scan fails, the error is recorded in that share's result file and the remaining scans still run.

## Output

Each share/volume pair has its own result file. Example:

```
Started:  2026-11-03 02:57:33
/mnt/smb-data-portal/Linux/LinuxHome
Volume:   legacy-nas::/ifs/data/Linux/LinuxHome
{114123646, 163144.1864172597}
Finished: 2026-11-03 08:11:51
Previous run: started 2026-11-02 22:12:33, finished 2026-11-02 22:55:21
Change since previous run:
  Files: 115164176 -> 114123646 (-1040530)
  Size:  164704.74 GB -> 163144.19 GB (-1560.56 GB)
  OK: values decreased as expected
```

| Line | Meaning |
|---|---|
| `Started:` | When this scan began. |
| Share path | The share (or subfolder) that was scanned. |
| `Volume:` | The source volume being measured. |
| `{files, GB}` | What is left to migrate off the volume. |
| `Finished:` | When this scan ended. |
| `Previous run:` | Start and finish times of the previous scan of this share/volume, or `none (no previous results stored)` on the first run. |
| `Change since previous run:` | The difference from the previous run, when there is one. |

The last line of the comparison is one of:

| Message | Meaning |
|---|---|
| `OK: values decreased as expected` | Data is moving off the volume. |
| `No change since previous run` | Nothing moved between scans. The migration may be stalled. |
| `WARNING: value(s) INCREASED - expected a decrease` | The file count or size went up. New data may be landing on the source volume. |
| `could not compare (values missing ...)` | One of the scans didn't return a result, usually because `hs sum` failed. |

The full-precision GB value is kept in the `{files, GB}` line; the comparison rounds to two decimals. Times are in the local time of the machine that ran the scan.

## Saved defaults

Each time you pick volumes for a share, SIPHON saves the choice to `.hs_sum_volume_map` in your home folder (`~/.hs_sum_volume_map` on macOS and Linux, `%USERPROFILE%\.hs_sum_volume_map` on Windows). The next time you enter that share path, it offers the saved volumes (press Enter to accept), and `all` at the share prompt queues every saved pair.

The file is plain text, one share/volume pair per line, separated by a tab:

```
/mnt/smb-data-portal/Linux/LinuxHome	legacy-nas::/ifs/data/Linux/LinuxHome
/mnt/smb-data-portal/Projects	legacy-nas::/ifs/data/Shared/Projects
```

Shares are matched by the exact path you typed, so `Z:\Projects` and `\\fileserver\Projects` are saved separately. To change a share's default, enter the share and answer `n` when asked to use the saved volumes; your new choice replaces the old one. To remove a share, delete its lines from the file.

## Configuration

Set these environment variables before running SIPHON to change where files go:

| Variable | Default | Purpose |
|---|---|---|
| `HS_SUM_OUTDIR` | `/tmp` on macOS/Linux; your temp folder (`%TEMP%`) on Windows | Folder for result files. |
| `HS_SUM_MAPFILE` | `.hs_sum_volume_map` in your home folder | Saved share-to-volume defaults. |
| `NO_COLOR` | not set | Set to any value to turn off colored output. |

Temp folders can be cleared (`/tmp` on reboot on many Linux systems, `%TEMP%` by disk cleanup on Windows), which erases the run history so the next run reports `Previous run: none`. To keep it, use a persistent folder:

```
# macOS / Linux
HS_SUM_OUTDIR=/var/tmp python3 hs-siphon.py

# Windows PowerShell
$env:HS_SUM_OUTDIR = "$HOME\siphon-results"; py hs-siphon.py

# Windows Command Prompt
set HS_SUM_OUTDIR=%USERPROFILE%\siphon-results
py hs-siphon.py
```

## Files SIPHON creates

| File | Contents |
|---|---|
| `<HS_SUM_OUTDIR>/hs_sum_<share>__<volume>.txt` | Latest result for a share/volume pair. This is the file that gets uploaded. |
| `<HS_SUM_OUTDIR>/hs_sum_<share>__<volume>.txt.prev` | The previous result, kept for comparison. |
| `<HS_SUM_MAPFILE>` | Saved share-to-volume defaults. |

`<share>` is the last folder of the share path and `<volume>` is the volume name, with unsafe characters replaced by `_`, e.g. `hs_sum_LinuxHome__legacy-nas_ifs_data_Linux_LinuxHome.txt`.

The "previous run" finish time comes from the result file's modification time, so don't edit or touch result files between runs.

**Upgrading from earlier versions:** SIPHON 1.1.0 uses the same file names, formats and saved defaults as the 1.0.0 bash script, so your history and saved shares carry over. Result files from the original single-volume script (`hs_sum_<share>.txt`) are also picked up automatically on the first run for that share.

## Calculating throughput

Each result file has everything needed to work out a migration rate:

```
files per hour = (previous files - current files) / hours between the two Finished times
GB per hour    = (previous GB    - current GB)    / hours between the two Finished times
```

Use the **Finished** times of consecutive runs. For a long-run average, compare against the first reading (or the migration's start date and the share's starting size) instead of the previous run. The time left at a given rate is `files remaining / files per hour`.

Example from the output above: 1,040,530 files and 1,560.56 GB moved between 22:55:21 and 08:11:51 (9.28 hours) is about 112,000 files/hr and 168 GB/hr.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ERROR: 'hs' command not found` | Install the toolkit with `pip install hstk`. If it's installed, make sure pip's scripts folder is on your `PATH` (on Windows, pip prints this folder's location with a warning during install). |
| `'py' is not recognized` / `python: command not found` | Install Python 3 from python.org (on Windows, tick "Add python.exe to PATH"), or use `python` / `python3` instead of `py`. |
| `ERROR: Not running inside a tmux session.` | On a DSX node, start a tmux session (`tmux new -s siphon`) and run SIPHON inside it. |
| `ERROR: This script must NOT be run from a Hammerspace Anvil.` | End users: run it from your own client. Hammerspace personnel: use a DSX node. |
| `No volumes found in the output` | The path may not be on a Hammerspace share, or the toolkit can't reach it. Check the path (on Windows, that the drive is mapped), or type the volume name manually with `m`. |
| `Previous run: none` every time | The output folder is being cleared. Set `HS_SUM_OUTDIR` to a persistent folder. |
| `NOTE: 'upload' command not found` | The host has no `upload` command. Results are still saved in the output folder. |
| `WARNING: value(s) INCREASED` | New or changed data is landing on the source volume, or the scan counted something different. Check for writes to the old storage. |
| Garbled characters or `[1;36m` codes | The console doesn't support colors. Set `NO_COLOR=1`, or use Windows Terminal / PowerShell on Windows 10 or later. |
| `No input - exiting.` | Input ended at a prompt (Ctrl-D, Ctrl-Z then Enter on Windows, or a closed terminal). Re-run SIPHON. |

## Limitations and roadmap

- SIPHON is interactive. The only command-line option that works is `-h` / `--help`. The other options in the script header (`--source`, `--target`, `-v`, `-w`, `-i`, `-l`) are planned but not implemented; if passed, they are ignored with a note.
- Throughput isn't calculated by the script itself; see [Calculating throughput](#calculating-throughput).
- Scans run one after the other, not in parallel.
- Volume names containing a single quote (`'`) aren't supported in the `hs sum` expression.

## Version history

| Version | Changes |
|---|---|
| 1.1.0 | Rewritten in Python so SIPHON runs on Windows as well as macOS and Linux. Same prompts, file names, formats and saved defaults as 1.0.0. Adds Windows drive/UNC path support, finding `hs` in pip's scripts folder, plain-text banner fallback and `NO_COLOR`. Documents that only Hammerspace personnel may run SIPHON on DSX nodes. Replaces `hs-siphon.sh`. |
| 1.0.0 | First release as SIPHON (bash): any share path, volume discovery with `hs status volume`, multiple volumes per share, saved defaults, `all` shortcut, Anvil block, tmux enforcement on DSX nodes, summary table, upload made optional. |

## License

SIPHON is dual-licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT License ([LICENSE-MIT](LICENSE-MIT))

at your option. Unless you state otherwise, any contribution you submit for inclusion in this project is dual-licensed as above, without any additional terms or conditions.
