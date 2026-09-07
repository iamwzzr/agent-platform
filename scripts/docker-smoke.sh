#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly SMOKE_STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
readonly HOST_ARTIFACT_MARKER=".agent-platform-host-artifact-${$}-${RANDOM}"
readonly LOG_FAILURE_PATTERN="traceback|permission denied|sk-[[:alnum:]_-]{16,}|[\"']?[[:alnum:]_]*(api_key|token|secret|password)[\"']?[[:space:]]*[:=][[:space:]]*[\"']?[^\"'[:space:],}]+|authorization[\"']?[[:space:]]*[:=][[:space:]]*[\"']?bearer[[:space:]]+[^\"'[:space:],}]+|begin ([[:alnum:]]+ )?private key"

declare -a HOST_MARKER_PATHS=()
COMPOSE_AVAILABLE=0
LOG_FILE=""

cd "${REPO_ROOT}"

cleanup_local_artifacts() {
    local path

    for path in "${HOST_MARKER_PATHS[@]:-}"; do
        if [[ -n "${path}" ]]; then
            rm -f -- "${path}"
        fi
    done
    HOST_MARKER_PATHS=()

    if [[ -n "${LOG_FILE}" ]]; then
        rm -f -- "${LOG_FILE}"
    fi
}

redact_sensitive_values() {
    sed -E \
        -e 's/sk-[[:alnum:]_-]{16,}/[REDACTED_OPENAI_KEY]/g' \
        -e "s/([\"']?[[:alnum:]_]*(api_key|token|secret|password)[\"']?[[:space:]]*[:=][[:space:]]*[\"']?)[^\"'[:space:],}]+/\\1[REDACTED]/Ig" \
        -e "s/(authorization[\"']?[[:space:]]*[:=][[:space:]]*[\"']?bearer[[:space:]]+)[^\"'[:space:],}]+/\\1[REDACTED]/Ig" \
        -e '/-----BEGIN ([[:alnum:]]+ )?PRIVATE KEY-----/,/-----END ([[:alnum:]]+ )?PRIVATE KEY-----/c\
[REDACTED PRIVATE KEY]'
}

print_current_compose_logs() {
    if (( COMPOSE_AVAILABLE == 0 )); then
        printf '%s\n' 'Compose was not available, so no service logs can be shown.' >&2
        return
    fi

    printf '%s\n' "--- Compose logs since ${SMOKE_STARTED_AT} (suspected credentials redacted) ---" >&2
    if ! docker compose logs --no-color --since "${SMOKE_STARTED_AT}" 2>&1 \
        | redact_sensitive_values >&2; then
        printf '%s\n' 'Unable to read Compose logs.' >&2
    fi
    printf '%s\n' '--- End Compose logs ---' >&2
}

on_error() {
    local exit_code=$?
    local line_number="${1:-unknown}"

    trap - ERR
    set +e
    printf 'Docker smoke failed at line %s (exit %s).\n' \
        "${line_number}" "${exit_code}" >&2
    print_current_compose_logs
    printf '%s\n' \
        'Services and volumes were left intact for diagnosis; no compose down was run.' >&2
    exit "${exit_code}"
}

on_exit() {
    local exit_code=$?

    trap - ERR
    set +e
    cleanup_local_artifacts
    exit "${exit_code}"
}

trap 'on_error "${LINENO}"' ERR
trap on_exit EXIT

require_command() {
    local command_name="$1"

    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'Required command is missing: %s\n' "${command_name}" >&2
        return 1
    fi
}

create_host_artifact_markers() {
    local artifact_dir
    local marker_path

    while IFS= read -r artifact_dir; do
        if [[ ! -w "${artifact_dir}" ]]; then
            printf 'Cannot create host-artifact marker in %s\n' "${artifact_dir}" >&2
            return 1
        fi
        marker_path="${artifact_dir}/${HOST_ARTIFACT_MARKER}"
        printf '%s\n' "${HOST_ARTIFACT_MARKER}" >"${marker_path}"
        HOST_MARKER_PATHS+=("${marker_path}")
    done < <(
        find "${REPO_ROOT}" -type d \
            \( -name .venv -o -name node_modules \) \
            -prune -print
    )
}

remove_host_artifact_markers() {
    local path

    for path in "${HOST_MARKER_PATHS[@]:-}"; do
        if [[ -n "${path}" ]]; then
            rm -f -- "${path}"
        fi
    done
    HOST_MARKER_PATHS=()
}

assert_non_root_service() {
    local service="$1"
    local uid

    uid="$(docker compose exec -T "${service}" id -u)"
    if [[ ! "${uid}" =~ ^[0-9]+$ ]]; then
        printf '%s returned a non-numeric UID: %s\n' "${service}" "${uid}" >&2
        return 1
    fi
    if [[ "${uid}" == "0" ]]; then
        printf '%s is running as root (UID 0).\n' "${service}" >&2
        return 1
    fi
    printf 'Verified %s runs as UID %s.\n' "${service}" "${uid}"
}

assert_healthy_service() {
    local service="$1"
    local container_id
    local container_state

    container_id="$(docker compose ps -q "${service}")"
    if [[ -z "${container_id}" ]]; then
        printf '%s has no running container.\n' "${service}" >&2
        return 1
    fi

    container_state="$(
        docker inspect --format \
            '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing-healthcheck{{end}}' \
            "${container_id}"
    )"
    if [[ "${container_state}" != "running healthy" ]]; then
        printf '%s is not running and healthy: %s\n' \
            "${service}" "${container_state}" >&2
        return 1
    fi
    printf 'Verified %s is running and healthy.\n' "${service}"
}

assert_secret_environment_absent() {
    local service="$1"
    local container_id
    local environment

    container_id="$(docker compose ps -q "${service}")"
    environment="$(
        docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
            "${container_id}"
    )"
    if grep -Eiq \
        '^[[:alnum:]_]*(api_key|token|secret|password)=.+' \
        <<<"${environment}"; then
        printf '%s has a sensitive environment variable configured.\n' \
            "${service}" >&2
        return 1
    fi
}

assert_paths_absent() {
    local service="$1"
    shift

    docker compose exec -T "${service}" sh -eu -c '
        for path do
            if [ -e "${path}" ]; then
                echo "Unexpected host-artifact path in runtime container: ${path}" >&2
                exit 1
            fi
        done
    ' sh "$@"
}

assert_marker_absent() {
    local service="$1"
    local search_root="$2"
    local marker_match

    marker_match="$(
        docker compose exec -T "${service}" sh -c \
            'if [ -d "$2" ]; then
                find "$2" -name "$1" -print -quit 2>/dev/null
            fi' \
            sh "${HOST_ARTIFACT_MARKER}" "${search_root}"
    )"
    if [[ -n "${marker_match}" ]]; then
        printf 'Host dependency artifact leaked into %s at %s\n' \
            "${service}" "${marker_match}" >&2
        return 1
    fi
}

frontend_origin() {
    local container_id
    local binding
    local published_host
    local published_port
    local url_host

    container_id="$(docker compose ps -q frontend)"
    if [[ -z "${container_id}" ]]; then
        printf '%s\n' 'The frontend container is not running.' >&2
        return 1
    fi

    binding="$(
        docker inspect --format \
            '{{range $port, $bindings := .NetworkSettings.Ports}}{{range $bindings}}{{println .HostIp .HostPort}}{{end}}{{end}}' \
            "${container_id}" | sed -n '1p'
    )"
    published_host="${binding% *}"
    published_port="${binding##* }"

    if [[ -z "${binding}" || "${published_port}" == "${binding}" ]]; then
        printf '%s\n' 'The frontend service has no published port.' >&2
        return 1
    fi
    if [[ ! "${published_port}" =~ ^[0-9]+$ ]]; then
        printf 'Invalid published frontend port: %s\n' "${published_port}" >&2
        return 1
    fi

    case "${published_host}" in
        ''|'0.0.0.0'|'::')
            url_host='127.0.0.1'
            ;;
        *:*)
            url_host="[${published_host}]"
            ;;
        *)
            url_host="${published_host}"
            ;;
    esac

    printf 'http://%s:%s' "${url_host}" "${published_port}"
}

require_command docker
require_command curl

if ! docker compose version >/dev/null 2>&1; then
    printf '%s\n' 'Docker Compose v2 (docker compose) is required.' >&2
    false
fi
COMPOSE_AVAILABLE=1

if ! docker info >/dev/null 2>&1; then
    printf '%s\n' 'The Docker daemon is unavailable.' >&2
    false
fi

LOG_FILE="$(mktemp "${TMPDIR:-/tmp}/agent-platform-compose-logs.XXXXXX")"

printf '%s\n' 'Validating Compose configuration...'
docker compose config --quiet

# Seed existing ignored dependency directories before the no-cache build. If a
# broad COPY bypasses a Docker ignore rule, the unique marker will be visible in
# the resulting runtime container. Markers are removed locally after the build.
create_host_artifact_markers

printf '%s\n' 'Building all Compose images without cache...'
docker compose build --no-cache
remove_host_artifact_markers

printf '%s\n' 'Starting services and waiting for their health checks...'
docker compose up -d --wait
assert_healthy_service backend
assert_healthy_service frontend
assert_secret_environment_absent backend
assert_secret_environment_absent frontend

FRONTEND_ORIGIN="$(frontend_origin)"
readonly FRONTEND_ORIGIN
readonly HEALTH_URL="${FRONTEND_ORIGIN}/api/v1/health/live"
readonly DEEP_LINK_URL="${FRONTEND_ORIGIN}/workspaces/smoke-workspace/runs/00000000-0000-0000-0000-000000000000"

printf 'Checking backend health through the published frontend port: %s\n' \
    "${HEALTH_URL}"
health_response="$(curl --fail --silent --show-error --max-time 10 "${HEALTH_URL}")"
if [[ "${health_response}" != *'"status":"ok"'* \
    && "${health_response}" != *'"status": "ok"'* ]]; then
    printf 'Unexpected health response: %s\n' "${health_response}" >&2
    false
fi

printf 'Checking SPA deep-link fallback: %s\n' "${DEEP_LINK_URL}"
deep_link_response="$(
    curl --fail --silent --show-error --max-time 10 "${DEEP_LINK_URL}"
)"
if [[ "${deep_link_response}" != *'id="root"'* ]]; then
    printf '%s\n' 'SPA deep link did not return the application HTML shell.' >&2
    false
fi

assert_non_root_service backend
assert_non_root_service frontend

# /opt/venv is the backend's lock-built production environment and is allowed.
# These paths are where an accidental source-tree COPY would expose host deps.
assert_paths_absent backend \
    /app/.venv \
    /app/node_modules \
    /app/backend/.venv \
    /app/backend/node_modules
assert_paths_absent frontend \
    /app/.venv \
    /app/node_modules \
    /usr/share/nginx/html/.venv \
    /usr/share/nginx/html/node_modules
assert_marker_absent backend /app
assert_marker_absent frontend /usr/share/nginx/html
printf '%s\n' 'Verified host .venv/node_modules artifacts are absent from runtime containers.'

docker compose logs --no-color --since "${SMOKE_STARTED_AT}" >"${LOG_FILE}" 2>&1
if grep -Eaiq "${LOG_FAILURE_PATTERN}" "${LOG_FILE}"; then
    printf '%s\n' \
        'Compose logs contain a traceback, permission error, or possible credential.' >&2
    false
fi
printf '%s\n' 'Compose logs passed the runtime error and secret-pattern scan.'

printf '\nDocker smoke passed. Services remain running for browser acceptance at:\n%s\n' \
    "${FRONTEND_ORIGIN}"
