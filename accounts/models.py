from phonenumber_field.modelfields import PhoneNumberField
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from cloudinary.models import CloudinaryField
from django.db import models
import os


class User(AbstractUser):
    email = models.EmailField(unique=True, db_index=True)
    phone_number = PhoneNumberField(unique=True, blank=True, null=True, db_index=True)
    is_verified = models.BooleanField(default=False)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_set',
        blank=True,
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_set',
        blank=True,
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
    profile_picture = models.URLField(max_length=1000, blank=True, null=True, verbose_name="Profile Picture URL")
    momo_provider = models.CharField(max_length=20, choices=MOMO_PROVIDER_CHOICES)
    momo_number = PhoneNumberField(unique=True)
    momo_name = models.CharField(max_length=255)

    def __str__(self):
        return self.full_name


def validate_image_extension(value):
    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = ['.jpg', '.jpeg', '.png']
    if ext not in valid_extensions:
        raise ValidationError('Only JPG, JPEG, and PNG files are allowed.')

class GroupAdminKYC(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='kyc')

    ghana_card_front = CloudinaryField(
        'image',
        folder='snappx/kyc/ghana_card/front',
        type='private',
        transformation=[{'quality': 'auto'}],
        null=True, blank=True
    )
    ghana_card_back = CloudinaryField(
        'image',
        folder='snappx/kyc/ghana_card/back',
        type='private',
        transformation=[{'quality': 'auto'}],
        null=True, blank=True
    )
    live_photo = CloudinaryField(
        'image',
        folder='snappx/kyc/live_photos',
        type='private',
        transformation=[{'width': 800, 'crop': 'limit'}],
        null=True, blank=True
    )

    is_manually_verified = models.BooleanField(default=False, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='verified_kycs')
    created_at = models.DateTimeField(auto_now_add=True)

class SavingsGroup(models.Model):
    FREQUENCY_CHOICES = (
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    )

    STATUS_CHOICES = (
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    )

    name = models.CharField(max_length=255)
    admin = models.ForeignKey(User, on_delete=models.PROTECT, related_name='admin_of_groups')
    group_name = models.CharField(max_length=255, unique=True)
    contribution_amount = models.DecimalField(max_digits=12, decimal_places=2)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    payout_timeline_days = models.PositiveIntegerField(help_text="e.g., 30 days")
    expected_members = models.PositiveIntegerField()
    current_members = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='approved_groups'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_public = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.group_name} by {self.admin.profile.full_name}"

    def clean(self):
        if self.current_members > self.expected_members:
            raise ValidationError("Current members cannot exceed expected members.")
