import ctypes
import psutil
import time

# Paramètres Windows pour empêcher la mise en veille
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

# Noms des processus à surveiller
process_names = ["lm studio.exe", "docker desktop.exe", "com.docker.backend.exe"]

def is_process_running(names):
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() in names:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

try:
    while True:
        if is_process_running(process_names):
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        else:
            # Laisse Windows gérer la mise en veille normalement
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        time.sleep(30)
finally:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

