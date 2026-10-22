"""
detect_roi.py가 만든 JSON 로그(logs/cctv_events.log)를 Grafana용 db/cctv.db 의 alerts 표에 넣는다.
가짜 데이터(fake-cam01)는 지우고, 같은 카메라의 이전 기록도 지운 뒤 새로 넣는다.

사용 예:
  python scripts/events_to_sqlite.py logs/cctv_events.log
"""
import json
import sqlite3
import sys
from pathlib import Path

log = Path(sys.argv[1] if len(sys.argv) > 1 else "logs/cctv_events.log")
rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]

Path("db").mkdir(exist_ok=True)
con = sqlite3.connect("db/cctv.db")
con.execute("CREATE TABLE IF NOT EXISTS alerts (ts TEXT, camera TEXT, track_id INT, event TEXT)")
con.execute("DELETE FROM alerts WHERE camera = 'fake-cam01'")
for cam in {r["camera"] for r in rows}:
    con.execute("DELETE FROM alerts WHERE camera = ?", (cam,))
con.executemany(
    "INSERT INTO alerts VALUES (?, ?, ?, ?)",
    [(r["ts"].replace("T", " "), r["camera"], r["track_id"],
      f"도난 의심: {r['zone']} {r['dwell_sec']}초 체류") for r in rows],
)
con.commit()
print(f"{len(rows)}건 넣음 → db/cctv.db (가짜 데이터 삭제)")
