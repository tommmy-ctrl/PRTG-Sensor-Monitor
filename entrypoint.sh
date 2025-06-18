# Exit immediately if a command exits with a non-zero status
set -e

# Define the configuration directory
CONFIG_DIR="/app/config"

# Print status message
echo "Entrypoint: Checking directories and permissions..."

# Create the configuration directory if it does not exist
mkdir -p ${CONFIG_DIR}

# Set ownership of the directory to user 'appuser' and group 'appgroup'
chown -R appuser:appgroup ${CONFIG_DIR}

# Print status message indicating setup is complete
echo "Entrypoint: Setup complete. Starting the application as 'appuser'..."

# Execute the given command as user 'appuser' (using gosu for privilege drop)
exec gosu