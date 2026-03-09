#!/usr/bin/env python3
"""
Proof-of-Concept: NetDEVSDK Integration via ctypes
Tests NETDEV_GetFileByTime API for downloading Uniview recordings
"""

import ctypes
from ctypes import *
from datetime import datetime, timedelta
import time
import os
import sys

# =============================================================================
# CONFIGURATION
# =============================================================================

SDK_PATH = r"C:\Users\PC\Downloads\NETDEVSDK_Win64_V2.7.0.1_IN\NETDEVSDK_Win64_V2.7.0.1_IN\bin\NetDEVSDK.dll"
CAMERA_IP = "192.168.100.208"
PORTS_TO_TRY = [80, 37777, 8000, 443, 554]  # Try all possible ports
USERNAME = "admin"
PASSWORD = "Sgs_2025_"
CHANNEL_ID = 1
OUTPUT_DIR = r"C:\Users\PC\Desktop\e171abab-6030-4c66-be1d-b73969cd489a-files\spovio-backend-main\sdk_downloads"

# =============================================================================
# CTYPES STRUCTURES (from NetDEVSDK.h)
# =============================================================================

class NETDEV_DEVICE_LOGIN_INFO_S(Structure):
    """Device login info structure (V30)"""
    _fields_ = [
        ("szIPAddr", c_char * 129),       # IP address
        ("dwPort", c_int),                 # Port
        ("szUserName", c_char * 33),      # Username
        ("szPassword", c_char * 65),      # Password
        ("dwLoginProto", c_int),          # Login protocol (0=Private, 1=ONVIF)
        ("byRes", c_byte * 103)           # Reserved
    ]

class NETDEV_SELOG_INFO_S(Structure):
    """Security log info structure"""
    _fields_ = [
        ("szDevMac", c_char * 64),        # Device MAC
        ("szDevSerial", c_char * 64),     # Device serial
        ("byRes", c_byte * 64)            # Reserved
    ]

class NETDEV_DEVICE_INFO_S(Structure):
    """Device info structure"""
    _fields_ = [
        ("dwDevType", c_int),
        ("byMasterSlaveType", c_byte),
        ("szSerialNum", c_char * 64),
        ("szDevModel", c_char * 64),
        ("szDevName", c_char * 132),
        ("byRes", c_byte * 192)
    ]

class NETDEV_PLAYBACKCOND_S(Structure):
    """Playback condition structure"""
    _fields_ = [
        ("dwChannelID", c_int),           # Channel ID
        ("tBeginTime", c_int64),          # Start time (Unix timestamp)
        ("tEndTime", c_int64),            # End time (Unix timestamp)
        ("hPlayWnd", c_void_p),           # Window handle (NULL for download)
        ("dwLinkMode", c_int),            # Protocol (TCP=0, UDP=1)
        ("dwFileType", c_int),            # File type
        ("dwDownloadSpeed", c_int),       # Download speed (0-8)
        ("byRes", c_byte * 256)           # Reserved
    ]

# =============================================================================
# CONSTANTS
# =============================================================================

NETDEV_TRUE = 1
NETDEV_FALSE = 0

# Login Protocol
NETDEV_LOGIN_PROTO_PRIVATE = 0  # Uniview VMS/NVR
NETDEV_LOGIN_PROTO_ONVIF = 1    # IP Cameras (IPC)

# Protocol
NETDEV_TRANSPROTOCAL_RTPTCP = 0
NETDEV_TRANSPROTOCAL_RTPUDP = 1

# File format
NETDEV_MEDIA_FILE_MP4 = 0
NETDEV_MEDIA_FILE_TS = 1

# Download speed
NETDEV_DOWNLOAD_SPEED_NORMAL = 1
NETDEV_DOWNLOAD_SPEED_EIGHT = 8

# Playback control
NETDEV_PLAY_CTRL_GETPLAYTIME = 2

# =============================================================================
# SDK WRAPPER
# =============================================================================

class NetDEVSDK:
    """Wrapper for Uniview NetDEVSDK"""
    
    def __init__(self, dll_path):
        """Load SDK DLL"""
        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"SDK DLL not found: {dll_path}")
        
        print(f"[SDK] Loading DLL: {dll_path}")
        self.dll = ctypes.CDLL(dll_path)
        self._setup_functions()
    
    def _setup_functions(self):
        """Define function signatures"""
        
        # NETDEV_Init
        self.dll.NETDEV_Init.argtypes = []
        self.dll.NETDEV_Init.restype = c_int
        
        # NETDEV_Cleanup
        self.dll.NETDEV_Cleanup.argtypes = []
        self.dll.NETDEV_Cleanup.restype = c_int
        
        # NETDEV_Login_V30
        self.dll.NETDEV_Login_V30.argtypes = [
            POINTER(NETDEV_DEVICE_LOGIN_INFO_S),
            POINTER(NETDEV_SELOG_INFO_S)
        ]
        self.dll.NETDEV_Login_V30.restype = c_void_p
        
        # NETDEV_Logout
        self.dll.NETDEV_Logout.argtypes = [c_void_p]
        self.dll.NETDEV_Logout.restype = c_int
        
        # NETDEV_GetFileByTime
        self.dll.NETDEV_GetFileByTime.argtypes = [
            c_void_p,                        # Device handle
            POINTER(NETDEV_PLAYBACKCOND_S),  # Playback condition
            c_char_p,                        # Save path
            c_int                            # Format
        ]
        self.dll.NETDEV_GetFileByTime.restype = c_void_p
        
        # NETDEV_StopGetFile
        self.dll.NETDEV_StopGetFile.argtypes = [c_void_p]
        self.dll.NETDEV_StopGetFile.restype = c_int
        
        # NETDEV_PlayBackControl
        self.dll.NETDEV_PlayBackControl.argtypes = [
            c_void_p,           # Handle
            c_int,              # Command
            POINTER(c_int64)    # Parameter
        ]
        self.dll.NETDEV_PlayBackControl.restype = c_int
        
        # NETDEV_GetLastError
        self.dll.NETDEV_GetLastError.argtypes = []
        self.dll.NETDEV_GetLastError.restype = c_int
    
    def init(self):
        """Initialize SDK"""
        result = self.dll.NETDEV_Init()
        if result != NETDEV_TRUE:
            raise Exception(f"SDK Init failed: {self.dll.NETDEV_GetLastError()}")
        print("[SDK] Initialized successfully")
    
    def cleanup(self):
        """Cleanup SDK"""
        result = self.dll.NETDEV_Cleanup()
        print(f"[SDK] Cleanup: {result}")
    
    def login(self, ip, port, username, password):
        """Login to device (V30 API)"""
        login_info = NETDEV_DEVICE_LOGIN_INFO_S()
        login_info.szIPAddr = ip.encode('utf-8')
        login_info.dwPort = port
        login_info.szUserName = username.encode('utf-8')
        login_info.szPassword = password.encode('utf-8')
        login_info.dwLoginProto = NETDEV_LOGIN_PROTO_ONVIF  # Use ONVIF for IPC cameras
        
        selog_info = NETDEV_SELOG_INFO_S()
        
        handle = self.dll.NETDEV_Login_V30(
            byref(login_info),
            byref(selog_info)
        )
        
        if not handle:
            error = self.dll.NETDEV_GetLastError()
            raise Exception(f"Login failed: Error {error}")
        
        print(f"[SDK] Logged in successfully")
        print(f"      Device MAC: {selog_info.szDevMac.decode('utf-8', errors='ignore')}")
        print(f"      Serial: {selog_info.szDevSerial.decode('utf-8', errors='ignore')}")
        
        return handle
    
    def logout(self, handle):
        """Logout from device"""
        result = self.dll.NETDEV_Logout(handle)
        print(f"[SDK] Logout: {result}")
    
    def download_recording(self, device_handle, channel_id, start_time, end_time, save_path):
        """Download recording by time"""
        
        # Prepare playback condition
        cond = NETDEV_PLAYBACKCOND_S()
        cond.dwChannelID = channel_id
        cond.tBeginTime = int(start_time.timestamp())
        cond.tEndTime = int(end_time.timestamp())
        cond.hPlayWnd = None
        cond.dwLinkMode = NETDEV_TRANSPROTOCAL_RTPTCP
        cond.dwDownloadSpeed = NETDEV_DOWNLOAD_SPEED_EIGHT
        
        print(f"\n[Download] Starting...")
        print(f"  Channel: {channel_id}")
        print(f"  Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')} (Unix: {int(start_time.timestamp())})")
        print(f"  End: {end_time.strftime('%Y-%m-%d %H:%M:%S')} (Unix: {int(end_time.timestamp())})")
        print(f"  Duration: {(end_time - start_time).total_seconds()} seconds")
        print(f"  Save to: {save_path}")
        
        # Start download
        download_handle = self.dll.NETDEV_GetFileByTime(
            device_handle,
            byref(cond),
            save_path.encode('utf-8'),
            NETDEV_MEDIA_FILE_MP4
        )
        
        if not download_handle:
            error = self.dll.NETDEV_GetLastError()
            raise Exception(f"Download failed to start: Error {error}")
        
        print(f"[Download] Started! Handle: {download_handle}")
        
        # Monitor progress
        try:
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())
            duration = end_ts - start_ts
            
            while True:
                # Get current playback time
                current_time = c_int64(0)
                result = self.dll.NETDEV_PlayBackControl(
                    download_handle,
                    NETDEV_PLAY_CTRL_GETPLAYTIME,
                    byref(current_time)
                )
                
                if result == NETDEV_TRUE:
                    cur_ts = current_time.value
                    if cur_ts >= end_ts:
                        print(f"\n[Download] Complete! Downloaded until {cur_ts}")
                        break
                    
                    # Calculate progress
                    if cur_ts > start_ts:
                        progress = ((cur_ts - start_ts) / duration) * 100
                        print(f"  Progress: {progress:.1f}% (Time: {cur_ts})", end='\r')
                
                time.sleep(1)
        
        finally:
            # Stop download
            print(f"\n[Download] Stopping...")
            self.dll.NETDEV_StopGetFile(download_handle)
            print(f"[Download] Stopped")

# =============================================================================
# MAIN TEST
# =============================================================================

def main():
    print("=" * 70)
    print("NetDEVSDK Proof-of-Concept Test")
    print("=" * 70)
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Initialize SDK
    sdk = NetDEVSDK(SDK_PATH)
    
    try:
        sdk.init()
        
        # Try multiple ports
        device_handle = None
        successful_port = None
        
        for port in PORTS_TO_TRY:
            print(f"\n[Login] Trying {CAMERA_IP}:{port}...")
            try:
                device_handle = sdk.login(CAMERA_IP, port, USERNAME, PASSWORD)
                successful_port = port
                print(f"✅ SUCCESS on port {port}!")
                break
            except Exception as e:
                print(f"❌ Failed on port {port}: {e}")
                continue
        
        if not device_handle:
            raise Exception("Login failed on all ports")
        
        try:
            # Define time range: last 5 minutes
            end_time = datetime.now()
            start_time = end_time - timedelta(minutes=5)
            
            # Output file
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(OUTPUT_DIR, f"recording_{timestamp_str}.mp4")
            
            # Download
            sdk.download_recording(
                device_handle,
                CHANNEL_ID,
                start_time,
                end_time,
                output_file
            )
            
            # Check file
            if os.path.exists(output_file):
                size_mb = os.path.getsize(output_file) / (1024 * 1024)
                print(f"\n✅ SUCCESS!")
                print(f"  File: {output_file}")
                print(f"  Size: {size_mb:.2f} MB")
                
                # Verify with ffprobe
                print(f"\n[Verify] Checking file integrity with ffprobe...")
                import subprocess
                try:
                    result = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_format", "-show_streams", output_file],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        print(f"✅ File is valid and playable!")
                    else:
                        print(f"⚠️  ffprobe returned error: {result.stderr}")
                except Exception as e:
                    print(f"⚠️  Could not verify with ffprobe: {e}")
            else:
                print(f"\n❌ File not created: {output_file}")
        
        finally:
            sdk.logout(device_handle)
    
    finally:
        sdk.cleanup()
    
    print("\n" + "=" * 70)
    print("Test Complete")
    print("=" * 70)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
