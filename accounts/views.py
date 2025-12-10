from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django_ratelimit.decorators import ratelimit
from .models import Profile
from .tasks import send_dawurobo_otp, verify_and_invalidate_otp_sync
from .serializers import (
    SendOTPSerializer, VerifyOTPSerializer, CustomTokenObtainPairSerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer, ProfileSerializer
)
import cloudinary.uploader
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class CustomLoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenObtainPairSerializer


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ratelimit(key='ip', rate='10/m', method='POST', block=True))
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        login_field = serializer.validated_data['login_field'].lower().strip()

        try:
            if '@' in login_field:
                user = User.objects.get(email=login_field)
            else:
                user = User.objects.get(profile__momo_number=login_field)
        except User.DoesNotExist:
            return Response({"error": "User not found with this email or phone"}, status=status.HTTP_404_NOT_FOUND)

        momo_number = str(user.profile.momo_number)
        send_dawurobo_otp.delay(momo_number)

        return Response({
            "message": "OTP sent to your registered phone for password reset.",
            "phone": momo_number
        }, status=status.HTTP_200_OK)


@method_decorator(never_cache, name='dispatch')
class FullSignupView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        data = request.data

        required_fields = [
            'email', 'password', 'password2', 'full_name', 'date_of_birth',
            'user_type', 'ghana_post_address', 'momo_provider', 'momo_number', 'momo_name'
        ]
        for field in required_fields:
            if not data.get(field):
                return Response({"error": f"{field.replace('_', ' ').title()} is required"}, status=400)

        if data['password'] != data['password2']:
            return Response({"error": "Passwords do not match"}, status=400)

        email = data['email'].lower().strip()
        momo_number = str(data['momo_number'])

        if User.objects.filter(email=email).exists():
            return Response({"error": "This email is already registered"}, status=400)
        if Profile.objects.filter(momo_number=momo_number).exists():
            return Response({"error": "This MoMo number is already registered"}, status=400)

        picture_url = None
        if request.FILES.get('profile_picture'):
            try:
                upload_result = cloudinary.uploader.upload(request.FILES['profile_picture'])
                picture_url = upload_result.get('secure_url')
            except Exception as e:
                logger.error(f"Cloudinary upload failed: {e}")
                return Response({"error": "Failed to upload photo. Try again."}, status=400)

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    username=email.split('@')[0],
                    password=data['password'],
                    is_verified=False
                )
                Profile.objects.create(
                    user=user,
                    full_name=data['full_name'],
                    date_of_birth=data['date_of_birth'],
                    user_type=data['user_type'],
                    ghana_post_address=data['ghana_post_address'],
                    profile_picture=picture_url,
                    momo_provider=data['momo_provider'],
                    momo_number=momo_number,
                    momo_name=data['momo_name']
                )
                send_dawurobo_otp.delay(momo_number)

        except IntegrityError:
            return Response({"error": "Email or MoMo number already in use"}, status=400)
        except Exception as e:
            logger.error(f"Signup error: {e}")
            return Response({"error": "Account creation failed. Please try again."}, status=500)

        return Response({
            "message": "Account created successfully! OTP sent to your phone.",
            "phone": momo_number,
            "next_step": "verify_otp"
        }, status=201)


@method_decorator([
    never_cache,
    ratelimit(key='ip', rate='5/m', method='POST', block=True)
], name='dispatch')
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['password']

        if not verify_and_invalidate_otp_sync(phone, code):
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            profile = Profile.objects.select_related('user').get(momo_number=phone)
            user = profile.user
            user.set_password(new_password)
            user.save(update_fields=['password'])

            logger.info(f"Password reset successful for {user.email} ({phone})")
            return Response({
                "message": "Password reset successful. You can now log in."
            }, status=status.HTTP_200_OK)

        except Profile.DoesNotExist:
            return Response({"error": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)


class SendOTPView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ratelimit(key='ip', rate='10/m', method='POST', block=True))
    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        phone = serializer.validated_data['phone_number']
        send_dawurobo_otp.delay(phone)
        return Response({"message": "OTP sent again!"}, status=200)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        phone = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']

        if verify_and_invalidate_otp_sync(phone, code):
            try:
                profile = Profile.objects.get(momo_number=phone)
                profile.user.is_verified = True
                profile.user.save(update_fields=['is_verified'])
                return Response({
                    "success": True,
                    "message": "Welcome to SnappX! Your account is verified."
                }, status=200)
            except Profile.DoesNotExist:
                return Response({"error": "Account not found"}, status=404)
        else:
            return Response({"error": "Invalid or expired OTP"}, status=400)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        profile = user.profile
        return Response({
            "user": {
                "id": user.id,
                "email": user.email,
                "is_verified": user.is_verified,
                "date_joined": user.date_joined.isoformat()
            },
            "profile": ProfileSerializer(profile).data
        })
