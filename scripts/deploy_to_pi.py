"""
Connects to the Raspberry Pi via SSH and:
1. Creates a virtual environment
2. Installs dependencies from requirements.txt
3. Starts the API with uvicorn in the background
"""
import paramiko
import time

HOST     = "192.168.0.103"
USER     = "pi"
PASSWORD = "raspberry"
APP_DIR  = "~/Programming/winddataAPI"

commands = [
    # Ensure pip & venv are available
    "sudo apt-get install -y python3-venv python3-pip",
    # Create venv
    f"cd {APP_DIR} && python3 -m venv .venv",
    # Upgrade pip
    f"cd {APP_DIR} && .venv/bin/pip install --upgrade pip",
    # Install requirements
    f"cd {APP_DIR} && .venv/bin/pip install -r requirements.txt",
    # Kill any previously running instance
    "pkill -f 'uvicorn' || true",
    # Start the API in the background, log to api.log
    f"cd {APP_DIR} && nohup .venv/bin/python main.py > api.log 2>&1 &",
    # Give it a moment, then show last lines of log
    "sleep 3",
    f"tail -20 {APP_DIR}/api.log",
]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

print(f"Connecting to {HOST} as {USER}...")
client.connect(HOST, username=USER, password=PASSWORD, timeout=15)
print("Connected.\n")

for cmd in commands:
    print(f">> {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=120, get_pty=True)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    if out:
        print(out)
    if err:
        print("[stderr]", err)
    print()

client.close()
print("Done. API should be running at http://192.168.0.103:8000")
print("Docs:  http://192.168.0.103:8000/docs")

