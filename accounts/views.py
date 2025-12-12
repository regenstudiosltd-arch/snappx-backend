from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from .models import SavingsGroup, Profile, GroupJoinRequest, GroupMembership
from .tasks import send_dawurobo_otp_sync, verify_and_invalidate_otp_sync, send_group_join_request_email_async, send_group_join_response_email_async
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers as rest_serializers
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from rest_framework.parsers import MultiPartParser
from django.db import transaction, IntegrityError
from django_ratelimit.decorators import ratelimit
from rest_framework.filters import SearchFilter
from django.contrib.auth import get_user_model
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics, status
from .permissions import IsGroupAdmin
from django.utils import timezone

from .serializers import (
    SavingsGroupCreateSerializer, SavingsGroupSerializer, SendOTPSerializer, VerifyOTPSerializer,
    CustomTokenObtainPairSerializer, ForgotPasswordSerializer, ResetPasswordSerializer, ProfileSerializer,
    FullSignupSerializer, GroupJoinRequestSerializer, GroupJoinActionSerializer
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
    serializer_class = ForgotPasswordSerializer

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
@extend_schema(
    request=FullSignupSerializer,
    responses={
        201: {
            'type': 'object',
            'properties': {
                'message': {'type': 'string'},
                'phone': {'type': 'string'},
                'next_step': {'type': 'string'},
            }
        },
        400: {'description': 'Validation or uniqueness error'},
        500: {'description': 'Server or OTP sending error'},
    },
    description="Complete user and profile registration, including optional file upload. Triggers phone verification.",
    tags=['Authentication & Registration']
)
class FullSignupView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser]

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
    serializer_class = ResetPasswordSerializer

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
    serializer_class = SendOTPSerializer

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
    serializer_class = VerifyOTPSerializer

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


class MeViewResponseSerializer(rest_serializers.Serializer):
    user = rest_serializers.DictField(
        child=rest_serializers.CharField(),
        help_text="Basic user fields like ID, email, and verification status."
    )
    profile = ProfileSerializer()


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    @extend_schema(
        responses={200: MeViewResponseSerializer},
        description="Retrieves the current authenticated user's details and profile data.",
        tags=['User Management']
    )

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
    serializer_class = SavingsGroupCreateSerializer

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

@extend_schema(
    description="Lists all savings groups created (and thus administered) by the authenticated user.",
    tags=['Savings Groups'],
    responses={
        200: SavingsGroupSerializer(many=True),
        401: {'description': 'Authentication credentials were not provided.'}
    }
)
class MyGroupsListView(generics.ListAPIView):
    """Groups where user is the admin"""
    serializer_class = SavingsGroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SavingsGroup.objects.filter(admin=self.request.user).select_related('admin__profile')

@extend_schema(
    parameters=[
        OpenApiParameter(
            name='id',
            type=int,
            location=OpenApiParameter.PATH,
            description='The ID of the savings group.',
            required=True
        ),
    ],
    description="Retrieves the details of a single savings group. Access is restricted to the admin/creator.",
    tags=['Savings Groups'],
    responses={
        200: SavingsGroupSerializer,
        401: {'description': 'Authentication required.'},
        404: {'description': 'Group not found or unauthorized access.'}
    }
)
class GroupDetailView(generics.RetrieveAPIView):
    """Single group detail"""
    serializer_class = SavingsGroupSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        return SavingsGroup.objects.filter(admin=user)

@extend_schema(
    description="Lists all Active savings groups across the platform, allowing filtering and searching.",
    tags=['Savings Groups'],
    parameters=[
        OpenApiParameter(
            name='search',
            type={'type': 'string'},
            location=OpenApiParameter.QUERY,
            description='Search by group name or description.'
        ),
        OpenApiParameter(
            name='frequency',
            type={'type': 'string'},
            location=OpenApiParameter.QUERY,
            description='Filter by contribution frequency (e.g., daily, weekly, monthly).'
        ),
        OpenApiParameter(
            name='expected_members',
            type={'type': 'integer'},
            location=OpenApiParameter.QUERY,
            description='Filter by exact expected number of members.'
        ),
    ],
    examples=[
        OpenApiExample(
            name='Filter and Search Example',
            description='Retrieve all weekly groups with "vacation" in the name/description.',
            value={
                'search': 'vacation',
                'frequency': 'weekly'
            },
            request_only=True
        ),
    ],
    responses={
        200: SavingsGroupSerializer(many=True),
        401: {'description': 'Authentication credentials were not provided.'}
    }
)
class AllGroupsListView(generics.ListAPIView):
    """Lists all active savings groups for the platform, with filtering and searching."""
    serializer_class = SavingsGroupSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]

    filterset_fields = ['frequency', 'expected_members', 'contribution_amount']

    search_fields = ['group_name', 'description']

    def get_queryset(self):
        # Only show groups that have been approved by an admin
        return (
            SavingsGroup.objects
            .filter(status='active')
            .select_related('admin__profile')
        )

@extend_schema(
    request=None,
    responses={
        201: {'description': 'Request submitted successfully.'},
        400: {'description': 'Already a member or request pending.'},
        404: {'description': 'Group not found or not active.'}
    },
    description="Allows an authenticated user to submit a join request to an active group.",
    tags=['Savings Groups']
)
class GroupJoinRequestView(APIView):
    """Endpoint for users to request to join a group."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, group_id):
        try:
            group = SavingsGroup.objects.get(id=group_id, status='active')
        except SavingsGroup.DoesNotExist:
            return Response({"error": "Group not found or not currently active."},
                            status=status.HTTP_404_NOT_FOUND)

        user = request.user

        # Check if already an approved member
        if GroupMembership.objects.filter(user=user, group_id=group_id).exists():
            return Response({"error": "You are already a member of this group."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            existing_request = GroupJoinRequest.objects.get(user=user, group_id=group_id)

            if existing_request.status == 'approved':
                return Response({"error": "Your request was already approved."},
                                status=status.HTTP_400_BAD_REQUEST)

            elif existing_request.status == 'pending':
                return Response({"error": "You already have a pending request for this group."},
                                status=status.HTTP_400_BAD_REQUEST)

            elif existing_request.status == 'rejected':
                existing_request.status = 'pending'
                existing_request.requested_at = timezone.now()
                existing_request.handled_at = None
                existing_request.handled_by = None
                existing_request.save(update_fields=['status', 'requested_at', 'handled_at', 'handled_by'])

                send_group_join_request_email_async.delay(existing_request.id)

                return Response({"message": f"Previous request re-submitted to admin of {group.group_name}."},
                                status=status.HTTP_200_OK)

        except GroupJoinRequest.DoesNotExist:
            # 4. No request exists yet, so create a new one
            new_request = GroupJoinRequest.objects.create(user=user, group=group, status='pending')

            send_group_join_request_email_async.delay(new_request.id)

            return Response({"message": f"Join request sent to admin of {group.group_name}. The admin has been notified via email."},
                            status=status.HTTP_201_CREATED)

@extend_schema(
    responses={
        200: GroupJoinRequestSerializer(many=True),
        403: {'description': 'User is not the group admin.'}
    },
    description="Group Admin can view all pending join requests for their specific group.",
    tags=['Savings Groups']
)
class GroupRequestsListView(generics.ListAPIView):
    """Endpoint for Group Admin to list pending join requests."""
    serializer_class = GroupJoinRequestSerializer
    permission_classes = [IsAuthenticated, IsGroupAdmin]

    def get_queryset(self):
        group_id = self.kwargs.get('group_id')

        # Check if the requesting user is the admin of the group
        try:
            group = SavingsGroup.objects.get(id=group_id, admin=self.request.user)
        except SavingsGroup.DoesNotExist:
            raise rest_serializers.ValidationError({"error": "Group not found or you are not the admin."})

        return GroupJoinRequest.objects.filter(
            group=group,
            status='pending'
        ).select_related('user__profile', 'group')


@extend_schema(
    request=GroupJoinActionSerializer,
    responses={
        200: {'description': 'Request handled successfully.'},
        400: {'description': 'Invalid action or request already handled.'},
        403: {'description': 'User is not the group admin.'},
        404: {'description': 'Request not found.'}
    },
    description="Group Admin approves or rejects a pending join request.",
    tags=['Savings Groups']
)
class GroupRequestActionView(APIView):
    """Endpoint for Group Admin to approve or reject a specific join request."""
    permission_classes = [IsAuthenticated, IsGroupAdmin]

    def get_object(self, pk):
        try:
            request_obj = GroupJoinRequest.objects.get(pk=pk)
            self.check_object_permissions(self.request, request_obj)
            return request_obj
        except GroupJoinRequest.DoesNotExist:
            raise status.HTTP_404_NOT_FOUND

    @transaction.atomic
    def post(self, request, pk):
        try:
            request_obj = GroupJoinRequest.objects.select_related('group__admin').get(pk=pk)
        except GroupJoinRequest.DoesNotExist:
            return Response({"error": "Join request not found."}, status=status.HTTP_404_NOT_FOUND)

        if request_obj.group.admin != request.user:
            return Response({'detail': 'You are not authorized to handle this request.'},
                            status=status.HTTP_403_FORBIDDEN)

        # Validation of input action
        serializer = GroupJoinActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']

        # Status Check
        if request_obj.status != 'pending':
            return Response({"error": f"Request is already {request_obj.status}."},
                            status=status.HTTP_400_BAD_REQUEST)

        if action == 'approve':
            group = request_obj.group

            # Check if group is full
            if group.current_members >= group.expected_members:
                return Response({'error': 'Cannot approve. Group is already full.'},
                                status=status.HTTP_400_BAD_REQUEST)

            try:
                GroupMembership.objects.create(user=request_obj.user, group=group)

                # Increment group member count
                group.current_members += 1
                group.save(update_fields=['current_members'])

                request_obj.status = 'approved'
                request_obj.handled_by = request.user
                request_obj.handled_at = timezone.now()
                request_obj.save(update_fields=['status', 'handled_by', 'handled_at'])

                send_group_join_response_email_async.delay(pk, 'approved')

                message = "User approved and added to the group successfully."

            except IntegrityError:
                return Response({"error": "User is already a confirmed member of this group."},
                                status=status.HTTP_400_BAD_REQUEST)

        elif action == 'reject':
            request_obj.status = 'rejected'
            request_obj.handled_by = request.user
            request_obj.handled_at = timezone.now()
            request_obj.save(update_fields=['status', 'handled_by', 'handled_at'])

            send_group_join_response_email_async.delay(pk, 'rejected')

            message = "User request has been rejected."

        else:
            message = "Invalid action."
            return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": message}, status=status.HTTP_200_OK)
