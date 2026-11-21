#!/usr/bin/env python3
# ==============================================================================
# S.I.P.H.O.N. — Storage Ingestion Progress & High-volume Orchestration Navigator
# Open Source Data Migration Telemetry for Hammerspace
# ==============================================================================
# Project:         SIPHON (github.com/vjason1/hs-siphon)
# Version:         1.3.0
# License:         Apache-2.0 OR MIT (see LICENSE-APACHE and LICENSE-MIT)
# Target Runtime:  Python 3.6+ on Windows, macOS or Linux, with the
#                  Hammerspace Toolkit (hstk)
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
# Description:
#   Real-time tracking, flow-rate observation, and integrity verification
#   utility for bulk data ingestion into Hammerspace global file systems.
#
# Usage:
#   python3 hs-siphon.py [OPTIONS] --source <PATH> --target <HAMMERSPACE_SHARE>
#
# Options:
#   -h, --help            Show this help dialogue and exit
#   -v, --verbose         Enable verbose logging output
#   -w, --watch           Run live curses/terminal progress monitor
#   -i, --interval <SEC>  Poll frequency for metadata scans (default: 5)
#   -l, --log-level <LVL> Set threshold: DEBUG, INFO, WARN, ERROR (default: INFO)
#       --cron            Run the saved scheduled report without prompts
#                         (this is what the cron job runs; Linux/macOS only)
#       --schedule-file <FILE>  Schedule file to use with --cron
#                         (default: ~/.hs_siphon_schedule.json)
# ==============================================================================
#
# What it does:
#   For each Hammerspace share path you choose, counts the files (and GB) that
#   still have an instance on a selected storage volume, i.e. what is left to
#   migrate off that volume. Results are saved, compared with the previous run,
#   and uploaded.
#
#   Run it once interactively, or (on Linux/macOS, including Hammerspace DSX
#   nodes) schedule the configured report to run every day at set times via
#   cron. No more than 2 scheduled runs per day are recommended.
#
#   The monitoring configuration (which share/volume pairs are monitored, and
#   which of them the scheduled report scans) can be reviewed and changed from
#   the main menu: add shares, remove them, or change the scheduled report.
#
# Requirement: Hammerspace Toolkit (provides the 'hs' command).
#   - Already installed on Hammerspace DSX nodes.
#   - On any other host (Windows, macOS, Linux):  pip install hstk
#     Homepage: https://github.com/hammer-space/hstk
#
# Who runs SIPHON where:
#   - End users: run it from your own client machine (pip install hstk).
#   - Hammerspace personnel only: may run it on a Hammerspace DSX node,
#     inside a tmux session they started (the script checks for this).
#   - Nobody: DO NOT run this script on a Hammerspace Anvil.
#
# Share-to-volume selections are saved as defaults for future runs in:
#   ~/.hs_sum_volume_map      (override with HS_SUM_MAPFILE=/path)
# Result files are written to /tmp, or the system temp folder on Windows
# (override with HS_SUM_OUTDIR=/path).
# Scheduled (cron) reports are saved in ~/.hs_siphon_schedule.json (override
# with HS_SIPHON_SCHEDULE=/path) and log to ~/.hs_siphon_cron.log.
# ==============================================================================

import datetime
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile

VERSION = "1.3.0"
IS_WINDOWS = os.name == "nt"

# --- [ Settings ] ------------------------------------------------------------
DEFAULT_OUTDIR = tempfile.gettempdir() if IS_WINDOWS else "/tmp"
OUTDIR = os.environ.get("HS_SUM_OUTDIR") or DEFAULT_OUTDIR
MAPFILE = os.environ.get("HS_SUM_MAPFILE") or os.path.join(os.path.expanduser("~"), ".hs_sum_volume_map")
SCHEDFILE = os.environ.get("HS_SIPHON_SCHEDULE") or os.path.join(os.path.expanduser("~"), ".hs_siphon_schedule.json")
CRON_LOG = os.path.join(os.path.expanduser("~"), ".hs_siphon_cron.log")
CRON_MARKER = "# SIPHON scheduled report"
RECOMMENDED_MAX_RUNS = 2

SUM_EXPR = ("IS_FILE AND NOT ISNA(INSTANCES[|VOLUME=STORAGE_VOLUME('{v}')])>0 AND "
            "ROWS(INSTANCES[|VOLUME=STORAGE_VOLUME('{v}')])>0 ?{{1FILE/FILES,SIZE/GBYTES}}")
VALUES_RE = re.compile(r"\{([0-9]+), *([0-9.eE+-]+)\}")


# --- [ Terminal Styling & ANSI Definitions ] ---------------------------------
def _enable_ansi():
    """Turn on ANSI colors where supported (Windows 10+ needs VT mode enabled)."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if IS_WINDOWS:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            if not kernel32.SetConsoleMode(handle, mode.value | 0x0004):  # VT processing
                return False
        except Exception:
            return False
    return True


USE_COLOR = _enable_ansi()
CLR_RESET = "\033[0m" if USE_COLOR else ""
CLR_BOLD = "\033[1m" if USE_COLOR else ""
CLR_CYAN = "\033[1;36m" if USE_COLOR else ""
CLR_BLUE = "\033[0;34m" if USE_COLOR else ""
CLR_GRAY = "\033[0;90m" if USE_COLOR else ""

# Make sure the banner's box-drawing characters can be printed (Windows consoles)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


# --- [ Banner Display Routine ] ----------------------------------------------
BANNER = u"""\
  ███████╗██╗██████╗ ██╗  ██╗ ██████╗ ███╗   ██╗
  ██╔════╝██║██╔══██╗██║  ██║██╔═══██╗████╗  ██║
  ███████╗██║██████╔╝███████║██║   ██║██╔██╗ ██║
  ╚════██║██║██╔═══╝ ██╔══██║██║   ██║██║╚██╗██║
  ███████║██║██║     ██║  ██║╚██████╔╝██║ ╚████║
  ╚══════╝╚═╝╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝"""

BANNER_ASCII = r"""
   ____ ___ ____  _   _  ___  _   _
  / ___|_ _|  _ \| | | |/ _ \| \ | |
  \___ \| || |_) | |_| | | | |  \| |
   ___) | ||  __/|  _  | |_| | |\  |
  |____/___|_|   |_| |_|\___/|_| \_|"""


def show_banner():
    try:
        print(BANNER)
    except UnicodeEncodeError:
        print(BANNER_ASCII)
    print("{}  Storage Ingestion Progress & High-volume Orchestration Navigator{}".format(CLR_CYAN, CLR_RESET))
    print("{}  Hammerspace Ingestion & Telemetry Monitor v{}{}\n".format(CLR_GRAY, VERSION, CLR_RESET))


def show_help():
    """Print the header comment block, up to 'What it does:'."""
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        lines = f.read().splitlines()[1:]
    for line in lines:
        if line.startswith("# What it does:"):
            break
        print(re.sub(r"^# ?", "", line))


# --- [ Helpers ] -------------------------------------------------------------
def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def file_mtime(path):
    """File modification time as 'YYYY-MM-DD HH:MM:SS'."""
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "unknown"


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def get_values(path):
    """Return (files, gb) from the hs sum result line, e.g. {102580, 938.16}, or None."""
    m = VALUES_RE.search(read_text(path))
    if not m:
        return None
    try:
        return int(m.group(1)), float(m.group(2))
    except ValueError:
        return None


def compare_values(prev_path, cur_path):
    """Compare previous vs. current values; values are expected to decrease."""
    old, new = get_values(prev_path), get_values(cur_path)
    if old is None or new is None:
        return "Change since previous run: could not compare (values missing from previous or current output)\n"
    df, ds = new[0] - old[0], new[1] - old[1]
    out = ["Change since previous run:",
           "  Files: {} -> {} ({:+d})".format(old[0], new[0], df),
           "  Size:  {:.2f} GB -> {:.2f} GB ({:+.2f} GB)".format(old[1], new[1], ds)]
    if df > 0 or ds > 0:
        out.append("  WARNING: value(s) INCREASED - expected a decrease")
    elif df == 0 and ds == 0:
        out.append("  No change since previous run")
    else:
        out.append("  OK: values decreased as expected")
    return "\n".join(out) + "\n"


def sanitize(text):
    """Turn a path/volume into a safe filename fragment."""
    s = text.replace("::", "_")
    s = re.sub(r"[^A-Za-z0-9._-]", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def normalize_path(p, pathmod=os.path):
    """Strip quotes and trailing separators, keeping a root like '/' or 'Z:\\'."""
    p = p.strip()
    if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
        p = p[1:-1].strip()
    seps = "/\\" if pathmod.sep == "\\" else "/"
    drive, rest = pathmod.splitdrive(p)
    stripped = rest.rstrip(seps)
    if rest and not stripped:          # the path is a root: "/", "\", "Z:\"
        return drive + rest[0]
    return drive + stripped


def share_name(share, pathmod=os.path):
    """Last folder of the share path (used in file names and volume suggestions)."""
    base = pathmod.basename(share)
    if not base:                       # a root such as "Z:\" or "\\server\Projects\"
        parts = [p for p in re.split(r"[\\/:]", share) if p]
        base = parts[-1] if parts else ""
    return base or "share"


class InputClosed(Exception):
    pass


def ask(prompt):
    """input() that stops cleanly if input ends (Ctrl-D/Ctrl-Z or a closed terminal)."""
    try:
        return input(prompt)
    except EOFError:
        raise InputClosed()


def ask_yn(prompt, default=""):
    """Ask a yes/no question until answered. default = 'y', 'n', or '' for 'must answer'."""
    hint = {"y": "(Y/n)", "n": "(y/N)"}.get(default, "(y/n)")
    while True:
        ans = ask("{} {}: ".format(prompt, hint)).strip() or default
        if ans.lower() in ("y", "yes"):
            return True
        if ans.lower() in ("n", "no"):
            return False
        print("  Please answer y or n.")


def find_command(name):
    """Locate a command on PATH, or in Python's scripts folders (where pip installs hstk)."""
    found = shutil.which(name)
    if found:
        return found
    dirs = [sysconfig.get_path("scripts")]
    try:
        scheme = "nt_user" if IS_WINDOWS else "posix_user"
        dirs.append(sysconfig.get_path("scripts", scheme))
    except Exception:
        pass
    for d in dirs:
        if d:
            found = shutil.which(name, path=d)
            if found:
                return found
    return None


# --- [ Saved defaults ] ------------------------------------------------------
def load_mappings():
    """Saved (share, volume) pairs, in file order."""
    pairs = []
    for line in read_text(MAPFILE).splitlines():
        if "\t" in line:
            share, volume = line.split("\t", 1)
            if share and volume:
                pairs.append((share, volume))
    return pairs


def saved_volumes(share):
    return [v for s, v in load_mappings() if s == share]


def save_mapping(share, volumes):
    """Replace the saved mapping for a share with the given volumes."""
    pairs = [(s, v) for s, v in load_mappings() if s != share] + [(share, v) for v in volumes]
    folder = os.path.dirname(MAPFILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = "{}.tmp.{}".format(MAPFILE, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for s, v in pairs:
            f.write("{}\t{}\n".format(s, v))
    os.replace(tmp, MAPFILE)


def remove_mappings(pairs):
    """Remove the given (share, volume) pairs from the saved defaults."""
    drop = set(tuple(p) for p in pairs)
    keep = [p for p in load_mappings() if p not in drop]
    folder = os.path.dirname(MAPFILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = "{}.tmp.{}".format(MAPFILE, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for s, v in keep:
            f.write("{}\t{}\n".format(s, v))
    os.replace(tmp, MAPFILE)


# --- [ Volume selection ] ----------------------------------------------------
def choose_volumes(hs, share):
    """Interactively choose volumes for a share via 'hs status volume'."""
    print()
    print("Running: hs status volume {}".format(share))
    try:
        res = subprocess.run([hs, "status", "volume", share], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, universal_newlines=True, errors="replace")
        out = res.stdout
    except OSError as e:
        out = "ERROR running hs: {}".format(e)
    print(out.rstrip("\n"))

    # Volume names are the quoted strings in the output
    vols = [v for v in re.findall(r'"([^"]+)"', out) if v]

    if not vols:
        print("No volumes found in the output (is the path a Hammerspace share?).")
        manual = ask("Type a volume name to use (blank to skip this share): ").strip()
        return [manual] if manual else []

    # Suggest volumes whose path (after '::') ends with the share's last folder name
    base = share_name(share).lower()
    suggested = []
    print()
    print("Volumes connected to {}:".format(share))
    for i, v in enumerate(vols, 1):
        mark = "  "
        if "::" in v and re.split(r"[/\\]", v)[-1].lower() == base:
            mark = "* "
            suggested.append(str(i))
        print("  {}{:2d}) {}".format(mark, i, v))
    if suggested:
        print("  (* = suggested match for '{}')".format(share_name(share)))

    while True:
        print()
        print("Select the volume(s) to measure migration progress from.")
        print("  Enter numbers separated by spaces or commas (e.g. 6  or  4,6).")
        if suggested:
            print("  Press Enter to use the suggested: {}".format(" ".join(suggested)))
        print("  'm' = type a volume name manually, 's' = skip this share")
        sel = ask("Selection: ").strip()
        if not sel and suggested:
            sel = " ".join(suggested)
        if sel.lower() == "s":
            return []
        if sel.lower() == "m":
            manual = ask("Volume name: ").strip()
            if manual:
                return [manual]
            continue
        chosen, bad = [], False
        for tok in re.split(r"[\s,]+", sel):
            if not tok:
                continue
            if tok.isdigit() and 1 <= int(tok) <= len(vols):
                chosen.append(vols[int(tok) - 1])
            else:
                print("  Invalid choice: {}".format(tok))
                bad = True
        if chosen and not bad:
            return chosen


# --- [ Preflight ] -----------------------------------------------------------
def preflight():
    """Check where we're running; return (hs_path, upload_path_or_None, is_hs_node)."""
    print("=" * 66)
    print(" Requires the Hammerspace Toolkit ('hs' command).")
    print("   - Already installed on Hammerspace DSX nodes.")
    print("   - Any other host (Windows, macOS, Linux):  pip install hstk")
    print("     (https://github.com/hammer-space/hstk)")
    print(" End users: run SIPHON from your own client machine.")
    print(" Only Hammerspace personnel may run it on a DSX node (inside tmux).")
    print(" Do NOT run this script on a Hammerspace Anvil.")
    print("=" * 66)
    print()

    # Always confirm where we're running
    print("Current host: {}".format(socket.gethostname() or "unknown"))
    if ask_yn("Are you running this on a Hammerspace Anvil?"):
        print()
        print("{}ERROR: This script must NOT be run from a Hammerspace Anvil.{}".format(CLR_BOLD, CLR_RESET))
        print("End users: run it from your own client machine. Hammerspace personnel: use a DSX node.")
        sys.exit(1)

    if ask_yn("Are you running this on a Hammerspace DSX node?"):
        hs_node = True
        print("DSX node: only Hammerspace personnel may run SIPHON here.")
        print("          End users should run it from their own client machine instead.")
        print("DSX node: the Hammerspace Toolkit is already installed.")
        # On a Hammerspace node the scans must run inside a tmux session that the
        # user started, so a dropped connection doesn't kill them.
        if not os.environ.get("TMUX"):
            print()
            print("{}ERROR: Not running inside a tmux session.{}".format(CLR_BOLD, CLR_RESET))
            print("On a Hammerspace node SIPHON must be run from within tmux; these scans")
            print("can run for hours and would be killed if your connection drops.")
            print("Start a tmux session, then re-run this script from inside it.")
            sys.exit(1)
        session = "unknown"
        try:
            session = subprocess.run(["tmux", "display-message", "-p", "#S"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, universal_newlines=True).stdout.strip() or session
        except OSError:
            pass
        print("Running inside tmux session: {}".format(session))
    else:
        hs_node = False
        print("Client host: the Hammerspace Toolkit must be installed (pip install hstk).")
        print("Keep this window open (and the computer awake) until the scans finish.")

    hs = find_command("hs")
    if not hs:
        print()
        print("ERROR: 'hs' command not found - the Hammerspace Toolkit is not installed or not on PATH.")
        if hs_node:
            print("It is normally present on DSX nodes; check your PATH.")
        else:
            print("Install it with:  pip install hstk")
            print("(Homepage: https://github.com/hammer-space/hstk)")
        sys.exit(1)

    upload = find_command("upload")
    if not upload:
        print("NOTE: 'upload' command not found on this host - result files will be saved but not uploaded.")

    try:
        os.makedirs(OUTDIR, exist_ok=True)
    except OSError as e:
        print("ERROR: cannot create output folder {}: {}".format(OUTDIR, e))
        sys.exit(1)
    return hs, upload, hs_node


# --- [ Choose shares & volumes ] ---------------------------------------------
def select_targets(hs, blank_label="start scanning"):
    run_list = []

    def add(share, volume):
        if (share, volume) not in run_list:
            run_list.append((share, volume))

    saved_pairs = load_mappings()
    if saved_pairs:
        print()
        print("Saved share -> volume defaults ({}):".format(MAPFILE))
        for s, v in saved_pairs:
            print("  {}  ->  {}".format(s, v))

    print()
    print("Share path examples:")
    print("  DSX:             /mnt/smb-data-portal/<sharename>/<optional/subfolder/path>")
    print("  Windows client:  the share's mapped drive or UNC path (e.g. Z:\\Projects, \\\\server\\Projects)")
    print("  Mac/Linux client: the share's mount point (e.g. /Volumes/Projects, /mnt/projects)")

    while True:
        print()
        prompt = "Enter a Hammerspace share path"
        if run_list:
            prompt = "Enter another share path (blank = {})".format(blank_label)
        if load_mappings():
            prompt += " ['all' = every saved share]"
        share = ask(prompt + ": ").strip()

        if not share:
            if run_list:
                break
            print("  Please enter a share path.")
            continue

        if share.lower() == "all" and load_mappings():
            for s, v in load_mappings():
                add(s, v)
            print("  Added all saved shares.")
        else:
            share = normalize_path(share)
            if not os.path.isdir(share):
                print("  WARNING: {} is not a directory on this host.".format(share))
                if not ask_yn("  Use it anyway?", "n"):
                    continue

            saved = saved_volumes(share)
            use_saved = False
            if saved:
                print("  Saved default volume(s) for this share:")
                for v in saved:
                    print("    {}".format(v))
                use_saved = ask_yn("  Use the saved volume(s)?", "y")

            if use_saved:
                chosen = saved
            else:
                chosen = choose_volumes(hs, share)
                if not chosen:
                    print("  Skipped {}.".format(share))
                    continue
                save_mapping(share, chosen)
                print("  Saved as the default for {}.".format(share))
            for v in chosen:
                add(share, v)

        print()
        print("Scan list so far:")
        for s, v in run_list:
            print("  {}  ->  {}".format(s, v))
        if not ask_yn("Add another share path?", "n"):
            break
    return run_list


# --- [ Run scans ] -----------------------------------------------------------
def run_scans(hs, upload, run_list, no_upload_note="(Not uploaded - 'upload' command not available on this host.)"):
    summary = []
    print()
    print("Starting {} scan(s), one after the other.".format(len(run_list)))

    for share, volume in run_list:
        name = share_name(share)
        outfile = os.path.join(OUTDIR, "hs_sum_{}__{}.txt".format(sanitize(name), sanitize(volume)))
        prevfile = outfile + ".prev"

        # Carry over history from the original script's file name (hs_sum_<share>.txt)
        legacy = os.path.join(OUTDIR, "hs_sum_{}.txt".format(name))
        if not os.path.isfile(outfile) and os.path.isfile(legacy):
            head = read_text(legacy).splitlines()[:2]
            if share in head:
                shutil.copy2(legacy, outfile)

        # Note when the previous run happened. The file's timestamp is when it was
        # last written, i.e. when the previous command FINISHED. The start time is
        # read from the "Started:" line inside the file, if present.
        if os.path.isfile(outfile):
            prev_finish = file_mtime(outfile)
            m = re.search(r"^Started: *(.*)$", read_text(outfile), re.M)
            prev_start = m.group(1).strip() if m else ""
            prev_note = "Previous run: finished {}".format(prev_finish)
            if prev_start:
                prev_note = "Previous run: started {}, finished {}".format(prev_start, prev_finish)
            shutil.copy2(outfile, prevfile)    # keep last results for comparison
            has_prev = True
        else:
            prev_note = "Previous run: none (no previous results stored)"
            has_prev = False

        print()
        print("{}=== {}  [volume: {}] ==={}".format(CLR_BLUE, share, volume, CLR_RESET))

        # Start time, share path, volume, command output, finish time, previous-run note
        with open(outfile, "w", encoding="utf-8", newline="\n") as f:
            f.write("Started:  {}\n".format(now()))
            f.write("{}\n".format(share))
            f.write("Volume:   {}\n".format(volume))
            f.flush()
            rc = 0
            try:
                res = subprocess.run([hs, "sum", "-e", SUM_EXPR.format(v=volume), share],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     universal_newlines=True, errors="replace")
                f.write(res.stdout if res.stdout.endswith("\n") or not res.stdout else res.stdout + "\n")
                rc = res.returncode
            except OSError as e:
                f.write("{}\n".format(e))
                rc = 127
            if rc != 0:
                f.write("ERROR: hs sum exited with status {}\n".format(rc))
            f.write("Finished: {}\n".format(now()))
            f.write("{}\n".format(prev_note))

        # Compare with previous results, if any
        if has_prev and os.path.isfile(prevfile):
            with open(outfile, "a", encoding="utf-8", newline="\n") as f:
                f.write(compare_values(prevfile, outfile))

        print(read_text(outfile), end="")
        vals = get_values(outfile)
        vals_txt = "{} {}".format(*VALUES_RE.search(read_text(outfile)).groups()) if vals else "<no result>"
        summary.append("{:<45} {:<42} {}".format(share, volume, vals_txt))

        # Upload the result file
        if upload:
            sys.stdout.flush()      # keep the log in order when output is redirected (cron)
            try:
                rc = subprocess.run([upload, os.path.basename(outfile)], cwd=OUTDIR).returncode
            except OSError:
                rc = 1
            if rc != 0:
                print("WARNING: upload of {} failed".format(os.path.basename(outfile)))

    print()
    print("================================ Summary ================================")
    print("{:<45} {:<42} {}".format("Share", "Volume", "Files  GB"))
    for line in summary:
        print(line)
    print()
    print("Done. Results saved in {}".format(os.path.join(OUTDIR, "hs_sum_*.txt")))
    if not upload:
        print(no_upload_note)


# --- [ Scheduling (cron) ] ---------------------------------------------------
def cron_available():
    """Scheduling needs a non-Windows host with the crontab command."""
    return (not IS_WINDOWS) and shutil.which("crontab") is not None


def read_crontab():
    """Current user's crontab text ('' if there is none)."""
    try:
        res = subprocess.run(["crontab", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
    except OSError:
        return ""
    return res.stdout if res.returncode == 0 else ""


def write_crontab(text):
    res = subprocess.run(["crontab", "-"], input=text, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True)
    if res.returncode != 0:
        raise RuntimeError(res.stdout.strip() or "crontab exited with status {}".format(res.returncode))


def siphon_cron_lines(text=None):
    text = read_crontab() if text is None else text
    return [l for l in text.splitlines() if CRON_MARKER in l]


def load_schedule(path=None):
    try:
        with open(path or SCHEDFILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def parse_times(text):
    """'6:00, 18:30' -> [(6, 0), (18, 30)] sorted and de-duplicated; raises ValueError."""
    times = set()
    for tok in re.split(r"[\s,;]+", text.strip()):
        if not tok:
            continue
        m = re.match(r"^(\d{1,2}):(\d{2})$", tok)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError("'{}' is not a valid 24-hour time (HH:MM)".format(tok))
        times.add((int(m.group(1)), int(m.group(2))))
    if not times:
        raise ValueError("enter at least one time")
    return sorted(times)


def fmt_times(times):
    return ", ".join("{:02d}:{:02d}".format(h, m) for h, m in times)


def local_tz():
    try:
        return datetime.datetime.now().astimezone().tzname() or "local time"
    except Exception:
        return "local time"


def cron_quote(arg):
    """Quote an argument for /bin/sh in a crontab line ('%' is special to cron)."""
    return shlex.quote(arg).replace("%", "\\%")


def show_schedule(sched, lines):
    print("Current SIPHON schedule:")
    if sched:
        print("  Runs every day at: {} ({})".format(fmt_times([tuple(t) for t in sched.get("times", [])]),
                                                    sched.get("timezone", "local time")))
        print("  Upload results:    {}".format("yes" if sched.get("upload") else "no"))
        print("  Results folder:    {}".format(sched.get("outdir")))
        print("  Log file:          {}".format(sched.get("log")))
        print("  Shares:")
        for s, v in sched.get("run_list", []):
            print("    {}  ->  {}".format(s, v))
    if lines:
        print("  Crontab entries:")
        for l in lines:
            print("    {}".format(l))
    else:
        print("  (No SIPHON entries found in your crontab - the schedule is not active.)")


def choose_mode(first=True):
    """Main menu: run now, schedule, both, review/change the configuration, remove the schedule, exit."""
    can_cron = cron_available()
    sched, lines = (load_schedule(), siphon_cron_lines()) if can_cron else (None, [])
    if first and not IS_WINDOWS and not can_cron:
        print()
        print("NOTE: 'crontab' not found on this host - scheduling is not available.")
    if first and (sched or lines):
        print()
        show_schedule(sched, lines)

    options = [("now", "Run the report once now")]
    if can_cron:
        options += [("schedule", "Schedule the report to run every day (cron)"),
                    ("both", "Run once now AND schedule it")]
    options.append(("manage", "Review or change the monitoring configuration"))
    if sched or lines:
        options.append(("remove", "Remove the existing schedule"))
    options.append(("exit", "Exit"))
    print()
    print("What would you like to do?")
    for i, (_, label) in enumerate(options, 1):
        print("  {}) {}".format(i, label))
    while True:
        sel = ask("Choice [1]: ").strip() or "1"
        if sel.isdigit() and 1 <= int(sel) <= len(options):
            return options[int(sel) - 1][0]
        print("  Please enter a number from 1 to {}.".format(len(options)))


def prompt_times():
    print()
    print("Enter the time(s) to run the report each day, in 24-hour HH:MM format,")
    print("separated by commas (e.g. 06:00, 18:00). Times use this host's clock ({}).".format(local_tz()))
    print("Recommended: no more than {} runs per day. Large shares can take hours to".format(RECOMMENDED_MAX_RUNS))
    print("scan, and a run is skipped if the previous one is still going.")
    while True:
        try:
            times = parse_times(ask("Run times: "))
        except ValueError as e:
            print("  {}.".format(str(e).capitalize()))
            continue
        if len(times) > RECOMMENDED_MAX_RUNS:
            print("  WARNING: {} runs per day is more than the recommended {}.".format(len(times), RECOMMENDED_MAX_RUNS))
            if not ask_yn("  Use {} runs per day anyway?".format(len(times)), "n"):
                continue
        return times


def prompt_outdir():
    print()
    print("Scheduled results folder (Enter = {}):".format(OUTDIR))
    if os.path.abspath(OUTDIR).startswith(("/tmp", "/var/tmp/systemd")):
        print("  Note: {} may be cleared on reboot, which erases the run history.".format(OUTDIR))
        print("  A folder such as /var/tmp/siphon or ~/siphon-results keeps it.")
    while True:
        d = ask("Results folder: ").strip() or OUTDIR
        d = os.path.abspath(os.path.expanduser(d))
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except OSError as e:
            print("  Cannot use {}: {}".format(d, e))


def schedule_setup(hs, upload, run_list):
    """Prompt for run times, folder and upload choice; save the schedule and install it in crontab."""
    print()
    print("=== Schedule a recurring report (cron) ===")
    print("The scheduled report scans these share/volume pairs:")
    for s, v in run_list:
        print("  {}  ->  {}".format(s, v))

    times = prompt_times()
    outdir = prompt_outdir()

    print()
    if upload:
        do_upload = ask_yn("Upload the results ({}) as part of each scheduled run?".format(upload))
    else:
        do_upload = False
        print("NOTE: 'upload' command not found on this host - scheduled runs will save results without uploading.")

    script = os.path.abspath(__file__)
    log = CRON_LOG
    sched = {
        "version": VERSION,
        "created": now(),
        "host": socket.gethostname(),
        "times": [list(t) for t in times],
        "timezone": local_tz(),
        "run_list": [list(p) for p in run_list],
        "upload": do_upload,
        "upload_cmd": upload if do_upload else None,
        "hs_cmd": hs,
        "outdir": outdir,
        "log": log,
        "python": sys.executable,
        "script": script,
    }
    cmd = "{} {} --cron --schedule-file {} >> {} 2>&1".format(
        cron_quote(sys.executable), cron_quote(script), cron_quote(SCHEDFILE), cron_quote(log))
    new_lines = ["{} {} * * * {} {}".format(m, h, cmd, CRON_MARKER) for h, m in times]

    print()
    print("Summary:")
    print("  Runs every day at: {} ({})".format(fmt_times(times), local_tz()))
    print("  Upload results:    {}".format("yes" if do_upload else "no"))
    print("  Results folder:    {}".format(outdir))
    print("  Log file:          {}".format(log))
    print("  Crontab entries:")
    for l in new_lines:
        print("    {}".format(l))
    if siphon_cron_lines():
        print("  (These replace your existing SIPHON schedule.)")
    if script.startswith(("/tmp/", "/var/tmp/")):
        print("  WARNING: the script is in a temporary folder; the schedule stops working if it is removed.")
    if not ask_yn("Install this schedule in your crontab?"):
        print("Schedule not installed.")
        return False

    others = [l for l in read_crontab().splitlines() if CRON_MARKER not in l]
    with open(SCHEDFILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sched, f, indent=2)
    os.replace(SCHEDFILE + ".tmp", SCHEDFILE)
    try:
        write_crontab("\n".join(others + new_lines) + "\n")
    except (OSError, RuntimeError) as e:
        print("ERROR: could not update your crontab: {}".format(e))
        return False

    if len(siphon_cron_lines()) != len(new_lines):
        print("WARNING: the schedule was saved, but the crontab entries could not be confirmed. Check with: crontab -l")
        return False
    print()
    print("Scheduled. SIPHON will run every day at {} ({}).".format(fmt_times(times), local_tz()))
    print("  Schedule file: {}".format(SCHEDFILE))
    print("  Log file:      {}".format(log))
    print("Keep hs-siphon.py at {} - the cron job runs it from there.".format(script))
    print("To change or remove the schedule, run SIPHON again and choose that option.")
    return True


def remove_schedule():
    if not ask_yn("Remove the SIPHON schedule from your crontab?"):
        print("Schedule kept.")
        return
    remove_schedule_now()


def remove_schedule_now():
    lines = siphon_cron_lines()
    if lines:
        others = [l for l in read_crontab().splitlines() if CRON_MARKER not in l]
        try:
            write_crontab("\n".join(others) + "\n" if others else "")
        except (OSError, RuntimeError) as e:
            print("ERROR: could not update your crontab: {}".format(e))
            return
    try:
        os.remove(SCHEDFILE)
    except OSError:
        pass
    print("Schedule removed. Existing result files and the log ({}) were kept.".format(CRON_LOG))


# --- [ Review / change the monitoring configuration ] ------------------------
def save_schedule(sched):
    with open(SCHEDFILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sched, f, indent=2)
    os.replace(SCHEDFILE + ".tmp", SCHEDFILE)


def config_entries(sched):
    """Every monitored pair: saved defaults first, then pairs only the schedule has.
    Returns a list of (share, volume, saved, scheduled)."""
    saved = load_mappings()
    scheduled = [tuple(p) for p in (sched or {}).get("run_list", [])]
    out = [(s, v, True, (s, v) in scheduled) for s, v in saved]
    out += [(s, v, False, True) for s, v in scheduled if (s, v) not in saved]
    return out


def show_config(entries, sched):
    print()
    print("Monitoring configuration")
    print("  Saved share/volume pairs: {}".format(MAPFILE))
    if sched:
        print("  Scheduled report:         every day at {} ({}), upload {}".format(
            fmt_times([tuple(t) for t in sched.get("times", [])]), sched.get("timezone", "local time"),
            "on" if sched.get("upload") else "off"))
    else:
        print("  Scheduled report:         none")
    print()
    if not entries:
        print("  No shares are monitored yet.")
        return
    for i, (s, v, saved, scheduled) in enumerate(entries, 1):
        tags = []
        if scheduled:
            tags.append("scheduled")
        if not saved:
            tags.append("schedule only")
        print("  {:2d}) {}  ->  {}{}".format(i, s, v, "   [{}]".format(", ".join(tags)) if tags else ""))


def parse_numbers(text, count):
    """'1, 3 4' -> [0, 2, 3] (zero-based, de-duplicated, in order); raises ValueError."""
    picks = []
    for tok in re.split(r"[\s,]+", text.strip()):
        if not tok:
            continue
        if not tok.isdigit() or not 1 <= int(tok) <= count:
            raise ValueError("'{}' is not a number from 1 to {}".format(tok, count))
        if int(tok) - 1 not in picks:
            picks.append(int(tok) - 1)
    return picks


def config_add(hs, sched):
    print()
    share = ask("Share path to add (blank = cancel): ").strip()
    if not share:
        return
    share = normalize_path(share)
    if not os.path.isdir(share):
        print("  WARNING: {} is not a directory on this host.".format(share))
        if not ask_yn("  Use it anyway?", "n"):
            return
    existing = saved_volumes(share)
    if existing:
        print("  Already monitored on: {}".format(", ".join(existing)))
        print("  Pick any volumes to add; the existing ones are kept.")
    chosen = choose_volumes(hs, share)
    new = [v for v in chosen if v not in existing]
    if not new:
        print("  Nothing added.")
        return
    save_mapping(share, existing + new)
    for v in new:
        print("  Added: {}  ->  {}".format(share, v))
    if sched:
        run_list = [tuple(p) for p in sched.get("run_list", [])]
        missing = [(share, v) for v in new if (share, v) not in run_list]
        if missing and ask_yn("  Add {} to the scheduled report too?".format(
                "it" if len(missing) == 1 else "them"), "y"):
            sched["run_list"] = [list(p) for p in run_list + missing]
            save_schedule(sched)
            print("  The scheduled report now scans {} pair(s), starting with its next run.".format(len(sched["run_list"])))


def config_remove(entries, sched):
    print()
    sel = ask("Numbers to remove, e.g. 2 or 1,3 (blank = cancel): ").strip()
    if not sel:
        return
    try:
        picks = [entries[i] for i in parse_numbers(sel, len(entries))]
    except ValueError as e:
        print("  {}.".format(str(e).capitalize()))
        return
    print("  Removing:")
    for s, v, _, _ in picks:
        print("    {}  ->  {}".format(s, v))
    if not ask_yn("  Remove {}?".format("it" if len(picks) == 1 else "these"), "n"):
        print("  Nothing removed.")
        return

    remove_mappings([(s, v) for s, v, saved, _ in picks if saved])
    in_sched = [(s, v) for s, v, _, scheduled in picks if scheduled]
    if in_sched and sched:
        print("  {} of these {} in the scheduled report.".format(len(in_sched), "is" if len(in_sched) == 1 else "are"))
        if ask_yn("  Remove {} from the scheduled report too?".format("it" if len(in_sched) == 1 else "them"), "y"):
            left = [p for p in sched.get("run_list", []) if tuple(p) not in in_sched]
            if not left:
                if ask_yn("  That leaves the scheduled report with nothing to scan. Remove the schedule?", "y"):
                    remove_schedule_now()
                else:
                    print("  The scheduled report was left unchanged.")
            else:
                sched["run_list"] = left
                save_schedule(sched)
                print("  The scheduled report now scans {} pair(s), starting with its next run.".format(len(left)))
    print("  Removed.")


def config_pick_scheduled(entries, sched):
    print()
    current = [str(i) for i, e in enumerate(entries, 1) if e[3]]
    print("Enter the numbers of the pairs the scheduled report should scan, e.g. 1,3.")
    while True:
        sel = ask("Scheduled pairs (Enter = keep {}): ".format(" ".join(current) or "current")).strip()
        if not sel:
            print("  No change.")
            return
        try:
            picks = parse_numbers(sel, len(entries))
        except ValueError as e:
            print("  {}.".format(str(e).capitalize()))
            continue
        if not picks:
            continue
        sched["run_list"] = [[entries[i][0], entries[i][1]] for i in picks]
        save_schedule(sched)
        print("  The scheduled report now scans {} pair(s), starting with its next run.".format(len(picks)))
        return


def manage_config(hs, upload):
    """Review the monitoring configuration and make additions or removals."""
    while True:
        sched = load_schedule() if cron_available() else None
        entries = config_entries(sched)
        show_config(entries, sched)

        actions = [("a", "Add a share (or more volumes for a share)")]
        if entries:
            actions.append(("r", "Remove share/volume pairs"))
        if sched and entries:
            actions.append(("s", "Choose which pairs the scheduled report scans"))
        if sched:
            actions.append(("t", "Change the schedule's run times, results folder or upload setting"))
        actions.append(("b", "Back to the main menu"))
        print()
        for key, label in actions:
            print("  {}) {}".format(key, label))
        choice = ask("Choice [b]: ").strip().lower() or "b"
        if choice not in [k for k, _ in actions]:
            print("  Please enter one of: {}.".format(", ".join(k for k, _ in actions)))
            continue
        if choice == "b":
            return
        if choice == "a":
            config_add(hs, sched)
        elif choice == "r":
            config_remove(entries, sched)
        elif choice == "s":
            config_pick_scheduled(entries, sched)
        elif choice == "t":
            schedule_setup(hs, upload, [tuple(p) for p in sched.get("run_list", [])])


def run_cron(schedfile):
    """Non-interactive scheduled run (called by cron)."""
    global OUTDIR
    print()
    print("#" * 72)
    print("SIPHON {} scheduled run started {} on {}".format(VERSION, now(), socket.gethostname()))
    sched = load_schedule(schedfile)
    if not sched or not sched.get("run_list"):
        print("ERROR: no schedule found in {}. Run SIPHON interactively to set one up.".format(schedfile))
        return 1

    # Skip this run if the previous scheduled run is still going
    lock = open(schedfile + ".lock", "w")
    try:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        print("Previous scheduled run is still in progress - skipping this run.")
        return 0

    hs = sched.get("hs_cmd")
    if not hs or not os.path.isfile(hs):
        hs = find_command("hs")
    if not hs:
        print("ERROR: 'hs' command not found (Hammerspace Toolkit). Install it with: pip install hstk")
        return 1

    upload, note = None, "(Not uploaded - upload is turned off for scheduled runs.)"
    if sched.get("upload"):
        upload = sched.get("upload_cmd")
        if not upload or not os.path.isfile(upload):
            upload = find_command("upload")
        if not upload:
            note = "(Not uploaded - 'upload' command not found on this host.)"

    OUTDIR = sched.get("outdir") or OUTDIR
    try:
        os.makedirs(OUTDIR, exist_ok=True)
    except OSError as e:
        print("ERROR: cannot create output folder {}: {}".format(OUTDIR, e))
        return 1

    run_scans(hs, upload, [tuple(p) for p in sched["run_list"]], no_upload_note=note)
    print("SIPHON scheduled run finished {}".format(now()))
    return 0


# --- [ Entry Point / Execution ] ---------------------------------------------
def main(argv):
    # Scheduled (cron) run: no banner, no prompts
    if "--cron" in argv:
        schedfile = SCHEDFILE
        if "--schedule-file" in argv:
            i = argv.index("--schedule-file")
            if i + 1 >= len(argv):
                print("ERROR: --schedule-file needs a file path")
                return 2
            schedfile = argv[i + 1]
        if IS_WINDOWS:
            print("ERROR: scheduled runs are only supported on Linux and macOS.")
            return 2
        return run_cron(schedfile)

    # Render the banner to the terminal upon execution
    show_banner()

    if argv and argv[0] in ("-h", "--help"):
        show_help()
        return 0
    if argv:
        print("NOTE: command-line options other than -h/--help and --cron are not implemented yet; ignoring: {}\n".format(" ".join(argv)))

    try:
        hs, upload, _hs_node = preflight()
        mode = choose_mode()
        while mode in ("manage", "remove"):
            if mode == "manage":
                manage_config(hs, upload)
            else:
                remove_schedule()
            mode = choose_mode(first=False)
        if mode == "exit":
            return 0
        run_list = select_targets(hs, "start scanning" if mode != "schedule" else "continue to scheduling")
        if mode in ("schedule", "both"):
            schedule_setup(hs, upload, run_list)
        if mode in ("now", "both"):
            run_scans(hs, upload, run_list)
    except InputClosed:
        print()
        print("No input - exiting.")
        return 1
    except KeyboardInterrupt:
        print()
        print("Interrupted - exiting.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
