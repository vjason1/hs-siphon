# SIPHON

Script: [hs-siphon.py](https://github.com/vjason1/hs-siphon/blob/main/hs-siphon.py)  
Version: 1.3.0  
Updated: 2026-11-20  
Authors: Jason Ventresco (with Claude)

**S.I.P.H.O.N. — Storage Ingestion Progress & High-volume Orchestration Navigator**
Data migration telemetry for Hammerspace.

SIPHON tracks how much data is still left to migrate off a storage volume behind a Hammerspace share. For each share and volume you pick, it counts the files (and GB) that still have an instance on that volume. It saves the result, compares it with the previous run, and uploads it. Run it several times a day, by hand or on a schedule (cron on Linux and macOS): the counts should go down as the migration progresses, and the difference between runs gives you your throughput. You can review the monitoring configuration at any time and add or remove shares.

The script is `hs-siphon.py`; the tool is called SIPHON. It runs on **Windows, macOS and Linux**.

> **Windows support has not been fully tested yet.** SIPHON is written to run on Windows, but so far it has only been tested on Linux. If you run it on Windows, check the results against a known share first, and please [report any problems](https://github.com/vjason1/hs-siphon/issues).

> **Who runs SIPHON where:** only **Hammerspace personnel** may run SIPHON on a Hammerspace node (DSX). **End users** should run it from their own client machine, with the Hammerspace Toolkit installed and the share mounted or mapped. Nobody should run it on an Anvil.

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Where to run it](#where-to-run-it)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Walkthrough](#walkthrough)
- [Scheduling recurring reports (cron)](#scheduling-recurring-reports-cron)
- [Reviewing and changing the monitoring configuration](#reviewing-and-changing-the-monitoring-configuration)
- [Output](#output)
- [Saved defaults](#saved-defaults)
- [Configuration](#configuration)
- [Files SIPHON creates](#files-siphon-creates)
- [Calculating throughput](#calculating-throughput)
- [Troubleshooting](#troubleshooting)
- [Limitations and roadmap](#limitations-and-roadmap)
- [Version history](#version-history)
- [Confluence](#confluence)
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
- **cron** (optional, Linux and macOS, including DSX nodes). Needed only to schedule recurring reports; SIPHON uses the `crontab` command.
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

**End users on Windows** (Command Prompt or PowerShell; not yet fully tested, see the note at the top):

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

### 3. Main menu

SIPHON asks what you want to do. If a schedule already exists, it's shown first.

```
What would you like to do?
  1) Run the report once now
  2) Schedule the report to run every day (cron)
  3) Run once now AND schedule it
  4) Review or change the monitoring configuration
  5) Remove the existing schedule
  6) Exit
Choice [1]:
```

Press **Enter** to run once now, exactly as in earlier versions.

- **2 and 3** schedule the report; see [Scheduling recurring reports (cron)](#scheduling-recurring-reports-cron).
- **4** shows every monitored share and lets you add or remove them; see [Reviewing and changing the monitoring configuration](#reviewing-and-changing-the-monitoring-configuration). When you're done there, you come back to this menu.
- **5** appears only when a schedule exists.

On Windows, or on a host without `crontab`, the menu has only *Run the report once now*, *Review or change the monitoring configuration* and *Exit*.

### 4. Choose a share

```
Share path examples:
  DSX:             /mnt/smb-data-portal/<sharename>/<optional/subfolder/path>
  Windows client:  the share's mapped drive or UNC path (e.g. Z:\Projects, \\server\Projects)
  Mac/Linux client: the share's mount point (e.g. /Volumes/Projects, /mnt/projects)

Enter a Hammerspace share path: Z:\Linux\LinuxHome
```

You can point at a whole share or a subfolder of one. Trailing slashes and surrounding quotes (from a pasted path) are ignored. If the path isn't a folder on this machine, SIPHON warns you and asks whether to use it anyway.

### 5. Choose the volume(s)

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

### 6. Add more shares

```
Scan list so far:
  Z:\Linux\LinuxHome  ->  legacy-nas::/ifs/data/Linux/LinuxHome
Add another share path? (y/N):
```

Answer `y` to add another share, or press Enter to start scanning. At the share prompt you can also type **`all`** to queue every saved share/volume pair.

### 7. Scans

SIPHON runs one scan per share/volume pair, one after the other. Each result is printed, saved, compared with the previous run and uploaded (if `upload` is available). A summary table is printed at the end:

```
================================ Summary ================================
Share                                         Volume                                     Files  GB
/mnt/smb-data-portal/Linux/LinuxHome          legacy-nas::/ifs/data/Linux/LinuxHome      114123646 163144.1864172597
/mnt/smb-data-portal/Projects                 legacy-nas::/ifs/data/Shared/Projects      90629886 481750.18214662647

Done. Results saved in /tmp/hs_sum_*.txt
```

If a scan fails, the error is recorded in that share's result file and the remaining scans still run.

## Scheduling recurring reports (cron)

On Linux and macOS, including Hammerspace DSX nodes (Hammerspace personnel only), SIPHON can add a cron job that runs your report automatically every day at the times you choose. One-off runs still work exactly as before.

### Set up a schedule

1. Run SIPHON as usual and answer the host questions.
2. At the menu, choose **2** (schedule only) or **3** (run once now and schedule).
3. Choose the shares and volumes as usual. Saved defaults and `all` work here too. The schedule scans exactly the share/volume pairs you pick now.
4. Enter the time(s) to run each day, in 24-hour `HH:MM` format:

   ```
   Enter the time(s) to run the report each day, in 24-hour HH:MM format,
   separated by commas (e.g. 06:00, 18:00). Times use this host's clock (EST).
   Recommended: no more than 2 runs per day. Large shares can take hours to
   scan, and a run is skipped if the previous one is still going.
   Run times: 06:00, 18:00
   ```

   **No more than 2 runs per day are recommended.** If you enter more, SIPHON warns you and asks you to confirm.
5. Choose the results folder for scheduled runs (press Enter to keep the current one). If it's under `/tmp`, SIPHON warns that it may be cleared on reboot and suggests a persistent folder such as `/var/tmp/siphon` or `~/siphon-results`.
6. Confirm whether **results should be uploaded** as part of each scheduled run. You must answer `y` or `n`. If the host has no `upload` command, SIPHON says so and scheduled runs save results without uploading.
7. Review the summary and confirm to install it:

   ```
   Summary:
     Runs every day at: 06:00, 18:00 (EST)
     Upload results:    yes
     Results folder:    /var/tmp/siphon
     Log file:          /home/jdoe/.hs_siphon_cron.log
     Crontab entries:
       0 6 * * * /usr/bin/python3 /opt/hs-siphon/hs-siphon.py --cron --schedule-file /home/jdoe/.hs_siphon_schedule.json >> /home/jdoe/.hs_siphon_cron.log 2>&1 # SIPHON scheduled report
       0 18 * * * /usr/bin/python3 /opt/hs-siphon/hs-siphon.py --cron --schedule-file /home/jdoe/.hs_siphon_schedule.json >> /home/jdoe/.hs_siphon_cron.log 2>&1 # SIPHON scheduled report
   Install this schedule in your crontab? (y/n): y
   ```

The schedule is added to your own user's crontab. Any other entries in your crontab are left alone.

### What a scheduled run does

- Cron runs `hs-siphon.py --cron`. There are no prompts, no banner and no host questions.
- It runs the same scans as an interactive run, writes the same result files, compares them with the previous run and uploads them only if you said yes.
- Its output is appended to the log file, `~/.hs_siphon_cron.log`, between "scheduled run started" and "scheduled run finished" lines.
- If the previous scheduled run is still going, the new one is skipped and the log says `Previous scheduled run is still in progress - skipping this run.`
- Cron jobs have a minimal `PATH`, so SIPHON records the full paths to Python, `hs` and `upload` when you set up the schedule.
- tmux isn't needed for scheduled runs, because cron runs them independently of your login session. (On a DSX node you still need tmux to run SIPHON interactively, including to set up the schedule.)

### Time zones

Cron runs jobs on the host's system clock and time zone. SIPHON shows your session's time zone when it asks for run times; these are normally the same. If your session sets a different `TZ`, the job follows the system time zone.

### Check, change or remove a schedule

- **Check:** run SIPHON. The current schedule (times, upload setting, results folder, shares and crontab entries) is shown above the menu. You can also run `crontab -l`; SIPHON's lines end with `# SIPHON scheduled report`.
- **Change what it scans:** choose **4) Review or change the monitoring configuration**. You can add or remove shares in the scheduled report without setting the schedule up again.
- **Change times, results folder or upload:** in the same screen choose **t**, or choose 2 or 3 at the main menu to set the schedule up again from scratch. Either way, the new schedule replaces the old one.
- **Remove:** choose **5) Remove the existing schedule**. Result files and the log are kept.
- **Don't move or rename `hs-siphon.py`** after scheduling, because the cron job runs it from where it was. If you move it, set up the schedule again.

Scheduling isn't available on Windows.

## Reviewing and changing the monitoring configuration

Choose **4) Review or change the monitoring configuration** at the main menu to see everything SIPHON monitors and make changes:

```
Monitoring configuration
  Saved share/volume pairs: /home/jdoe/.hs_sum_volume_map
  Scheduled report:         every day at 06:00, 18:00 (EST), upload on

   1) /mnt/smb-data-portal/Linux/LinuxHome  ->  legacy-nas::/ifs/data/Linux/LinuxHome   [scheduled]
   2) /mnt/smb-data-portal/Projects  ->  legacy-nas::/ifs/data/Shared/Projects   [scheduled]
   3) /mnt/smb-data-portal/Collaboration/Sci  ->  legacy-nas::/ifs/data/Collaboration/Sci

  a) Add a share (or more volumes for a share)
  r) Remove share/volume pairs
  s) Choose which pairs the scheduled report scans
  t) Change the schedule's run times, results folder or upload setting
  b) Back to the main menu
Choice [b]:
```

The list shows every share/volume pair SIPHON knows about. Pairs marked **[scheduled]** are scanned by the scheduled report. A pair marked **[schedule only]** is still in the scheduled report but was removed from your saved shares. Options **s** and **t** appear only when a schedule exists.

| Action | What it does |
|---|---|
| **a) Add** | Enter a share path and pick its volume(s) from `hs status volume`, the same way as for a scan. If the share is already monitored, the volumes you pick are added to the ones it has. If a schedule exists, SIPHON asks whether to add the new pairs to the scheduled report too (the default is yes). |
| **r) Remove** | Enter the numbers of the pairs to remove, e.g. `2` or `1,3`, and confirm. If any of them are in the scheduled report, SIPHON asks whether to remove them from it too (the default is yes). If that would leave the scheduled report with nothing to scan, it offers to remove the schedule. Result files are kept. |
| **s) Scheduled pairs** | Enter the numbers of the pairs the scheduled report should scan. Press Enter to keep the current ones. |
| **t) Schedule settings** | Change the run times, results folder or upload setting, with the same prompts as when you first set up the schedule. |

Changes are saved straight away and apply from the next scan or scheduled run; there's no separate save step. The crontab doesn't change when you add or remove scheduled pairs, because the cron job reads the list each time it runs.

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

Shares are matched by the exact path you typed, so `Z:\Projects` and `\\fileserver\Projects` are saved separately. To change a share's default, enter the share and answer `n` when asked to use the saved volumes; your new choice replaces the old one. To review the list or remove a share, choose **4) Review or change the monitoring configuration** at the main menu.

## Configuration

Set these environment variables before running SIPHON to change where files go:

| Variable | Default | Purpose |
|---|---|---|
| `HS_SUM_OUTDIR` | `/tmp` on macOS/Linux; your temp folder (`%TEMP%`) on Windows | Folder for result files. |
| `HS_SUM_MAPFILE` | `.hs_sum_volume_map` in your home folder | Saved share-to-volume defaults. |
| `HS_SIPHON_SCHEDULE` | `~/.hs_siphon_schedule.json` | Scheduled report settings (Linux/macOS). |
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
| `~/.hs_siphon_schedule.json` | Scheduled report settings: run times, shares, results folder, upload choice. |
| `~/.hs_siphon_schedule.json.lock` | Stops a scheduled run from starting while the previous one is still going. |
| `~/.hs_siphon_cron.log` | Output of every scheduled run. It grows over time; delete or trim it whenever you like. |

`<share>` is the last folder of the share path and `<volume>` is the volume name, with unsafe characters replaced by `_`, e.g. `hs_sum_LinuxHome__legacy-nas_ifs_data_Linux_LinuxHome.txt`.

The "previous run" finish time comes from the result file's modification time, so don't edit or touch result files between runs.

**Upgrading from earlier versions:** SIPHON 1.1.0 and later use the same file names, formats and saved defaults as the 1.0.0 bash script, so your history and saved shares carry over. Result files from the original single-volume script (`hs_sum_<share>.txt`) are also picked up automatically on the first run for that share.

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
| `NOTE: 'crontab' not found on this host - scheduling is not available` | Install cron (for example the `cron` or `cronie` package) to schedule reports, or run SIPHON by hand. |
| A scheduled run didn't happen | Check `crontab -l` for lines ending `# SIPHON scheduled report`, check `~/.hs_siphon_cron.log`, and make sure `hs-siphon.py` hasn't been moved. The cron service must be running on the host. |
| `Previous scheduled run is still in progress - skipping this run.` | The scans take longer than the gap between run times. Choose fewer or more widely spaced run times. |
| `No input - exiting.` | Input ended at a prompt (Ctrl-D, Ctrl-Z then Enter on Windows, or a closed terminal). Re-run SIPHON. |

## Limitations and roadmap

- SIPHON is interactive, apart from scheduled runs. The command-line options that work are `-h` / `--help`, and `--cron` with `--schedule-file` (used by the cron job). The other options in the script header (`--source`, `--target`, `-v`, `-w`, `-i`, `-l`) are planned but not implemented; if passed, they are ignored with a note.
- Scheduling uses cron, so it's available on Linux and macOS only. There's one SIPHON schedule per user.
- Throughput isn't calculated by the script itself; see [Calculating throughput](#calculating-throughput).
- Scans run one after the other, not in parallel.
- Volume names containing a single quote (`'`) aren't supported in the `hs sum` expression.

## Version history

| Version | Changes |
|---|---|
| 1.3.0 | Review and change the monitoring configuration from the main menu: list every monitored share/volume pair, add or remove pairs, choose which pairs the scheduled report scans, and change schedule settings. The main menu now has an Exit option and appears on every host, including Windows. |
| 1.2.0 | Adds recurring reports via cron on Linux and macOS (including DSX nodes): run once now, schedule, or both; daily run times (no more than 2 per day recommended); upload choice for scheduled runs; overlap protection; log file; remove-schedule option. One-off runs unchanged. |
| 1.1.0 | Rewritten in Python so SIPHON runs on Windows as well as macOS and Linux (Windows not yet fully tested). Same prompts, file names, formats and saved defaults as 1.0.0. Adds Windows drive/UNC path support, finding `hs` in pip's scripts folder, plain-text banner fallback and `NO_COLOR`. Documents that only Hammerspace personnel may run SIPHON on DSX nodes. Replaces `hs-siphon.sh`. |
| 1.0.0 | First release as SIPHON (bash): any share path, volume discovery with `hs status volume`, multiple volumes per share, saved defaults, `all` shortcut, Anvil block, tmux enforcement on DSX nodes, summary table, upload made optional. |

## Confluence

Two Confluence versions of these docs are in [`docs/`](docs/). Neither contains GitHub links, because they're meant for an internal Confluence space.

- [`SIPHON-confluence-paste.html`](docs/SIPHON-confluence-paste.html): download it, open it in a browser, click **Copy for Confluence** and paste into a Confluence page. This works in any Confluence editor.
- [`SIPHON-confluence.wiki`](docs/SIPHON-confluence.wiki): Confluence wiki markup, for editors with **Insert → Markup**.

## License

SIPHON is dual-licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT License ([LICENSE-MIT](LICENSE-MIT))

at your option. Unless you state otherwise, any contribution you submit for inclusion in this project is dual-licensed as above, without any additional terms or conditions.
