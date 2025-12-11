from .views import CreateSavingsGroupView, MyGroupsListView, GroupDetailView, AllGroupsListView, GroupJoinRequestView, GroupRequestsListView, GroupRequestActionView

from django.urls import path

urlpatterns = [
    path('groups/create/', CreateSavingsGroupView.as_view(), name='create-savings-group'),
    path('groups/my-groups/', MyGroupsListView.as_view(), name='my-groups'),
    path('groups/all/', AllGroupsListView.as_view(), name='all-groups'),
    path('groups/<int:id>/', GroupDetailView.as_view(), name='group-detail'),

    # Join group request endpoints
    path('groups/<int:group_id>/request_join/', GroupJoinRequestView.as_view(), name='group-request-join'),
    path('groups/<int:group_id>/requests/', GroupRequestsListView.as_view(), name='group-requests-list'),
    path('groups/requests/<int:pk>/action/', GroupRequestActionView.as_view(), name='group-request-action'),
]
