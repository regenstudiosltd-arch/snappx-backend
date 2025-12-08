from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.contrib.auth import get_user_model
from .models import Profile
from .tasks import send_dawurobo_otp, verify_dawurobo_otp
from .serializers import SendOTPSerializer, VerifyOTPSerializer, CustomTokenObtainPairSerializer, ForgotPasswordSerializer, ResetPasswordSerializer
import cloudinary.uploader
from celery.exceptions import OperationalError
import logging
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

logger = logging.getLogger(__name__)
User = get_user_model()

class CustomLoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenObtainPairSerializer

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        login_field = serializer.validated_data['login_field']

        try:
            if '@' in login_field:
                user = User.objects.get(email=login_field)
            else:
                user = User.objects.get(profile__momo_number=login_field)
        except User.DoesNotExist:
            return Response({"error": "User not found with this email or phone"}, status=status.HTTP_404_NOT_FOUND)

        momo_number = str(user.profile.momo_number)
        try:
            send_dawurobo_otp.delay(momo_number)
            return Response({
                "message": "OTP sent to your registered phone for password reset.",
                "phone": momo_number
            }, status=status.HTTP_200_OK)
        except OperationalError:
            return Response({"error": "Failed to send OTP. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['password']

        result = verify_dawurobo_otp.delay(phone, code).get(timeout=15)

        if result.get("success"):
            try:
                profile = Profile.objects.get(momo_number=phone)
                user = profile.user
                user.set_password(new_password)
                user.save()
                return Response({"message": "Password reset successful. You can now log in."}, status=status.HTTP_200_OK)
            except Profile.DoesNotExist:
                return Response({"error": "User not found with this phone"}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)

class FullSignupView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        data = request.data
        email = data.get('email')
        password = data.get('password')
        password2 = data.get('password2')
        full_name = data.get('full_name')
        date_of_birth = data.get('date_of_birth')
        user_type = data.get('user_type')
        phone_number = data.get('phone_number')
        ghana_post_address = data.get('ghana_post_address')
        momo_provider = data.get('momo_provider')
        momo_number = data.get('momo_number')
        momo_name = data.get('momo_name')
        profile_picture = request.FILES.get('profile_picture')
        if not all([email, password, password2, full_name, date_of_birth, user_type,
                    phone_number, ghana_post_address, momo_provider, momo_number, momo_name]):
            return Response({"error": "All fields are required except profile picture"}, status=400)
        if password != password2:
            return Response({"error": "Passwords do not match"}, status=400)
        if User.objects.filter(email=email).exists():
            return Response({"error": "Email already registered"}, status=400)
        if Profile.objects.filter(momo_number=momo_number).exists():
            return Response({"error": "This MoMo number is already registered"}, status=400)
        picture_url = None
        if profile_picture:
            try:
                upload_result = cloudinary.uploader.upload(profile_picture)
                picture_url = upload_result.get('secure_url')
            except Exception as e:
                return Response({"error": "Failed to upload photo"}, status=400)
        user = User.objects.create_user(
            email=email,
            password=password,
            username=email.split('@')[0],
            is_verified=False
        )
        Profile.objects.create(
            user=user,
            full_name=full_name,
            date_of_birth=date_of_birth,
            user_type=user_type,
            ghana_post_address=ghana_post_address,
            profile_picture=picture_url,
            momo_provider=momo_provider,
            momo_number=momo_number,
            momo_name=momo_name
        )
        max_retries = 5
        for attempt in range(max_retries):
            try:
                send_dawurobo_otp.delay(momo_number)
                break
            except OperationalError as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to send OTP after {max_retries} attempts: {str(e)}")
                    return Response({"error": "Failed to send OTP. Please try again later."}, status=500)
        return Response({
            "message": "Account created successfully! OTP sent to your phone.",
            "phone": momo_number,
            "next_step": "verify_otp"
        }, status=201)
class SendOTPView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        if serializer.is_valid():
            send_dawurobo_otp.delay(serializer.validated_data['phone_number'])
            return Response({"message": "OTP sent again!"}, status=200)
        return Response(serializer.errors, status=400)
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        phone = serializer.validated_data['phone_number']
        code = serializer.validated_data['code']
        result = verify_dawurobo_otp.delay(phone, code).get(timeout=15)
        if result.get("success"):
            try:
                profile = Profile.objects.get(momo_number=phone)
                profile.user.is_verified = True
                profile.user.save()
                return Response({
                    "success": True,
                    "message": "Welcome to SnappX! Your account is verified."
                }, status=200)
            except Profile.DoesNotExist:
                return Response({"error": "Account not found"}, status=404)
        else:
            return Response({"error": "Invalid or expired OTP"}, status=400)
