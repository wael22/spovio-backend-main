import time
import subprocess
from datetime import datetime, timedelta
from app import create_app
from src.models.user import Court

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
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
        print(f"✅ Capture finished: {filename}")
        print("Please open this file and check if it shows PAST footage or LIVE footage.")
    except Exception as e:
        print(f"❌ Failed: {e}")

app = create_app()
with app.app_context():
    # Credentials (Hardcoded for test based on previous success)
    IP = "192.168.100.208"
    PORT = 554
    USER = "admin"
    PASS = "Sgs_2025_"
    
    # Target Time: 1 hour ago (to ensure it's definitely past)
    now = datetime.now()
    start_dt = now - timedelta(hours=1)
    end_dt = start_dt + timedelta(minutes=2)
    
    print(f"Target Time: {start_dt} to {end_dt}")
    
    # Format 1: Current (YYYY_MM_DD...)
    # rtsp://user:pass@ip:port/playback/service?starttime=...
    t_start_1 = start_dt.strftime("%Y_%m_%d_%H_%M_%S")
    t_end_1 = end_dt.strftime("%Y_%m_%d_%H_%M_%S")
    url1 = f"rtsp://{USER}:{PASS}@{IP}:{PORT}/playback/service?starttime={t_start_1}&endtime={t_end_1}"
    
    # Format 2: Unix Timestamp (c1/b.../e.../replay)
    # rtsp://user:pass@ip:port/c1/b{ts_start}/e{ts_end}/replay
    ts_start = int(start_dt.timestamp())
    ts_end = int(end_dt.timestamp())
    url2 = f"rtsp://{USER}:{PASS}@{IP}:{PORT}/c1/b{ts_start}/e{ts_end}/replay"
    
    # Format 3: Unix Timestamp variant (unicast/c1/s0/playback...) - speculative
    url3 = f"rtsp://{USER}:{PASS}@{IP}:{PORT}/unicast/c1/s0/playback?starttime={ts_start}&endtime={ts_end}"

    test_url(url1, "Format 1 (Current - Underscores)", "test_fmt1.mp4")
    test_url(url2, "Format 2 (Unix Timestamp)", "test_fmt2.mp4")
    # test_url(url3, "Format 3 (Unix Variant)", "test_fmt3.mp4")
