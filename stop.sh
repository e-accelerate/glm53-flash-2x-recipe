#!/usr/bin/env bash
# Stop both ranks through the kit's own stop path.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -d "$HERE/kit" ] || { echo "nothing to stop (kit/ not fetched yet)"; exit 0; }
# shellcheck disable=SC1091
set -a; . "$HERE/recipe.env"; set +a
if [ "${HEAD_DOCKER_SUDO:-0}" = "1" ]; then
    docker() { sudo -n /usr/bin/docker "$@"; }
    export -f docker
fi
cd "$HERE/kit"
exec ./start.sh stop
