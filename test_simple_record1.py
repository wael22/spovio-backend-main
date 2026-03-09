import subprocess

def test_url(url, description, filename):
    print(f"\n--- Testing: {description} ---")
    print(f"URL: {url}")
    
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-c", "copy",
        "-t", "10",
        filename
    ]
    
    try:
        # Run and capture output
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        
        # Print FULL stderr for debugging
        print("\n--- FFmpeg Output (stderr) ---")
        print(result.stderr.decode())
        
        if result.returncode == 0:
            print(f"✅ Capture finished: {filename}")
        else:
            print(f"❌ FFmpeg failed with code {result.returncode}")
            
    except subprocess.TimeoutExpired:
        print("❌ Timeout: FFmpeg took too long")
    except Exception as e:
        print(f"❌ Python Error: {e}")

# Credentials
IP = "192.168.100.208"
PORT = 554
USER = "admin"
PASS = "Sgs_2025_"

# Simple URL: No time parameters
url = f"rtsp://{USER}:{PASS}@{IP}:{PORT}/media/record1"

test_url(url, "Simple /media/record1", "simple_record1_test.mp4")
