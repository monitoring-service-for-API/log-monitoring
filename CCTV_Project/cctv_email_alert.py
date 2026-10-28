import os
import smtplib
import ssl
import time
import threading

from pathlib import Path
from email.message import EmailMessage

BASE_DIR = Path.home() / "CCTV_Project"
MIN_EMAIL_INTERVAL = 60

_last_email_time = 0.0
_email_lock = threading.Lock()


def send_snapshot_email(snapshot_path):
    global _last_email_time

    snapshot_path = Path(snapshot_path).resolve()
    snapshot_dir = (BASE_DIR / "snapshots").resolve()

    # 지정된 사진 저장 폴더의 JPG만 허용
    if snapshot_path.parent != snapshot_dir:
        print("이메일 전송 거부: 허용되지 않은 사진 경로")
        return False

    if not snapshot_path.is_file() or snapshot_path.suffix.lower() != ".jpg":
        print("이메일 전송 실패: JPG 파일 없음")
        return False

    gmail_user = os.environ.get("CCTV_SMTP_USER")
    gmail_password = os.environ.get("CCTV_SMTP_PASSWORD")
    receiver = os.environ.get("CCTV_ALERT_RECEIVER")

    if not all([gmail_user, gmail_password, receiver]):
        print("이메일 환경변수가 설정되지 않았습니다.")
        return False

    with _email_lock:
        now = time.monotonic()

        if now - _last_email_time < MIN_EMAIL_INTERVAL:
            print("사진 이메일 발송 제한: 1분 대기 중")
            return False

        message = EmailMessage()
        message["From"] = gmail_user
        message["To"] = receiver
        message["Subject"] = "[CCTV 보안 경고] 미등록 얼굴 감지 사진"
        message.set_content(
            "CCTV에서 미등록 얼굴이 감지되었습니다.\n\n"
            f"캡처 파일: {snapshot_path.name}\n"
            "탐지 결과는 자동 얼굴 인식에 의한 것으로 "
            "보안 담당자의 확인이 필요합니다.\n\n"
            "Grafana 대시보드에서 탐지 로그를 확인해 주세요."
        )

        with snapshot_path.open("rb") as file:
            message.add_attachment(
                file.read(),
                maintype="image",
                subtype="jpeg",
                filename=snapshot_path.name
            )

        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(gmail_user, gmail_password)
                smtp.send_message(message)

            _last_email_time = time.monotonic()
            print(f"사진 첨부 이메일 발송 성공: {snapshot_path.name}")
            return True

        except (smtplib.SMTPException, OSError) as error:
            print(f"사진 첨부 이메일 발송 실패: {type(error).__name__}")
            return False
