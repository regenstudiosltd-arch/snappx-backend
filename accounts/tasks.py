import requests
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib.sites.models import Site
from django.urls import NoReverseMatch, reverse
from celery import shared_task

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


@shared_task
def send_group_join_request_email_async(request_id: int):
    """
    Celery task to send an email to the Group Admin notifying them
    of a new join request.
    """
    try:
        from .models import GroupJoinRequest

        join_request = GroupJoinRequest.objects.select_related(
            'group__admin', 'user__profile'
        ).get(pk=request_id)

    except GroupJoinRequest.DoesNotExist:
        print(f"ERROR: GroupJoinRequest with ID {request_id} not found.")
        return False

    group = join_request.group
    admin_user = group.admin
    requester_name = join_request.user.profile.full_name

    # Construct the Deep Link URL
    current_site = Site.objects.get_current()
    protocol = "http" if settings.DEBUG else "https"

    try:
        relative_url = reverse('group-requests-list', kwargs={'group_id': group.id})
    except NoReverseMatch:
        print("URL Reverse Match Error: Check URL configuration for 'group-requests-list'")
        return False

    full_review_url = f"{protocol}://{current_site.domain}{relative_url}"

    # Render Email Content
    context = {
        'admin_name': admin_user.profile.full_name,
        'group_name': group.group_name,
        'requester_name': requester_name,
        'review_url': full_review_url,
    }

    email_html_content = render_to_string('emails/new_join_request.html', context)
    email_text_content = f"A new user, {requester_name}, has requested to join your group: {group.group_name}. Review the request here: {full_review_url}"

    # Send Email
    try:
        send_mail(
            subject=f"🚀 New Join Request for '{group.group_name}'",
            message=email_text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[admin_user.email],
            html_message=email_html_content,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"EMAIL SEND ERROR for Group ID {group.id}: {e}")
        return False


@shared_task
def send_group_join_response_email_async(request_id: int, action: str):
    """
    Celery task to send an email to the applicant (user) notifying them
    that their join request has been approved or rejected by the admin.
    """
    try:
        from .models import GroupJoinRequest

        join_request = GroupJoinRequest.objects.select_related(
            'group__admin', 'user__profile'
        ).get(pk=request_id)

    except GroupJoinRequest.DoesNotExist:
        print(f"ERROR: GroupJoinRequest with ID {request_id} not found for response.")
        return False

    group = join_request.group
    applicant_user = join_request.user
    applicant_name = applicant_user.profile.full_name

    clean_group_name = group.group_name.strip('*').strip()

    # Construct the Deep Link URL
    current_site = Site.objects.get_current()
    protocol = "http" if settings.DEBUG else "https"

    try:
        relative_url = reverse('group-detail', kwargs={'id': group.id})
    except NoReverseMatch:
        print("URL Reverse Match Error: Check URL configuration for 'group-detail'")
        relative_url = reverse('group_list_all')

    full_group_url = f"{protocol}://{current_site.domain}{relative_url}"

    # Determine Subject and Template based on action
    if action == 'approved':
        subject = f"🎉 Welcome! You've Joined '{clean_group_name}'"
        template_name = 'emails/join_request_approved.html'
        message_prefix = "Congratulations! Your request to join"
    elif action == 'rejected':
        subject = f"😔 Update: Request to Join '{clean_group_name}'"
        template_name = 'emails/join_request_rejected.html'
        message_prefix = "Unfortunately, your request to join"
    else:
        print(f"ERROR: Invalid action '{action}' passed to email task.")
        return False

    # Render Email Content
    context = {
        'applicant_name': applicant_name,
        'group_name': group.group_name,
        'group_url': full_group_url,
        'action': action,
        'admin_name': group.admin.profile.full_name,
    }

    email_html_content = render_to_string(template_name, context)
    email_text_content = (
    f"Update for group '{clean_group_name}': Your request was {action}. "
    f"Log in to view details: {full_group_url}"
)

    # Send Email
    try:
        send_mail(
            subject=subject,
            message=email_text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[applicant_user.email],
            html_message=email_html_content,
            fail_silently=False,
        )
        print(f"Group join response '{action}' email sent to {applicant_user.email}")
        return True
    except Exception as e:
        print(f"EMAIL SEND ERROR for Request ID {request_id}: {e}")
        return False
