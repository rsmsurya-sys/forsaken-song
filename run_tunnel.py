import subprocess
import re
import time
import webbrowser
import sys
import socket
from pathlib import Path

def is_server_running(host="127.0.0.1", port=8000):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0

def start_server_if_needed():
    if is_server_running():
        print("✓ Local server is already running on http://127.0.0.1:8000")
        return None
    
    print("Local server is not running. Starting uvicorn on http://127.0.0.1:8000...")
    server_cmd = [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
    try:
        server_proc = subprocess.Popen(server_cmd)
        # Give server 2 seconds to bind port
        time.sleep(2)
        return server_proc
    except Exception as e:
        print(f"Warning: Could not auto-start server ({e}). Please ensure run_local.bat is running.")
        return None

def main():
    print("--------------------------------------------------")
    print("Starting Forsaken Music & Cloudflare Tunnel...")
    print("--------------------------------------------------")

    # Auto-start backend server if not running
    server_proc = start_server_if_needed()

    exe_path = Path("cloudflared.exe")
    if not exe_path.exists():
        print("Error: cloudflared.exe not found in workspace.")
        return

    # Use HTTP2 protocol to bypass ISP UDP/QUIC port blocks (fixes Error 1033)
    cmd = [
        str(exe_path.resolve()), 
        "tunnel", 
        "--protocol", "http2", 
        "--url", "http://127.0.0.1:8000"
    ]
    
    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1
    )

    url_found = False
    try:
        for line in proc.stderr:
            print(line, end="", flush=True)
            if not url_found:
                match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
                if match:
                    url = match.group(0)
                    url_found = True
                    
                    # Save to file
                    Path("CLOUDFLARE_URL.txt").write_text(
                        f"Your Live App URL: {url}\n"
                        f"Desktop Player: {url}/desktop\n"
                        f"Mobile Player:  {url}/mobile\n"
                        f"Admin Portal:   {url}/admin\n", 
                        encoding="utf-8"
                    )
                    
                    print("\n" + "="*70)
                    print("  🎉 CLOUDFLARE LIVE URL IS READY! 🎉")
                    print(f"  Desktop Player: {url}/desktop")
                    print(f"  Mobile Player:  {url}/mobile")
                    print(f"  Admin Portal:   {url}/admin")
                    print("="*70)
                    print("  Waiting 5 seconds for Cloudflare Global DNS to activate...")
                    print("="*70 + "\n")
                    
                    time.sleep(5)
                    try:
                        webbrowser.open(f"{url}/desktop")
                    except Exception:
                        pass

        proc.wait()
    except KeyboardInterrupt:
        print("\nStopping Tunnel and Server...")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        if server_proc:
            try:
                server_proc.terminate()
            except Exception:
                pass

if __name__ == "__main__":
    main()
