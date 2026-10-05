"""One-command boot for GrainGuard.

    python run.py            start the server and open the browser
    python run.py --no-open  start the server only

Runs fully offline. Works with no hardware (simulation mode) and no SLM.
"""
import os
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "src", "backend")
HOST = os.environ.get("GRAINGUARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("GRAINGUARD_PORT", "8000"))
URL = f"http://{HOST}:{PORT}/"


def main():
    sys.path.insert(0, BACKEND)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

    try:
        import uvicorn
    except ImportError:
        print("Missing dependencies. Run:  pip install -r requirements.txt")
        return 1

    if "--no-open" not in sys.argv:
        def opener():
            time.sleep(1.5)
            webbrowser.open(URL)
        threading.Thread(target=opener, daemon=True).start()

    print("=" * 58)
    print("  GrainGuard - offline-first grain storage early warning")
    print(f"  Console : {URL}")
    print("  Mode    : simulation / mock telemetry (no hardware required)")
    print("=" * 58)

    uvicorn.run("main:app", host=HOST, port=PORT, log_level="warning",
                reload=False, workers=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())