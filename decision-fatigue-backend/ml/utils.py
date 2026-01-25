import sqlite3
import json
import numpy as np

DB_PATH = "../behavior.db"

FEATURES = [
    "typing_speed",
    "typing_variance",
    "backspace_rate",
    "backspace_burst_rate",
    "ctrl_z_rate",
    "mouse_speed",
    "mouse_distance"
]

def load_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT data FROM behavior_windows")
    rows = cursor.fetchall()
    conn.close()

    X = []
    for row in rows:
        window = json.loads(row[0])
        X.append([window[f] for f in FEATURES])

    return np.array(X)
