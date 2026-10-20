# 경보 CSV를 SQLite(db/cctv.db)에 쌓는다 -> Grafana가 이 파일을 읽음
import csv, sqlite3, sys
from datetime import datetime, timedelta
from pathlib import Path
csv_path, camera, start = sys.argv[1], sys.argv[2], sys.argv[3]
start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")  # 영상 속 0초가 실제로 몇 시인지
Path("db").mkdir(exist_ok=True)
con = sqlite3.connect("db/cctv.db")
con.execute("CREATE TABLE IF NOT EXISTS alerts (ts TEXT, camera TEXT, track_id INT, event TEXT)")
con.execute("DELETE FROM alerts WHERE camera = ?", (camera,))  # 같은 영상을 다시 넣어도 중복 안 되게
n = 0
with open(csv_path, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        ts = start_dt + timedelta(seconds=float(r["time_sec"]))
        con.execute("INSERT INTO alerts VALUES (?, ?, ?, ?)",
                    (ts.strftime("%Y-%m-%d %H:%M:%S"), camera, int(r["track_id"]), r["event"]))
        n += 1
con.commit()
total = con.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
print(f"{camera}: {n}건 저장, db/cctv.db 전체 {total}건")
