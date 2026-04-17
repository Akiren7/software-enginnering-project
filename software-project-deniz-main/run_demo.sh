#!/usr/bin/env bash
#
# Unix demo launcher (macOS / Linux).
# Starts one server and three clients in separate terminal windows.
#

set -e

SERVER_ID="my-server"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[LAUNCHER] Spawning terminal windows..."
echo ""

# Helper to spawn a new terminal window
spawn_terminal() {
    local title=$1
    local cmd="cd '${SCRIPT_DIR}' && ${PYTHON_BIN} $2"
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS: Use AppleScript to tell Terminal.app
        osascript -e "tell application \"Terminal\" to do script \"${cmd}\"" >/dev/null
    else
        # Linux: Try common terminal emulators
        if command -v gnome-terminal &> /dev/null; then
            gnome-terminal --title="$title" -- bash -c "$cmd; exec bash"
        elif command -v konsole &> /dev/null; then
            konsole -e bash -c "$cmd; exec bash" &
        elif command -v xfce4-terminal &> /dev/null; then
            xfce4-terminal -T "$title" -e "bash -c '$cmd; exec bash'" &
        elif command -v xterm &> /dev/null; then
            xterm -title "$title" -e "bash -c '$cmd; exec bash'" &
        else
            echo "[ERROR] Could not find a supported terminal emulator."
            return 1
        fi
    fi
}

echo "-> Starting Server (${SERVER_ID})"
spawn_terminal "Server" "-m server.main --id ${SERVER_ID} --reset --gui"

sleep 1.5

for i in 1 2 3; do
    echo "-> Starting Client ${i}"
    spawn_terminal "Client ${i}" "-m client.main --id ${SERVER_ID} --login-id student${i} --password secret${i} --no-record"
    sleep 0.5
done

echo ""
echo "[LAUNCHER] All windows spawned. You can close this window now."
