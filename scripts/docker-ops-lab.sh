#!/usr/bin/env bash

# Repeatable Linux practice using the project's existing images. The only
# disposable data is a labelled lab volume; the application's /data is read-only.
set -euo pipefail

readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly LAB_STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
readonly LAB_TOKEN="$(date -u '+%Y%m%d%H%M%S')-${$}-${RANDOM}"
readonly LAB_NAME="agent-platform-ops-lab-${LAB_TOKEN}"
readonly LAB_VOLUME="${LAB_NAME}-data"
readonly LAB_LABEL="com.agent-platform.ops-lab"
VOLUME_CREATED=0
PASSED=0

cd "${REPO_ROOT}"

pass() {
    PASSED=$((PASSED + 1))
    printf '[PASS %s] %s\n' "${PASSED}" "$1"
}

cleanup() {
    local status=$?
    local owner
    trap - EXIT ERR
    set +e
    # Remove only objects carrying this invocation's exact ownership token.
    owner="$(docker inspect --format "{{index .Config.Labels \"${LAB_LABEL}\"}}" "${LAB_NAME}" 2>/dev/null)"
    if [[ "${owner}" == "${LAB_TOKEN}" ]]; then
        docker rm -f "${LAB_NAME}" >/dev/null || status=1
    fi
    if (( VOLUME_CREATED == 1 )); then
        owner="$(docker volume inspect --format "{{index .Labels \"${LAB_LABEL}\"}}" "${LAB_VOLUME}" 2>/dev/null)"
        if [[ "${owner}" == "${LAB_TOKEN}" ]]; then
            if docker volume rm "${LAB_VOLUME}" >/dev/null; then
                printf 'Removed disposable lab volume: %s (test markers only).\n' "${LAB_VOLUME}"
            else
                printf 'Cleanup incomplete; retained lab volume: %s\n' "${LAB_VOLUME}" >&2
                status=1
            fi
        else
            printf 'Volume ownership mismatch; cleanup refused.\n' >&2
            status=1
        fi
    fi
    if (( status == 0 )); then
        printf '\n%s/8 exercises passed; application services remain running.\n' "${PASSED}"
    else
        printf '\nLab stopped after %s/8 exercises (exit %s); application data is retained.\n' "${PASSED}" "${status}" >&2
    fi
    exit "${status}"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

expect_failure() {
    local pattern="$1"
    local output
    local status
    shift
    if output="$("$@" 2>&1)"; then
        printf 'Expected failure did not occur.\n' >&2
        return 1
    else
        status=$?
    fi
    if ! printf '%s\n' "${output}" | grep -Eiq "${pattern}"; then
        printf 'Unexpected failure type (exit %s); stopping the exercise.\n' "${status}" >&2
        return 1
    fi
    # Only this helper's controlled, synthetic test commands may call it.
    printf 'Expected failure (exit %s): %s\n' "${status}" "${output}"
}

redact_logs() {
    sed -E \
        -e 's/sk-[[:alnum:]_-]{16,}/[REDACTED_OPENAI_KEY]/g' \
        -e "s/([\"']?[[:alnum:]_]*(api_key|token|secret|password)[\"']?[[:space:]]*[:=][[:space:]]*[\"']?)[^\"'[:space:],}]+/\\1[REDACTED]/Ig" \
        -e "s/(authorization[\"']?[[:space:]]*[:=][[:space:]]*[\"']?bearer[[:space:]]+)[^\"'[:space:],}]+/\\1[REDACTED]/Ig" \
        -e '/-----BEGIN ([[:alnum:]]+ )?PRIVATE KEY-----/,/-----END ([[:alnum:]]+ )?PRIVATE KEY-----/c\
[REDACTED PRIVATE KEY]'
}

lab_run() {
    docker run --rm --pull never --name "${LAB_NAME}" \
        --label "${LAB_LABEL}=${LAB_TOKEN}" \
        --security-opt no-new-privileges:true \
        "$@" --entrypoint sh "${LAB_IMAGE}" -eu -c "${LAB_COMMAND}"
}

command -v docker >/dev/null
command -v curl >/dev/null
docker info >/dev/null
docker compose config --quiet
docker compose up -d --no-build --wait --wait-timeout 60

BACKEND_ID="$(docker compose ps -q backend)"
FRONTEND_ID="$(docker compose ps -q frontend)"
for container_id in "${BACKEND_ID}" "${FRONTEND_ID}"; do
    [[ "$(docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' "${container_id}")" == 'running healthy' ]]
done
docker compose ps
pass 'Start services and verify both health checks'

docker compose exec -T backend sh -c 'uname -srm; id; pwd; ls -ldn /data; ls -ln /data/agent-platform.db'
docker compose exec -T frontend sh -c 'id; ps; netstat -lnt'
[[ "$(docker compose exec -T backend id -u)" != '0' ]]
[[ "$(docker compose exec -T frontend id -u)" != '0' ]]
pass 'Read Linux processes, listeners, UID/GID and file permissions'

# Use the actual published binding, including an overridden Compose host port.
FRONTEND_BINDING="$(docker compose port frontend 8080)"
ORIGIN="http://${FRONTEND_BINDING}"
BACKEND_BINDINGS="$(docker inspect --format '{{json (index .NetworkSettings.Ports "8000/tcp")}}' "${BACKEND_ID}")"
[[ "${BACKEND_BINDINGS}" == 'null' || "${BACKEND_BINDINGS}" == '[]' ]]
printf 'Published frontend: %s; backend: no host binding\n' "${ORIGIN}"
curl --noproxy '*' --fail --silent --show-error --max-time 10 \
    "${ORIGIN}/api/v1/health/live"
printf '\n'
docker compose logs --no-color --tail=20 --since "${LAB_STARTED_AT}" | redact_logs
pass 'Verify host port, HTTP response and recent service logs'

# 127.0.0.1 here means frontend itself. The API listens in backend instead.
expect_failure 'connection refused' docker compose exec -T frontend \
    wget -T 3 -qO- http://127.0.0.1:8000/api/v1/health/live
docker compose exec -T frontend wget -T 3 -qO- http://backend:8000/api/v1/health/live
printf '\n'
pass 'Diagnose connection refused and recover using the service name'

LAB_IMAGE="$(docker inspect --format '{{.Image}}' "${FRONTEND_ID}")"
LAB_NETWORK="$(docker inspect --format '{{range $name, $value := .NetworkSettings.Networks}}{{println $name}}{{end}}' "${FRONTEND_ID}" | sed -n '1p')"
[[ -n "${LAB_NETWORK}" ]]
docker inspect --format '{{range $name, $value := .NetworkSettings.Networks}}{{println $name}}{{end}}' "${BACKEND_ID}" | grep -Fxq "${LAB_NETWORK}"
LAB_COMMAND='wget -T 3 -qO- http://backend:8000/api/v1/health/live'
expect_failure 'bad address|name or service not known|temporary failure' lab_run --network none
lab_run --network "${LAB_NETWORK}"
printf '\n'
pass 'Diagnose missing Docker DNS/network access and recover on the shared network'

# A fresh labelled volume is the only place where root creates or repairs files.
if docker volume inspect "${LAB_VOLUME}" >/dev/null 2>&1; then
    printf 'Lab volume already exists; refusing to reuse it.\n' >&2
    exit 1
fi
docker volume create --label "${LAB_LABEL}=${LAB_TOKEN}" "${LAB_VOLUME}" >/dev/null
VOLUME_CREATED=1
LAB_COMMAND='mkdir /lab/private; chmod 700 /lab/private; chown 0:0 /lab/private; ls -ldn /lab/private'
lab_run --network none --user 0:0 --mount "type=volume,source=${LAB_VOLUME},target=/lab"
LAB_COMMAND='touch /lab/private/marker'
expect_failure 'permission denied' lab_run --network none --user 101:101 \
    --mount "type=volume,source=${LAB_VOLUME},target=/lab"
LAB_COMMAND='chown 101:101 /lab/private; chmod 750 /lab/private; ls -ldn /lab/private'
lab_run --network none --user 0:0 --mount "type=volume,source=${LAB_VOLUME},target=/lab"
LAB_COMMAND='id; touch /lab/private/marker /tmp/lab-layer-marker; ls -ln /lab/private/marker'
lab_run --network none --user 101:101 --mount "type=volume,source=${LAB_VOLUME},target=/lab"
pass 'Reproduce permission denied, fix ownership and mode, verify non-root writes'

# Every lab_run is a new container. Its /tmp is new; the named volume is reused.
LAB_COMMAND='test -f /lab/private/marker; test ! -e /tmp/lab-layer-marker; echo "Named-volume marker survived; previous container-layer marker is absent."'
lab_run --network none --user 101:101 --mount "type=volume,source=${LAB_VOLUME},target=/lab"
pass 'Recreate a disposable container and verify named-volume persistence'

docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}volume={{.Name}} destination={{.Destination}} writable={{.RW}}{{end}}{{end}}' "${BACKEND_ID}"
docker compose exec -T backend python -c '
import sqlite3
with sqlite3.connect("file:/data/agent-platform.db?mode=ro", uri=True) as connection:
    for table in ("jobs", "agent_runs", "artifact_records"):
        count = connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        print(f"Existing {table}: {count}")
'
curl --noproxy '*' --fail --silent --show-error --max-time 10 "${ORIGIN}/api/v1/health/live"
printf '\n'
pass 'Read existing application volume and confirm service recovery'
