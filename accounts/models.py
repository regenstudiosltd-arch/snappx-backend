import uuid
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import AbstractUser
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField
from django.core.validators import RegexValidator


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone_number = PhoneNumberField(unique=True, blank=True, null=True)
    is_verified = models.BooleanField(default=False)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_set',
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_set',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )


class Profile(models.Model):
    USER_TYPE_CHOICES = (('student', 'Student'), ('worker', 'Worker'))
    MOMO_PROVIDER_CHOICES = (
        ('mtn', 'MTN MoMo'),
        ('telecel', 'Telecel Cash'),
        ('airteltigo', 'AirtelTigo Cash'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=255)
    date_of_birth = models.DateField()
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES)
    ghana_post_address = models.CharField(
        max_length=20,
        validators=[RegexValidator(r'^[A-Z]{2}-\d{3}-\d{4}$', 'Format: GA-123-4567')]
    )
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    momo_provider = models.CharField(max_length=20, choices=MOMO_PROVIDER_CHOICES)
    momo_number = PhoneNumberField()
    momo_name = models.CharField(max_length=255)

    def __str__(self):
        return self.full_name


class OTPCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    purpose = models.CharField(max_length=20, default='signup')

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.user.email} - {self.code} ({'used' if self.is_used else 'active'})"
