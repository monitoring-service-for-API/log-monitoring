# Grafana 연결 연습용 가짜 경보 파일 (실제 모델 결과가 아님)
import csv, random
random.seed(1)
rows = []
for _ in range(20):
    t = random.randint(0, 9 * 3600)  # 영상 시작 후 0~9시간 사이 아무 시각(초)
    rows.append({"time_sec": t, "frame": t * 30, "track_id": random.randint(1, 15),
                 "event": "도난 의심(숨김 행동 지속)"})
rows.sort(key=lambda r: r["time_sec"])
with open("fake_alerts.csv", "w", newline="", encoding="utf-8-sig") as f:  # alerts.csv와 같은 칸 구성
    w = csv.DictWriter(f, fieldnames=["time_sec", "frame", "track_id", "event"])
    w.writeheader()
    w.writerows(rows)
print(f"가짜 경보 {len(rows)}건 -> fake_alerts.csv")
