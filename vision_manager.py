import subprocess
import sys
import os

proc = None

def start_vision():
    global proc
    if proc is not None and proc.poll() is None:
        return "Vision control is already running, sir."

    script_path = os.path.join(os.path.dirname(__file__), "vision_controller.py")
    if not os.path.exists(script_path):
        return f"Cannot find vision_controller.py at {script_path}"

    try:
        proc = subprocess.Popen([sys.executable, script_path])
        return "Holographic workspace online. Deploying Mark 57 HUD."
    except Exception as e:
        return f"Failed to activate vision control: {str(e)}"

def stop_vision():
    global proc
    if proc is not None and proc.poll() is None:
        proc.terminate()
        proc.wait()
        proc = None
        return "Disengaging holographic interface. Camera released."
    return "Holographic interface is not running, sir."

def toggle_vision(action="start"):
    if action == "start":
        return start_vision()
    elif action == "stop":
        return stop_vision()
    else:
        if proc is not None and proc.poll() is None:
            return stop_vision()
        return start_vision()