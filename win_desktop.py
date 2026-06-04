"""
Attach current process to the interactive desktop (WinSta0\Default) in the current session.
This allows screen capture APIs (mss, gdigrab) to work when launched via PsExec or services.
"""
import ctypes
from ctypes import wintypes

# Windows API constants
WINSTA_ACCESS_ALL = 0x37f
DESKTOP_ACCESS_ALL = 0x01ff

# Load libraries
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Function prototypes
OpenWindowStationW = user32.OpenWindowStationW
OpenWindowStationW.restype = wintypes.HANDLE
OpenWindowStationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]

SetProcessWindowStation = user32.SetProcessWindowStation
SetProcessWindowStation.restype = wintypes.BOOL
SetProcessWindowStation.argtypes = [wintypes.HANDLE]

OpenDesktopW = user32.OpenDesktopW
OpenDesktopW.restype = wintypes.HANDLE
OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

SetThreadDesktop = user32.SetThreadDesktop
SetThreadDesktop.restype = wintypes.BOOL
SetThreadDesktop.argtypes = [wintypes.HANDLE]

CloseWindowStation = user32.CloseWindowStation
CloseWindowStation.restype = wintypes.BOOL
CloseWindowStation.argtypes = [wintypes.HANDLE]

CloseDesktop = user32.CloseDesktop
CloseDesktop.restype = wintypes.BOOL
CloseDesktop.argtypes = [wintypes.HANDLE]

def attach_to_interactive_desktop():
    """Switch current process/thread to WinSta0\\Default desktop for screen capture."""
    hwinsta = None
    hdesk = None
    try:
        # Open WinSta0 window station
        hwinsta = OpenWindowStationW("WinSta0", False, WINSTA_ACCESS_ALL)
        if not hwinsta:
            raise OSError(f"OpenWindowStation failed: {ctypes.GetLastError()}")

        if not SetProcessWindowStation(hwinsta):
            raise OSError(f"SetProcessWindowStation failed: {ctypes.GetLastError()}")

        # Open Default desktop
        hdesk = OpenDesktopW("Default", 0, False, DESKTOP_ACCESS_ALL)
        if not hdesk:
            raise OSError(f"OpenDesktop failed: {ctypes.GetLastError()}")

        if not SetThreadDesktop(hdesk):
            raise OSError(f"SetThreadDesktop failed: {ctypes.GetLastError()}")

        return True
    except Exception as e:
        # Don't leak handles on failure
        if hdesk:
            CloseDesktop(hdesk)
        if hwinsta:
            CloseWindowStation(hwinsta)
        raise e
    # Note: we intentionally don't close the handles here because Windows needs them to stay open
    # for the process to remain attached to the desktop. Closing them would detach us.
