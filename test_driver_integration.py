import logging
import os
import sys
from datetime import datetime, timedelta

# Add src to python path to import the driver
sys.path.append(os.path.join(os.getcwd()))

from src.video_system.drivers.uniview import UniviewDriver

# Configuration
CAMERA_IP = "192.168.100.208"
CAMERA_PORT = 80 # The driver handles the port logic (maps 80 -> 554 for RTSP)
USERNAME = "admin"
PASSWORD = "Sgs_2025_"
OUTPUT_DIR = "download_test_output"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestIntegration")

if __name__ == "__main__":
    print("=== Testing UniviewDriver (RTSP Replay) Integration ===")
    
    # 1. Initialize Driver
    driver = UniviewDriver(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
    print(f"Driver initialized. RTSP Port: {driver.rtsp_port}")
    
    # 2. Health Check
    if driver.health_check():
         print("✅ Health check PASSED (RTSP Port Open)")
    else:
         print("❌ Health check FAILED")
         exit(1)
         
    # 3. Find Recordings (Virtual Segment)
    # Be careful with time zones. Driver uses local time in formatted strings?
    # The formatted string is just the passed datetime.
    # Let's use current time - 5 mins.
    
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=1)
    
    print(f"Requesting recordings from {start_time} to {end_time}")
    
    segments = driver.find_recordings(start_time, end_time)
    
    if not segments:
        print("❌ No segments returned (Unexpected for virtual driver)")
        exit(1)
        
    print(f"✅ Returned {len(segments)} segments")
    seg = segments[0]
    print(f"   URL: {seg.download_url}")
    
    # 4. Download
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    output_path = os.path.join(OUTPUT_DIR, f"integrated_test_{int(datetime.now().timestamp())}.mp4")
    print(f"Downloading to: {output_path}")
    print("⏳ This should take about 1 minute + overhead...")
    
    start_dl = datetime.now()
    success = driver.download_segment(seg, output_path, timeout=120)
    duration = (datetime.now() - start_dl).total_seconds()
    
    if success:
        print(f"✅ Download SUCCESS in {duration:.1f}s")
        print(f"File size: {os.path.getsize(output_path)} bytes")
    else:
        print("❌ Download FAILED")
