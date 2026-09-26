#!/usr/bin/env bash
# GLM-5.3-Flash EXL3 on 2x GB10 — fetch the pinned MiaAI-Lab kit, apply this
# recipe's launcher patch and settings, then hand over to the kit's start.sh.
#
#   ./run.sh            start (or attach if already healthy)
#   ./run.sh restart    restart with the current recipe.env
#   ./run.sh <cmd>      any other kit start.sh subcommand (status, logs, ...)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$HERE/kit"
PATCH="$HERE/patches/dual-rail-launcher.patch"

log() { printf '\033[1;36m[recipe]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[recipe] %s\033[0m\n' "$*" >&2; exit 1; }

[ -f "$HERE/recipe.env" ] || die "recipe.env missing"
# shellcheck disable=SC1091
set -a; . "$HERE/recipe.env"; set +a
: "${KIT_REPO:?}" "${KIT_COMMIT:?}" "${IMAGE:?}"

# 1. kit at the pinned commit
if [ ! -d "$KIT/.git" ]; then
    log "cloning $KIT_REPO"
    git clone -q "$KIT_REPO" "$KIT"
fi
if [ "$(git -C "$KIT" rev-parse --short=7 HEAD)" != "${KIT_COMMIT:0:7}" ]; then
    git -C "$KIT" diff --quiet || die "kit/ has local edits and is not at $KIT_COMMIT — move them aside first"
    git -C "$KIT" fetch -q origin
    git -C "$KIT" checkout -q "$KIT_COMMIT"
    log "kit pinned at $KIT_COMMIT"
fi

# 2. launcher patch (idempotent)
if git -C "$KIT" apply --reverse --check "$PATCH" 2>/dev/null; then
    :
elif git -C "$KIT" apply --check "$PATCH" 2>/dev/null; then
    git -C "$KIT" apply "$PATCH"
    log "applied $(basename "$PATCH")"
else
    die "$(basename "$PATCH") does not apply to kit@$KIT_COMMIT — kit/start.sh was edited by hand?"
fi

# 3. compose kit/.env = kit defaults + this recipe (later lines win)
{
    cat "$KIT/.env.example"
    printf '\n# ==== recipe.env (%s) ====\n' "$(date -u +%FT%TZ)"
    grep -v -E '^(KIT_REPO|KIT_COMMIT|HEAD_DOCKER_SUDO)=' "$HERE/recipe.env"
} > "$KIT/.env"

# 4. adaptive-k runtime tuning (read live by the server; no restart needed to retune)
CACHE_ROOT="${CACHE_ROOT:-$HOME/.cache/vllm-glm53-flash}"
mkdir -p "$CACHE_ROOT"
cp "$HERE/adaptive_k.json" "$CACHE_ROOT/glm53_adaptive_k.json"

# 5. docker through sudo on the head if requested (worker: WORKER_DOCKER_SUDO)
if [ "${HEAD_DOCKER_SUDO:-0}" = "1" ]; then
    docker() { sudo -n /usr/bin/docker "$@"; }
    export -f docker
fi

# 6. first run builds the image from the pinned kit (the launcher ships it to the worker)
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    log "image $IMAGE not found — building from kit@$KIT_COMMIT (first run only)"
    export BUILD=1
fi

cd "$KIT"
exec ./start.sh "$@"
