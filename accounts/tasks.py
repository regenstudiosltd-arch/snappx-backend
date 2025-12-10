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

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
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
            print(f"OTP already active for {phone_number} — expected")
            return {"success": True, "note": "Already active"}
        response.raise_for_status()
        print(f"OTP sent successfully to {phone_number}")
        return {"success": True}
    except Exception as e:
        print(f"DAWUROBO SEND ERROR → {e}")
        raise self.retry(exc=e)


@shared_task
def verify_dawurobo_otp(phone_number: str, code: str):
    payload = {"otpcode": code.upper(), "number": phone_number.replace("+", "")}
    try:
        response = requests.post(f"{DAWUROBO_BASE}/verify", json=payload, headers=HEADERS, timeout=10)
        return response.status_code == 200 and "success" in response.text.lower()
    except Exception:
        return False


def verify_and_invalidate_otp_sync(phone_number: str, code: str) -> bool:
    """
    Secure synchronous OTP verification + immediate invalidation.
    Used for account verification and password reset.
    """
    payload = {"otpcode": code.upper(), "number": phone_number.replace("+", "")}

    try:
        verify_response = requests.post(f"{DAWUROBO_BASE}/verify", json=payload, headers=HEADERS, timeout=10)
        if verify_response.status_code == 200 and "success" in verify_response.text.lower():
            # Immediately invalidate to prevent reuse
            requests.post(
                f"{DAWUROBO_BASE}/invalidate",
                json={"number": phone_number.replace("+", "")},
                headers=HEADERS,
                timeout=10
            )
            print(f"[SECURE] OTP verified and invalidated: {phone_number}")
            return True
        else:
            print(f"[SECURE] Invalid OTP: {verify_response.text}")
            return False
    except Exception as e:
        print(f"[SECURE] OTP verify/invalidate failed: {e}")
        return False
