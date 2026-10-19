#!/usr/bin/python3
from flask import Flask, render_template, request, redirect, url_for, session

# 2026.10.19
# limjaeseo
# written in python 3.12




app = Flask(__name__)
app.secret_key = "change-this-secret-key"  # 세션 쓰려면 반드시 있어야 함.


USERS = {"admin": "1234"}   # 테스트용 계정 - 나중에 데이터베이스에 있는 내용으로 바꾸자. 기회가 된다면 admin 에 대한 권한도 별도로 부여해보고.
# USERS = {"green": "1234"}
# USERS = {"blue": "1234"}
# USERS = {"red": "1234"}


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if USERS.get(username) == password:
            session["username"] = username
            return redirect(url_for("home"))
        return render_template("index.html", error="ID or PASSWORD is wrong")
    return render_template("index.html")


@app.route("/home")
def home():
    if "username" not in session:
        return redirect(url_for("index"))
    return render_template("home.html", username=session["username"])


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("index"))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)