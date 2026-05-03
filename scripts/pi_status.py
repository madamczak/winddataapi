import paramiko, time

HOST     = "192.168.0.103"
USER     = "pi"
PASSWORD = "raspberry"
APP_DIR  = "~/Programming/winddataAPI"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=15)

cmds = [
    # Install requirements with system pip
    (f"pip3 install -r {APP_DIR}/requirements.txt", 180),
    # Kill old instances
    ("pkill -f 'main.py' || true; pkill -f uvicorn || true", 10),
    # Start API with system python
    (f"cd {APP_DIR} && nohup python3 main.py > api.log 2>&1 & echo started_pid:$!", 10),
    # Wait and check log
    ("sleep 4", 10),
    (f"cat {APP_DIR}/api.log", 10),
    ("ps aux | grep -E 'uvicorn|main.py' | grep -v grep", 10),
]

with open("C:/Users/adamc/PycharmProjects/winddataAPI/scripts/pi_status.txt", "w") as f:
    for cmd, timeout in cmds:
        f.write(f">> {cmd}\n")
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=False)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        f.write(out)
        if err.strip():
            f.write("[stderr] " + err)
        f.write("\n")

client.close()
print("done")
