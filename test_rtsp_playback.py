import cv2
import time
from datetime import datetime, timedelta

# Configuration
CAMERA_IP = "192.168.100.208"
CAMERA_PORT = 554
USERNAME = "admin"
PASSWORD = "Sgs_2025_"

def test_rtsp_playback_url(description, url):
    print(f"\nTesting URL pattern: {description}")
    print(f"URL: {url.replace(PASSWORD, '****')}") # Hide password in logs
    
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print("    ❌ Failed to open stream")
        return False
    
    print("    ✅ Stream Opened! Reading frames...")
    
    # Try to read a few frames
    frames_read = 0
    for i in range(10):
        ret, frame = cap.read()
        if ret:
            frames_read += 1
            if i == 0:
                print(f"    ✅ First frame received: {frame.shape[1]}x{frame.shape[0]}")
        else:
            break
    
    cap.release()
    
    if frames_read > 0:
        print(f"    ✅ Success! Read {frames_read} frames.")
        return True
    else:
        print("    ⚠️ Stream opened but no frames received (might be invalid time range or unsupported)")
        return False

if __name__ == "__main__":
    print("=== Testing RTSP Playback (Replay) ===")
    
    # Calculate a valid time range (e.g., 10 minutes ago, for 1 minute)
    # Ensure this time actually exists on the SD card!
    now = datetime.now()
    start_time = now - timedelta(minutes=10)
    end_time = start_time + timedelta(minutes=1)
    
    # Format times for common Uniview patterns
    # Pattern 1: YYYYMMDDTHHMMSSZ (ISO-like)
    t_start_iso = start_time.strftime("%Y%m%dT%H%M%SZ")
    t_end_iso = end_time.strftime("%Y%m%dT%H%M%SZ")
    
    # Pattern 2: YYYY_MM_DD_HH_MM_SS
    t_start_flat = start_time.strftime("%Y_%m_%d_%H_%M_%S")
    t_end_flat = end_time.strftime("%Y_%m_%d_%H_%M_%S")
    
    # Pattern 3: Unix Timestamp
    t_start_unix = int(start_time.timestamp())
    t_end_unix = int(end_time.timestamp())

    patterns = [
        (
            "Standard ONVIF/Uniview Replay",
            f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:{CAMERA_PORT}/playback/service?starttime={t_start_flat}&endtime={t_end_flat}"
        ),
        (
            "Uniview Pattern 2",
            f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:{CAMERA_PORT}/media/video1/playback?starttime={t_start_iso}&endtime={t_end_iso}"
        ),
        (
            "Uniview Unicast Playback",
            f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:{CAMERA_PORT}/unicast/c1/s0/playback?starttime={t_start_iso}&endtime={t_end_iso}"
        ),
         (
            "Alternative Time Format",
            f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:{CAMERA_PORT}/playback/service?starttime={t_start_iso}&endtime={t_end_iso}"
        )
    ]
    
    success = False
    for desc, url in patterns:
        if test_rtsp_playback_url(desc, url):
            print(f"\n🎉 FOUND WORKING URL: {desc}")
            print(f"Format: {url.replace(PASSWORD, '****')}")
            success = True
            break
            
    if not success:
        print("\n❌ All RTSP playback patterns failed.")
        print("Tip: Ensure there is actual recording on the SD card for the requested time range.")
