console.log("✅ Decision Fatigue extension loaded");

// ---------- Storage Helpers ----------

const STORAGE_KEY = "decision_fatigue_feature_windows";

let lastAlertShown = 0;
const ALERT_COOLDOWN = 10 * 60 * 1000; // 10 minutes


function saveFeatureWindow(featureWindow) {
  const existing =
    JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];

  existing.push(featureWindow);

  localStorage.setItem(STORAGE_KEY, JSON.stringify(existing));
}

function getStoredWindows() {
  return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
}

// ---- Mouse Metrics ----
let mouseMoves = 0;
let mousePositions = [];

document.addEventListener("mousemove", (e) => {
  mouseMoves++;
  mousePositions.push({ x: e.clientX, y: e.clientY, t: Date.now() });
});


// ---- Decision Regret Metrics ----
let ctrlZCount = 0;
let backspaceBurstCount = 0;
let lastBackspaceTime = 0;



// =====================
// Decision Fatigue Tracker
// =====================

// ---- Typing Metrics ----
let keystrokes = 0;
let backspaces = 0;
let typingTimestamps = [];

// Capture keyboard behavior
document.addEventListener("keydown", (e) => {
  if (e.key.length === 1) {
    keystrokes++;
    typingTimestamps.push(Date.now());
  }

  if (e.key === "Backspace") {
  backspaces++;

  const now = Date.now();
  if (now - lastBackspaceTime < 400) {
    backspaceBurstCount++;
  }
  lastBackspaceTime = now;
  } 

  if (e.ctrlKey && e.key === "z") {
    ctrlZCount++;
  }


});

function calculateTypingStats() {
  if (typingTimestamps.length < 2) {
    return {
      typing_speed: 0,
      typing_variance: 0
    };
  }

  const intervals = [];
  for (let i = 1; i < typingTimestamps.length; i++) {
    intervals.push(
      (typingTimestamps[i] - typingTimestamps[i - 1]) / 1000
    );
  }

  const avgInterval =
    intervals.reduce((a, b) => a + b, 0) / intervals.length;

  const variance =
    intervals.reduce((a, b) => a + Math.pow(b - avgInterval, 2), 0) /
    intervals.length;

  return {
    typing_speed: 1 / avgInterval,
    typing_variance: variance
  };
}

function calculateMouseStats() {
  if (mousePositions.length < 2) {
    return {
      mouse_speed: 0,
      mouse_distance: 0
    };
  }

  let totalDist = 0;
  for (let i = 1; i < mousePositions.length; i++) {
    const dx = mousePositions[i].x - mousePositions[i - 1].x;
    const dy = mousePositions[i].y - mousePositions[i - 1].y;
    totalDist += Math.sqrt(dx*dx + dy*dy);
  }

  return {
    mouse_speed: totalDist / ((Date.now() - windowStart) / 1000),
    mouse_distance: totalDist
  };
}

function calculateRegretStats() {
  return {
    ctrl_z_rate: ctrlZCount,
    backspace_burst_rate: backspaceBurstCount
  };
}



let windowStart = Date.now();


function showFatigueAlert() {
  if (document.getElementById("fatigue-alert")) return;

  const alertBox = document.createElement("div");
  alertBox.id = "fatigue-alert";
  alertBox.innerText =
    "⚠️ You may be experiencing decision fatigue.\n" +
    "A short break could help 🧠";

  Object.assign(alertBox.style, {
    position: "fixed",
    bottom: "20px",
    right: "20px",
    background: "#111",
    color: "#fff",
    padding: "14px 18px",
    borderRadius: "10px",
    fontSize: "14px",
    zIndex: "999999",
    boxShadow: "0 4px 12px rgba(0,0,0,0.35)",
    whiteSpace: "pre-line"
  });

  document.body.appendChild(alertBox);

  setTimeout(() => alertBox.remove(), 8000);
}

window.__testFatigueAlert = showFatigueAlert;


setInterval(() => {
  const duration = (Date.now() - windowStart) / 1000;

  const typingStats = calculateTypingStats();
  const mouseStats = calculateMouseStats();

  const regretStats = calculateRegretStats();


  const features = {
    timestamp: new Date().toISOString(),
    typing_speed: typingStats.typing_speed,
    typing_variance: typingStats.typing_variance,
    backspace_rate: keystrokes > 0 ? backspaces / keystrokes : 0,
    mouse_speed: mouseStats.mouse_speed,
    mouse_distance: mouseStats.mouse_distance,
    window_duration: duration,
    ctrl_z_rate: regretStats.ctrl_z_rate,
    backspace_burst_rate: regretStats.backspace_burst_rate
    
  };

  console.log("📊 Feature Window:", features);
  saveFeatureWindow(features);

  console.log("🚀 Sending to backend...");

  fetch("http://127.0.0.1:8000/collect", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(features)
})
.then(res => res.json())
.then(data => {
  console.log("🧠 Final Fatigue Score:", data.final_score);

  if (data.alert && Date.now() - lastAlertShown > ALERT_COOLDOWN) {
  showFatigueAlert();
  lastAlertShown = Date.now();
  }  
});


  // reset
  keystrokes = 0;
  backspaces = 0;
  typingTimestamps = [];
  mouseMoves = 0;
  mousePositions = [];
  ctrlZCount = 0;
  backspaceBurstCount = 0;
  lastBackspaceTime = 0;

  windowStart = Date.now();
}, 60000);


// 🔧 Debug trigger via DOM event
document.addEventListener("df-test-alert", () => {
  showFatigueAlert();
  console.log("🧪 Test alert triggered");
});



