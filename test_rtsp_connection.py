import cv2
import time
import socket
from urllib.parse import urlparse

# Configuration provided by user
RTSP_URL = "rtsp://admin:Sgs_2025_@102.159.10.239:554/media/video1"
# RTSP_URL = "rtsp://admin:Sgs_2025_@192.168.100.208:554/media/video1" # Alternative local IP if needed

def parse_rtsp_url(url):
    """Simulate the parsing logic"""
    print(f"\n[1] Parsing URL: {url}")
    try:
        # Simple manual parsing to match service logic
        if '@' in url:
            clean_url = url.split('://')[-1]
            auth_part, address_part = clean_url.split('@', 1)
            
            if ':' in auth_part:
                username, password = auth_part.split(':', 1)
            else:
                username = auth_part
                password = None
            
            if '/' in address_part:
                address_part = address_part.split('/')[0]
                
            if ':' in address_part:
                ip, port_str = address_part.split(':', 1)
                port = int(port_str)
            else:
                ip = address_part
                port = 554
                
            print(f"    ✅ User: {username}")
            print(f"    ✅ Pass: {password}")
            print(f"    ✅ IP:   {ip}")
            print(f"    ✅ Port: {port}")
            return ip, port, username, password
        else:
            print("    ❌ No credentials found in URL")
            return None
    except Exception as e:
        print(f"    ❌ Parsing failed: {e}")
        return None

def check_socket_connection(ip, port):
    """Check if the port is open"""
    print(f"\n[2] Checking TCP Connection to {ip}:{port}...")
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0) # 3 seconds timeout
        result = sock.connect_ex((ip, port))
        sock.close()
        duration = time.time() - start
        
        if result == 0:
            print(f"    ✅ Connection SUCCESS ({duration:.2f}s)")
            return True
        else:
            print(f"    ❌ Connection FAILED (Error code: {result})")
            return False
    except Exception as e:
        print(f"    ❌ Connection ERROR: {e}")
        return False

def test_rtsp_stream(url):
    """Try to open the stream with OpenCV"""
    print(f"\n[3] Testing RTSP Stream with OpenCV...")
    print("    ⏳ Connecting... (this may take up to 10s)")
    
    cap = cv2.VideoCapture(url)
    
    if not cap.isOpened():
        print("    ❌ Failed to open RTSP stream")
        return
    
    print("    ✅ Stream Opened Successfully!")
    
    # Try to read a frame
    ret, frame = cap.read()
    if ret:
        print(f"    ✅ Frame received! Resolution: {frame.shape[1]}x{frame.shape[0]}")
        # Optional: Save a frame to prove it works
        # cv2.imwrite("test_frame.jpg", frame)
    else:
        print("    ⚠️ Stream opened but failed to read first frame")
        
    cap.release()

if __name__ == "__main__":
    print("=== RTSP Connection Validation Tool ===")
    
    parsed = parse_rtsp_url(RTSP_URL)
    
    if parsed:
        ip, port, user, pwd = parsed
        
        # 1. Check network reachability
        if check_socket_connection(ip, port):
            # 2. Check stream content
            test_rtsp_stream(RTSP_URL)
        else:
            print("\n⚠️ Skipping stream test because port is unreachable.")
    
    print("\n=== End of Test ===")
