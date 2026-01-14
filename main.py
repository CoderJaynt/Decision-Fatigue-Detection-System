from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
import json
from fastapi.middleware.cors import CORSMiddleware
import statistics
from fastapi.responses import HTMLResponse
import numpy as np
import tensorflow as tf
import os
from datetime import datetime, timedelta

fatigue_history = []
FATIGUE_WINDOW = 5      # last 5 minutes
ALERT_THRESHOLD = 0.6

DEV_FORCE_ALERT = True  # set False in production


last_alert_time = None
HIGH_FATIGUE_COUNT = 0
ALERT_COOLDOWN_MINUTES = 30


load_model = tf.keras.models.load_model

ae_model = None
ae_mean = None
ae_std = None
ae_threshold = None

if os.path.exists("ml/autoencoder.h5"):
    ae_model = load_model("ml/autoencoder.h5")
    ae_mean = np.load("ml/mean.npy")
    ae_std = np.load("ml/std.npy")
    ae_threshold = float(np.load("ml/threshold.npy"))
    print("✅ Autoencoder model loaded")
else:
    print("⚠️ Autoencoder model not found. ML scoring disabled.")


# -----------------------------
# LSTM Autoencoder (temporal)
# -----------------------------
lstm_model = None
lstm_mean = None
lstm_std = None
lstm_threshold = None
lstm_buffer = []

LSTM_SEQUENCE_LENGTH = 5

if os.path.exists("ml/lstm_autoencoder.h5"):
    lstm_model = tf.keras.models.load_model("ml/lstm_autoencoder.h5")
    lstm_mean = np.load("ml/lstm_mean.npy")
    lstm_std = np.load("ml/lstm_std.npy")
    lstm_threshold = float(np.load("ml/lstm_threshold.npy"))
    print("✅ LSTM Autoencoder loaded")
else:
    print("⚠️ LSTM model not found. Temporal ML disabled.")


app = FastAPI()



FEATURES = [
    "typing_speed",
    "typing_variance",
    "backspace_rate",
    "backspace_burst_rate",
    "ctrl_z_rate",
    "mouse_speed",
    "mouse_distance"
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Database Setup ----------
conn = sqlite3.connect("behavior.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS behavior_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    data TEXT,
    fatigue_score REAL,
    rule_score REAL,
    ml_score REAL
)
""")
conn.commit()



# ---------- Schema ----------
class FeatureWindow(BaseModel):
    timestamp: str
    typing_speed: float
    typing_variance: float
    backspace_rate: float
    mouse_speed: float
    mouse_distance: float
    ctrl_z_rate: int
    backspace_burst_rate: int
    window_duration: float

def get_recent_fatigue_average(conn, limit=5):
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT fatigue_score 
        FROM behavior_windows
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,)
    )
    rows = cursor.fetchall()

    if len(rows) == 0:
        return None

    scores = [r[0] for r in rows]
    return sum(scores) / len(scores)


def get_baseline(min_windows: int = 10):

    cursor = conn.cursor()

    cursor.execute("SELECT data FROM behavior_windows")
    rows = cursor.fetchall()

    # Not enough data → no baseline yet
    if len(rows) < min_windows:
        return None

    windows = [json.loads(r[0]) for r in rows]

    import statistics

    def stats(feature):
        vals = [w.get(feature, 0) for w in windows]
        return {
            "mean": statistics.mean(vals),
            "std": statistics.stdev(vals) if len(vals) > 1 else 1.0
        }

    return {
        "typing_speed": stats("typing_speed"),
        "typing_variance": stats("typing_variance"),
        "backspace_rate": stats("backspace_rate"),
        "backspace_burst_rate": stats("backspace_burst_rate"),
        "ctrl_z_rate": stats("ctrl_z_rate"),
        "mouse_speed": stats("mouse_speed"),
        "mouse_distance": stats("mouse_distance")
    }


def compute_fatigue_score(current, baseline):
    weights = {
        "typing_speed": 0.15,
        "typing_variance": 0.2,
        "backspace_rate": 0.15,
        "backspace_burst_rate": 0.15,
        "ctrl_z_rate": 0.1,
        "mouse_speed": 0.15,
        "mouse_distance": 0.1
    }

    score = 0

    for feature, weight in weights.items():
        mean = baseline[feature]["mean"]
        std = baseline[feature]["std"] or 1
        z = abs(current[feature] - mean) / std
        score += min(z / 3, 1) * weight  # normalize

    return round(score, 3)

def ml_fatigue_score(window: dict) -> float:
    if ae_model is None:
        return 0.0

    x = np.array([window[f] for f in FEATURES], dtype=np.float32)
    x_norm = (x - ae_mean) / ae_std

    recon = ae_model.predict(x_norm.reshape(1, -1), verbose=0)
    error = np.mean((x_norm - recon[0]) ** 2)

    score = min(error / ae_threshold, 1.0)
    return round(float(score), 3)


def lstm_fatigue_score(window: dict) -> float:
    if lstm_model is None:
        return 0.0

    features = np.array(
        [window[f] for f in FEATURES],
        dtype=np.float32
    )

    # Normalize
    x = (features - lstm_mean) / lstm_std

    # Buffer last N windows
    lstm_buffer.append(x)

    if len(lstm_buffer) < LSTM_SEQUENCE_LENGTH:
        return 0.0

    if len(lstm_buffer) > LSTM_SEQUENCE_LENGTH:
        lstm_buffer.pop(0)

    seq = np.array(lstm_buffer).reshape(
        1, LSTM_SEQUENCE_LENGTH, len(features)
    )

    recon = lstm_model.predict(seq, verbose=0)
    error = np.mean((seq - recon) ** 2)

    score = min(error / lstm_threshold, 1.0)
    return round(float(score), 3)

ALERT_THRESHOLD = 0.40
SUSTAINED_WINDOWS = 2  # number of consecutive windows

def should_alert(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT fatigue_score
        FROM behavior_windows
        ORDER BY id DESC
        LIMIT ?
    """, (SUSTAINED_WINDOWS,))
    
    rows = cursor.fetchall()
    
    if len(rows) < SUSTAINED_WINDOWS:
        return False

    return all(score[0] >= ALERT_THRESHOLD for score in rows)



# ---------- API ----------
@app.post("/collect")
def collect_data(window: FeatureWindow):

    baseline = get_baseline()

    # -------- Rule-based score --------
    rule_score = (
        compute_fatigue_score(window.dict(), baseline)
        if baseline else 0.0
    )

    # -------- ML-based scores --------
    ae_score = ml_fatigue_score(window.dict()) if ae_model else 0.0
    lstm_score = lstm_fatigue_score(window.dict()) if lstm_model else 0.0

    ml_score = round((ae_score + lstm_score) / 2, 3)

    # -------- Score fusion --------
    final_score = round(
        0.4 * rule_score +
        0.2 * ae_score +
        0.4 * lstm_score,
        3
    )

    # 🚨 TEST ALERT LOGIC (ONLY THIS)
    alert = False

    

    if final_score >= ALERT_THRESHOLD:
        alert = True

    # -------- Store in DB --------
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO behavior_windows 
        (timestamp, data, fatigue_score, rule_score, ml_score)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            window.timestamp,
            json.dumps(window.dict()),
            final_score,
            rule_score,
            ml_score
        )
    )
    conn.commit()

    print(f"Final Score: {final_score}")
    print(f"🚨 ALERT SENT: {alert}")

    return {
        "status": "stored",
        "final_score": final_score,
        "rule_score": rule_score,
        "ml_score": ml_score,
        "alert": alert
    }

    





@app.get("/baseline")
def build_baseline(min_windows: int = 20):
    cursor.execute("SELECT data FROM behavior_windows")
    rows = cursor.fetchall()

    if len(rows) < min_windows:
        return {
            "status": "not_ready",
            "message": f"Need at least {min_windows} windows, currently have {len(rows)}"
        }

    # Parse JSON rows
    windows = [json.loads(row[0]) for row in rows]

    def stats(feature):
        values = [w[feature] for w in windows if w[feature] is not None]
        return {
            "mean": statistics.mean(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0.0
        }

    baseline = {
        "typing_speed": stats("typing_speed"),
        "typing_variance": stats("typing_variance"),
        "backspace_rate": stats("backspace_rate"),
        "backspace_burst_rate": stats("backspace_burst_rate"),
        "ctrl_z_rate": stats("ctrl_z_rate"),
        "mouse_speed": stats("mouse_speed"),
        "mouse_distance": stats("mouse_distance")
    }

    return {
        "status": "ready",
        "baseline": baseline
    }

@app.get("/dashboard-data")
def dashboard_data(limit: int = 50):
    cursor.execute("""
        SELECT timestamp, fatigue_score
        FROM behavior_windows
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()

    rows.reverse()  # oldest → newest

    return {
        "timestamps": [r[0] for r in rows],
        "fatigue_scores": [r[1] for r in rows]
    }

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Decision Fatigue Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f5f6fa;
                padding: 30px;
            }
            h2 {
                text-align: center;
            }
            .container {
                max-width: 900px;
                margin: auto;
                background: white;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>📊 Decision Fatigue Dashboard</h2>
            <canvas id="fatigueChart"></canvas>
        </div>

        <script>
            fetch("/dashboard-data")
              .then(res => res.json())
              .then(data => {
                  const ctx = document.getElementById("fatigueChart").getContext("2d");
                  new Chart(ctx, {
                      type: "line",
                      data: {
                          labels: data.timestamps,
                          datasets: [{
                              label: "Fatigue Score",
                              data: data.fatigue_scores,
                              fill: false,
                              borderColor: "rgb(75, 192, 192)",
                              tension: 0.3
                          }]
                      },
                      options: {
                          scales: {
                              y: {
                                  min: 0,
                                  max: 1
                              }
                          }
                      }
                  });
              });
        </script>
    </body>
    </html>
    """
