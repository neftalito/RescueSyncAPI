#!/usr/bin/env bash
# Construye y comprueba la imagen real en una red y una base descartables.
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project="rescuesync-t38-$$"
export T38_IMAGE_TAG="$project"
compose=(docker compose --env-file /dev/null --project-name "$project"
  --file "$repo_dir/compose.production-test.yaml")

cleanup() {
  result=$?
  if (( result != 0 )); then
    "${compose[@]}" logs --no-color --tail 100 || true
  fi
  "${compose[@]}" down --volumes --remove-orphans || true
  docker image rm "rescuesync-national-api-t38:$T38_IMAGE_TAG" >/dev/null 2>&1 || true
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"${compose[@]}" config --quiet
"${compose[@]}" build api
"${compose[@]}" up --wait --wait-timeout 120 api
# Otra instancia de la misma imagen comprueba el acceso por la red Docker:
# una API enlazada sólo a loopback no puede superar esta prueba.
"${compose[@]}" run --rm --no-deps -T api python - \
  < "$repo_dir/scripts/comprobar_imagen_produccion.py"
