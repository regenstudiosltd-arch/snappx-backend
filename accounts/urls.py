from .views import (
    CreateSavingsGroupView, MyGroupsListView, GroupDetailView, FullSignupView, SendOTPView, VerifyOTPView,
    CustomLoginView, ForgotPasswordView, ResetPasswordView, MeView, AllGroupsListView
)
from rest_framework_simplejwt.views import TokenRefreshView
from django.urls import path

urlpatterns = [
    path('signup/', FullSignupView.as_view(), name='signup'),
    path('otp/send/', SendOTPView.as_view(), name='otp-send'),
    path('otp/verify/', VerifyOTPView.as_view(), name='otp-verify'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset_password'),
    path('me/', MeView.as_view(), name='me'),

    # groups endpoints
    path('groups/create/', CreateSavingsGroupView.as_view(), name='create-savings-group'),
    path('groups/my-groups/', MyGroupsListView.as_view(), name='my-groups'),
    path('groups/all/', AllGroupsListView.as_view(), name='all-groups'),
    path('groups/<int:id>/', GroupDetailView.as_view(), name='group-detail'),
]
