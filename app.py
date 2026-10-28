#!/usr/bin/python3
from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify
import logging
from logging.handlers import RotatingFileHandler

# --- 모니터링용 추가 import (모두 표준 라이브러리라 별도 설치 불필요) ---
import json
import os
import re
import threading
import time
from collections import defaultdict, deque, Counter
from urllib.parse import unquote


from functools import wraps



# 2026.10.19
# limjaeseo
# written in python 3.12


app = Flask(__name__)
# 세션 쓰려면 반드시 있어야 함. 운영 시에는 환경변수로 넣자: export FLASK_SECRET_KEY='긴 랜덤 문자열'
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret-key")



# ============================================================
# 로그 설정
#   access.log   : werkzeug 접근 로그 (기존 그대로, fail2ban 401 필터용)
#   api.log      : API 요청 1건당 JSON 1줄 (분석/대시보드용)
#   security.log : 로그인 실패, 요청 제한, 404 스캔, 의심 입력 등 보안 이벤트
#   error.log    : 500 에러와 예외 스택
# ============================================================

LOG_DIR = os.environ.get("FLASK_LOG_DIR", "/var/log/flask")


def make_handler(filename, fmt=None):
    h = RotatingFileHandler(
        os.path.join(LOG_DIR, filename), maxBytes=1_000_000, backupCount=5, encoding='utf-8'
    )
    h.setLevel(logging.INFO)
    if fmt:
        h.setFormatter(logging.Formatter(fmt, datefmt='%Y-%m-%d %H:%M:%S'))
    return h


def make_logger(name, handler):
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.addHandler(handler)
    lg.propagate = False
    return lg


# 기존 access.log (werkzeug) - 형식을 바꾸지 않음
file_handler = make_handler('access.log')
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)
werkzeug_logger.addHandler(file_handler)

# 로그인 성공/실패는 시각이 붙는 security.log 로 이동
security_logger = make_logger('security', make_handler('security.log', '%(asctime)s %(message)s'))
login_logger = security_logger

# API 요청 로그 (JSON 한 줄)
api_logger = make_logger('api', make_handler('api.log', '%(message)s'))

# 500 에러 / 예외 스택
app.logger.addHandler(make_handler('error.log', '%(asctime)s %(levelname)s %(message)s'))



# ============================================================
# 모니터링 설정값
# ============================================================

# 이 경로로 시작하면 API 로 보고 모니터링한다. API 가 늘어나면 여기에 추가.
API_PREFIXES = ("/test/data", "/temp/data", "/api/")

RATE_LIMIT = 60        # IP 하나당
RATE_WINDOW = 60       # 이 시간(초) 동안 API 요청 허용 횟수
SLOW_MS = 1000         # 이보다 느린 API 응답은 security.log 에 SLOW 로 기록

# SQL 인젝션, XSS, 경로 탐색, 템플릿 인젝션에서 자주 보이는 패턴 (탐지용, 차단은 안 함)
SUSPICIOUS = re.compile(
    r"('|--|;|<script|javascript:|\.\./|\.\.\\|union\s+select|or\s+1=1|\{\{|\{%|/etc/passwd)",
    re.IGNORECASE,
)

START_TIME = time.time()
_lock = threading.Lock()
_hits = defaultdict(deque)                       # ip -> 최근 API 요청 시각들 (요청 제한용)
_stats = defaultdict(lambda: {"count": 0, "errors": 0, "total_ms": 0.0, "max_ms": 0.0,
                              "status": Counter()})
_ip_counter = Counter()                          # IP 별 API 요청 수 (재시작 시 초기화)


def is_api(path):
    return path.startswith(API_PREFIXES)


def clean(s, n=60):
    """로그에 넣을 문자열 정리. 줄바꿈/공백/= 등을 없애서 로그 위조(로그 인젝션)를 막는다."""
    return re.sub(r"[^\w./@-]", "_", s or "")[:n]


def check_rate_limit(ip):
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        q.append(now)
        count = len(q)
        # IP 가 너무 많이 쌓이면 오래된 기록 정리 (메모리 보호)
        if len(_hits) > 10_000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                del _hits[k]
    return count <= RATE_LIMIT


def find_suspicious():
    """경로, 쿼리스트링, 폼 값에서 의심 패턴이 있는 필드 이름을 반환 (값 자체는 기록하지 않음)"""
    fields = []
    if SUSPICIOUS.search(unquote(request.path)):
        fields.append("path")
    for key, value in request.args.items():
        if SUSPICIOUS.search(value):
            fields.append("arg." + clean(key, 20))
    for key, value in request.form.items():
        if key == "password":          # 비밀번호는 검사도 기록도 하지 않음
            continue
        if SUSPICIOUS.search(value):
            fields.append("form." + clean(key, 20))
    return fields



# ============================================================
# 모든 요청 앞뒤에서 실행되는 모니터링 훅
# ============================================================

@app.before_request
def monitor_before():
    g.start = time.perf_counter()
    ip = request.remote_addr

    bad = find_suspicious()
    if bad:
        security_logger.warning(
            "SUSPICIOUS ip=%s method=%s path=%s fields=%s",
            ip, request.method, clean(request.path), ",".join(bad),
        )

    if is_api(request.path) and not check_rate_limit(ip):
        return jsonify(error="too many requests"), 429


@app.after_request
def monitor_after(resp):
    path = request.path
    ip = request.remote_addr
    status = resp.status_code
    ms = round((time.perf_counter() - g.get("start", time.perf_counter())) * 1000, 1)

    if is_api(path):
        api_logger.info(json.dumps({
            "ts": time.strftime('%Y-%m-%d %H:%M:%S'),
            "ip": ip,
            "method": request.method,
            "path": path,
            "status": status,
            "ms": ms,
            "user": session.get("username"),
            "ua": request.headers.get("User-Agent", "")[:200],
            "bytes_in": request.content_length or 0,
        }, ensure_ascii=False))

        with _lock:
            st = _stats[path]
            st["count"] += 1
            st["total_ms"] += ms
            st["max_ms"] = max(st["max_ms"], ms)
            st["status"][status] += 1
            if status >= 400:
                st["errors"] += 1
            _ip_counter[ip] += 1

        if ms >= SLOW_MS:
            security_logger.warning("SLOW ip=%s path=%s ms=%s", ip, clean(path), ms)
        if status in (401, 403):
            security_logger.warning("API_AUTH_FAIL ip=%s path=%s status=%s", ip, clean(path), status)

    if status == 429:
        security_logger.warning("RATE_LIMIT ip=%s path=%s", ip, clean(path))
    elif status == 404:
        # 존재하지 않는 경로 접근: /.env, /wp-login.php 같은 스캐닝 탐지용
        security_logger.info("NOT_FOUND ip=%s path=%s", ip, clean(path))
    elif status >= 500:
        security_logger.error("SERVER_ERROR ip=%s path=%s status=%s", ip, clean(path), status)

    return resp


def admin_required(page=False):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = session.get("username")
            if user == "admin":
                return view(*args, **kwargs)
 
            event, status = ("UNAUTH", 401) if user is None else ("FORBIDDEN", 403)
            security_logger.warning(
                "%s ip=%s path=%s user=%s",
                event, request.remote_addr, clean(request.path), clean(user or "-"),
            )
            g.auth_logged = True   # after_request 에서 같은 내용을 한 번 더 남기지 않도록
 
            if page:
                return redirect(url_for("index"))
            return jsonify(error="admin only"), status
        return wrapper
    return decorator







USERS = {"admin": "1234"}   # 테스트용 계정 - 나중에 데이터베이스에 있는 내용으로 바꾸자. 기회가 된다면 admin 에 대한 권한도 별도로 부여해보고.
# USERS = {"green": "1234"}
# USERS = {"blue": "1234"}
# USERS = {"red": "1234"}


@app.route("/", methods=["GET", "POST"])
def index():

    '''
    if USERS.get(username) == password:
        login_logger.info(f'LOGIN SUCCESS user={username} ip={request.remote_addr}')
        session["username"] = username
        return redirect(url_for("home"))
    login_logger.warning(f'LOGIN FAIL user={username} ip={request.remote_addr}')
    '''

    

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("index.html", error="ID and PASSWORD are required"), 400

        # 변경: ip 를 앞에 두고 username 은 clean() 처리 (로그 인젝션 방지, fail2ban 필터 안정성)
        if USERS.get(username) == password:
            login_logger.info("LOGIN SUCCESS ip=%s user=%s", request.remote_addr, clean(username))
            session["username"] = username
            return redirect(url_for("home"))       

        login_logger.warning("LOGIN FAIL ip=%s user=%s", request.remote_addr, clean(username))
        return render_template("index.html", error="ID or PASSWORD is wrong"), 401

    return render_template("index.html")

    '''

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("index.html", error="ID and PASSWORD are required"), 400

        if USERS.get(username) == password:
            login_logger.info(f"LOGIN SUCCESS user={username} ip={request.remote_addr}")
            session["username"] = username
            return redirect(url_for("home"))         

        login_logger.warning(f"LOGIN FAIL user={username} ip={request.remote_addr}")
        return render_template("index.html", error="ID or PASSWORD is wrong"), 401

    return render_template("index.html")    
    '''

    '''
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if USERS.get(username) == password:
            session["username"] = username
            return redirect(url_for("home"))
        return render_template("index.html", error="ID or PASSWORD is wrong")
    return render_template("index.html")
    '''


@app.route("/home")
def home():
    if "username" not in session:
        return redirect(url_for("index"))
    return render_template("home.html", username=session["username"])


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("index"))


# 아래 코드를 지우면 /test 접속시 404
@app.route("/test")
@admin_required(page = True)            # admin 아닌 경우 못보게    @admin_required(page = True)  면 로그인 화면으로.
def test_page():
    return render_template("test.html")




# api
@app.route("/test/data")
@admin_required()            # admin 아닌 경우 못보게
def receive_test_data():
    return {"name":"Piggy-Chan", "weight": 104}


@app.route("/temp/data/a")
def datadata():
    return "<h1>이 페이지는 test내의 data 내부 중 하나를 나타냅니다</h1>"



@app.route("/test/error")
def test_error():
    1 / 0





# ---------------------------------------------------




@app.route("/monitor/stats")
@admin_required(page = True)            # admin 아닌 경우 못보게
def monitor_stats():
    if session.get("username") != "admin":
        security_logger.warning("FORBIDDEN ip=%s path=%s", request.remote_addr, clean(request.path))
        return jsonify(error="forbidden"), 403

    with _lock:
        endpoints = {
            path: {
                "count": st["count"],
                "errors": st["errors"],
                "error_rate": round(st["errors"] / st["count"] * 100, 1) if st["count"] else 0,
                "avg_ms": round(st["total_ms"] / st["count"], 1) if st["count"] else 0,
                "max_ms": st["max_ms"],
                "status": {str(k): v for k, v in st["status"].items()},
            }
            for path, st in _stats.items()
        }
        top_ips = _ip_counter.most_common(10)

    return jsonify(
        uptime_sec=int(time.time() - START_TIME),
        rate_limit=f"{RATE_LIMIT} req / {RATE_WINDOW}s per IP",
        endpoints=endpoints,
        top_ips=[{"ip": ip, "count": c} for ip, c in top_ips],
    )


if __name__ == '__main__':

    # login_logger.info("Test")

    app.run(host='0.0.0.0', port=8000)
