import threading
from cctv_email_alert import send_snapshot_email
import cv2
import time
import threading
from pathlib import Path
from flask import Flask, Response
from ultralytics import YOLO
from access_events import write_access_event

BASE_DIR = Path.home() / "CCTV_Project"
CAMERA_URL = "http://172.24.128.1:5000/video"
LOG_INTERVAL = 10
MATCH_THRESHOLD = 65
SNAPSHOT_DIR = BASE_DIR / "snapshots"
SNAPSHOT_INTERVAL = 10

SNAPSHOT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

app = Flask(__name__)
latest_frame = None
frame_lock = threading.Lock()

yolo = YOLO(str(BASE_DIR / "yolo11n.pt"))

detector = cv2.FaceDetectorYN.create(
    str(BASE_DIR / "models" / "face_detection_yunet.onnx"),
    "",
    (320, 320),
    0.7,
    0.3,
    5000
)

recognizer = cv2.face.LBPHFaceRecognizer_create()
recognizer.read(
    str(BASE_DIR / "registered_faces" / "face_model.yml")
)


def process_camera():
    global latest_frame

    last_log_time = 0
    last_snapshot_time = 0

    while True:
        cap = cv2.VideoCapture(CAMERA_URL)

        if not cap.isOpened():
            print("CCTV 연결 실패. 3초 후 재시도")
            time.sleep(3)
            continue

        print("CCTV 영상 수신 시작")

        try:
            while True:
                ret, frame = cap.read()

                if not ret:
                    print("영상 수신 중단. 재연결 시도")
                    break

                height, width = frame.shape[:2]

                # YOLO 사람 감지
                results = yolo(frame, verbose=False)

                for result in results:
                    for box in result.boxes:
                        if int(box.cls[0]) != 0:
                            continue

                        x1, y1, x2, y2 = map(int, box.xyxy[0])

                        cv2.rectangle(
                            frame, (x1, y1), (x2, y2),
                            (0, 255, 0), 2
                        )

                        cv2.putText(
                            frame, "PERSON",
                            (x1, max(25, y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 255, 0), 2
                        )

                # YuNet 얼굴 감지
                detector.setInputSize((width, height))
                _, faces = detector.detect(frame)

                if faces is not None:
                    for face in faces:
                        x, y, w, h = map(int, face[:4])

                        x1 = max(0, x)
                        y1 = max(0, y)
                        x2 = min(width, x + w)
                        y2 = min(height, y + h)

                        if x2 <= x1 or y2 <= y1:
                            continue

                        gray = cv2.cvtColor(
                            frame[y1:y2, x1:x2],
                            cv2.COLOR_BGR2GRAY
                        )

                        face_image = cv2.resize(gray, (200, 200))
                        face_image = cv2.equalizeHist(face_image)

                        label, distance = recognizer.predict(face_image)

                        if distance <= MATCH_THRESHOLD:
                            status = "POSSIBLE_MATCH"
                            color = (0, 255, 0)
                        else:
                            status = "UNVERIFIED"
                            color = (0, 0, 255)

                        if status == "UNVERIFIED":
                            now_snapshot = time.monotonic()

                            if now_snapshot - last_snapshot_time >= SNAPSHOT_INTERVAL:
                                face_crop = frame[y1:y2, x1:x2].copy()

                                if face_crop.size > 0:
                                    filename = (
                                        "unverified_"
                                        + time.strftime("%Y%m%d_%H%M%S")
                                        + f"_{time.time_ns()}.jpg"
                                    )

                                    save_path = SNAPSHOT_DIR / filename

                                    saved = cv2.imwrite(
                                        str(save_path),
                                        face_crop,
                                        [cv2.IMWRITE_JPEG_QUALITY, 85]
                                    )

                                    if saved:
                                        save_path.chmod(0o600)
                                        last_snapshot_time = now_snapshot
                                        print(f"미등록 얼굴 사진 저장: {save_path}")
                                        threading.Thread(
                                            target=send_snapshot_email,
                                            args=(save_path,),
                                            daemon=True
                                        ).start()

                        cv2.rectangle(
                            frame, (x1, y1), (x2, y2),
                            color, 2
                        )

                        cv2.putText(
                            frame,
                            f"{status} | distance: {distance:.1f}",
                            (x1, max(25, y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, color, 2
                        )

                        now = time.monotonic()

                        if now - last_log_time >= LOG_INTERVAL:
                            if status == "POSSIBLE_MATCH":
                                write_access_event(
                                    "UNVERIFIED",
                                    "POSSIBLE_REGISTERED_FACE_MATCH",
                                    "LOW"
                                )
                            else:
                                write_access_event(
                                    "UNVERIFIED",
                                    "FACE_NOT_MATCHED_REVIEW_REQUIRED",
                                    "MEDIUM"
                                )

                            last_log_time = now
                            print(f"얼굴 비교 이벤트: {status}")

                # 분석 완료된 프레임을 JPEG로 변환
                success, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 75]
                )

                if success:
                    with frame_lock:
                        latest_frame = encoded.tobytes()

        finally:
            cap.release()

        time.sleep(2)


def generate_frames():
    while True:
        with frame_lock:
            frame = latest_frame

        if frame is None:
            time.sleep(0.1)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )

        time.sleep(0.1)


@app.route("/video")
def video():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/")
def index():
    return """
    <html>
      <body style="margin:0;background:#111;color:white">
        <h3>CCTV Security Monitoring</h3>
        <img src="/video" style="width:100%;height:auto">
      </body>
    </html>
    """



# Grafana 통계 기능
import json
import urllib.parse
import urllib.request
from flask import jsonify

LOKI_URL = "http://127.0.0.1:3100"

def loki_count(query):
    params = urllib.parse.urlencode({"query": query})
    url = LOKI_URL + "/loki/api/v1/query?" + params

    with urllib.request.urlopen(url, timeout=5) as response:
        data = json.load(response)

    if data.get("status") != "success":
        raise RuntimeError("Loki query failed")

    results = data.get("data", {}).get("result", [])
    return int(float(results[0]["value"][1])) if results else 0


@app.route("/stats")
def stats():
    try:
        total = loki_count(
            'sum(count_over_time({job="cctv_face"}[5m]))'
        )
        medium = loki_count(
            'sum(count_over_time({job="cctv_face"} | json | risk_level="MEDIUM" [5m]))'
        )
        low = loki_count(
            'sum(count_over_time({job="cctv_face"} | json | risk_level="LOW" [5m]))'
        )

        return jsonify({
            "total": total,
            "medium": medium,
            "low": low,
            "status": "ok"
        })
    except Exception as exc:
        app.logger.warning("Loki stats error: %s", exc)
        return jsonify({"status": "error", "message": "Stats unavailable"}), 503


@app.route("/dashboard")
def dashboard():
    return """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
  margin: 0;
  background: #14191f;
  color: #eee;
  font-family: Arial, sans-serif;
}
.container { padding: 18px; }
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
h2 { margin: 0 0 8px; font-size: 22px; }
.subtitle { color: #aaa; font-size: 13px; }
.live { color: #35d07f; font-weight: bold; }
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin: 20px 0;
}
.stat {
  background: #242c33;
  padding: 15px;
  border-radius: 9px;
}
.label { color: #aaa; font-size: 13px; }
.value { font-size: 30px; font-weight: bold; margin-top: 8px; }
.medium { color: #ff6969; }
.low { color: #35d07f; }
.video { width: 100%; display: block; border-radius: 8px; }
.note { color: #aaa; font-size: 12px; margin-top: 12px; }
@media(max-width: 500px) {
  .stats { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h2>CCTV Security Monitoring</h2>
      <div class="subtitle">CAM_01 · AI Security Monitoring</div>
    </div>
    <div class="live">● LIVE</div>
  </div>

  <div class="stats">
    <div class="stat">
      <div class="label">최근 5분 얼굴 비교 이벤트</div>
      <div class="value" id="total">-</div>
    </div>
    <div class="stat">
      <div class="label">확인 필요 이벤트 · MEDIUM</div>
      <div class="value medium" id="medium">-</div>
    </div>
    <div class="stat">
      <div class="label">낮은 위험도 · LOW</div>
      <div class="value low" id="low">-</div>
    </div>
  </div>

  <h3>CAM_01 · 실시간 AI 분석 영상</h3>
  <img class="video" src="video" alt="CCTV 분석 영상">
  <div class="note" id="status">통계 연결 중...</div>
</div>

<script>
async function updateStats() {
  try {
    const response = await fetch("stats", {cache: "no-store"});
    if (!response.ok) throw new Error("API error");

    const data = await response.json();
    if (data.status !== "ok") throw new Error("Stats error");

    document.getElementById("total").textContent = data.total;
    document.getElementById("medium").textContent = data.medium;
    document.getElementById("low").textContent = data.low;
    document.getElementById("status").textContent =
      "Loki 통계 정상 · 5초마다 자동 갱신";
  } catch (err) {
    document.getElementById("total").textContent = "-";
    document.getElementById("medium").textContent = "-";
    document.getElementById("low").textContent = "-";
    document.getElementById("status").textContent =
      "Loki 통계를 가져올 수 없습니다";
  }
}
updateStats();
setInterval(updateStats, 5000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    thread = threading.Thread(
        target=process_camera,
        daemon=True
    )
    thread.start()

    print("Grafana CCTV 분석 영상 서버 시작")
    print("주소: http://127.0.0.1:8765/video")

    app.run(
        host="0.0.0.0",
        port=8765,
        threaded=True,
        debug=False
    )
