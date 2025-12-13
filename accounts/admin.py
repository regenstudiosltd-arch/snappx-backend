from .models import GroupAdminKYC, PayoutOrder, SavingsGroup, GroupJoinRequest, GroupMembership
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import admin
import cloudinary

@admin.register(GroupAdminKYC)
class GroupAdminKYCAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_manually_verified', 'created_at', 'verification_status']
    list_filter = ['is_manually_verified', 'created_at']
    search_fields = ['user__email', 'user__profile__momo_number']

    fieldsets = (
        ('User Info', {
            'fields': ('user', 'created_at')
        }),
        ('Verification Decision', {
            'fields': ('is_manually_verified', 'verified_by', 'verified_at'),
            'description': "Check the images below. If they match, check 'Is Manually Verified' and Save."
        }),
        ('Ghana Card (ID)', {
            'fields': ('front_preview', 'back_preview'),
            'description': "Verify the name and face on the ID card."
        }),
        ('Live Selfie', {
            'fields': ('live_preview',),
            'description': "Compare this selfie with the face on the Ghana Card above."
        }),
    )

    readonly_fields = [
        'user', 'created_at', 'verified_by', 'verified_at',
        'front_preview', 'back_preview', 'live_preview'
    ]

    def save_model(self, request, obj, form, change):
        if obj.is_manually_verified and not obj.verified_at:
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
        super().save_model(request, obj, form, change)

    # generate signed URLs for private images
    def _get_signed_url(self, image_field):
        """
        Explicitly builds a signed URL for private Cloudinary resources.
        """
        if not image_field:
            return None

        try:
            return cloudinary.CloudinaryImage(image_field.public_id).build_url(
                type='private',
                sign_url=True,
                secure=True,
                expires_in=3600
            )
        except Exception as e:
            return None

    def front_preview(self, obj):
        url = self._get_signed_url(obj.ghana_card_front)
        if url:
            return format_html(
                '<a href="{}" target="_blank"><img src="{}" width="400" style="border-radius:8px; border: 2px solid #ccc;"/></a>',
                url, url
            )
        return "No Front Image"

    front_preview.short_description = "Ghana Card Front"

    def back_preview(self, obj):
        url = self._get_signed_url(obj.ghana_card_back)
        if url:
            return format_html(
                '<a href="{}" target="_blank"><img src="{}" width="400" style="border-radius:8px; border: 2px solid #ccc;"/></a>',
                url, url
            )
        return "No Back Image"

    back_preview.short_description = "Ghana Card Back"

    def live_preview(self, obj):
        url = self._get_signed_url(obj.live_photo)
        if url:
            return format_html(
                '<a href="{}" target="_blank"><img src="{}" width="400" style="border-radius:8px; border: 2px solid #007bff;"/></a>',
                url, url
            )
        return "No Live Selfie"

    live_preview.short_description = "Live Selfie"

    def verification_status(self, obj):
        return "✅ Verified" if obj.is_manually_verified else "❌ Pending"

@admin.register(SavingsGroup)
class SavingsGroupAdmin(admin.ModelAdmin):
    list_display = ['group_name', 'admin', 'contribution_amount', 'frequency', 'status', 'expected_members', 'created_at']
    list_filter = ['status', 'frequency', 'created_at']
    search_fields = ['group_name', 'admin__email']
    readonly_fields = ['admin', 'created_at', 'approved_at']
    actions = ['approve_groups', 'suspend_groups', 'reject_groups']

    def approve_groups(self, request, queryset):
        queryset.update(status='active', approved_by=request.user, approved_at=timezone.now())
        for group in queryset:
            group.admin.kyc.is_manually_verified = True
            group.admin.kyc.verified_by = request.user
            group.admin.kyc.verified_at = timezone.now()
            group.admin.kyc.save()

            # Activation logic if group is full
            if group.current_members >= group.expected_members and not group.start_date:
                group.start_date = timezone.now().date()
                group.save(update_fields=['start_date'])

                # Generate payout order based on join order (earliest first)
                memberships = group.members.order_by('joined_at')
                for pos, membership in enumerate(memberships, start=1):
                    PayoutOrder.objects.create(
                        group=group,
                        membership=membership,
                        position=pos
                    )

    approve_groups.short_description = "Approve and activate selected groups (if full)"

    def suspend_groups(self, request, queryset):
        queryset.update(status='suspended')
    suspend_groups.short_description = "Suspend selected groups"

    def reject_groups(self, request, queryset):
        queryset.update(status='rejected')
    reject_groups.short_description = "Reject selected groups"

@admin.register(GroupJoinRequest)
class GroupJoinRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'group', 'status', 'requested_at', 'handled_by']
    list_filter = ['status', 'requested_at']
    search_fields = ['user__email', 'group__group_name']
    readonly_fields = ['user', 'group', 'requested_at', 'handled_by', 'handled_at']


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'group', 'joined_at']
    list_filter = ['joined_at']
    search_fields = ['user__email', 'group__group_name']
    readonly_fields = ['user', 'group', 'joined_at']
