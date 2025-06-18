# Dokumentation: PRTG Sensor Monitor

## 1. Projektübersicht

Dieses System besteht aus zwei Docker-Compose-Stacks:
1.  **PRTG Monitor:** Ein Python-Dienst, der PRTG-Server abfragt und Sensoren im Fehlerzustand in eine PostgreSQL-Datenbank schreibt.
2.  **Datenbank-Stack:** Stellt eine PostgreSQL-Datenbank und ein Adminer-Webinterface zur Verwaltung bereit.

## 2. Voraussetzungen

*   Ein Linux-Server mit Docker und Docker Compose.
*   Die Ports `8888` (Adminer) und `5432` (PostgreSQL) müssen in allen übergeordneten Firewalls (z.B. VMware ESXi, Cloud) für den Docker-Host freigegeben sein.

## 3. Einrichtungsanleitung

### 3.1. Schritt 1: Datenbank-Stack bereitstellen

1.  **Per SSH mit dem Server verbinden.**
2.  **Verzeichnis für die Datenbank erstellen:**
    ```bash
    mkdir ~/database-stack
    cd ~/database-stack
    ```
3.  **`docker-compose.yml` für die Datenbank erstellen:**
    Erstellen Sie die Datei mit `nano docker-compose.yml`. **Ersetzen Sie `DEIN_SUPER_SICHERES_PASSWORT`** für den `postgres`-Superuser.

    ```yaml
    services:
      postgres:
        image: postgres:16
        container_name: postgres-db
        restart: unless-stopped
        environment:
          POSTGRES_PASSWORD: "DEIN_SUPER_SICHERES_PASSWORT"
        volumes:
          - postgres-data:/var/lib/postgresql/data
        ports:
          - "5432:5432"
        command: postgres -c 'listen_addresses=*'

      adminer:
        image: adminer
        container_name: adminer-webui
        restart: unless-stopped
        ports:
          - "8888:8080"
        networks:
          - db_network

    volumes:
      postgres-data:
      
    networks:
      db_network:
        driver: bridge
    ```

4.  **Datenbank-Stack starten:**
    ```bash
    docker compose up -d
    ```
    Überprüfen Sie mit `docker ps`, ob beide Container (`postgres-db` und `adminer-webui`) laufen.

5.  **Datenbank, Benutzer und Tabelle initialisieren:**
    *   Öffnen Sie Adminer (`http://<server_ip>:8888`).
    *   Loggen Sie sich als **Superuser** ein (Benutzer: `postgres`, Passwort: Ihr Superuser-Passwort, DB: `postgres`, Server: `<server_ip>`).
    *   Führen Sie unter **"SQL command"** die folgenden Befehle aus. **Ersetzen Sie `DEIN_PASSWORT_FUER_PRTG_USER`** durch ein sicheres Passwort.

    ```sql
    -- 1. Datenbank, Benutzer und Rechte erstellen
    CREATE DATABASE prtg_data;
    CREATE USER prtg_user WITH PASSWORD 'DEIN_PASSWORT_FUER_PRTG_USER';
    GRANT ALL PRIVILEGES ON DATABASE prtg_data TO prtg_user;

    -- 2. Mit der neuen Datenbank verbinden
    \c prtg_data

    -- 3. Zieltabelle erstellen und Rechte vergeben
    CREATE TABLE sensor_readings (
        id SERIAL PRIMARY KEY,
        reading_timestamp TIMESTAMPTZ DEFAULT NOW(),
        server_alias VARCHAR(100),
        sensor_id INT,
        sensor_name TEXT,
        status VARCHAR(50),
        status_code INT,
        last_value TEXT,
        message TEXT,
        priority INT
    );
    GRANT ALL PRIVILEGES ON TABLE sensor_readings TO prtg_user;
    GRANT USAGE, SELECT ON SEQUENCE sensor_readings_id_seq TO prtg_user;
    ```
---

### 3.2. Schritt 2: PRTG Monitor Dienst bereitstellen

1.  **Git-Repository klonen:**
    ```bash
    cd ~
    git clone https://github.com/tommmy-ctrl/PRTG-Service-Linux.git
    cd PRTG-Service-Linux
    ```

2.  **Private Konfiguration erstellen (WICHTIG):**
    Dieser Schritt ist notwendig, da der `config`-Ordner aus Sicherheitsgründen von Git ignoriert wird.

    ```bash
    # Konfigurationsordner erstellen
    mkdir config

    # Konfigurationsdatei erstellen und bearbeiten
    nano config/config.ini
    ```
    Fügen Sie den folgenden Inhalt ein und passen Sie die `[database]`- und `[prtg-...]`-Sektionen an:

    ```ini
    [database]
    host = postgres-db
    port = 5432
    dbname = prtg_data
    user = prtg_user
    password = DEIN_PASSWORT_FUER_PRTG_USER # Selbes Passwort wie oben

    [prtg-main-server]
    server_ip = <deine_prtg_server_ip>
    port = 443
    protocol = https
    refresh_interval_seconds = 60
    use_api_token = true
    api_token = <dein_privater_prtg_api_token>
    username = 
    password =
    ignore_ssl_errors = true
    ```

3.  **PRTG-Monitor-Stack starten:**
    ```bash
    docker compose up -d --build
    ```

4.  **Funktion überprüfen:**
    *   Logs ansehen: `docker logs -f prtg-monitor-py`.
    *   In Adminer prüfen, ob Daten in die `sensor_readings`-Tabelle geschrieben werden.

## 4. Wartung und Updates

### Code aktualisieren
1.  Navigieren Sie zum Projektverzeichnis: `cd ~/PRTG-Service-Linux`.
2.  Holen Sie die neuesten Änderungen: `git pull`.
3.  Bauen und starten Sie den Dienst neu: `docker compose up -d --build`.

### Konfiguration ändern
1.  Bearbeiten Sie die private Konfigurationsdatei: `nano ~/PRTG-Service-Linux/config/config.ini`.
2.  Starten Sie den Dienst neu: `docker compose up -d`.