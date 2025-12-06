import base64
import requests
from celery import shared_task
from django.conf import settings

HUBTEL_OTP_URL = "https://api-otp.hubtel.com/otp"
AUTH_HEADER = f"Basic {settings.HUBTEL_OTP_AUTH}"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": AUTH_HEADER
}

@shared_task
def send_hubtel_otp(phone_number: str, country_code: str = "GH"):
    payload = {
        "senderId": settings.HUBTEL_SENDER_ID,
        "phoneNumber": phone_number,
        "countryCode": country_code
    }

    try:
        response = requests.post(f"{HUBTEL_OTP_URL}/send", json=payload, headers=HEADERS)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == "0000":
            request_id = data["data"]["requestId"]
            prefix = data["data"]["prefix"]
            print(f"OTP sent! RequestId: {request_id}, Prefix: {prefix}")
            return {"request_id": request_id, "prefix": prefix}
        else:
            print(f"Hubtel error: {data}")
            return {"error": data.get("message")}
    except Exception as e:
        print(f"Hubtel OTP failed: {e}")
        return {"error": str(e)}


@shared_task
def verify_hubtel_otp(request_id: str, prefix: str, code: str):
    payload = {
        "requestId": request_id,
        "prefix": prefix,
        "code": code
    }

    try:
        response = requests.post(f"{HUBTEL_OTP_URL}/verify", json=payload, headers=HEADERS)
        if response.status_code == 200:
            return {"success": True, "message": "OTP verified!"}
        else:
            return {"success": False, "error": "Invalid or expired OTP"}
    except Exception as e:
        return {"success": False, "error": str(e)}
