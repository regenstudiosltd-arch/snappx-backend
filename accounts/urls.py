from django.urls import path
from .views import SignupView, ProfileCreateView, SendOTPView, VerifyOTPView

urlpatterns = [
    path('signup/', SignupView.as_view(), name='signup'),
    path('profile/', ProfileCreateView.as_view(), name='profile'),
    path('otp/send/', SendOTPView.as_view(), name='otp-send'),
    path('otp/verify/', VerifyOTPView.as_view(), name='otp-verify'),
]
