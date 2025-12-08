from celery import shared_task
import requests
from django.conf import settings

DAWUROBO_BASE = "https://devs.sms.api.dawurobo.com/v1/otp"

HEADERS = {
    "accept": "application/json",
    "x-api-key": settings.DAWUROBO_API_KEY,
    "x-access-token": settings.DAWUROBO_ACCESS_TOKEN,
    "Content-Type": "application/json"
}

@shared_task(bind=True, max_retries=1, default_retry_delay=10)
def send_dawurobo_otp(self, phone_number: str):
    payload = {
        "senderid": settings.DAWUROBO_SENDER_ID,
        "number": phone_number.replace("+", ""),
        "messagetemplate": "Your SnappX verification code is: %OTPCODE%. Expires in %EXPIRY% minutes.",
        "expiry": 10,
        "length": 6,
        "type": "NUMERIC"
    }
    try:
        response = requests.post(f"{DAWUROBO_BASE}/generate", json=payload, headers=HEADERS, timeout=45)

        if response.status_code == 409:
            print(f"OTP already active for {phone_number} — normal & expected")
            return {"success": True, "note": "OTP already sent recently"}

        response.raise_for_status()
        print(f"OTP successfully sent to {phone_number}")
        return {"success": True, "data": response.json()}

    except Exception as e:
        print(f"DAWUROBO ERROR → {e}")
        return {"success": False, "error": str(e)}


@shared_task
def verify_dawurobo_otp(phone_number: str, code: str):
    payload = {
        "otpcode": code.upper(),
        "number": phone_number.replace("+", "")
    }

    try:
        response = requests.post(f"{DAWUROBO_BASE}/verify", json=payload, headers=HEADERS)
        if response.status_code == 200 and "success" in response.text:
            print(f"OTP verified for {phone_number}")
            return {"success": True}
        else:
            print(f"Invalid OTP: {response.text}")
            return {"success": False, "error": "Invalid or expired OTP"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def verify_dawurobo_otp_sync(phone_number: str, code: str) -> bool:
    """
    Synchronous version of OTP verification.
    Used when Celery result backend is unreachable (network_mode: host).
    """
    payload = {
        "otpcode": code.upper(),
        "number": phone_number.replace("+", "")
    }

    try:
        response = requests.post(
            f"{DAWUROBO_BASE}/verify",
            json=payload,
            headers=HEADERS,
            timeout=10
        )
        if response.status_code == 200 and "success" in response.text.lower():
            print(f"[SYNC] OTP verified successfully for {phone_number}")
            return True
        else:
            print(f"[SYNC] Invalid OTP response: {response.text}")
            return False
    except Exception as e:
        print(f"[SYNC] DAWUROBO VERIFY ERROR → {e}")
        return False
