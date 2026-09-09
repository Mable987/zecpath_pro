from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Employer, Candidate, Job, Application


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # BaseUserAdmin assumes the default username-based User; override the
    # fieldsets/lists since ours is email-based with a role field instead.
    ordering = ("email",)
    list_display = ("email", "phone", "role", "is_active", "is_verified", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_verified", "is_staff")
    search_fields = ("email", "phone")
    readonly_fields = ("created_at", "updated_at", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("phone", "role")}),
        ("Status", {"fields": ("is_active", "is_verified", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "phone", "role", "password1", "password2"),
        }),
    )


admin.site.register(Employer)
admin.site.register(Candidate)
admin.site.register(Job)
admin.site.register(Application)