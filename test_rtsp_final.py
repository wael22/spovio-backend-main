import subprocess
from datetime import datetime, timedelta

def test_url(url, description, filename):
    print(f"\n--- Testing: {description} ---")
    print(f"URL: {url}")
    
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-c", "copy",
        "-t", "5",
        filename
    ]
    
    try:
        # Increase timeout to 30s as replay seek can be slow
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode == 0:
            print(f"✅ Capture finished: {filename}")
            print("Please check if this video shows PAST footage.")
        else:
            print(f"❌ FFmpeg failed with code {result.returncode}")
            print(result.stderr.decode())
    except subprocess.TimeoutExpired:
        print("❌ Timeout: FFmpeg took too long (camera might be slow to seek)")

# Credentials
IP = "192.168.100.208"
PORT = 554
USER = "admin"
PASS = "Sgs_2025_"

# Time: 1 hour ago
now = datetime.now()
start_dt = now - timedelta(hours=1)
end_dt = start_dt + timedelta(minutes=2)

# Format: ISO 8601 (Standard ONVIF)
# YYYY-MM-DDTHH:MM:SSZ
t_start = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
t_end = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

url = f"rtsp://{USER}:{PASS}@{IP}:{PORT}/media/record1?starttime={t_start}&endtime={t_end}"

test_url(url, "ONVIF Replay /media/record1 (ISO8601)", "test_final.mp4")
