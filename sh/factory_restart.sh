#!/bin/sh
# Copyright 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This script restarts factory test program.

SCRIPT="$0"

. "$(dirname "$(readlink -f "${SCRIPT}")")"/common.sh

# Restart without session ID, the parent process may be one of the
# processes we plan to kill.
if [ -z "$_DAEMONIZED" ]; then
  _DAEMONIZED=TRUE setsid "$SCRIPT" "$@"
  exit $?
fi

# Add /sbin to PATH; that's usually where stop and start are, and
# /sbin may not be in the path.
PATH=/sbin:"$PATH"

usage_help() {
  echo "usage: $SCRIPT [options]
    options:
      -s | state:   clear state files ($FACTORY_BASE/state)
      -l | log:     clear factory log files ($FACTORY_BASE/log)
      -t | tests:   clear test data ($FACTORY_BASE/tests)
      -r | run:     clear run data (/run/factory)
      -a | all:     clear all of the above data
      -d | vpd:     clear VPD
      -c | chrome:  restart Chrome (UI)
      -h | help:    this help screen
      --automation-mode MODE:
                    set factory automation mode (none, partial, full);
                    default: none
      --no-auto-run-on-start:
                    do not automatically run test list when Goofy starts
  "
}

kill_tree() {
  local signal="${1:-TERM}"
  local pid
  shift

  # $* may contain spaces so we cannot quote it.
  # shellcheck disable=SC2048
  for pid in $*; do
    printf "%s " "${pid}"
    # ps output may contain leading space so we have to unquote it.
    kill_tree "${signal}" "$(ps -o pid --no-headers --ppid "${pid}")"
    kill "-${signal}" "${pid}" 2>/dev/null
  done
}

clear_vpd() {
  local region

  # $* may contain spaces so we cannot quote it.
  # shellcheck disable=SC2048
  for region in $*; do
    echo "Clearing ${region} VPD region..."
    vpd -i "${region}_VPD" -O
  done
}

clear_data() {
  local data
  if [ -z "$*" ]; then
    return
  fi

  echo "Clear data: $*"
  # $* may contain spaces so we cannot quote it.
  # shellcheck disable=SC2048
  for data in $*; do
    rm -rf "${data}"
    mkdir -p "${data}"
  done
}

stop_services() {
  local service
  # Ensure full stop (instead of 'restart'), we don't want to have the same
  # factory process recycled after we've been killing bits of it. Also because we
  # need two jobs (factory and ui) both restarted.

  # $* may contain spaces so we cannot quote it.
  # shellcheck disable=SC2048
  for service in $*; do
    (status "${service}" | grep -q 'stop/waiting') || stop "${service}"
  done
}

stop_session() {
  local goofy_control_pid="$(pgrep goofy_control)"
  local sec

  printf "Attempt to stop gracefully... "
  # save pids in case their parents die and they are orphaned
  local all_pids="$(kill_tree TERM "${goofy_control_pid}")"
  for sec in 3 2 1; do
    printf "%s " "${sec}"
    sleep 1
  done

  printf "Stopping factory test programs... "
  # all_pids must be passed as individual parameters so we should not quote it.
  kill_tree KILL "${all_pids}" > /dev/null
  echo "done."
}

enable_automation() {
  local automation_mode="$1"
  local stop_auto_run_on_start="$2"

  find "${FACTORY_BASE}" -wholename "${AUTOMATION_MODE_TAG_FILE}" -delete
  if [ "${automation_mode}" != "none" ]; then
    echo "Enable factory test automation with mode: ${automation_mode}"
    echo "${automation_mode}" > "${AUTOMATION_MODE_TAG_FILE}"
    if "${stop_auto_run_on_start}"; then
      touch "${STOP_AUTO_RUN_ON_START_TAG_FILE}"
    else
      rm -f "${STOP_AUTO_RUN_ON_START_TAG_FILE}"
    fi
  fi
}

main() {
  local data=""
  local vpd=""
  local services="factory"
  local stop_auto_run_on_start=false automation_mode="none"
  # TODO(hungte) Find right URL for presenter mode.
  local chrome_url="http://127.0.0.1:4012"

  while [ $# -gt 0 ]; do
    opt="$1"
    shift
    case "${opt}" in
      -l | log )
        data="${data} ${FACTORY_BASE}/log"
        ;;
      -s | state )
        data="${data} ${FACTORY_BASE}/state"
        ;;
      -t | tests )
        data="${data} ${FACTORY_BASE}/tests"
        ;;
      -r | run )
        data="${data} /run/factory"
        ;;
      -a | all )
        data="${data} ${FACTORY_BASE}/log ${FACTORY_BASE}/state"
        data="${data} ${FACTORY_BASE}/tests /run/factory"
        ;;
      -c | chrome )
        chrome_url=""
        services="${services} ui"
        ;;
      -d | vpd )
        vpd="${vpd} RO RW"
        ;;
      -h | help )
        usage_help
        exit 0
        ;;
      --automation-mode )
        case "$1" in
          none | partial | full )
            automation_mode="$1"
            shift
            ;;
          * )
            usage_help
            exit 1
            ;;
        esac
        ;;
      --no-auto-run-on-start )
        stop_auto_run_on_start=true
        ;;
      * )
        echo "Unknown option: $opt"
        usage_help
        exit 1
        ;;
    esac
  done

  if [ -n "${chrome_url}" ]; then
    chrome_openurl "${chrome_url}/restarting.html"
  fi

  stop_session
  stop_services "${services}"
  clear_data "${data}"
  clear_vpd "${vpd}"
  enable_automation "${automation_mode}" "${stop_auto_run_on_start}"

  echo "Restarting factory session..."
  start factory
}
main "$@"
