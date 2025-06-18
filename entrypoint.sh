# Beendet das Skript sofort, wenn ein Befehl fehlschlägt
set -e

# Definiert das Konfigurationsverzeichnis
CONFIG_DIR="/app/config"

# Gibt eine Statusmeldung aus
echo "Entrypoint: Überprüfe Verzeichnisse und Berechtigungen..."

# Erstellt das Konfigurationsverzeichnis, falls es nicht existiert
mkdir -p ${CONFIG_DIR}

# Setzt die Besitzrechte für das Verzeichnis auf den Benutzer 'appuser' und die Gruppe 'appgroup'
chown -R appuser:appgroup ${CONFIG_DIR}

# Gibt eine Statusmeldung aus, dass das Setup abgeschlossen ist
echo "Entrypoint: Setup abgeschlossen. Starte die Anwendung als 'appuser'..."

# Startet die übergebenen Befehle als Benutzer 'appuser' (über gosu für Rechtewechsel)
exec gosu appuser "$@"