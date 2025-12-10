import requests
from django.conf import settings

# Dawurobo API constants
DAWUROBO_BASE = "https://devs.sms.api.dawurobo.com/v1/otp"

HEADERS = {
    "accept": "application/json",
    "x-api-key": settings.DAWUROBO_API_KEY,
    "x-access-token": settings.DAWUROBO_ACCESS_TOKEN,
    "Content-Type": "application/json"
}


def send_dawurobo_otp_sync(phone_number: str) -> dict:
    """
    Synchronous version used in local development.
    Works exactly like the old .delay() version but runs immediately.
    """
    payload = {
        "senderid": settings.DAWUROBO_SENDER_ID,
        "number": phone_number.replace("+", "").replace(" ", ""),
        "messagetemplate": "Your SnappX verification code is: %OTPCODE%. Expires in %EXPIRY% minutes.",
        "expiry": 10,
        "length": 6,
        "type": "NUMERIC"
    }

    try:
        response = requests.post(
            f"{DAWUROBO_BASE}/generate",
            json=payload,
            headers=HEADERS,
            timeout=30
        )

        if response.status_code in (200, 201, 409):
            print(f"OTP sent successfully to {phone_number}")
            return {"success": True, "status_code": response.status_code}

        response.raise_for_status()
        return {"success": True}

    except requests.exceptions.RequestException as e:
        print(f"DAWUROBO SEND ERROR → {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return {"success": False, "error": str(e)}


def verify_and_invalidate_otp_sync(phone_number: str, code: str) -> bool:
    """
    Secure synchronous verification + immediate invalidation.
    Used for signup verification and password reset.
    """
    clean_number = phone_number.replace("+", "").replace(" ", "")
    verify_payload = {"otpcode": code.upper(), "number": clean_number}

    try:
        verify_resp = requests.post(
            f"{DAWUROBO_BASE}/verify",
            json=verify_payload,
            headers=HEADERS,
            timeout=10
        )

        success = verify_resp.status_code == 200 and "success" in verify_resp.text.lower()

        if success:
            # Immediately invalidate to prevent reuse
            requests.post(
                f"{DAWUROBO_BASE}/invalidate",
                json={"number": clean_number},
                headers=HEADERS,
                timeout=10
            )
            print(f"OTP verified and invalidated for {phone_number}")
            return True
        else:
            print(f"Invalid OTP attempt: {verify_resp.text}")
            return False

    except Exception as e:
        print(f"OTP verify/invalidate failed: {e}")
        return False
