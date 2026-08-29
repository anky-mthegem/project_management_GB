from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from projects.models import (
    Project, ProjectMember, Task, TaskDependency, TaskComment,
    TaskAttachment, ActivityLog
)


class CustomUserAdmin(BaseUserAdmin):
    def has_delete_permission(self, request, obj=None):
        if obj and obj.username == 'aman':
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        if obj.username == 'aman':
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        queryset = queryset.exclude(username='aman')
        super().delete_queryset(request, queryset)


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, CustomUserAdmin)


class ProjectMemberInline(admin.TabularInline):
    model = ProjectMember
    extra = 1


class TaskInline(admin.TabularInline):
    model = Task
    fields = ('name', 'start_date', 'end_date', 'duration_days', 'progress', 'status', 'priority', 'is_critical', 'assignee')
    extra = 0
    show_change_link = True

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assignee":
            kwargs["queryset"] = User.objects.filter(is_active=True).exclude(username='aman')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'status_badge', 'start_date', 'end_date', 'progress_bar', 'owner', 'created_at')
    list_filter = ('status', 'created_at', 'owner', 'exclude_weekends')
    search_fields = ('name', 'code', 'description')
    prepopulated_fields = {'code': ('name',)}
    inlines = [ProjectMemberInline, TaskInline]

    def status_badge(self, obj):
        colors = {
            'PLANNING': '#6366f1',
            'ACTIVE': '#10b981',
            'ON_HOLD': '#f59e0b',
            'COMPLETED': '#3b82f6',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 9999px; font-weight: 600; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def progress_bar(self, obj):
        val = obj.progress
        return format_html(
            '<div style="width: 100px; background: #e5e7eb; border-radius: 4px; overflow: hidden; height: 14px;">'
            '<div style="width: {}%; background: #10b981; height: 100%; text-align: center; font-size: 10px; color: white; line-height: 14px;">{}%</div>'
            '</div>',
            val, val
        )
    progress_bar.short_description = 'Progress'


class PredecessorInline(admin.TabularInline):
    model = TaskDependency
    fk_name = 'to_task'
    extra = 1
    verbose_name = 'Predecessor Dependency'
    verbose_name_plural = 'Predecessor Dependencies'


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    readonly_fields = ('author', 'created_at')


class TaskAttachmentInline(admin.TabularInline):
    model = TaskAttachment
    extra = 0
    readonly_fields = ('uploaded_by', 'file_size', 'created_at')


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        'wbs_code_display', 'name', 'project', 'start_date', 'end_date',
        'duration_days', 'progress_bar', 'status_badge', 'priority_badge',
        'cpm_badge', 'is_milestone', 'assignee'
    )
    list_filter = ('project', 'status', 'priority', 'is_critical', 'is_milestone', 'start_date')
    search_fields = ('name', 'description', 'project__name')
    inlines = [PredecessorInline, TaskCommentInline, TaskAttachmentInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "assignee":
            kwargs["queryset"] = User.objects.filter(is_active=True).exclude(username='aman')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def wbs_code_display(self, obj):
        return format_html('<strong>{}</strong>', obj.wbs_code)
    wbs_code_display.short_description = 'WBS'

    def cpm_badge(self, obj):
        if obj.is_critical:
            return format_html('<span style="color: #ef4444; font-weight: bold; font-size: 11px;">CRITICAL</span>')
        return format_html('<span style="color: #9ca3af; font-size: 11px;">{}d float</span>', obj.total_float_days)
    cpm_badge.short_description = 'Critical Path'

    def status_badge(self, obj):
        colors = {
            'NOT_STARTED': '#9ca3af',
            'IN_PROGRESS': '#3b82f6',
            'COMPLETE': '#10b981',
            'DELAYED': '#ef4444',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 7px; border-radius: 4px; font-weight: 500; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def priority_badge(self, obj):
        colors = {
            'LOW': '#9ca3af',
            'MEDIUM': '#3b82f6',
            'HIGH': '#f59e0b',
            'CRITICAL': '#ef4444',
        }
        color = colors.get(obj.priority, '#6b7280')
        return format_html(
            '<span style="color: {}; font-weight: bold; font-size: 11px;">{}</span>',
            color, obj.get_priority_display()
        )
    priority_badge.short_description = 'Priority'

    def progress_bar(self, obj):
        val = obj.progress
        return format_html(
            '<div style="width: 70px; background: #e5e7eb; border-radius: 4px; overflow: hidden; height: 12px;">'
            '<div style="width: {}%; background: #3b82f6; height: 100%;"></div>'
            '</div>',
            val
        )
    progress_bar.short_description = 'Progress'


@admin.register(TaskDependency)
class TaskDependencyAdmin(admin.ModelAdmin):
    list_display = ('from_task', 'dependency_type', 'to_task', 'lag_days', 'created_at')
    list_filter = ('dependency_type', 'from_task__project')
    search_fields = ('from_task__name', 'to_task__name')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('project', 'user', 'action', 'task', 'created_at')
    list_filter = ('project', 'action', 'created_at')
    search_fields = ('details', 'action', 'user__username')


# ==============================================================================
# Custom Django Admin URLs & Branding (Database Import / Export)
# ==============================================================================
from django.urls import path
from projects.admin_database import (
    database_manage_view,
    database_export_view,
    database_import_view,
    database_restore_backup_view,
    database_delete_backup_view,
    database_clear_view,
    database_seed_teams_view,
    database_seed_projects_view,
    get_database_stats
)

admin.site.site_header = "Milestone Management — Admin Portal"
admin.site.site_title = "Milestone Management Portal"
admin.site.index_title = "System Management & Database Administration"

_original_get_urls = admin.site.get_urls
_original_index = admin.site.index

def _custom_admin_urls():
    custom_urls = [
        path('database-manage/', admin.site.admin_view(database_manage_view), name='database_manage'),
        path('database-export/', admin.site.admin_view(database_export_view), name='database_export'),
        path('database-import/', admin.site.admin_view(database_import_view), name='database_import'),
        path('database-restore/<str:backup_name>/', admin.site.admin_view(database_restore_backup_view), name='database_restore_backup'),
        path('database-delete/<str:backup_name>/', admin.site.admin_view(database_delete_backup_view), name='database_delete_backup'),
        path('database-clear/', admin.site.admin_view(database_clear_view), name='database_clear'),
        path('database-seed-teams/', admin.site.admin_view(database_seed_teams_view), name='database_seed_teams'),
        path('database-seed-projects/', admin.site.admin_view(database_seed_projects_view), name='database_seed_projects'),
    ]
    return custom_urls + _original_get_urls()

def _custom_admin_index(request, extra_context=None):
    extra_context = extra_context or {}
    try:
        extra_context['db_stats'] = get_database_stats()
    except Exception:
        extra_context['db_stats'] = None
    return _original_index(request, extra_context=extra_context)

admin.site.get_urls = _custom_admin_urls
admin.site.index = _custom_admin_index
