#!/usr/bin/env python3
"""
macos_privacy.py -- macOS Screen Recording Permission request.

Uses ctypes to call CoreGraphics APIs.
1. Checks if we already have permission.
2. If not, requests it (this triggers the native macOS popup).
3. If still denied, guides the user to System Settings.
"""

import sys
import time

def check_and_request_permission():
    if sys.platform != "darwin":
        return True

    try:
        import ctypes
        import ctypes.util

        # Load CoreGraphics framework
        cg_path = ctypes.util.find_library("CoreGraphics")
        if not cg_path:
            return False
        
        CG = ctypes.cdll.LoadLibrary(cg_path)

        # bool CGPreflightScreenCaptureAccess(void);
        CG.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        CG.CGPreflightScreenCaptureAccess.argtypes = []

        # bool CGRequestScreenCaptureAccess(void);
        CG.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        CG.CGRequestScreenCaptureAccess.argtypes = []

        # 1. Check if we already have it
        has_access = CG.CGPreflightScreenCaptureAccess()
        if has_access:
            print("  [OK] Screen Recording permission: Granted")
            return True

        # 2. We don't have it, request it
        print("  [!!] Screen Recording permission required.")
        print("       Triggering macOS permission prompt...")
        
        # This triggers the popup
        CG.CGRequestScreenCaptureAccess()

        # Give the user a moment to see the prompt
        print("  [>>] Please click 'Open System Settings' and grant permission to your terminal.")
        print("       Once granted, you MUST restart this terminal for it to take effect.")
        return False

    except Exception as e:
        print(f"  [FAIL] Could not verify macOS permissions: {e}")
        return False

if __name__ == "__main__":
    if sys.platform != "darwin":
        print("This script is only for macOS.")
        sys.exit(0)
        
    print("\nChecking macOS Privacy Settings...")
    if check_and_request_permission():
        sys.exit(0)
    else:
        sys.exit(1)
