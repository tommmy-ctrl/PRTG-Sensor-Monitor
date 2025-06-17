import configparser
import requests
import os
import time
import schedule
import threading
from datetime import datetime
import signal
import sys
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Globale Variable für den sauberen Shutdown ---
shutdown_flag = threading.Event()

# --- Konfiguration laden ---
config = configparser.ConfigParser()
# Wir suchen an zwei Orten: zuerst im /app/config-Ordner (für Docker), dann lokal.
config_paths = ['/app/config/config.ini', 'config.ini']
try:
    if not config.read(config_paths):
        print("FEHLER: Konfigurationsdatei (config.ini) konnte an keinem der erwarteten Orte gefunden werden. Beende.")
        sys.exit(1)
except configparser.Error as e:
    print(f"FEHLER beim Parsen der Konfigurationsdatei: {e}")
    sys.exit(1)


STORAGE_CONFIG = config['storage']
OUTPUT_PATH = STORAGE_CONFIG.get('output_path', '/app/data')
MAX_FILES = STORAGE_CONFIG.getint('max_file_count_per_server', 20)

class PrtgPoller:
    """Eine Klasse, die einen einzelnen PRTG-Server überwacht."""

    def __init__(self, server_alias, server_config):
        self.alias = server_alias
        self.config = server_config
        self.server_ip = self.config.get('server_ip')
        self.port = self.config.getint('port')
        self.protocol = self.config.get('protocol', 'http')
        self.ignore_ssl = self.config.getboolean('ignore_ssl_errors', False)

        os.makedirs(OUTPUT_PATH, exist_ok=True)
        print(f"[{self.alias}] Poller initialisiert. Daten werden in '{OUTPUT_PATH}' gespeichert.")

    def _build_url(self):
        base_url = f"{self.protocol}://{self.server_ip}:{self.port}/api/table.json?content=sensors&columns=objid,sensor,status,message,lastvalue,priority&filter_status=4&filter_status=5"
        if self.config.getboolean('use_api_token'):
            auth_part = f"apitoken={self.config.get('api_token')}"
        else:
            auth_part = f"username={self.config.get('username')}&password={self.config.get('password')}"
        return f"{base_url}&{auth_part}"

    def poll(self):
        if shutdown_flag.is_set():
            return
        print(f"[{self.alias}] Starte Datenabruf...")
        api_url = self._build_url()
        try:
            response = requests.get(api_url, verify=not self.ignore_ssl, timeout=15)
            response.raise_for_status()
            self._save_data(response.text)
        except requests.exceptions.RequestException as e:
            print(f"[{self.alias}] FEHLER beim Abruf: {e}")

    def _save_data(self, data):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.alias}_{timestamp}.json"
        filepath = os.path.join(OUTPUT_PATH, filename)
        try:
            with open(filepath, 'w') as f:
                f.write(data)
            print(f"[{self.alias}] Daten erfolgreich gespeichert: {filename}")
            self._cleanup_old_files()
        except IOError as e:
            print(f"[{self.alias}] FEHLER beim Speichern der Datei: {e}")

    def _cleanup_old_files(self):
        try:
            files = [f for f in os.listdir(OUTPUT_PATH) if f.startswith(f"{self.alias}_") and f.endswith(".json")]
            files.sort(key=lambda name: os.path.getmtime(os.path.join(OUTPUT_PATH, name)))
            while len(files) > MAX_FILES:
                file_to_delete = files.pop(0)
                os.remove(os.path.join(OUTPUT_PATH, file_to_delete))
                print(f"[{self.alias}] Alte Datei gelöscht: {file_to_delete}")
        except Exception as e:
            print(f"[{self.alias}] FEHLER beim Bereinigen alter Dateien: {e}")

def run_threaded(job_func):
    job_thread = threading.Thread(target=job_func)
    job_thread.start()

def shutdown_handler(signum, frame):
    """Behandelt SIGTERM und SIGINT für einen sauberen Shutdown."""
    print("\nShutdown-Signal empfangen. Beende geplante Jobs und warte auf Abschluss...")
    shutdown_flag.set()
    schedule.clear()

def main():
    print("--- PRTG Monitor Dienst startet ---")
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    server_sections = [s for s in config.sections() if s != 'storage']
    if not server_sections:
        print("FEHLER: Keine Server in config.ini gefunden. Beende.")
        return

    for server_alias in server_sections:
        poller = PrtgPoller(server_alias, config[server_alias])
        interval = config[server_alias].getint('refresh_interval_seconds', 60)
        schedule.every(interval).seconds.do(run_threaded, poller.poll)
    
    print("Alle Jobs geplant. Starte Endlosschleife... (Drücke Ctrl+C zum Beenden)")
    run_threaded(schedule.run_all)
    
    while not shutdown_flag.is_set():
        schedule.run_pending()
        time.sleep(1)

    print("--- PRTG Monitor Dienst wurde sauber beendet. ---")

if __name__ == "__main__":
    main()