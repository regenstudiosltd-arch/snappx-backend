from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from rest_framework.parsers import MultiPartParser
from django.db import transaction, IntegrityError
from django_ratelimit.decorators import ratelimit
from .serializers import SavingsGroupSerializer
from django.contrib.auth import get_user_model
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework import status
from .models import SavingsGroup
from .models import Profile

from .serializers import (
    SavingsGroupCreateSerializer, SendOTPSerializer, VerifyOTPSerializer, CustomTokenObtainPairSerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer, ProfileSerializer
)
from .tasks import send_dawurobo_otp_sync, verify_and_invalidate_otp_sync

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
                user = User.objects.select_related('profile').get(email=login_field)
            else:
                user = User.objects.select_related('profile').get(profile__momo_number=login_field)
        except User.DoesNotExist:
            return Response({"error": "User not found with this email or phone"},
                            status=status.HTTP_404_NOT_FOUND)

        momo_number = str(user.profile.momo_number)
        result = send_dawurobo_otp_sync(momo_number)

        if result.get("success"):
            return Response({
                "message": "OTP sent to your registered phone for password reset.",
                "phone": momo_number
            }, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Failed to send OTP. Try again later."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        # Check required fields
        for field in required_fields:
            if not data.get(field):
                return Response(
                    {"error": f"{field.replace('_', ' ').title()} is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Password match
        if data['password'] != data['password2']:
            return Response({"error": "Passwords do not match"}, status=400)

        email = data['email'].lower().lower().strip()
        momo_number = str(data['momo_number']).strip()

        # Uniqueness checks
        if User.objects.filter(email=email).exists():
            return Response({"error": "This email is already registered"}, status=400)
        if Profile.objects.filter(momo_number=momo_number).exists():
            return Response({"error": "This MoMo number is already registered"}, status=400)

        # Handle profile picture
        profile_picture_url = None
        if 'profile_picture' in request.FILES:
            try:
                upload_result = cloudinary.uploader.upload(
                    request.FILES['profile_picture'],
                    folder="snappx/profiles/",
                    transformation=[
                        {'width': 500, 'height': 500, 'crop': 'limit'},
                        {'quality': "auto"}
                    ]
                )
                profile_picture_url = upload_result.get('secure_url')
                logger.info(f"Profile picture uploaded: {profile_picture_url}")
            except Exception as e:
                logger.warning(f"Cloudinary upload failed (continuing without photo): {e}")
        try:
            with transaction.atomic():
                # Create user
                user = User.objects.create_user(
                    email=email,
                    username=email.split('@')[0],
                    password=data['password'],
                    is_verified=False
                )

                # Create profile
                Profile.objects.create(
                    user=user,
                    full_name=data['full_name'],
                    date_of_birth=data['date_of_birth'],
                    user_type=data['user_type'],
                    ghana_post_address=data['ghana_post_address'],
                    profile_picture=profile_picture_url,
                    momo_provider=data['momo_provider'],
                    momo_number=momo_number,
                    momo_name=data['momo_name']
                )

                # Send OTP via Dawurobo
                result = send_dawurobo_otp_sync(momo_number)

                if not result.get("success"):
                    raise Exception("OTP sending failed")

        except IntegrityError:
            return Response({"error": "Email or phone already in use"}, status=400)
        except Exception as e:
            logger.error(f"Signup failed: {e}")
            return Response({"error": "Account creation failed. Please try again."}, status=500)

        return Response({
            "message": "Account created successfully! OTP sent to your phone.",
            "phone": momo_number,
            "next_step": "verify_otp"
        }, status=201)

@method_decorator([never_cache, ratelimit(key='ip', rate='5/m', method='POST', block=True)], name='dispatch')
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
            return Response({"message": "Password reset successful. You can now log in."})
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
        result = send_dawurobo_otp_sync(phone)

        if result.get("success"):
            return Response({"message": "OTP sent again!"}, status=200)
        else:
            return Response({"error": "Failed to send OTP"}, status=500)


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
        user = User.objects.select_related('profile').get(pk=request.user.pk)
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


class CreateSavingsGroupView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = SavingsGroupCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            group = serializer.save()
            return Response({
                "success": True,
                "message": "Savings group created successfully! Awaiting admin approval.",
                "group": {
                    "id": group.id,
                    "name": group.group_name,
                    "status": group.status,
                    "created_at": group.created_at
                }
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Group creation failed: {e}")
            return Response({
                "error": "Failed to create group. Please try again."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MyGroupsListView(generics.ListAPIView):
    """Groups where user is the admin"""
    serializer_class = SavingsGroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SavingsGroup.objects.filter(admin=self.request.user).select_related('admin__profile')

class GroupDetailView(generics.RetrieveAPIView):
    """Single group detail"""
    serializer_class = SavingsGroupSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        # user sees any group they are part of or created
        user = self.request.user
        return SavingsGroup.objects.filter(admin=user)
