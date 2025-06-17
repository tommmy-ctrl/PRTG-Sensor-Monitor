set -e

CONFIG_DIR="/app/config"

echo "Entrypoint: Überprüfe Verzeichnisse und Berechtigungen..."

mkdir -p ${CONFIG_DIR}

chown -R appuser:appgroup ${CONFIG_DIR}

echo "Entrypoint: Setup abgeschlossen. Starte die Anwendung als 'appuser'..."

exec gosu appuser "$@"