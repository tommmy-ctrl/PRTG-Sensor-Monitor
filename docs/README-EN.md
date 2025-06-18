# Documentation: PRTG Sensor Monitor

## 1. Project Overview

This system consists of two main components, operated as Docker containers via Docker Compose:

1.  **PRTG Monitor (`prtg-monitor-py`):** A Python service that periodically queries one or more PRTG servers. It collects information about all sensors currently in a "Warning" or "Down" state and writes this data into a PostgreSQL database.
2.  **Database Stack (`database-stack`):** A Docker Compose stack that provides a PostgreSQL database for persistent data storage and an Adminer web interface for easy database management.

The entire system is designed to run on a single Docker host (e.g., an Ubuntu VM).

## 2. Prerequisites

*   A Linux server with `root` or `sudo` access (tested on Ubuntu 24.04).
*   Docker and Docker Compose installed on the server.
*   Ports `8888` (for Adminer) and `5432` (for PostgreSQL) must be open for inbound traffic in all upstream firewalls (e.g., VMware ESXi, Cloud Provider Security Groups).

## 3. Setup Guide

The setup is performed in two main steps: first, deploy the database stack, then deploy the PRTG monitor service.

### 3.1. Step 1: Deploy the Database Stack

This stack provides the PostgreSQL database and the Adminer web interface.

1.  **Connect to your server via SSH:**
    ```bash
    ssh <user>@<server_ip>
    ```

2.  **Create the project directory for the database:**
    ```bash
    mkdir ~/database-stack
    cd ~/database-stack
    ```

3.  **Create the `docker-compose.yml` for the database:**
    Create the file using `nano docker-compose.yml`. **Replace `YOUR_SUPER_SECURE_PASSWORD`** with a strong password for the `postgres` superuser.

    ```yaml
    services:
      postgres:
        image: postgres:16
        container_name: postgres-db
        restart: unless-stopped
        environment:
          POSTGRES_PASSWORD: "YOUR_SUPER_SECURE_PASSWORD"
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

4.  **Start the database stack:**
    ```bash
    docker compose up -d
    ```
    Wait about 30 seconds for the database to initialize. Verify that both containers (`postgres-db` and `adminer-webui`) are running with `docker ps`.

5.  **Initialize the Database, User, and Table:**
    *   Open Adminer in your browser: `http://<server_ip>:8888`.
    *   Log in as the **superuser**:
        *   System: `PostgreSQL`
        *   Server: `<server_ip>`
        *   Username: `postgres`
        *   Password: The `YOUR_SUPER_SECURE_PASSWORD` you set.
        *   Database: `postgres`
    *   Click on **"SQL command"** and execute the following commands. **Replace `YOUR_PASSWORD_FOR_PRTG_USER`** with a secure password.

    ```sql
    -- 1. Create the database, user, and grant privileges
    CREATE DATABASE prtg_data;
    CREATE USER prtg_user WITH PASSWORD 'YOUR_PASSWORD_FOR_PRTG_USER';
    GRANT ALL PRIVILEGES ON DATABASE prtg_data TO prtg_user;

    -- 2. Connect to the new database
    \c prtg_data

    -- 3. Create the target table and grant permissions
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
The database is now ready.

---

### 3.2. Step 2: Deploy the PRTG Monitor Service

1.  **Clone the Git Repository:**
    ```bash
    cd ~
    git clone https://github.com/tommmy-ctrl/PRTG-Service-Linux.git
    cd PRTG-Service-Linux
    ```

2.  **Create the Private Configuration (IMPORTANT):**
    This step is necessary because the `config` directory is ignored by Git for security reasons.

    ```bash
    # Create the configuration directory
    mkdir config

    # Create and edit the configuration file
    nano config/config.ini
    ```
    Add the following content and customize the `[database]` and `[prtg-...]` sections with your details:

    ```ini
    [database]
    host = postgres-db
    port = 5432
    dbname = prtg_data
    user = prtg_user
    password = YOUR_PASSWORD_FOR_PRTG_USER # Same password as above

    [prtg-main-server]
    server_ip = <your_prtg_server_ip>
    port = 443
    protocol = https
    refresh_interval_seconds = 60
    use_api_token = true
    api_token = <your_private_prtg_api_token>
    username = 
    password =
    ignore_ssl_errors = true
    ```

3.  **Start the PRTG Monitor Stack:**
    The `--build` flag is important for the first run to build the image.
    ```bash
    docker compose up -d --build
    ```

4.  **Verify Functionality:**
    *   Check the logs to ensure there are no errors: `docker logs -f prtg-monitor-py`.
    *   Check in Adminer (`http://<server_ip>:8888`) to see if data is being written to the `sensor_readings` table.

## 4. Maintenance and Updates

### Updating the Code
If the Python code (`main.py`) or dependencies (`requirements.txt`) are updated in the Git repository:

1.  Connect to the server via SSH.
2.  Navigate to the project directory: `cd ~/PRTG-Service-Linux`.
3.  Pull the latest changes from GitHub: `git pull`.
4.  Rebuild the image and restart the service:
    ```bash
    docker compose up -d --build
    ```

### Changing the Configuration
Changes to `config.ini` only require a restart of the container, not a rebuild.

1.  Edit the private configuration file: `nano ~/PRTG-Service-Linux/config/ini`.
2.  Restart the service to apply the changes:
    ```bash
    cd ~/PRTG-Service-Linux
    docker compose up -d
    ```