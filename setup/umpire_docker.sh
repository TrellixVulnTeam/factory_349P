#!/bin/bash
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#


SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

. "${SCRIPT_DIR}/cros_docker.sh"

UMPIRE_IMAGE_FILEPATH="${SCRIPT_DIR}/${UMPIRE_IMAGE_FILENAME}"

# Separate umpire db for each container.
HOST_DB_DIR="/docker_umpire/${UMPIRE_CONTAINER_NAME}"
CONTAINER_DB_DIR="/var/db/factory/umpire"

. ${UMPIRE_BUILD_DIR}/config.sh

UMPIRE_DOCKERFILE="${UMPIRE_BUILD_DIR}/Dockerfile"
FACTORY_DIR="$(dirname "${SCRIPT_DIR}")"

check_status() {
  local container_name="$1"
  local status="$(${DOCKER} ps | grep ${container_name} | grep Up)"

  if [ -z "${status}" ]; then
    die "${UMPIRE_CONTAINER_NAME} container is not running"
  fi
}

do_shell() {
  check_docker

  local container_name="$1"
  check_status "${container_name}"
  shift

  ${DOCKER} exec -it "${container_name}" bash
}

do_build() {
  check_docker

  # Use prebuilt image if we can.
  do_pull

  if [ -f "${UMPIRE_IMAGE_FILEPATH}" ]; then
    echo "Found prebuilt image ${UMPIRE_IMAGE_FILEPATH}"
    if ${DOCKER} load <"${UMPIRE_IMAGE_FILEPATH}"; then
      return
    else
      # the prebuilt image is corrupted, remove it.
      rm -f "${UMPIRE_IMAGE_FILEPATH}"
      echo "Load prebuilt image fail! start building image."
    fi
  fi

  ${DOCKER} build \
    --file "${UMPIRE_DOCKERFILE}" \
    --tag "${UMPIRE_IMAGE_NAME}" \
    "${FACTORY_DIR}"
  if [ $? -eq 0 ]; then
    echo "${UMPIRE_CONTAINER_NAME} container successfully built."
  fi
}

do_pull() {
  # check the file locally first if we run the script twice we don't need to
  # download it again.
  if [ ! -f "${UMPIRE_IMAGE_FILEPATH}" ]; then
    wget -P "${SCRIPT_DIR}" \
      "${PREBUILT_IMAGE_DIR_URL}/${UMPIRE_IMAGE_FILENAME}" || \
      rm -f "${UMPIRE_IMAGE_FILEPATH}"
  fi
}

do_destroy() {
  check_docker

  echo -n "Deleting ${UMPIRE_CONTAINER_NAME} container ... "
  ${DOCKER} stop "${UMPIRE_CONTAINER_NAME}" >/dev/null 2>&1
  ${DOCKER} rm "${UMPIRE_CONTAINER_NAME}" >/dev/null 2>&1
  echo "done"
}

do_start() {
  check_docker

  echo -n 'Starting container ... '
  sudo mkdir -p ${DOCKER_SHARED_DIR}
  sudo mkdir -p ${HOST_DB_DIR}

  if [ -n "$(${DOCKER} ps --all --format {{.Names}} | \
      grep ^${UMPIRE_CONTAINER_NAME}$)" ]; then
    if [ -z "$(${DOCKER} ps --all --format '{{.Names}} {{.Image}}' | \
        grep ^${UMPIRE_CONTAINER_NAME}\ ${UMPIRE_IMAGE_NAME}$)" ]; then
      warn "A container with name ${UMPIRE_CONTAINER_NAME} exists," \
           'but is using an old image.'
    fi
    ${DOCKER} start "${UMPIRE_CONTAINER_NAME}"
  else
    local p1=${UMPIRE_PORT}              # Imaging & Shopfloor
    local p2=$(expr ${UMPIRE_PORT} + 2)  # CLI RPC
    local p3=$(expr ${UMPIRE_PORT} + 4)  # Rsync
    local umpire_port_map="-p $p1:$p1 -p $p2:$p2 -p $p3:$p3"

    ${DOCKER} run -d \
      --privileged \
      -p 4455:4455 \
      -p 9000:9000 \
      ${umpire_port_map} \
      -v /etc/localtime:/etc/localtime:ro \
      -v ${DOCKER_SHARED_DIR}:/mnt \
      -v ${HOST_DB_DIR}:${CONTAINER_DB_DIR} \
      --restart unless-stopped \
      --name "${UMPIRE_CONTAINER_NAME}" \
      "${UMPIRE_IMAGE_NAME}"

    if [ $? -ne 0 ]; then
      echo -n 'Removing stale container due to error ... '
      ${DOCKER} rm ${UMPIRE_CONTAINER_NAME}
      echo 'Possibly wrong port binding? Please fix and retry.'
      return
    fi
  fi

  if [ $? -eq 0 ]; then
    echo 'done'
    echo
    echo '*** NOTE ***'
    echo "- Host directory ${DOCKER_SHARED_DIR} is mounted" \
         'under /mnt in the container.'
    echo "- Host directory ${HOST_DB_DIR} is mounted" \
         "under ${CONTAINER_DB_DIR} in the container."
    echo '- Umpire service ports is mapped to the local machine.'
    echo '- Overlord service ports 4455, 9000 are mapped to the local machine.'
  fi
}

do_stop() {
  check_docker

  echo -n "Stopping ${UMPIRE_CONTAINER_NAME} container ... "
  ${DOCKER} stop "${UMPIRE_CONTAINER_NAME}" >/dev/null 2>&1
  echo "done"
}

usage() {
  cat << __EOF__
Usage: $0 COMMAND [arg ...]

Commands:
    build       build umpire container
    pull        pull umpire image down
    destroy     destroy umpire container
    start       start umpire container
    stop        stop umpire container
    shell (ssh) invoke a shell (bash) inside umpire container
    help        Show this help message

Options:
    -h, --help  Show this help message
__EOF__
}

main() {

  case "$1" in
    build)
      do_build
      ;;
    pull)
      do_pull
      ;;
    destroy)
      do_destroy
      ;;
    start)
      do_start
      ;;
    stop)
      do_stop
      ;;
    ssh | shell)
      shift
      do_shell "${UMPIRE_CONTAINER_NAME}" "$@"
      ;;
    *|help|-h|--help)
      usage
      ;;
  esac
}

main "$@"
