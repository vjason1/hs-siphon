#!/usr/bin/env python3
# ==============================================================================
# S.I.P.H.O.N. — Storage Ingestion Progress & High-volume Orchestration Navigator
# Open Source Data Migration Telemetry for Hammerspace
# ==============================================================================
# Project:         SIPHON (github.com/vjason1/hs-siphon)
# Version:         1.1.0
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
# ==============================================================================
#
# What it does:
#   For each Hammerspace share path you choose, counts the files (and GB) that
#   still have an instance on a selected storage volume, i.e. what is left to
#   migrate off that volume. Results are saved, compared with the previous run,
#   and uploaded.
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
# ==============================================================================

import datetime
import os
import re
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile

VERSION = "1.1.0"
IS_WINDOWS = os.name == "nt"

# --- [ Settings ] ------------------------------------------------------------
DEFAULT_OUTDIR = tempfile.gettempdir() if IS_WINDOWS else "/tmp"
OUTDIR = os.environ.get("HS_SUM_OUTDIR") or DEFAULT_OUTDIR
MAPFILE = os.environ.get("HS_SUM_MAPFILE") or os.path.join(os.path.expanduser("~"), ".hs_sum_volume_map")

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
    """Check where we're running; return (hs_path, upload_path_or_None)."""
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
    return hs, upload


# --- [ Choose shares & volumes ] ---------------------------------------------
def select_targets(hs):
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
            prompt = "Enter another share path (blank = start scanning)"
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
def run_scans(hs, upload, run_list):
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
        print("(Not uploaded - 'upload' command not available on this host.)")


# --- [ Entry Point / Execution ] ---------------------------------------------
def main(argv):
    # Render the banner to the terminal upon execution
    show_banner()

    if argv and argv[0] in ("-h", "--help"):
        show_help()
        return 0
    if argv:
        print("NOTE: command-line options other than -h/--help are not implemented yet; ignoring: {}\n".format(" ".join(argv)))

    try:
        hs, upload = preflight()
        run_list = select_targets(hs)
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
