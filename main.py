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
import psycopg2
import urllib3

# Disable warnings for insecure HTTPS connections (e.g., self-signed certificates)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Global variable for clean shutdown ---
shutdown_flag = threading.Event()  # Set when the program should terminate

# --- Load configuration ---
config = configparser.ConfigParser()
config_paths = ['/app/config/config.ini', 'config.ini']  # Search for config file in two locations
try:
    if not config.read(config_paths):
        print("ERROR: Configuration file (config.ini) could not be found.")
        sys.exit(1)
except configparser.Error as e:
    print(f"ERROR parsing configuration file: {e}")
    sys.exit(1)

# --- Establish database connection ---
def get_db_connection():
    """
    Establishes a connection to the PostgreSQL database.
    Returns a psycopg2 connection object or None on error.
    """
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
        print(f"ERROR connecting to the database: {e}")
        return None

class PrtgPoller:
    """
    Class that monitors a PRTG server and regularly queries sensors with error status,
    writing them to the database.
    """

    def __init__(self, server_alias, server_config):
        """
        Initializes the poller with alias and configuration.
        """
        self.alias = server_alias
        self.config = server_config
        self.server_ip = self.config.get('server_ip')
        self.port = self.config.getint('port')
        self.protocol = self.config.get('protocol', 'http')
        self.ignore_ssl = self.config.getboolean('ignore_ssl_errors', False)
        print(f"[{self.alias}] Poller initialized.")

    def _build_url(self):
        """
        Builds the API URL for the PRTG server based on the configuration.
        """
        base_url = f"{self.protocol}://{self.server_ip}:{self.port}/api/table.json?content=sensors&columns=objid,sensor,status,message,lastvalue,priority&filter_status=4&filter_status=5"
        if self.config.getboolean('use_api_token'):
            auth_part = f"apitoken={self.config.get('api_token')}"
        else:
            auth_part = f"username={self.config.get('username')}&password={self.config.get('password')}"
        return f"{base_url}&{auth_part}"

    def poll(self):
        """
        Executes a polling operation:
        - Queries the PRTG API
        - Parses the response
        - Stores the results in the database
        """
        if shutdown_flag.is_set():
            return
        print(f"[{self.alias}] Starting data retrieval...")
        api_url = self._build_url()
        try:
            response = requests.get(api_url, verify=not self.ignore_ssl, timeout=15)
            response.raise_for_status()
            
            # Parse the JSON response from PRTG
            prtg_response = json.loads(response.text)
            sensors = prtg_response.get('sensors', [])
            
            self._save_to_db(sensors)

        except requests.exceptions.RequestException as e:
            print(f"[{self.alias}] ERROR during request: {e}")
        except json.JSONDecodeError as e:
            print(f"[{self.alias}] ERROR parsing JSON response: {e}")

    def _save_to_db(self, sensors):
        """
        Deletes old entries for this server and inserts the new sensor data.
        """
        conn = get_db_connection()
        if not conn:
            print(f"[{self.alias}] Skipping save, no DB connection.")
            return

        try:
            with conn.cursor() as cur:
                # Step 1: Delete old entries for this server
                print(f"[{self.alias}] Deleting old entries from the database...")
                cur.execute("DELETE FROM sensor_readings WHERE server_alias = %s;", (self.alias,))
                
                # Step 2: Insert new sensor data
                if not sensors:
                    print(f"[{self.alias}] No new sensors with problems found.")
                else:
                    print(f"[{self.alias}] Inserting {len(sensors)} new entries into the database...")
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
                                sensor.get('status_raw'),  # PRTG API provides status_raw for the code
                                sensor.get('lastvalue'),
                                sensor.get('message'),
                                sensor.get('priority_raw')  # PRTG API provides priority_raw
                            )
                        )
                
                # Commit changes to the database
                conn.commit()
                print(f"[{self.alias}] Database update completed successfully.")

        except Exception as e:
            print(f"[{self.alias}] ERROR writing to the database: {e}")
            conn.rollback()  # Roll back changes on error
        finally:
            if conn:
                conn.close()

def run_threaded(job_func):
    """
    Starts the given function in a separate thread.
    """
    job_thread = threading.Thread(target=job_func)
    job_thread.start()

def shutdown_handler(signum, frame):
    """
    Signal handler for SIGINT/SIGTERM.
    Sets the shutdown flag and stops scheduled jobs.
    """
    print("\nShutdown signal received. Stopping scheduled jobs...")
    shutdown_flag.set()
    schedule.clear()

def main():
    """
    Main function of the service:
    - Tests the DB connection
    - Initializes all pollers for the configured servers
    - Schedules the jobs with the desired interval
    - Starts the main loop
    """
    print("--- PRTG Monitor Service starting ---")
    # Test the DB connection at startup
    conn = get_db_connection()
    if conn:
        print("Database connection successfully tested.")
        conn.close()
    else:
        print("WARNING: Could not connect to the database. Script continues and will retry.")

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # Load all server sections from the configuration (except storage/database)
    server_sections = [s for s in config.sections() if s not in ['storage', 'database']]
    if not server_sections:
        print("ERROR: No servers found in config.ini. Exiting.")
        return

    # Create and schedule a poller for each server
    for server_alias in server_sections:
        poller = PrtgPoller(server_alias, config[server_alias])
        interval = config[server_alias].getint('refresh_interval_seconds', 60)
        schedule.every(interval).seconds.do(run_threaded, poller.poll)
    
    print("All jobs scheduled. Starting main loop...")
    run_threaded(schedule.run_all)
    
    # Main loop: runs scheduled jobs until shutdown flag is set
    while not shutdown_flag.is_set():
        schedule.run_pending()
        time.sleep(1)

    print("--- PRTG Monitor Service shut down cleanly. ---")

if __name__ == "__main__":
    main()