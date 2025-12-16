from time import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import GroupAdminKYC, Profile, SavingsGroup, GroupJoinRequest, GroupMembership, Contribution, SavingsGoal, GoalContribution
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from rest_framework import serializers
from django.conf import settings
from django.db.models import Sum
from drf_spectacular.utils import extend_schema_field, OpenApiTypes
from decimal import Decimal
from django.utils import timezone

User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    remember_me = serializers.BooleanField(default=False, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['login_field'] = serializers.CharField(required=True)
        self.fields.pop(self.username_field, None)

    def validate(self, attrs):
        login_field = attrs['login_field']
        password = attrs['password']
        remember_me = attrs['remember_me']

        # Find user by email or phone (momo_number)
        try:
            if '@' in login_field:
                user = User.objects.select_related('profile').get(email=login_field)
            else:
                user = User.objects.select_related('profile').get(profile__momo_number=login_field)
        except User.DoesNotExist:
            raise AuthenticationFailed('No user found with this email or phone')

        if not user.check_password(password):
            raise AuthenticationFailed('Incorrect password')

        if not user.is_verified:
            raise AuthenticationFailed('Account not verified. Please verify your phone first.')

        # Generate tokens
        refresh = RefreshToken.for_user(user)

        # Extend refresh lifetime if remember_me is True
        if remember_me:
            extended_lifetime = settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'] * 30
            refresh.set_exp(lifetime=extended_lifetime)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

class FullSignupSerializer(serializers.Serializer):
    """
    Serializer used solely for documenting the FullSignupView request body.
    The validation and creation logic remains in the view.
    """
    email = serializers.EmailField(
        max_length=255,
        help_text="User's email address."
    )
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        help_text="Desired password."
    )
    password2 = serializers.CharField(
        write_only=True,
        help_text="Password confirmation."
    )
    full_name = serializers.CharField(
        max_length=255,
        help_text="Full name of the user."
    )
    date_of_birth = serializers.DateField(
        help_text="Date of birth (YYYY-MM-DD)."
    )
    user_type = serializers.ChoiceField(
        choices=[('individual', 'Individual'), ('business', 'Business')],
        help_text="Type of user: 'individual' or 'business'."
    )
    ghana_post_address = serializers.CharField(
        max_length=255,
        help_text="User's Ghana Post Digital Address."
    )
    momo_provider = serializers.CharField(
        max_length=50,
        help_text="Mobile Money provider (e.g., MTN, Vodafone)."
    )
    momo_number = serializers.CharField(
        max_length=15,
        help_text="Mobile Money phone number."
    )
    momo_name = serializers.CharField(
        max_length=255,
        help_text="Name registered on the Mobile Money account."
    )
    profile_picture = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="Optional: User's profile photo (e.g., a selfie)."
    )

class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True)
    class Meta:
        model = User
        fields = ('email', 'password', 'password2')
    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError("Passwords don't match")
        return data
    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            username=validated_data['email'].split('@')[0]
        )
        return user
class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = '__all__'
        read_only_fields = ('user',)
class SendOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
class VerifyOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=10)

class ForgotPasswordSerializer(serializers.Serializer):
    login_field = serializers.CharField(required=True)
class ResetPasswordSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20, required=True)
    code = serializers.CharField(max_length=10, required=True)
    password = serializers.CharField(min_length=8, required=True)
    password2 = serializers.CharField(required=True)

    def validate(self, data):
        if data['password'] != data['password2']:
            raise ValidationError("Passwords don't match")
        return data
class GroupAdminKYCSerializer(serializers.ModelSerializer):
    ghana_card_front = serializers.ImageField(
        required=True,
        write_only=True,
        help_text="Upload Ghana Card front"
    )
    ghana_card_back = serializers.ImageField(
        required=True,
        write_only=True,
        help_text="Upload Ghana Card back"
    )
    live_photo = serializers.ImageField(
        required=True,
        write_only=True,
        help_text="Upload live selfie"
    )

    class Meta:
        model = GroupAdminKYC
        fields = ['ghana_card_front', 'ghana_card_back', 'live_photo']

    def create(self, validated_data):
        user = self.context['request'].user
        return GroupAdminKYC.objects.create(user=user, **validated_data)

class SavingsGroupCreateSerializer(serializers.ModelSerializer):
    kyc = GroupAdminKYCSerializer(required=True)

    class Meta:
        model = SavingsGroup
        fields = [
            'group_name',
            'contribution_amount',
            'frequency',
            'payout_timeline_days',
            'expected_members',
            'description',
            'kyc'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if 'request' in self.context and self.context['request'].method == 'POST':
            user = self.context['request'].user

            self.kyc_exists = GroupAdminKYC.objects.filter(user=user).exists()

            if self.kyc_exists:
                self.fields['kyc'].required = False

                kyc_fields = self.fields['kyc'].fields
                for field_name in kyc_fields:
                    kyc_fields[field_name].required = False

    def create(self, validated_data):
        kyc_data = validated_data.pop('kyc')
        user = self.context['request'].user

        kyc_exists = getattr(self, 'kyc_exists', GroupAdminKYC.objects.filter(user=user).exists())

        if not kyc_exists:
            GroupAdminKYC.objects.create(
                user=user,
                ghana_card_front=kyc_data.get('ghana_card_front'),
                ghana_card_back=kyc_data.get('ghana_card_back'),
                live_photo=kyc_data.get('live_photo')
            )
        else:
            pass

        # Create the Savings Group
        group = SavingsGroup.objects.create(
            admin=user,
            status='pending',
            **validated_data
        )

        # Add the admin as a member of the group
        GroupMembership.objects.create(user=user, group=group)

        return group
class SavingsGroupSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin.profile.full_name', read_only=True)
    admin_phone = serializers.CharField(source='admin.profile.momo_number', read_only=True)
    admin_photo = serializers.URLField(source='admin.profile.profile_picture', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    total_savings = serializers.SerializerMethodField(
        help_text="Total amount the admin (you) has personally contributed to this group across ALL cycles (historical + current)."
    )
    next_due = serializers.SerializerMethodField(
        help_text="Next payout date (end of current contribution cycle)."
    )

    class Meta:
        model = SavingsGroup
        fields = [
            'id', 'group_name', 'contribution_amount', 'frequency',
            'payout_timeline_days', 'expected_members', 'current_members',
            'description', 'status', 'status_display', 'created_at',
            'admin_name', 'admin_phone', 'admin_photo',
            'total_savings', 'next_due'
        ]
        read_only_fields = ['status', 'current_members', 'created_at']

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_total_savings(self, obj):
        """
        Returns the users total personal contributions across ALL cycles in this group.
        """
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0.0

        try:
            membership = obj.members.get(user=request.user)
            total = membership.contributions.aggregate(total=Sum('amount'))['total']
            return float(total or 0.0)
        except GroupMembership.DoesNotExist:
            return 0.0

    @extend_schema_field(OpenApiTypes.STR)
    def get_next_due(self, obj):
        if obj.next_payout_date:
            return obj.next_payout_date.strftime('%m/%d/%Y')
        return None

class RequestingUserSerializer(serializers.ModelSerializer):
    """Minimal serializer to show details of the user who submitted the request."""
    full_name = serializers.CharField(source='profile.full_name', read_only=True)
    momo_number = serializers.CharField(source='profile.momo_number', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'momo_number']

class GroupJoinRequestSerializer(serializers.ModelSerializer):
    """Serializer for admin to view pending join requests."""
    user_details = RequestingUserSerializer(source='user', read_only=True)
    group_name = serializers.CharField(source='group.group_name', read_only=True)

    reason = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
        default='',
        help_text="Reason provided by the user when requesting to join."
    )

    class Meta:
        model = GroupJoinRequest
        fields = [
            'id',
            'group',
            'group_name',
            'user',
            'user_details',
            'status',
            'requested_at',
            'reason'
        ]
        read_only_fields = ['group', 'user', 'status', 'requested_at', 'handled_by', 'handled_at']

class GroupJoinActionSerializer(serializers.Serializer):
    """Serializer for the admin to take an action (Approve/Reject)."""
    action = serializers.ChoiceField(
        choices=['approve', 'reject'],
        help_text="Action to take on the request: 'approve' or 'reject'."
    )

class GroupJoinRequestCreateSerializer(serializers.Serializer):
    """
    Serializer for submitting a join request to a savings group.
    Only 'reason' is accepted from the user input.
    """
    reason = serializers.CharField(
        max_length=1000,
        allow_blank=True,
        required=False,
        trim_whitespace=True,
        help_text="Optional explanation of why you want to join this group. This will be visible to the group admin."
    )

    def validate_reason(self, value):
        if value and len(value.strip()) < 10:
            raise serializers.ValidationError("Reason should be at least 10 characters if provided.")
        return value.strip()

class GroupDashboardCardSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(read_only=True)
    current_members = serializers.IntegerField(read_only=True)
    next_payout_days = serializers.SerializerMethodField()
    user_total_contribution = serializers.SerializerMethodField()
    total_saved = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = SavingsGroup
        fields = [
            'id', 'group_name', 'current_members', 'next_payout_days',
            'user_total_contribution', 'total_saved', 'progress_percentage',
            'contribution_amount', 'frequency'
        ]

    @extend_schema_field(OpenApiTypes.INT)
    def get_next_payout_days(self, obj):
        return obj.days_until_next_payout

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_user_total_contribution(self, obj):
        user = self.context['request'].user
        membership = GroupMembership.objects.filter(user=user, group=obj).first()
        if not membership:
            return 0.0
        total = membership.contributions.aggregate(total=Sum('amount'))['total']
        return float(total) if total else 0.0

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_total_saved(self, obj):
        current_cycle = obj.current_cycle_number
        total = Contribution.objects.filter(
            membership__group=obj,
            cycle_number=current_cycle
        ).aggregate(total=Sum('amount'))['total']
        return float(total) if total else 0.0

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_progress_percentage(self, obj):
        current_cycle = obj.current_cycle_number
        total_contributed = Contribution.objects.filter(
            membership__group=obj,
            cycle_number=current_cycle
        ).aggregate(total=Sum('amount'))['total'] or 0

        expected_per_cycle = obj.contribution_amount * obj.expected_members
        if expected_per_cycle == 0:
            return 0.0
        percentage = (total_contributed / expected_per_cycle) * 100
        return round(percentage, 1)


class DashboardResponseSerializer(serializers.Serializer):
    """
    Serializer defining the complete structure of the /api/accounts/dashboard/ GET response.
    This resolves the drf-spectacular schema definition issues.
    """
    total_savings = serializers.FloatField(
        help_text='Total amount saved by the user across all groups.'
    )
    growth_percentage = serializers.FloatField(
        help_text='Percentage change in total savings compared to the previous month.'
    )
    growth_text = serializers.CharField(
        help_text="A display string showing the growth (e.g., '+12.5% from last month')."
    )
    joined_groups = GroupDashboardCardSerializer(
        many=True,
        help_text='List of active groups the authenticated user is a member of.'
    )

class SavingsGoalCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new personal savings goal.
    """
    class Meta:
        model = SavingsGoal
        fields = [
            'name', 'target_amount', 'regular_contribution', 'target_date','frequency']

    def validate(self, data):
        """
        Additional validation: ensure target date is in the future.
        """
        if data['target_date'] < timezone.now().date():
            raise serializers.ValidationError("Target date must be in the future.")
        if data['target_amount'] <= 0:
            raise serializers.ValidationError("Target amount must be greater than zero.")
        if data['regular_contribution'] <= 0:
            raise serializers.ValidationError("Regular contribution must be greater than zero.")
        return data

    def create(self, validated_data):
        user = self.context['request'].user
        goal = SavingsGoal.objects.create(user=user, **validated_data)
        return goal

class SavingsGoalSerializer(serializers.ModelSerializer):
    """
    Base serializer for SavingsGoal with computed fields used in lists and details.
    """
    current_saved = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()
    contribution_display = serializers.SerializerMethodField()

    class Meta:
        model = SavingsGoal
        fields = [
            'id', 'name', 'target_amount', 'regular_contribution', 'frequency',
            'target_date', 'created_at', 'current_saved', 'progress_percentage',
            'days_left', 'contribution_display'
        ]
        read_only_fields = ['created_at', 'current_saved', 'progress_percentage', 'days_left']

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_current_saved(self, obj):
        return float(obj.current_saved)

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_progress_percentage(self, obj):
        return round(obj.progress_percentage, 1)

    @extend_schema_field(OpenApiTypes.STR)
    def get_days_left(self, obj):
        return obj.days_left

    @extend_schema_field(OpenApiTypes.STR)
    def get_contribution_display(self, obj):
        freq_map = dict(SavingsGoal.FREQUENCY_CHOICES)
        frequency_label = freq_map.get(obj.frequency, obj.frequency).capitalize()
        return f"₵{obj.regular_contribution} {frequency_label}"

class GoalDashboardCardSerializer(SavingsGoalSerializer):
    """
    Serializer used specifically for the individual goals.
    It inherits all fields and methods from SavingsGoalSerializer, providing:
      - goal name
      - current_saved of target_amount (e.g., ₵3,200 of ₵5,000)
      - contribution_display (e.g., ₵500 Monthly)
      - progress_percentage (for progress bar)
      - days_left (e.g., "6 days" or "Overdue")
    """
    pass

class GoalsDashboardResponseSerializer(serializers.Serializer):
    """
    Top-level response serializer for the /goals/dashboard/ endpoint.
    Defines the structure of the overview card + list of goal cards.
    """
    total_target = serializers.FloatField(
        help_text="Sum of target_amount across all user's goals."
    )
    total_saved = serializers.FloatField(
        help_text="Sum of current_saved across all user's goals."
    )
    overall_progress = serializers.FloatField(
        help_text="Overall progress percentage (total_saved / total_target × 100)."
    )
    active_goals_count = serializers.IntegerField(
        help_text="Number of goals that are still active (not completed and not overdue if you prefer, but here includes overdue but incomplete)."
    )
    goals = GoalDashboardCardSerializer(
        many=True,
        help_text="Detailed list of all the user's savings goals as cards."
    )


class SavingsGoalUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavingsGoal
        fields = [
            'name', 'target_amount', 'regular_contribution',
            'target_date', 'frequency'
        ]
        partial = True

    def validate(self, data):
        instance = self.instance
        if 'target_date' in data and data['target_date'] < timezone.now().date():
            raise serializers.ValidationError("Target date must be in the future.")
        if 'target_amount' in data and data['target_amount'] <= 0:
            raise serializers.ValidationError("Target amount must be greater than zero.")
        if 'regular_contribution' in data and data['regular_contribution'] <= 0:
            raise serializers.ValidationError("Regular contribution must be greater than zero.")
        # Prevent reducing target below current saved
        if 'target_amount' in data and instance and data['target_amount'] < instance.current_saved:
            raise serializers.ValidationError("Cannot set target below current saved amount.")
        return data


class GroupsStatsResponseSerializer(serializers.Serializer):
    total_groups = serializers.IntegerField(help_text="Number of active groups the user is currently a member of.")
    total_members = serializers.IntegerField(help_text="Total number of members across all the user's active groups.")
    group_savings = serializers.FloatField(help_text="Combined total of current savings (sum of verified contributions in the current cycle) across all the user's active groups.")


class JoinRequestsStatsSerializer(serializers.Serializer):
    pending = serializers.IntegerField(
        help_text="Number of pending join requests across all groups administered by the user."
    )
    accepted = serializers.IntegerField(
        help_text="Number of accepted join requests across all groups administered by the user."
    )
    declined = serializers.IntegerField(
        help_text="Number of declined (rejected) join requests across all groups administered by the user."
    )
