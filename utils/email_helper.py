"""
EMAIL HELPER
--------------
Send password-reset OTP emails through Gmail SMTP.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")


def send_otp_email(to_email: str, otp: str):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = "Password Reset OTP - Incident Response Console"

    body = f"""Hi,

You requested to reset your password for Incident Response Console.

Your OTP is: {otp}

This code will expire in 10 minutes. If you did not request this, please ignore this email.

Regards,
Incident Response Console
"""
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)

    print(f"[EMAIL] OTP sent to {to_email}")
