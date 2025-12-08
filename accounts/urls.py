from django.urls import path
from .views import FullSignupView, SendOTPView, VerifyOTPView, CustomLoginView, TokenRefreshView, ForgotPasswordView, ResetPasswordView

urlpatterns = [
    path('signup/', FullSignupView.as_view(), name='signup'),
    path('otp/send/', SendOTPView.as_view(), name='otp-send'),
    path('otp/verify/', VerifyOTPView.as_view(), name='otp-verify'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset_password'),
]
