#!/usr/bin/env bash
# Datenschutz-Scan: bricht ab (exit 1), sobald Geheimnisse oder persoenliche Daten im Repo oder Image stehen.
# Laeuft in der CI auf jedem PR und vor jedem Image-Push, lokal als pre-push-Hook (tools/pre-push).
#
#   privacy-scan.sh repo  <verzeichnis>         Arbeitsbaum + ganze Git-Historie (Sperrliste, gitleaks, trufflehog)
#   privacy-scan.sh image <image> <basis-image> Image: eigene Schichten + ENV/Labels/History (Sperrliste),
#                                               ganzes Dateisystem + Metadaten (gitleaks, trufflehog)
#   privacy-scan.sh sperrliste <verzeichnis>    nur die Sperrliste (Arbeitsbaum + Historie, ohne Docker)
#   privacy-scan.sh werkzeuge <verzeichnis> git|dir   nur gitleaks + trufflehog
#
# Sperrliste: Variable PRIVACY_DENYLIST (Inhalt, in der CI das gleichnamige Secret) oder PRIVACY_DENYLIST_FILE.
# Ein regulaerer Ausdruck (ERE, Gross/Klein egal) je Zeile, # leitet Kommentare ein. Sie steht nie im Repo.
# Fehlt sie, ist das ein Fehler (exit 2), kein stilles Bestehen. Ausgegeben wird nur "Treffer in <Ort>", nie der Wert.
set -uo pipefail

GITLEAKS="zricethezav/gitleaks:v8.21.2@sha256:0e99e8821643ea5b235718642b93bb32486af9c8162c8b8731f7cbdc951a7f46"
TRUFFLEHOG="trufflesecurity/trufflehog:3.82.13@sha256:9abf17c8902d58c05d82f910cf5dec05d100912482e8002d88918511fb44b6f6"

ARBEIT=$(mktemp -d)
trap 'rm -rf "$ARBEIT"' EXIT
FUNDE=0

fund() { echo "FUND: $*"; FUNDE=$((FUNDE + 1)); }

sperrliste_laden() {
  local roh
  if [ -n "${PRIVACY_DENYLIST:-}" ]; then
    roh="$PRIVACY_DENYLIST"
  elif [ -n "${PRIVACY_DENYLIST_FILE:-}" ] && [ -r "$PRIVACY_DENYLIST_FILE" ]; then
    roh=$(cat "$PRIVACY_DENYLIST_FILE")
  else
    echo "FEHLER: Sperrliste fehlt (PRIVACY_DENYLIST oder PRIVACY_DENYLIST_FILE)" >&2
    exit 2
  fi
  printf '%s\n' "$roh" | tr -d '\r' | grep -v '^[[:space:]]*#' | grep -v '^[[:space:]]*$' > "$ARBEIT/sperrliste"
  local n
  n=$(wc -l < "$ARBEIT/sperrliste")
  if [ "$n" -lt 5 ]; then
    echo "FEHLER: Sperrliste hat nur $n Regeln" >&2
    exit 2
  fi
  echo "Sperrliste: $n Regeln"
}

# Dateien unter $1 gegen die Sperrliste; Ausgabe relativ zu $1, nie die Fundstelle selbst
sperrliste_dateien() {
  local wurzel=$1 datei
  while IFS= read -r datei; do
    fund "Sperrliste: Treffer in ${datei#"$wurzel"/}"
  done < <(grep -rlaiE -f "$ARBEIT/sperrliste" "$wurzel" 2>/dev/null)
}

sperrliste_repo() {
  local dir=$1 c
  ( cd "$dir" && git ls-files -z | xargs -0 -r grep -laiE -f "$ARBEIT/sperrliste" -- 2>/dev/null ) \
    | while IFS= read -r datei; do echo "FUND: Sperrliste: Treffer in $datei"; done > "$ARBEIT/baum"
  while IFS= read -r c; do
    if git -C "$dir" show --format=fuller --stat -p "$c" | grep -qaiE -f "$ARBEIT/sperrliste"; then
      echo "FUND: Sperrliste: Treffer in Commit $c" >> "$ARBEIT/baum"
    fi
  done < <(git -C "$dir" rev-list --all)
  # Zweig- und Tag-Namen
  if git -C "$dir" for-each-ref --format='%(refname)' | grep -qaiE -f "$ARBEIT/sperrliste"; then
    echo "FUND: Sperrliste: Treffer in einem Zweig- oder Tag-Namen" >> "$ARBEIT/baum"
  fi
  if [ -s "$ARBEIT/baum" ]; then
    cat "$ARBEIT/baum"
    FUNDE=$((FUNDE + $(wc -l < "$ARBEIT/baum")))
  fi
}

# gitleaks + trufflehog in Docker; modus git (Historie) oder dir (Dateisystem). Nur Ort und Regel ausgeben.
werkzeuge() {
  local dir modus=$2 aus
  dir=$(cd "$1" && pwd)
  aus=$(mktemp -d)
  chmod 777 "$aus"
  local git_env=(-e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*')
  if [ "$modus" = git ]; then
    docker run --rm "${git_env[@]}" -v "$dir":/scan:ro -v "$aus":/out "$GITLEAKS" git /scan \
      --no-banner --redact --exit-code 0 --report-format json --report-path /out/gitleaks.json >/dev/null 2>"$aus/gl.err"
    docker run --rm "${git_env[@]}" -v "$dir":/scan:ro "$TRUFFLEHOG" git file:///scan \
      --no-update --no-verification --json > "$aus/th.json" 2>"$aus/th.err"
  else
    docker run --rm -v "$dir":/scan:ro -v "$aus":/out "$GITLEAKS" dir /scan \
      --no-banner --redact --exit-code 0 --report-format json --report-path /out/gitleaks.json >/dev/null 2>"$aus/gl.err"
    docker run --rm -v "$dir":/scan:ro "$TRUFFLEHOG" filesystem /scan \
      --no-update --no-verification --json > "$aus/th.json" 2>"$aus/th.err"
  fi
  if ! jq -e 'type == "array"' "$aus/gitleaks.json" >/dev/null 2>&1; then
    echo "FEHLER: gitleaks lief nicht" >&2
    tail -5 "$aus/gl.err" >&2
    exit 2
  fi
  if grep -q '"level":"error"' "$aus/th.err" || ! grep -q 'finished scanning' "$aus/th.err"; then
    echo "FEHLER: trufflehog lief nicht sauber" >&2
    tail -5 "$aus/th.err" >&2
    exit 2
  fi
  while IFS= read -r z; do fund "gitleaks: $z"; done < <(jq -r '.[] |
    "Treffer in \(.File | sub("^/scan/"; ""))\(if .Commit != "" then " (Commit \(.Commit))" else "" end), Regel \(.RuleID)"' \
    "$aus/gitleaks.json")
  while IFS= read -r z; do fund "trufflehog: $z"; done < <(jq -r 'select(.DetectorName) |
    (.SourceMetadata.Data.Git // .SourceMetadata.Data.Filesystem // {}) as $m |
    "Treffer in \(($m.file // "?") | sub("^/scan/"; ""))\(if $m.commit then " (Commit \($m.commit))" else "" end), Detektor \(.DetectorName)"' \
    "$aus/th.json")
  echo "gitleaks + trufflehog ($modus): $(jq length "$aus/gitleaks.json") + $(grep -c DetectorName "$aus/th.json") Funde"
  rm -rf "$aus"
}

image_scan() {
  local img=$1 basis=$2 n_basis n_eigen
  mkdir -p "$ARBEIT/tar" "$ARBEIT/eigen" "$ARBEIT/fs" "$ARBEIT/meta"
  docker image inspect "$basis" >/dev/null 2>&1 || docker pull -q "$basis" >/dev/null
  n_basis=$(docker image inspect "$basis" --format '{{len .RootFS.Layers}}')
  docker save "$img" | tar -x -C "$ARBEIT/tar"
  # Schichten in Reihenfolge: zuerst die der Basis, dahinter die eigenen
  mapfile -t schichten < <(jq -r '.[0].Layers[]' "$ARBEIT/tar/manifest.json")
  n_eigen=$(( ${#schichten[@]} - n_basis ))
  if [ "$n_basis" -lt 1 ] || [ "$n_eigen" -lt 1 ]; then
    echo "FEHLER: Schichten nicht zuordenbar (Basis $n_basis, gesamt ${#schichten[@]})" >&2
    exit 2
  fi
  for s in "${schichten[@]:$n_basis}"; do
    tar -tf "$ARBEIT/tar/$s" >> "$ARBEIT/meta/dateiliste.txt"
    tar -x --no-same-owner --no-same-permissions -f "$ARBEIT/tar/$s" -C "$ARBEIT/eigen" 2>/dev/null
  done
  echo "Image $img: $n_eigen eigene von ${#schichten[@]} Schichten, $(wc -l < "$ARBEIT/meta/dateiliste.txt") Eintraege"
  docker image inspect "$img" --format '{{json .Config}}' | jq . > "$ARBEIT/meta/config.json"
  docker history --no-trunc --format '{{.CreatedBy}} {{.Comment}}' "$img" > "$ARBEIT/meta/history.txt"
  local cid
  cid=$(docker create "$img")
  docker export "$cid" | tar -x --no-same-owner --no-same-permissions -C "$ARBEIT/fs" --exclude='dev/*' 2>/dev/null
  docker rm "$cid" >/dev/null
  if [ "$(find "$ARBEIT/fs" -type f | head -50 | wc -l)" -lt 50 ]; then
    echo "FEHLER: Image-Dateisystem nicht exportiert" >&2
    exit 2
  fi
  sperrliste_dateien "$ARBEIT/eigen"
  sperrliste_dateien "$ARBEIT/meta"
  chmod -R a+rX "$ARBEIT/fs" "$ARBEIT/meta" 2>/dev/null
  werkzeuge "$ARBEIT/fs" dir
  werkzeuge "$ARBEIT/meta" dir
}

case "${1:-}" in
  repo)
    sperrliste_laden
    sperrliste_repo "$2"
    werkzeuge "$2" git
    ;;
  sperrliste)
    sperrliste_laden
    sperrliste_repo "$2"
    ;;
  werkzeuge)
    werkzeuge "$2" "$3"
    ;;
  image)
    sperrliste_laden
    image_scan "$2" "$3"
    ;;
  *)
    sed -n '2,13p' "$0"
    exit 2
    ;;
esac

if [ "$FUNDE" -gt 0 ]; then
  echo "ABBRUCH: $FUNDE Funde"
  exit 1
fi
echo "sauber"
