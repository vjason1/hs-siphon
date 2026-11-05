#!/usr/bin/env bash
# ==============================================================================
# S.I.P.H.O.N. — Storage Ingestion Progress & High-volume Orchestration Navigator
# Open Source Data Migration Telemetry for Hammerspace
# ==============================================================================
# Project:         SIPHON (github.com/vjason1/hs-siphon)
# Version:         1.0.0
# License:         Apache-2.0 OR MIT (see LICENSE-APACHE and LICENSE-MIT)
# Target Runtime:  Hammerspace Data Environment / Linux x86_64
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
# Description:
#   Real-time tracking, flow-rate observation, and integrity verification
#   utility for bulk data ingestion into Hammerspace global file systems.
#
# Usage:
#   ./hs-siphon.sh [OPTIONS] --source <PATH> --target <HAMMERSPACE_SHARE>
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
#   - On a non-Hammerspace host (remote client):  pip install hstk
#     Homepage: https://github.com/hammer-space/hstk
#
# Who runs SIPHON where:
#   - End users: run it from your own client machine (pip install hstk).
#   - Hammerspace personnel only: may run it on a Hammerspace DSX node.
#   - Nobody: DO NOT run this script on a Hammerspace Anvil.
# On a DSX node, start your own tmux session first and run SIPHON inside it;
# the script checks for this and exits if tmux is not in use.
#
# Share-to-volume selections are saved as defaults for future runs in:
#   ~/.hs_sum_volume_map      (override with HS_SUM_MAPFILE=/path)
# Result files are written to /tmp (override with HS_SUM_OUTDIR=/path).
# ==============================================================================

# Exit immediately if a command exits with a non-zero status, treat unset
# variables as an error, and ensure piped command failures propagate.
set -euo pipefail
IFS=$'\n\t'

# --- [ Terminal Styling & ANSI Definitions ] ---------------------------------
readonly CLR_RESET="\033[0m"
readonly CLR_BOLD="\033[1m"
readonly CLR_CYAN="\033[1;36m"
readonly CLR_BLUE="\033[0;34m"
readonly CLR_GRAY="\033[0;90m"

# --- [ Settings ] ------------------------------------------------------------
OUTDIR="${HS_SUM_OUTDIR:-/tmp}"
MAPFILE="${HS_SUM_MAPFILE:-$HOME/.hs_sum_volume_map}"
TAB=$'\t'
RUN_LIST=()          # entries: "share<TAB>volume", run in order
CHOSEN=()

# --- [ Banner Display Routine ] ----------------------------------------------
show_banner() {
    cat << "EOF"
  ███████╗██╗██████╗ ██╗  ██╗ ██████╗ ███╗   ██╗
  ██╔════╝██║██╔══██╗██║  ██║██╔═══██╗████╗  ██║
  ███████╗██║██████╔╝███████║██║   ██║██╔██╗ ██║
  ╚════██║██║██╔═══╝ ██╔══██║██║   ██║██║╚██╗██║
  ███████║██║██║     ██║  ██║╚██████╔╝██║ ╚████║
  ╚══════╝╚═╝╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
EOF
    echo -e "${CLR_CYAN}  Storage Ingestion Progress & High-volume Orchestration Navigator${CLR_RESET}"
    echo -e "${CLR_GRAY}  Hammerspace Ingestion & Telemetry Monitor v1.0.0${CLR_RESET}\n"
}

# Print the header comment block (used by -h / --help)
show_help() {
    sed -n '2,/^# What it does:/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
}

# --- [ Helpers ] -------------------------------------------------------------

# File modification time as "YYYY-MM-DD HH:MM:SS" (GNU stat, falls back to BSD/macOS stat)
file_mtime() {
    local t
    if t="$(stat -c '%y' "$1" 2>/dev/null)"; then
        printf '%s\n' "${t%%.*}"
    else
        stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "$1" 2>/dev/null || echo "unknown"
    fi
}

# Pull "files size" from the hs sum result line, e.g. {102580, 938.1625112339999}
get_values() {
    { grep -m1 -oE '\{[0-9]+, *[0-9.eE+-]+\}' "$1" || true; } | tr -d '{},'
}

# Compare previous vs. current values; values are expected to decrease
compare_values() {
    local old new
    old="$(get_values "$1")"
    new="$(get_values "$2")"
    if [[ -z "$old" || -z "$new" ]]; then
        echo "Change since previous run: could not compare (values missing from previous or current output)"
        return 0
    fi
    awk -v o="$old" -v n="$new" 'BEGIN {
        split(o, a, " "); split(n, b, " ")
        df = b[1] - a[1]; ds = b[2] - a[2]
        print "Change since previous run:"
        printf "  Files: %d -> %d (%+d)\n", a[1], b[1], df
        printf "  Size:  %.2f GB -> %.2f GB (%+.2f GB)\n", a[2], b[2], ds
        if (df > 0 || ds > 0)       print "  WARNING: value(s) INCREASED - expected a decrease"
        else if (df == 0 && ds == 0) print "  No change since previous run"
        else                         print "  OK: values decreased as expected"
    }'
}

# Turn a path/volume into a safe filename fragment
sanitize() {
    printf '%s' "$1" | sed -e 's#::#_#g' -e 's#[^A-Za-z0-9._-]#_#g' -e 's#__*#_#g' -e 's#^_##' -e 's#_$##'
}

# Join arguments with a space (IFS is newline/tab, so "${arr[*]}" won't do this)
join_sp() {
    local out="" x
    for x in "$@"; do out="${out:+$out }$x"; done
    printf '%s' "$out"
}

# Stop cleanly if input ends (e.g. Ctrl-D or a closed terminal) instead of looping
input_closed() { echo; echo "No input - exiting."; exit 1; }

# Ask a yes/no question until answered. $2 = default (y/n) or empty for "must answer"
ask_yn() {
    local prompt="$1" def="${2:-}" ans hint="(y/n)"
    if [[ "$def" == "y" ]]; then hint="(Y/n)"; fi
    if [[ "$def" == "n" ]]; then hint="(y/N)"; fi
    while true; do
        read -r -p "$prompt $hint: " ans || input_closed
        if [[ -z "$ans" ]]; then ans="$def"; fi
        case "$ans" in
            [yY]|[yY][eE][sS]) return 0 ;;
            [nN]|[nN][oO])     return 1 ;;
        esac
        echo "  Please answer y or n."
    done
}

# Saved volumes for a share (one per line)
saved_volumes() {
    if [[ -f "$MAPFILE" ]]; then
        awk -F'\t' -v s="$1" '$1 == s { print $2 }' "$MAPFILE"
    fi
    return 0
}

# Replace the saved mapping for a share with the given volumes ($2.. = volumes)
save_mapping() {
    local share="$1"; shift
    local tmp="${MAPFILE}.tmp.$$" v
    touch "$MAPFILE"
    awk -F'\t' -v s="$share" '$1 != s' "$MAPFILE" > "$tmp"
    for v in "$@"; do printf '%s\t%s\n' "$share" "$v" >> "$tmp"; done
    mv "$tmp" "$MAPFILE"
}

# Normalize a share path: strip trailing slashes (but keep "/")
normalize_path() {
    local p="$1"
    while [[ "$p" == */ && "$p" != "/" ]]; do p="${p%/}"; done
    printf '%s' "$p"
}

add_to_run() {
    local entry="$1${TAB}$2" e
    for e in ${RUN_LIST[@]+"${RUN_LIST[@]}"}; do
        if [[ "$e" == "$entry" ]]; then return 0; fi
    done
    RUN_LIST+=("$entry")
}

# Interactively choose volumes for a share via 'hs status volume'.
# Sets CHOSEN=() with the selected volume names.
choose_volumes() {
    local share="$1" out line i sel tok manual base mark bad
    local vols=() suggested=() toks=()
    CHOSEN=()

    echo
    echo "Running: hs status volume $share"
    out="$(hs status volume "$share" 2>&1)" || true
    echo "$out"

    # Volume names are the quoted strings in the output
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then vols+=("$line"); fi
    done < <(printf '%s\n' "$out" | { grep -oE '"[^"]+"' || true; } | tr -d '"')

    if [[ ${#vols[@]} -eq 0 ]]; then
        echo "No volumes found in the output (is the path a Hammerspace share?)."
        read -r -p "Type a volume name to use (blank to skip this share): " manual || input_closed
        if [[ -n "$manual" ]]; then CHOSEN=("$manual"); fi
        return 0
    fi

    # Suggest volumes whose path (after '::') ends with the share's last folder name
    base="$(basename "$share")"
    echo
    echo "Volumes connected to $share:"
    for i in "${!vols[@]}"; do
        mark="  "
        if [[ "${vols[$i]}" == *::* && "${vols[$i]##*/}" == "$base" ]]; then
            mark="* "; suggested+=("$((i+1))")
        fi
        printf '  %s%2d) %s\n' "$mark" "$((i+1))" "${vols[$i]}"
    done
    if [[ ${#suggested[@]} -gt 0 ]]; then echo "  (* = suggested match for '$base')"; fi

    while true; do
        echo
        echo "Select the volume(s) to measure migration progress from."
        echo "  Enter numbers separated by spaces or commas (e.g. 6  or  4,6)."
        if [[ ${#suggested[@]} -gt 0 ]]; then
            echo "  Press Enter to use the suggested: $(join_sp "${suggested[@]}")"
        fi
        echo "  'm' = type a volume name manually, 's' = skip this share"
        read -r -p "Selection: " sel || input_closed
        if [[ -z "$sel" && ${#suggested[@]} -gt 0 ]]; then sel="$(join_sp "${suggested[@]}")"; fi
        case "$sel" in
            s|S) return 0 ;;
            m|M)
                read -r -p "Volume name: " manual || input_closed
                if [[ -n "$manual" ]]; then CHOSEN=("$manual"); return 0; fi
                continue ;;
        esac
        CHOSEN=(); bad=0; toks=()
        IFS=' ,' read -r -a toks <<< "$sel" || true
        for tok in ${toks[@]+"${toks[@]}"}; do
            [[ -z "$tok" ]] && continue
            if [[ "$tok" =~ ^[0-9]+$ ]] && (( tok >= 1 && tok <= ${#vols[@]} )); then
                CHOSEN+=("${vols[$((tok-1))]}")
            else
                echo "  Invalid choice: $tok"; bad=1
            fi
        done
        if [[ $bad -eq 0 && ${#CHOSEN[@]} -gt 0 ]]; then return 0; fi
    done
}

# --- [ Preflight ] -----------------------------------------------------------
preflight() {
    echo "=================================================================="
    echo " Requires the Hammerspace Toolkit ('hs' command)."
    echo "   - Already installed on Hammerspace DSX nodes."
    echo "   - Non-Hammerspace hosts:  pip install hstk"
    echo "     (https://github.com/hammer-space/hstk)"
    echo " End users: run SIPHON from your own client machine."
    echo " Only Hammerspace personnel may run it on a DSX node (inside tmux)."
    echo " Do NOT run this script on a Hammerspace Anvil."
    echo "=================================================================="
    echo

    # Always confirm where we're running
    echo "Current host: $(hostname 2>/dev/null || echo unknown)"
    local hs_node
    if ask_yn "Are you running this on a Hammerspace Anvil?" ""; then
        echo
        echo -e "${CLR_BOLD}ERROR: This script must NOT be run from a Hammerspace Anvil.${CLR_RESET}"
        echo "End users: run it from your own client machine. Hammerspace personnel: use a DSX node."
        exit 1
    elif ask_yn "Are you running this on a Hammerspace DSX node?" ""; then
        hs_node=1
        echo "DSX node: only Hammerspace personnel may run SIPHON here."
        echo "          End users should run it from their own client machine instead."
        echo "DSX node: the Hammerspace Toolkit is already installed."

        # On a Hammerspace node the scans must run inside a tmux session that the
        # user started, so a dropped connection doesn't kill them.
        if [[ -z "${TMUX:-}" ]]; then
            echo
            echo -e "${CLR_BOLD}ERROR: Not running inside a tmux session.${CLR_RESET}"
            echo "On a Hammerspace node SIPHON must be run from within tmux; these scans"
            echo "can run for hours and would be killed if your connection drops."
            echo "Start a tmux session, then re-run this script from inside it."
            exit 1
        fi
        echo "Running inside tmux session: $(tmux display-message -p '#S' 2>/dev/null || echo unknown)"
    else
        hs_node=0
        echo "Non-Hammerspace host: the Hammerspace Toolkit must be installed (pip install hstk)."
    fi

    if ! command -v hs >/dev/null 2>&1; then
        echo
        echo "ERROR: 'hs' command not found - the Hammerspace Toolkit is not installed or not on PATH."
        if [[ $hs_node -eq 1 ]]; then
            echo "It is normally present on DSX nodes; check your PATH."
        else
            echo "Install it with:  pip install hstk"
            echo "(Homepage: https://github.com/hammer-space/hstk)"
        fi
        exit 1
    fi

    HAVE_UPLOAD=1
    if ! command -v upload >/dev/null 2>&1; then
        HAVE_UPLOAD=0
        echo "NOTE: 'upload' command not found on this host - result files will be saved but not uploaded."
    fi

    mkdir -p "$OUTDIR" || { echo "ERROR: cannot create output folder $OUTDIR"; exit 1; }
}

# --- [ Choose shares & volumes ] ---------------------------------------------
select_targets() {
    local prompt share s v e use_saved
    local saved=()

    if [[ -s "$MAPFILE" ]]; then
        echo
        echo "Saved share -> volume defaults ($MAPFILE):"
        awk -F'\t' '{ printf "  %s  ->  %s\n", $1, $2 }' "$MAPFILE"
    fi

    echo
    echo "Share path examples:"
    echo "  DSX:            /mnt/smb-data-portal/<sharename>/<optional/subfolder/path>"
    echo "  Remote client:  the share's mapped drive or mount point (e.g. /Volumes/Projects, /mnt/z)"

    while true; do
        echo
        prompt="Enter a Hammerspace share path"
        if [[ ${#RUN_LIST[@]} -gt 0 ]]; then prompt="Enter another share path (blank = start scanning)"; fi
        if [[ -s "$MAPFILE" ]]; then prompt="$prompt ['all' = every saved share]"; fi
        read -r -p "$prompt: " share || input_closed

        if [[ -z "$share" ]]; then
            if [[ ${#RUN_LIST[@]} -gt 0 ]]; then break; fi
            echo "  Please enter a share path."; continue
        fi

        if [[ "$share" == "all" && -s "$MAPFILE" ]]; then
            while IFS="$TAB" read -r s v; do
                if [[ -n "$s" && -n "$v" ]]; then add_to_run "$s" "$v"; fi
            done < "$MAPFILE"
            echo "  Added all saved shares."
        else
            share="$(normalize_path "$share")"
            if [[ ! -d "$share" ]]; then
                echo "  WARNING: $share is not a directory on this host."
                ask_yn "  Use it anyway?" n || continue
            fi

            saved=()
            while IFS= read -r v; do
                if [[ -n "$v" ]]; then saved+=("$v"); fi
            done < <(saved_volumes "$share")

            use_saved=0
            if [[ ${#saved[@]} -gt 0 ]]; then
                echo "  Saved default volume(s) for this share:"
                printf '    %s\n' "${saved[@]}"
                if ask_yn "  Use the saved volume(s)?" y; then use_saved=1; fi
            fi

            if [[ $use_saved -eq 1 ]]; then
                CHOSEN=("${saved[@]}")
            else
                choose_volumes "$share"
                if [[ ${#CHOSEN[@]} -eq 0 ]]; then echo "  Skipped $share."; continue; fi
                save_mapping "$share" "${CHOSEN[@]}"
                echo "  Saved as the default for $share."
            fi
            for v in "${CHOSEN[@]}"; do add_to_run "$share" "$v"; done
        fi

        echo
        echo "Scan list so far:"
        for e in ${RUN_LIST[@]+"${RUN_LIST[@]}"}; do
            printf '  %s  ->  %s\n' "${e%%"$TAB"*}" "${e#*"$TAB"}"
        done
        ask_yn "Add another share path?" n || break
    done
}

# --- [ Run scans ] -----------------------------------------------------------
run_scans() {
    local entry share volume name outfile legacy prev_finish prev_start prev_note vals rc
    local summary=()

    echo
    echo "Starting ${#RUN_LIST[@]} scan(s), one after the other."

    for entry in "${RUN_LIST[@]}"; do
        share="${entry%%"$TAB"*}"
        volume="${entry#*"$TAB"}"
        name="$(basename "$share")"
        outfile="${OUTDIR}/hs_sum_$(sanitize "$name")__$(sanitize "$volume").txt"

        # Carry over history from the original script's file name (hs_sum_<share>.txt)
        legacy="${OUTDIR}/hs_sum_${name}.txt"
        if [[ ! -f "$outfile" && -f "$legacy" ]]; then
            if [[ "$(sed -n '2p' "$legacy")" == "$share" || "$(sed -n '1p' "$legacy")" == "$share" ]]; then
                cp -p "$legacy" "$outfile"
            fi
        fi

        # Note when the previous run happened. The file's timestamp is when it was
        # last written, i.e. when the previous command FINISHED. The start time is
        # read from the "Started:" line inside the file, if present.
        if [[ -f "$outfile" ]]; then
            prev_finish="$(file_mtime "$outfile")"
            prev_start="$({ grep -m1 '^Started:' "$outfile" || true; } | sed 's/^Started: *//')"
            prev_note="Previous run: finished ${prev_finish}"
            if [[ -n "$prev_start" ]]; then
                prev_note="Previous run: started ${prev_start}, finished ${prev_finish}"
            fi
            cp -p "$outfile" "${outfile}.prev"   # keep last results for comparison
        else
            prev_note="Previous run: none (no previous results stored)"
        fi

        echo
        echo -e "${CLR_BLUE}=== ${share}  [volume: ${volume}] ===${CLR_RESET}"

        # Start time, share path, volume, command output, finish time, previous-run note
        echo "Started:  $(date '+%Y-%m-%d %H:%M:%S')" > "$outfile"
        echo "$share" >> "$outfile"
        echo "Volume:   $volume" >> "$outfile"
        rc=0
        hs sum -e "IS_FILE AND NOT ISNA(INSTANCES[|VOLUME=STORAGE_VOLUME('${volume}')])>0 AND ROWS(INSTANCES[|VOLUME=STORAGE_VOLUME('${volume}')])>0 ?{1FILE/FILES,SIZE/GBYTES}" "$share" >> "$outfile" 2>&1 || rc=$?
        if [[ $rc -ne 0 ]]; then echo "ERROR: hs sum exited with status $rc" >> "$outfile"; fi
        echo "Finished: $(date '+%Y-%m-%d %H:%M:%S')" >> "$outfile"
        echo "$prev_note" >> "$outfile"

        # Compare with previous results, if any
        if [[ -f "${outfile}.prev" && "$prev_note" != *"none"* ]]; then
            compare_values "${outfile}.prev" "$outfile" >> "$outfile"
        fi

        cat "$outfile"
        vals="$(get_values "$outfile")"
        summary+=("$(printf '%-45s %-42s %s' "$share" "$volume" "${vals:-<no result>}")")

        # Upload the result file
        if [[ $HAVE_UPLOAD -eq 1 ]]; then
            (cd "$OUTDIR" && upload "$(basename "$outfile")") || echo "WARNING: upload of $(basename "$outfile") failed"
        fi
    done

    echo
    echo "================================ Summary ================================"
    printf '%-45s %-42s %s\n' "Share" "Volume" "Files  GB"
    printf '%s\n' "${summary[@]}"
    echo
    echo "Done. Results saved in ${OUTDIR}/hs_sum_*.txt"
    if [[ $HAVE_UPLOAD -eq 0 ]]; then
        echo "(Not uploaded - 'upload' command not available on this host.)"
    fi
}

# --- [ Entry Point / Execution ] ---------------------------------------------
main() {
    # Render the banner to the terminal upon execution
    show_banner

    case "${1:-}" in
        -h|--help) show_help; exit 0 ;;
        "") ;;
        *) echo "NOTE: command-line options other than -h/--help are not implemented yet; ignoring: $*"; echo ;;
    esac

    preflight
    select_targets
    run_scans
}

main "$@"
