# 학습한 모델로 영상을 분석해, 같은 사람이 숨기는 동작을 여러 프레임 연속으로 하면 도난 의심으로 기록한다.
import sys, csv
from collections import defaultdict
import cv2
from ultralytics import YOLO

weights, video = sys.argv[1], sys.argv[2]
SUSPECT_CLASS = "conceal_item"  # 의심 행동 라벨 이름
MIN_FRAMES = 8                  # 몇 프레임 연속이면 경보할지 (한두 프레임 오탐 거르기)
CONF = 0.5                      # 이 점수 미만 박스는 무시

model = YOLO(weights)
fps = cv2.VideoCapture(video).get(cv2.CAP_PROP_FPS) or 30
streak = defaultdict(int)   # 사람 번호별 연속 의심 프레임 수
alerted = set()             # 이미 경보한 사람 번호
rows, writer = [], None

# track(): 프레임마다 탐지하고, 같은 사람에게 같은 번호를 붙여 줌
for i, r in enumerate(model.track(video, persist=True, stream=True, conf=CONF, verbose=False)):
    seen = set()
    if r.boxes.id is not None:
        for tid, c in zip(r.boxes.id.int().tolist(), r.boxes.cls.int().tolist()):
            if model.names[c] == SUSPECT_CLASS:
                seen.add(tid)
    for tid in list(streak) + list(seen):
        streak[tid] = streak[tid] + 1 if tid in seen else 0
        if streak[tid] >= MIN_FRAMES and tid not in alerted:
            alerted.add(tid)
            rows.append({"time_sec": round(i / fps, 1), "frame": i, "track_id": tid, "event": "도난 의심(숨김 행동 지속)"})
            print(f"[경보] {i / fps:.1f}초, 사람 번호 {tid}")
    frame = r.plot()  # 박스가 그려진 화면
    if writer is None:
        h, w = frame.shape[:2]
        writer = cv2.VideoWriter("result.mp4", cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    writer.write(frame)

if writer:
    writer.release()
with open("alerts.csv", "w", newline="", encoding="utf-8-sig") as f:  # 엑셀에서 한글 안 깨지게
    w = csv.DictWriter(f, fieldnames=["time_sec", "frame", "track_id", "event"])
    w.writeheader()
    w.writerows(rows)
print(f"완료: 경보 {len(rows)}건 -> alerts.csv, 결과 영상 -> result.mp4")
