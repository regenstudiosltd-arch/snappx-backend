from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import GroupAdminKYC, Profile, SavingsGroup
from rest_framework_simplejwt.tokens import RefreshToken
from .models import GroupAdminKYC, SavingsGroup
from django.contrib.auth import get_user_model
from rest_framework import serializers
from django.conf import settings

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
    # Cloudinary private uploads — no "required=" argument
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

    def create(self, validated_data):
        kyc_data = validated_data.pop('kyc')
        user = self.context['request'].user

        kyc = GroupAdminKYC(user=user)
        kyc.ghana_card_front = kyc_data['ghana_card_front']
        kyc.ghana_card_back = kyc_data['ghana_card_back']
        kyc.live_photo = kyc_data['live_photo']
        kyc.save()

        group = SavingsGroup.objects.create(
            admin=user,
            status='pending',
            **validated_data
        )

        return group
class SavingsGroupSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin.profile.full_name', read_only=True)
    admin_phone = serializers.CharField(source='admin.profile.momo_number', read_only=True)
    admin_photo = serializers.URLField(source='admin.profile.profile_picture', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SavingsGroup
        fields = [
            'id', 'group_name', 'contribution_amount', 'frequency',
            'payout_timeline_days', 'expected_members', 'current_members',
            'description', 'status', 'status_display', 'created_at',
            'admin_name', 'admin_phone', 'admin_photo'
        ]
        read_only_fields = ['status', 'current_members', 'created_at']
