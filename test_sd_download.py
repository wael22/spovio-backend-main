import requests
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass
from requests.auth import HTTPDigestAuth

# Configuration
CAMERA_IP = "192.168.100.208"
CAMERA_PORT = 80 # Default HTTP port
USERNAME = "admin"
PASSWORD = "Sgs_2025_"
DOWNLOAD_DIR = "download_test_output"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestDownload")

# --- Mocking/Copying necessary classes to be standalone ---

@dataclass
class RecordingSegment:
    start_time: datetime
    end_time: datetime
    size_bytes: int
    download_url: str
    filename: str

class UniviewDriver:
    def __init__(self, ip: str, port: int, username: str, password: str):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
        self.base_url = f"http://{self.ip}:{self.port}/LAPI/V1.0"
        self.auth = HTTPDigestAuth(self.username, self.password)
        
    def health_check(self) -> bool:
        """Check connection by querying device info"""
        try:
            url = f"{self.base_url}/System/Device/Info"
            print(f"Checking health at: {url}")
            response = requests.get(url, auth=self.auth, timeout=5)
            print(f"Health check status: {response.status_code}")
            if response.status_code == 200:
                 print(f"Device Info: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Uniview health check failed: {e}")
            return False

    def find_recordings(self, start_time: datetime, end_time: datetime) -> List[RecordingSegment]:
        segments = []
        
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
        
        payload = {
            "BeginTime": start_ts,
            "EndTime": end_ts,
            "Type": 0, # 0=Schedule usually
            "Offset": 0,
            "Limit": 100
        }
        
        # Uniview API structure might slightly vary. 
        endpoints_to_try = [
            f"{self.base_url}/Record/Query",
            f"{self.base_url}/Record/Content/Query",
            f"{self.base_url}/Play/Media/Query" 
        ]

        data = {}
        for url in endpoints_to_try:
            print(f"Querying recordings: {url}")
            try:
                response = requests.post(url, json=payload, auth=self.auth, timeout=10)
                print(f"Query response: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    print(f"Response Data: {data}")
                    
                    # Check if valid response
                    resp_wrapper = data.get("Response", {})
                    # If ResponseCode is 0 (Success) or Data exists, we consider it a hit
                    # But if ResponseString is "Not Supported", keep trying
                    if resp_wrapper.get("ResponseString") != "Not Supported":
                         if resp_wrapper.get("ResponseCode") == 0 or "Data" in resp_wrapper:
                            print(f"✅ Success with endpoint: {url}")
                            break 
            except Exception as e:
                print(f"Failed to query {url}: {e}")
        
        try:
            if "Response" in data and "Data" in data["Response"]:
                # Handle both single record (dict) or list of records
                records_data = data["Response"]["Data"]
                
                # Check for null data
                if not records_data or records_data == "null":
                    return []

                # Some versions return { Total: X, Records: [...] }
                # Others might differ. Code expects "Records" inside Data.
                if isinstance(records_data, dict):
                    records = records_data.get("Records", [])
                else:
                    records = [] # Unknown format
                
                print(f"Found {len(records)} records")
                
                for rec in records:
                    seg_start = datetime.fromtimestamp(rec.get("BeginTime"))
                    seg_end = datetime.fromtimestamp(rec.get("EndTime"))
                    
                    # Use clean URL construction
                    download_url = (
                        f"{self.base_url}/Record/Download"
                        f"?BeginTime={rec.get('BeginTime')}"
                        f"&EndTime={rec.get('EndTime')}"
                    )
                    
                    segments.append(RecordingSegment(
                        start_time=seg_start,
                        end_time=seg_end,
                        size_bytes=rec.get("Size", 0),
                        download_url=download_url,
                        filename=f"uniview_{rec.get('BeginTime')}_{rec.get('EndTime')}.mp4"
                    ))
                    
        except Exception as e:
            logger.error(f"Error searching Uniview recordings: {e}")
            
        return segments

    def download_segment(self, segment: RecordingSegment, output_path: str, timeout: int = 300) -> bool:
        try:
            logger.info(f"Downloading segment from {segment.download_url}")
            
            # Streaming download
            with requests.get(segment.download_url, auth=self.auth, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        f.write(chunk)
            
            return True
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

if __name__ == "__main__":
    print("=== Testing SD Card Download ===")
    
    driver = UniviewDriver(CAMERA_IP, CAMERA_PORT, USERNAME, PASSWORD)
    
    # 1. Health Check
    if not driver.health_check():
        print("❌ Health check FAILED. Aborting.")
        exit(1)
    
    print("✅ Health check PASSED.")
    
    # Check Time Info (Stability Check)
    try:
        url = f"http://{driver.ip}:{driver.port}/LAPI/V1.0/System/Time/Info"
        r = requests.get(url, auth=driver.auth, timeout=5)
        print(f"Time Info Status: {r.status_code}")
    except:
        pass

    # Check Storage
    try:
        url = f"http://{driver.ip}:{driver.port}/LAPI/V1.0/System/Storage/Info"
        print(f"Checking Storage at: {url}")
        r = requests.get(url, auth=driver.auth, timeout=5)
        print(f"Storage Info: {r.text}")
    except Exception as e:
        print(f"Storage check failed: {e}")

    # 2. Search for recordings (Last 24 hours to be safe)
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)
    
    print(f"Searching recordings from {start_time} to {end_time}...")
    segments = driver.find_recordings(start_time, end_time)
    
    if not segments:
        print("❌ No recordings found.")
        exit(0)
        
    print(f"✅ Found {len(segments)} segments.")
    
    # 3. Download the FIRST segment (shortest test)
    import os
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        
    # Pick the last one (most recent)
    target_segment = segments[-1]
    output_file = os.path.join(DOWNLOAD_DIR, f"test_download_{int(time.time())}.mp4")
    
    print(f"Downloading segment: {target_segment.filename}")
    print(f"Size: {target_segment.size_bytes} bytes")
    
    if driver.download_segment(target_segment, output_file):
        print(f"✅ Download SUCCESS: {output_file}")
        print(f"File size on disk: {os.path.getsize(output_file)} bytes")
    else:
        print("❌ Download FAILED.")
