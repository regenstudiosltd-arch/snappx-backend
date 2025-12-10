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
