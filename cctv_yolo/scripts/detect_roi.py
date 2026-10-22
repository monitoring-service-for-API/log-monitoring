"""
기획서 방식의 CCTV 도난 의심 탐지

규칙: 운영시간 외 + 관심영역(ROI) 안에 사람이 + 정해진 초 이상 머무르면 "도난 의심" 이벤트
- 사람 탐지는 기본 yolo11n.pt(학습 필요 없음, person 클래스)를 그대로 사용
- 결과는 한 줄에 하나씩 JSON 로그(logs/cctv_events.log)로 저장 → Promtail → Loki → Grafana
- 영상 원본은 내보내지 않고, 이벤트 순간 스냅샷만 snapshots/ 에 저장

사용 예:
  python scripts/detect_roi.py videos/theft01.mp4 --start "2026-10-22 23:10:00"
  python scripts/detect_roi.py videos/theft01.mp4 --roi 0.3,0.3,0.7,0.9 --dwell 5 --show-roi
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import cv2
from ultralytics import YOLO

p = argparse.ArgumentParser()
p.add_argument("video")
p.add_argument("--model", default="yolo11n.pt")
p.add_argument("--camera", default="cam01")
p.add_argument("--zone", default="counter", help="ROI 이름 (예: counter=계산대)")
p.add_argument("--roi", default="0.3,0.3,0.7,0.9",
               help="관심영역 x1,y1,x2,y2 (화면 비율 0~1)")
p.add_argument("--open", default="09:00", help="운영 시작 시각")
p.add_argument("--close", default="22:00", help="운영 종료 시각")
p.add_argument("--start", default=None,
               help='영상 첫 장면의 실제 시각 "YYYY-MM-DD HH:MM:SS" (없으면 지금)')
p.add_argument("--dwell", type=float, default=5.0, help="이 초 이상 머물면 경보")
p.add_argument("--conf", type=float, default=0.4)
p.add_argument("--all-hours", action="store_true", help="운영시간 무시 (테스트용)")
p.add_argument("--show-roi", action="store_true", help="첫 장면에 ROI를 그려 roi_check.jpg로 저장하고 끝냄")
p.add_argument("--out", default="logs/cctv_events.log")
a = p.parse_args()

rx1, ry1, rx2, ry2 = [float(v) for v in a.roi.split(",")]
start = datetime.strptime(a.start, "%Y-%m-%d %H:%M:%S") if a.start else datetime.now()
t_open = datetime.strptime(a.open, "%H:%M").time()
t_close = datetime.strptime(a.close, "%H:%M").time()

cap = cv2.VideoCapture(a.video)
fps = cap.get(cv2.CAP_PROP_FPS) or 30
ok, first = cap.read()
cap.release()
if not ok:
    raise SystemExit(f"영상을 열 수 없어요: {a.video}")
H, W = first.shape[:2]
roi = (int(rx1 * W), int(ry1 * H), int(rx2 * W), int(ry2 * H))

if a.show_roi:
    cv2.rectangle(first, roi[:2], roi[2:], (0, 0, 255), 3)
    cv2.imwrite("roi_check.jpg", first)
    print("roi_check.jpg 저장. 빨간 네모가 감시할 곳(계산대 등)에 맞는지 보세요.")
    raise SystemExit

out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
snap_dir = Path("snapshots")
snap_dir.mkdir(exist_ok=True)


def after_hours(t):
    return not (t_open <= t.time() < t_close)


dwell = {}      # track_id -> ROI 안에 연속으로 있었던 초
alerted = set()
events = 0
model = YOLO(a.model)

with out.open("a", encoding="utf-8") as f:
    for i, r in enumerate(model.track(a.video, persist=True, stream=True,
                                      classes=[0], conf=a.conf, verbose=False)):
        now = start + timedelta(seconds=i / fps)
        seen = set()
        if r.boxes.id is not None:
            for (x1, y1, x2, y2), tid in zip(r.boxes.xyxy.tolist(), r.boxes.id.int().tolist()):
                fx, fy = (x1 + x2) / 2, y2          # 발 위치(박스 아래 가운데)
                if roi[0] <= fx <= roi[2] and roi[1] <= fy <= roi[3]:
                    seen.add(tid)
                    dwell[tid] = dwell.get(tid, 0) + 1 / fps
        for tid in list(dwell):
            if tid not in seen:
                dwell.pop(tid)                      # ROI를 벗어나면 다시 0부터

        for tid, sec in dwell.items():
            if sec >= a.dwell and tid not in alerted and (a.all_hours or after_hours(now)):
                alerted.add(tid)
                events += 1
                snap = snap_dir / f"{a.camera}_{now:%Y%m%d_%H%M%S}_id{tid}.jpg"
                img = r.plot()
                cv2.rectangle(img, roi[:2], roi[2:], (0, 0, 255), 3)
                cv2.imwrite(str(snap), img)
                ev = {
                    "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
                    "host": "cctv-node", "source": "cctv", "severity": "high",
                    "zone": a.zone, "camera": a.camera, "track_id": tid,
                    "event": "theft_suspect", "dwell_sec": round(sec, 1),
                    "snapshot": snap.name,
                }
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                print("[경보]", ev["ts"], f"사람 {tid}번", f"{sec:.1f}초 체류")

print(f"끝. 경보 {events}건 → {out}")
