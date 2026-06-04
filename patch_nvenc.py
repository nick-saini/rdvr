#!/usr/bin/env python3
r"""Apply .1337 patch files to NVIDIA driver DLLs to remove NVENC session limit.

Usage (as Administrator):
    python patch_nvenc.py --patch
    python patch_nvenc.py --restore

The patch files (.1337) are searched in .\nvidia-patch\<driver_version>\.
Driver version is auto-detected from nvencodeapi64.dll product version.
"""
from __future__ import annotations
import os, sys, re, struct, shutil, glob, subprocess, argparse

PATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nvidia-patch")
DLL_DIRS = [
    r"C:\Windows\System32",
    r"C:\Windows\SysWOW64",
]


def _find_dll(name: str) -> str | None:
    for d in DLL_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def _get_driver_version() -> str:
    """Detect NVIDIA driver version from nvidia-smi."""
    nsmi = r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    cmd = [nsmi] if os.path.isfile(nsmi) else ["nvidia-smi"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    m = re.search(r"Driver Version:\s+([0-9]+\.[0-9]+)", out)
    if m:
        return m.group(1)
    m = re.search(r"NVIDIA-SMI\s+([0-9]+\.[0-9]+)", out)
    if m:
        return m.group(1)
    raise RuntimeError("Cannot detect driver version from nvidia-smi")


def _parse_1337(path: str) -> dict[str, list[tuple[int, int, int]]]:
    """Return {dll_name: [(offset, old_byte, new_byte), ...]}."""
    patches: dict[str, list[tuple[int, int, int]]] = {}
    current_dll: str | None = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(">"):
                current_dll = line[1:].strip()
                patches.setdefault(current_dll, [])
                continue
            if current_dll is None:
                continue
            m = re.match(r"^([0-9A-Fa-f]+):([0-9A-Fa-f]{2})->([0-9A-Fa-f]{2})$", line)
            if not m:
                continue
            off = int(m.group(1), 16)
            old = int(m.group(2), 16)
            new = int(m.group(3), 16)
            patches[current_dll].append((off, old, new))
    return patches


def _apply_1337(patch_path: str, dry_run: bool = False) -> list[str]:
    patches = _parse_1337(patch_path)
    applied: list[str] = []
    for dll_name, offs in patches.items():
        dll_path = _find_dll(dll_name)
        if not dll_path:
            print(f"  [!] {dll_name} not found — skipped")
            continue
        bak = dll_path + ".bak"
        if not dry_run and not os.path.exists(bak):
            try:
                shutil.copy2(dll_path, bak)
                print(f"  [+] Backed up {dll_name}")
            except Exception as e:
                print(f"  [!] Could not back up {dll_name}: {e}")
                continue
        try:
            mode = "rb" if dry_run else "r+b"
            with open(dll_path, mode) as f:
                for off, old, new in offs:
                    f.seek(off)
                    byte = struct.unpack("B", f.read(1))[0]
                    if byte != old:
                        print(f"  [!] {dll_name} @ 0x{off:X}: expected 0x{old:02X}, found 0x{byte:02X} — aborting this file")
                        break
                    if not dry_run:
                        f.seek(off)
                        f.write(struct.pack("B", new))
                else:
                    applied.append(dll_name)
                    if dry_run:
                        print(f"  [i] {dll_name} verified OK (dry-run)")
                    else:
                        print(f"  [+] Patched {dll_name}")
        except PermissionError:
            print(f"  [!] Permission denied accessing {dll_name}. Run as Administrator and ensure the file is not locked.")
        except Exception as e:
            print(f"  [!] Error patching {dll_name}: {e}")
    return applied


def _restore_dlls() -> None:
    for dll_name in ("nvencodeapi64.dll", "nvencodeapi.dll"):
        for d in DLL_DIRS:
            p = os.path.join(d, dll_name)
            bak = p + ".bak"
            if os.path.isfile(bak):
                shutil.copy2(bak, p)
                print(f"  [+] Restored {dll_name} from backup")


def _find_patch_files(driver_ver: str) -> list[str]:
    """Look for exact or closest patch files."""
    # Exact match
    exact = os.path.join(PATCH_DIR, driver_ver)
    if os.path.isdir(exact):
        files = glob.glob(os.path.join(exact, "*.1337"))
        if files:
            return files
    # Fallback: try to find closest lower version
    if not os.path.isdir(PATCH_DIR):
        return []
    versions = [d for d in os.listdir(PATCH_DIR) if os.path.isdir(os.path.join(PATCH_DIR, d))]
    versions.sort(key=lambda v: [int(x) for x in v.split(".")])
    candidates = [v for v in versions if v <= driver_ver]
    if candidates:
        closest = candidates[-1]
        print(f"  [i] No exact patch for {driver_ver}; using closest {closest} (may or may not work)")
        return glob.glob(os.path.join(PATCH_DIR, closest, "*.1337"))
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply NVENC session-limit patch")
    parser.add_argument("--patch", action="store_true", help="Apply patch")
    parser.add_argument("--restore", action="store_true", help="Restore original DLLs")
    parser.add_argument("--dry-run", action="store_true", help="Verify patch without writing")
    parser.add_argument("--force-version", help="Override driver version for patch lookup")
    args = parser.parse_args()

    if not (args.patch or args.restore or args.dry_run):
        parser.print_help()
        sys.exit(1)

    if args.restore:
        print("[*] Restoring original nvencodeapi DLLs...")
        _restore_dlls()
        sys.exit(0)

    ver = args.force_version or _get_driver_version()
    print(f"[*] Detected NVIDIA driver version: {ver}")

    patch_files = _find_patch_files(ver)
    if not patch_files:
        print(f"[!] No patch files found for driver {ver} in {PATCH_DIR}")
        print("    Options:")
        print("    1) Downgrade to a supported driver (see README_NVENC.md)")
        print("    2) Wait for nvidia-patch maintainers to add support")
        print("    3) Use --force-version VERSION to try a nearby patch (risky)")
        sys.exit(1)

    mode = "dry-run" if args.dry_run else "patch"
    print(f"[*] Applying {mode} using {len(patch_files)} patch file(s)...")
    for pf in patch_files:
        print(f"[*] Reading {os.path.basename(pf)}...")
        _apply_1337(pf, dry_run=args.dry_run)

    if args.dry_run:
        print("[*] Dry-run complete. No files were modified.")
    else:
        print("[*] Patch applied. Reboot recommended before testing NVENC.")


if __name__ == "__main__":
    main()
