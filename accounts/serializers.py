from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Profile
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
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
                user = User.objects.get(email=login_field)
            else:
                user = User.objects.get(profile__momo_number=login_field)
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
