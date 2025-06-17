import configparser
import requests
import os
import time
import schedule
import threading
from datetime import datetime
import signal
import sys
import json
import psycopg2 # Neue Bibliothek für PostgreSQL
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Globale Variable für den sauberen Shutdown ---
shutdown_flag = threading.Event()

# --- Konfiguration laden ---
config = configparser.ConfigParser()
config_paths = ['/app/config/config.ini', 'config.ini']
try:
    if not config.read(config_paths):
        print("FEHLER: Konfigurationsdatei (config.ini) konnte nicht gefunden werden.")
        sys.exit(1)
except configparser.Error as e:
    print(f"FEHLER beim Parsen der Konfigurationsdatei: {e}")
    sys.exit(1)

# --- Datenbankverbindung herstellen ---
def get_db_connection():
    """Stellt eine Verbindung zur PostgreSQL-Datenbank her."""
    try:
        db_config = config['database']
        conn = psycopg2.connect(
            host=db_config.get('host'),
            port=db_config.get('port'),
            dbname=db_config.get('dbname'),
            user=db_config.get('user'),
            password=db_config.get('password')
        )
        return conn
    except Exception as e:
        print(f"FEHLER bei der Datenbankverbindung: {e}")
        return None

class PrtgPoller:
    """Eine Klasse, die einen PRTG-Server überwacht und Daten in die DB schreibt."""

    def __init__(self, server_alias, server_config):
        self.alias = server_alias
        self.config = server_config
        self.server_ip = self.config.get('server_ip')
        self.port = self.config.getint('port')
        self.protocol = self.config.get('protocol', 'http')
        self.ignore_ssl = self.config.getboolean('ignore_ssl_errors', False)
        print(f"[{self.alias}] Poller initialisiert.")

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
            
            # Die JSON-Antwort von PRTG parsen
            prtg_response = json.loads(response.text)
            sensors = prtg_response.get('sensors', [])
            
            self._save_to_db(sensors)

        except requests.exceptions.RequestException as e:
            print(f"[{self.alias}] FEHLER beim Abruf: {e}")
        except json.JSONDecodeError as e:
            print(f"[{self.alias}] FEHLER beim Parsen der JSON-Antwort: {e}")

    def _save_to_db(self, sensors):
        """Löscht alte Einträge für diesen Server und fügt die neuen hinzu."""
        conn = get_db_connection()
        if not conn:
            print(f"[{self.alias}] Überspringe Speichern, keine DB-Verbindung.")
            return

        try:
            with conn.cursor() as cur:
                # Schritt 1: Alle alten Einträge für diesen Server löschen (TRUNCATE-Teil)
                print(f"[{self.alias}] Lösche alte Einträge aus der Datenbank...")
                cur.execute("DELETE FROM sensor_readings WHERE server_alias = %s;", (self.alias,))
                
                # Schritt 2: Die neuen Sensordaten einfügen (LOAD-Teil)
                if not sensors:
                    print(f"[{self.alias}] Keine neuen Sensoren mit Problemen gefunden.")
                else:
                    print(f"[{self.alias}] Füge {len(sensors)} neue Einträge in die Datenbank ein...")
                    for sensor in sensors:
                        cur.execute(
                            """
                            INSERT INTO sensor_readings (server_alias, sensor_id, sensor_name, status, status_code, last_value, message, priority)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                            """,
                            (
                                self.alias,
                                sensor.get('objid'),
                                sensor.get('sensor'),
                                sensor.get('status'),
                                sensor.get('status_raw'), # PRTG API gibt status_raw für den Code
                                sensor.get('lastvalue'),
                                sensor.get('message'),
                                sensor.get('priority_raw') # PRTG API gibt priority_raw
                            )
                        )
                
                # Änderungen in der Datenbank bestätigen
                conn.commit()
                print(f"[{self.alias}] Datenbank-Update erfolgreich abgeschlossen.")

        except Exception as e:
            print(f"[{self.alias}] FEHLER beim Schreiben in die Datenbank: {e}")
            conn.rollback() # Änderungen im Fehlerfall zurückrollen
        finally:
            if conn:
                conn.close()

# --- Der Rest des Skripts bleibt fast gleich ---

def run_threaded(job_func):
    job_thread = threading.Thread(target=job_func)
    job_thread.start()

def shutdown_handler(signum, frame):
    print("\nShutdown-Signal empfangen. Beende geplante Jobs...")
    shutdown_flag.set()
    schedule.clear()

def main():
    print("--- PRTG Monitor Dienst startet ---")
    # Teste die DB-Verbindung beim Start
    conn = get_db_connection()
    if conn:
        print("Datenbankverbindung erfolgreich getestet.")
        conn.close()
    else:
        print("WARNUNG: Konnte keine Verbindung zur Datenbank herstellen. Skript läuft weiter und versucht es erneut.")

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    server_sections = [s for s in config.sections() if s not in ['storage', 'database']]
    if not server_sections:
        print("FEHLER: Keine Server in config.ini gefunden. Beende.")
        return

    for server_alias in server_sections:
        poller = PrtgPoller(server_alias, config[server_alias])
        interval = config[server_alias].getint('refresh_interval_seconds', 60)
        schedule.every(interval).seconds.do(run_threaded, poller.poll)
    
    print("Alle Jobs geplant. Starte Endlosschleife...")
    run_threaded(schedule.run_all)
    
    while not shutdown_flag.is_set():
        schedule.run_pending()
        time.sleep(1)

    print("--- PRTG Monitor Dienst wurde sauber beendet. ---")

if __name__ == "__main__":
    main()