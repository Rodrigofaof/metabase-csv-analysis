#!/usr/bin/env sh
# Starts Metabase (JAR, no Docker) on http://localhost:3000 - macOS / Linux.
cd "$(dirname "$0")/metabase" || exit 1
export MB_DB_FILE="$(pwd)/metabase.db"
export MB_JETTY_PORT=3000
exec java -Xmx2g --add-opens java.base/java.nio=ALL-UNNAMED -jar metabase.jar
