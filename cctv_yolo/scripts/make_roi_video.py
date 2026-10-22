"""
Grafana '분석영상' 패널용 영상 만들기
사람 박스 + 관심영역(빨간 네모)을 그린 영상을 브라우저에서 재생되는 H.264로 저장한다.

사용 예:
  python scripts/make_roi_video.py videos/cctv01.mp4 --roi 0.5,0.5,1,1
결과: web/result_web.mp4  (Grafana 분석영상 패널이 이 파일을 재생)
"""
import argparse
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
from ultralytics import YOLO

p = argparse.ArgumentParser()
p.add_argument("video")
p.add_argument("--model", default="yolo11n.pt")
p.add_argument("--roi", default="0.3,0.3,0.7,0.9")
p.add_argument("--conf", type=float, default=0.4)
p.add_argument("--out", default="web/result_web.mp4")
a = p.parse_args()

cap = cv2.VideoCapture(a.video)
fps = cap.get(cv2.CAP_PROP_FPS) or 30
W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
cap.release()
rx1, ry1, rx2, ry2 = [float(v) for v in a.roi.split(",")]
roi = (int(rx1 * W), int(ry1 * H), int(rx2 * W), int(ry2 * H))

tmp = Path("web/_tmp.mp4")
tmp.parent.mkdir(exist_ok=True)
writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))

model = YOLO(a.model)
for r in model.track(a.video, persist=True, stream=True, classes=[0], conf=a.conf, verbose=False):
    img = r.plot()
    cv2.rectangle(img, roi[:2], roi[2:], (0, 0, 255), 3)
    cv2.putText(img, "ROI", (roi[0] + 8, roi[1] + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    writer.write(img)
writer.release()

subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(tmp),
                "-vcodec", "libx264", "-pix_fmt", "yuv420p", a.out], check=True)
tmp.unlink()
print(f"완료 → {a.out}")
