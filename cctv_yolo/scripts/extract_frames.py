import sys
from pathlib import Path
import cv2

def extract(video_path, out_dir, interval_sec):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[!] 열 수 없음: {video_path}")
        return 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(int(round(fps * interval_sec)), 1)
    saved, idx = 0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            cv2.imwrite(str(out_dir / f"{video_path.stem}_{idx:06d}.jpg"), frame)
            saved += 1
        idx += 1
    cap.release()
    return saved

def main():
    if len(sys.argv) != 4:
        print("사용법: python scripts/extract_frames.py <영상폴더> <저장폴더> <간격(초)>")
        sys.exit(1)
    video_dir, out_dir, interval = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    videos = sorted(video_dir.glob("*.mp4"))
    if not videos:
        print(f"[!] mp4 없음: {video_dir}")
        sys.exit(1)
    total = 0
    for v in videos:
        n = extract(v, out_dir, interval)
        print(f"{v.name}: {n}장 저장")
        total += n
    print(f"완료: 총 {total}장 -> {out_dir}/")

if __name__ == "__main__":
    main()
