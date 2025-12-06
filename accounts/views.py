from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from .serializers import SignupSerializer, ProfileSerializer, OTPSendSerializer, OTPVerifySerializer
from .models import OTPCode, Profile, User
from .tasks import send_otp_sms
import random
from .tasks import send_hubtel_otp, verify_hubtel_otp
from django.core.cache import cache

class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({"user_id": user.id, "message": "User created. Send phone for OTP."}, status=201)
        return Response(serializer.errors, status=400)

class ProfileCreateView(APIView):
    def post(self, request):
        user_id = request.data.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            profile_data = request.data.copy()
            profile_data['user'] = user.id
            serializer = ProfileSerializer(data=profile_data)
            if serializer.is_valid():
                serializer.save()
                return Response({"message": "Profile completed! Sending OTP..."}, status=201)
            return Response(serializer.errors, status=400)
        except User.DoesNotExist:
            return Response({"error": "Invalid user"}, status=400)

class SendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone = request.data.get('phone_number')
        if not phone:
            return Response({"error": "Phone number required"}, status=400)

        result = send_hubtel_otp.delay(phone)
        cache.set(f"otp_session_{phone}", {"pending": True}, timeout=600)

        return Response({
            "message": "OTP sent successfully via Hubtel!",
            "tip": "If SMS delays, dial *713*90# to view code"
        })


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone = request.data.get('phone_number')
        prefix = request.data.get('prefix')
        code = request.data.get('code')
        request_id = request.data.get('request_id')

        if not all([phone, prefix, code, request_id]):
            return Response({"error": "Missing fields"}, status=400)

        result = verify_hubtel_otp.delay(request_id, prefix, code)

        try:
            profile = Profile.objects.get(momo_number=phone)
            profile.user.is_verified = True
            profile.user.save()
            return Response({"message": "Phone verified! Welcome to SnappX"})
        except Profile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=404)
