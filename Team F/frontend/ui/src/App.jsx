import { useEffect, useState } from "react";

function App() {
  const [muscleData, setMuscleData] = useState({
    taker_L: 0,
    taker_R: 0,
    goalie_L: 0,
    goalie_R: 0,
  });
  const [peakTaker, setPeakTaker] = useState({ L: 0, R: 0 });
  const [peakGoalie, setPeakGoalie] = useState({ L: 0, R: 0 });
  const [gameState, setGameState] = useState("IDLE");
  const [timeLeft, setTimeLeft] = useState(0);
  const [takerAction, setTakerAction] = useState("Center");
  const [goalieAction, setGoalieAction] = useState("Center");

  const ACTIVE_THRESHOLD = 300;
  const OVERSHOOT_THRESHOLD = 800;

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8080");
    ws.onmessage = (event) => setMuscleData(JSON.parse(event.data));
    return () => ws.close();
  }, []);

  useEffect(() => {
    if (gameState === "TAKER_TURN") {
      setPeakTaker((prev) => ({
        L: Math.max(prev.L, muscleData.taker_L),
        R: Math.max(prev.R, muscleData.taker_R),
      }));
    } else if (gameState === "GOALIE_TURN") {
      setPeakGoalie((prev) => ({
        L: Math.max(prev.L, muscleData.goalie_L),
        R: Math.max(prev.R, muscleData.goalie_R),
      }));
    }
  }, [muscleData, gameState]);

  useEffect(() => {
    if (timeLeft > 0) {
      const timer = setTimeout(() => setTimeLeft(timeLeft - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [timeLeft, gameState]);

  useEffect(() => {
    if (timeLeft === 0) {
      if (gameState === "TAKER_TURN") {
        // Evaluate Attacker
        let finalAction = "Center";
        if (peakTaker.L > ACTIVE_THRESHOLD || peakTaker.R > ACTIVE_THRESHOLD) {
          if (peakTaker.L > peakTaker.R) {
            finalAction =
              peakTaker.L > OVERSHOOT_THRESHOLD ? "OutLeft" : "Left";
          } else {
            finalAction =
              peakTaker.R > OVERSHOOT_THRESHOLD ? "OutRight" : "Right";
          }
        }
        setTakerAction(finalAction);

        // Transition to Goalie - ⚠️ GIVING THE GOALIE 3 SECONDS
        setGameState("GOALIE_TURN");
        setTimeLeft(3);
        setPeakGoalie({ L: 0, R: 0 });
      } else if (gameState === "GOALIE_TURN") {
        // Evaluate Defender (No overshoot penalty for Goalie)
        let finalAction = "Center";
        if (
          peakGoalie.L > ACTIVE_THRESHOLD ||
          peakGoalie.R > ACTIVE_THRESHOLD
        ) {
          finalAction = peakGoalie.L > peakGoalie.R ? "Left" : "Right";
        }
        setGoalieAction(finalAction);
        setGameState("RESULT");
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeLeft]);

  const startGame = () => {
    setGameState("TAKER_TURN");
    setTimeLeft(5);
    setTakerAction("Center");
    setGoalieAction("Center");
    setPeakTaker({ L: 0, R: 0 });
    setPeakGoalie({ L: 0, R: 0 });
  };

  const getPositionOffset = (action) => {
    if (action === "Left") return "-100px";
    if (action === "Right") return "100px";
    if (action === "OutLeft") return "-220px";
    if (action === "OutRight") return "220px";
    return "0px";
  };

  let resultText = "GOAL!";
  let resultColor = "#10b981";

  if (gameState === "RESULT") {
    if (takerAction === "OutLeft" || takerAction === "OutRight") {
      resultText = "MISSED WIDE!";
      resultColor = "#f59e0b";
    } else if (takerAction === goalieAction) {
      resultText = "SAVE!";
      resultColor = "#ef4444";
    }
  }

  return (
    <>
      <style>{`
        body { margin: 0; background-color: #0f172a; }
        .app-container { background: radial-gradient(circle at 50% 0%, #1e293b, #0f172a); min-height: 100vh; font-family: 'Inter', system-ui, sans-serif; display: flex; flex-direction: column; alignItems: center; color: #f8fafc; overflow: hidden; padding-top: 40px; }
        .glass-panel { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 20px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); display: flex; flex-direction: column; align-items: center; padding: 30px; margin: 0 auto; max-width: 800px; }
        .title { margin: 0px 0 20px 0; font-size: 35px; font-weight: 800; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; color: transparent; letter-spacing: -1px; }
        .status-badge { background: rgba(0,0,0,0.3); padding: 12px 24px; border-radius: 30px; font-size: 1.2rem; font-weight: 600; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }
        .btn-play { background: linear-gradient(135deg, #0ea5e9, #3b82f6); border: none; padding: 16px 48px; border-radius: 30px; color: white; font-size: 1.1rem; font-weight: 700; letter-spacing: 1px; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 10px 20px -10px rgba(59, 130, 246, 0.5); }
        .btn-play:hover { transform: translateY(-2px); box-shadow: 0 15px 25px -10px rgba(59, 130, 246, 0.8); }
        .pitch { width: 600px; height: 350px; background: repeating-linear-gradient(0deg, #166534, #166534 40px, #15803d 40px, #15803d 80px); position: relative; border-radius: 12px; border: 3px solid rgba(255,255,255,0.8); box-shadow: inset 0 0 60px rgba(0,0,0,0.6), 0 20px 40px rgba(0,0,0,0.4); overflow: hidden; margin-bottom: 30px;}
        .penalty-box { position: absolute; top: 0; left: 100px; width: 400px; height: 140px; border: 3px solid rgba(255,255,255,0.6); border-top: none; }
        .goal-arc { position: absolute; top: 140px; left: 225px; width: 150px; height: 75px; border: 3px solid rgba(255,255,255,0.6); border-top: none; border-radius: 0 0 75px 75px; }
        .goal-net { position: absolute; top: 0; left: 180px; width: 240px; height: 30px; border: 4px solid #cbd5e1; border-top: none; background: repeating-linear-gradient(45deg, transparent, transparent 5px, rgba(255,255,255,0.3) 5px, rgba(255,255,255,0.3) 10px); border-radius: 0 0 8px 8px; z-index: 5; }
        .hud-debugger { background: #020617; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; font-family: 'Fira Code', 'Courier New', monospace; width: 100%; box-sizing: border-box; box-shadow: inset 0 0 20px rgba(0,0,0,0.8); }
        .hud-header { border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 15px; color: #64748b; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 2px; display: flex; justify-content: space-between;}
        .hud-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .data-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 0.95rem; }
        .val-live { color: #38bdf8; font-weight: bold; }
        .val-peak { color: #facc15; font-weight: bold; }
      `}</style>

      <div className="app-container">
        <div className="glass-panel">
          <h1 className="title">EMG BASED PENALTY SHOOTOUT</h1>

          <div
            style={{ height: "70px", display: "flex", alignItems: "center" }}
          >
            {gameState === "IDLE" || gameState === "RESULT" ? (
              <button className="btn-play" onClick={startGame}>
                {gameState === "IDLE" ? "INITIALIZE MATCH" : "PLAY AGAIN"}
              </button>
            ) : (
              <div className="status-badge">
                <span
                  style={{
                    color: gameState === "TAKER_TURN" ? "#38bdf8" : "#10b981",
                  }}
                >
                  {gameState === "TAKER_TURN"
                    ? "● TAKER RECORDING"
                    : "● GOALIE RECORDING"}
                </span>
                <span
                  style={{
                    color: "#f8fafc",
                    background: "#334155",
                    padding: "4px 12px",
                    borderRadius: "20px",
                  }}
                >
                  00:0{timeLeft}
                </span>
              </div>
            )}
          </div>

          <div className="pitch">
            <div className="penalty-box"></div>
            <div className="goal-arc"></div>
            <div className="goal-net"></div>

            <div
              style={{
                width: "50px",
                height: "50px",
                backgroundColor: "#10b981",
                position: "absolute",
                top: "40px",
                left: "275px",
                borderRadius: "50%",
                boxShadow:
                  "0 0 20px rgba(16, 185, 129, 0.6), inset 0 -5px 10px rgba(0,0,0,0.3)",
                transition: "transform 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)",
                zIndex: 10,
                transform: `translateX(${gameState === "RESULT" ? (goalieAction === "Left" ? "-100px" : goalieAction === "Right" ? "100px" : "0px") : "0px"})`,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  width: "15px",
                  height: "15px",
                  background: "#fff",
                  borderRadius: "50%",
                  top: "15px",
                  left: "-10px",
                }}
              ></div>
              <div
                style={{
                  position: "absolute",
                  width: "15px",
                  height: "15px",
                  background: "#fff",
                  borderRadius: "50%",
                  top: "15px",
                  right: "-10px",
                }}
              ></div>
            </div>

            <div
              style={{
                width: "30px",
                height: "30px",
                background:
                  "radial-gradient(circle at 30% 30%, #ffffff, #cbd5e1, #475569)",
                position: "absolute",
                bottom: "40px",
                left: "285px",
                borderRadius: "50%",
                boxShadow: "2px 5px 10px rgba(0,0,0,0.5)",
                transition: "transform 0.5s cubic-bezier(0.25, 1, 0.5, 1)",
                zIndex: 15,
                transform: `translate(${gameState === "RESULT" ? getPositionOffset(takerAction) : "0px"}, ${gameState === "RESULT" ? "-250px" : "0px"}) scale(${gameState === "RESULT" ? 0.7 : 1})`,
              }}
            ></div>

            {gameState === "RESULT" && (
              <div
                style={{
                  position: "absolute",
                  top: "130px",
                  width: "100%",
                  textAlign: "center",
                  fontSize: "3.5rem",
                  fontWeight: "900",
                  color: resultColor,
                  textShadow: "0 10px 30px rgba(0,0,0,0.8), 0 2px 4px #000",
                  letterSpacing: "2px",
                  zIndex: 20,
                }}
              >
                {resultText}
              </div>
            )}
          </div>

          <div className="hud-debugger">
            <div className="hud-header">
              <span>BCI Telemetry System</span>
              <span style={{ color: "#0ea5e9" }}>
                ACTIVE_THR: {ACTIVE_THRESHOLD} | LIMIT: {OVERSHOOT_THRESHOLD}
              </span>
            </div>

            <div className="hud-grid">
              <div>
                <div
                  style={{
                    color: "#64748b",
                    marginBottom: "8px",
                    fontSize: "0.8rem",
                  }}
                >
                  ATTACKER [L/R]
                </div>
                <div className="data-row">
                  <span>LIVE SIGNAL:</span>
                  <span className="val-live">
                    L:{muscleData.taker_L.toString().padStart(4, "0")} R:
                    {muscleData.taker_R.toString().padStart(4, "0")}
                  </span>
                </div>
                <div className="data-row">
                  <span>PEAK LOCK:</span>
                  <span className="val-peak">
                    L:{peakTaker.L.toString().padStart(4, "0")} R:
                    {peakTaker.R.toString().padStart(4, "0")}
                  </span>
                </div>
                <div
                  className="data-row"
                  style={{
                    marginTop: "12px",
                    borderTop: "1px dashed #334155",
                    paddingTop: "8px",
                  }}
                >
                  <span>CALC VECTOR:</span>
                  <span style={{ color: "#fff" }}>
                    [{takerAction.toUpperCase()}]
                  </span>
                </div>
              </div>

              <div
                style={{ borderLeft: "1px solid #1e293b", paddingLeft: "20px" }}
              >
                <div
                  style={{
                    color: "#64748b",
                    marginBottom: "8px",
                    fontSize: "0.8rem",
                  }}
                >
                  DEFENDER [L/R]
                </div>
                <div className="data-row">
                  <span>LIVE SIGNAL:</span>
                  <span className="val-live" style={{ color: "#10b981" }}>
                    L:{muscleData.goalie_L.toString().padStart(4, "0")} R:
                    {muscleData.goalie_R.toString().padStart(4, "0")}
                  </span>
                </div>
                <div className="data-row">
                  <span>PEAK LOCK:</span>
                  <span className="val-peak">
                    L:{peakGoalie.L.toString().padStart(4, "0")} R:
                    {peakGoalie.R.toString().padStart(4, "0")}
                  </span>
                </div>
                <div
                  className="data-row"
                  style={{
                    marginTop: "12px",
                    borderTop: "1px dashed #334155",
                    paddingTop: "8px",
                  }}
                >
                  <span>CALC VECTOR:</span>
                  <span style={{ color: "#fff" }}>
                    [{goalieAction.toUpperCase()}]
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

export default App;
