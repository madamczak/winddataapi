import paramiko

HOST     = "192.168.0.103"
USER     = "pi"
PASSWORD = "raspberry"
APP_DIR  = "~/Programming/winddataAPI"

CRON_JOB = f"@reboot sleep 10 && cd {APP_DIR} && python3 main.py >> {APP_DIR}/api.log 2>&1 &"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=15)

# Add cron job only if it doesn't already exist, then show current crontab
cmd = (
    f'(crontab -l 2>/dev/null | grep -v "winddataAPI"; echo "{CRON_JOB}") | crontab - '
    f'&& echo "Cron updated:" && crontab -l'
)

with open("C:/Users/adamc/PycharmProjects/winddataAPI/scripts/pi_start_log.txt", "w") as f:
    f.write(f">> {cmd}\n")
    _, stdout, stderr = client.exec_command(cmd, timeout=15)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    f.write(out)
    if err.strip():
        f.write("[stderr] " + err)

client.close()
print("done")

