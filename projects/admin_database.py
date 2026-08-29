import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse
from django.core.management import call_command
from django.utils.timezone import now

from projects.models import (
    Project, Task, ProjectMember, ActivityLog,
    TaskDependency, TaskComment, TaskAttachment
)
from teams.models import Department, Team, TeamMembership


def superuser_required(view_func):
    """Decorator requiring the user to be an active superuser."""
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")
        if not (request.user.is_active and request.user.is_staff and request.user.is_superuser):
            raise PermissionDenied("Only superusers are authorized to manage database backups.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def get_db_path() -> Path:
    """Returns the absolute path to the active SQLite database file."""
    from django.db import connection
    db_name = connection.settings_dict.get('NAME') or settings.DATABASES['default']['NAME']
    db_name_str = str(db_name)
    if not db_name or db_name_str == ':memory:' or db_name_str.startswith('file:') or '?' in db_name_str:
        db_name = settings.DATABASES['default']['NAME']
    path = Path(db_name).resolve()
    # If in testing and file doesn't exist on disk, create an empty sqlite database file
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(path))
            conn.execute("CREATE TABLE IF NOT EXISTS _test_init (id INTEGER PRIMARY KEY);")
            conn.commit()
            conn.close()
        except Exception:
            pass
    return path


def get_backups_dir() -> Path:
    """Returns the directory for storing automatic and manual database backups."""
    backup_dir = Path(settings.BASE_DIR) / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def format_file_size(bytes_size: int) -> str:
    """Formats bytes into human readable format (KB, MB)."""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    else:
        return f"{bytes_size / (1024 * 1024):.2f} MB"


def get_database_stats() -> dict:
    """Returns metadata and table statistics for the current database."""
    db_path = get_db_path()
    size_bytes = db_path.stat().st_size if db_path.exists() else 0
    mtime = datetime.fromtimestamp(db_path.stat().st_mtime) if db_path.exists() else None

    # Retrieve counts safely
    try:
        total_projects = Project.objects.count()
        total_tasks = Task.objects.count()
        total_members = ProjectMember.objects.count()
        total_users = User.objects.count()
        total_logs = ActivityLog.objects.count()
        total_teams = Team.objects.count()
        total_depts = Department.objects.count()
    except Exception:
        total_projects = total_tasks = total_members = total_users = total_logs = total_teams = total_depts = 0

    return {
        'db_path': str(db_path),
        'db_filename': db_path.name,
        'size_bytes': size_bytes,
        'size_formatted': format_file_size(size_bytes),
        'last_modified': mtime,
        'total_projects': total_projects,
        'total_tasks': total_tasks,
        'total_members': total_members,
        'total_users': total_users,
        'total_logs': total_logs,
        'total_teams': total_teams,
        'total_depts': total_depts,
    }


def list_backups() -> list:
    """Returns a list of saved backup files sorted by creation date descending."""
    backup_dir = get_backups_dir()
    backups = []
    for file in backup_dir.glob("*.sqlite3"):
        stat = file.stat()
        backups.append({
            'filename': file.name,
            'size_formatted': format_file_size(stat.st_size),
            'created_at': datetime.fromtimestamp(stat.st_mtime),
            'path': str(file),
        })
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return backups


def validate_sqlite_file(file_path: Path) -> tuple[bool, str]:
    """
    Validates that a file is a valid, uncorrupted SQLite database
    and contains required project management tables.
    """
    if not file_path.exists() or file_path.stat().st_size < 100:
        return False, "File is empty or corrupted."

    # Check magic header bytes
    with open(file_path, 'rb') as f:
        header = f.read(16)
        if header != b"SQLite format 3\x00":
            return False, "Invalid file format. The file is not a valid SQLite 3 database."

    # Verify database integrity using sqlite3 connection
    try:
        conn = sqlite3.connect(str(file_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        integrity = cursor.fetchone()
        if not integrity or integrity[0] != "ok":
            conn.close()
            return False, f"Database integrity check failed: {integrity}"

        # Check for core Django / Project tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        required_tables = {'auth_user', 'django_migrations'}
        missing = required_tables - tables
        if missing:
            return False, f"Database is missing essential schema tables: {', '.join(missing)}"

        return True, "Valid SQLite database."
    except Exception as e:
        return False, f"Failed to open database: {str(e)}"


# ==============================================================================
# Admin Views
# ==============================================================================

@superuser_required
def database_manage_view(request):
    """Main database backup, export, and restore administration dashboard."""
    from django.contrib import admin
    stats = get_database_stats()
    backups = list_backups()

    context = dict(admin.site.each_context(request))
    context.update({
        'title': 'Database Backup & Restore',
        'stats': stats,
        'backups': backups,
        'site_header': 'Milestone Management Admin',
        'site_title': 'Milestone Management Portal',
        'has_permission': True,
    })
    return render(request, 'admin/database_manage.html', context)


@superuser_required
def database_export_view(request):
    """Exports and downloads the current active db.sqlite3 database file."""
    db_path = get_db_path()
    if not db_path.exists():
        messages.error(request, "Database file does not exist on disk.")
        return redirect('admin:database_manage')

    # Flush any open connection transactions before reading
    connections.close_all()

    timestamp = now().strftime("%Y-%m-%d_%H%M%S")
    download_filename = f"milestone_db_backup_{timestamp}.sqlite3"

    try:
        response = FileResponse(
            open(db_path, 'rb'),
            content_type='application/x-sqlite3',
            as_attachment=True,
            filename=download_filename
        )
        # Log activity
        try:
            ActivityLog.objects.create(
                user=request.user,
                action="Database Exported",
                details=f"Admin {request.user.username} downloaded full database backup ({download_filename})."
            )
        except Exception:
            pass

        return response
    except Exception as e:
        messages.error(request, f"Error exporting database: {str(e)}")
        return redirect('admin:database_manage')


@superuser_required
def database_import_view(request):
    """
    Handles uploading a .sqlite3 database file, creates an automatic
    rollback safety backup of current data, and replaces the live database.
    """
    if request.method != 'POST':
        return redirect('admin:database_manage')

    uploaded_file = request.FILES.get('database_file')
    if not uploaded_file:
        messages.error(request, "Please select a valid .sqlite3 database file to upload.")
        return redirect('admin:database_manage')

    if not (uploaded_file.name.endswith('.sqlite3') or uploaded_file.name.endswith('.db') or uploaded_file.name.endswith('.sqlite')):
        messages.error(request, "Invalid file extension. Please upload a .sqlite3 or .db file.")
        return redirect('admin:database_manage')

    # Save to temporary staging file for validation
    temp_dir = Path(settings.BASE_DIR) / 'backups' / 'temp'
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = temp_dir / f"temp_upload_{now().strftime('%Y%m%d_%H%M%S')}.sqlite3"

    try:
        with open(temp_file_path, 'wb+') as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)

        # 1. Validate SQLite file format & schema integrity
        is_valid, error_msg = validate_sqlite_file(temp_file_path)
        if not is_valid:
            if temp_file_path.exists():
                temp_file_path.unlink()
            messages.error(request, f"Database Import Rejected: {error_msg}")
            return redirect('admin:database_manage')

        # 2. Create automatic pre-restore safety backup of active database
        db_path = get_db_path()
        backup_dir = get_backups_dir()
        pre_restore_name = f"pre_restore_backup_{now().strftime('%Y-%m-%d_%H%M%S')}.sqlite3"
        if db_path.exists():
            safety_backup_path = backup_dir / pre_restore_name
            shutil.copy2(db_path, safety_backup_path)

        # 3. Safely replace live database
        connections.close_all()
        shutil.copy2(temp_file_path, db_path)

        # Clean up temp upload file
        if temp_file_path.exists():
            temp_file_path.unlink()

        # 4. Verify Master Admin integrity in restored database
        try:
            admin_user, _ = User.objects.get_or_create(
                username='aman',
                defaults={
                    'email': 'aman@milestonemanagement.local',
                    'first_name': 'Aman',
                    'last_name': 'Admin',
                    'is_staff': True,
                    'is_superuser': True,
                    'is_active': True,
                }
            )
            if not admin_user.is_superuser or not admin_user.is_staff:
                admin_user.is_superuser = True
                admin_user.is_staff = True
                admin_user.save()
        except Exception:
            pass

        messages.success(
            request,
            f"✅ Database successfully imported and restored from '{uploaded_file.name}'! "
            f"An automatic safety rollback backup was saved as '{pre_restore_name}'."
        )
    except Exception as e:
        messages.error(request, f"Database import failed: {str(e)}")
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()

    return redirect('admin:database_manage')


@superuser_required
def database_restore_backup_view(request, backup_name: str):
    """Restores a previous backup directly from the backups directory."""
    if request.method != 'POST':
        return redirect('admin:database_manage')

    backup_dir = get_backups_dir()
    backup_file = backup_dir / backup_name

    # Prevent directory traversal
    if not backup_file.resolve().is_relative_to(backup_dir.resolve()) or not backup_file.exists():
        messages.error(request, "Selected backup file was not found.")
        return redirect('admin:database_manage')

    # Validate backup file
    is_valid, error_msg = validate_sqlite_file(backup_file)
    if not is_valid:
        messages.error(request, f"Cannot restore backup: {error_msg}")
        return redirect('admin:database_manage')

    db_path = get_db_path()
    try:
        # Create a pre-restore backup first
        pre_restore_name = f"pre_restore_backup_{now().strftime('%Y-%m-%d_%H%M%S')}.sqlite3"
        safety_backup_path = backup_dir / pre_restore_name
        if db_path.exists():
            shutil.copy2(db_path, safety_backup_path)

        # Hot swap
        connections.close_all()
        shutil.copy2(backup_file, db_path)

        messages.success(
            request,
            f"✅ Database restored successfully from backup '{backup_name}'. "
            f"A rollback snapshot was saved as '{pre_restore_name}'."
        )
    except Exception as e:
        messages.error(request, f"Failed to restore backup: {str(e)}")

    return redirect('admin:database_manage')


@superuser_required
def database_delete_backup_view(request, backup_name: str):
    """Deletes a specific backup file from the backups directory."""
    if request.method != 'POST':
        return redirect('admin:database_manage')

    backup_dir = get_backups_dir()
    backup_file = backup_dir / backup_name

    if not backup_file.resolve().is_relative_to(backup_dir.resolve()) or not backup_file.exists():
        messages.error(request, "Backup file not found.")
        return redirect('admin:database_manage')

    try:
        backup_file.unlink()
        messages.success(request, f"Backup file '{backup_name}' deleted successfully.")
    except Exception as e:
        messages.error(request, f"Error deleting backup file: {str(e)}")

    return redirect('admin:database_manage')


@superuser_required
def database_clear_view(request):
    """
    Clears all project, task, and team data from the database while preserving
    the master administrator superuser account (aman). Automatically creates an
    instant pre-clear rollback backup first.
    """
    if request.method != 'POST':
        return redirect('admin:database_manage')

    confirm_text = request.POST.get('confirm_text', '').strip()
    if confirm_text != 'CLEAR':
        messages.error(request, "Database Clear Aborted: Please type 'CLEAR' (all uppercase) to confirm.")
        return redirect('admin:database_manage')

    db_path = get_db_path()
    backup_dir = get_backups_dir()
    pre_clear_name = f"pre_clear_backup_{now().strftime('%Y-%m-%d_%H%M%S')}.sqlite3"

    try:
        # 1. Create an automatic safety rollback backup before purging
        if db_path.exists() and db_path.is_file():
            try:
                shutil.copy2(db_path, backup_dir / pre_clear_name)
            except Exception:
                pass

        # 2. Perform atomic purge of records
        with transaction.atomic():
            TaskComment.objects.all().delete()
            TaskAttachment.objects.all().delete()
            TaskDependency.objects.all().delete()
            Task.objects.all().delete()
            Project.objects.all().delete()
            ActivityLog.objects.all().delete()
            TeamMembership.objects.all().delete()
            Team.objects.all().delete()
            Department.objects.all().delete()

            # Optional: Remove other created team users if requested
            if request.POST.get('remove_non_admin_users') == '1':
                User.objects.exclude(username='aman').delete()

            # Ensure master admin 'aman' is preserved and active
            admin_user, _ = User.objects.get_or_create(
                username='aman',
                defaults={
                    'email': 'aman@milestonemanagement.local',
                    'first_name': 'Aman',
                    'last_name': 'Admin',
                    'is_staff': True,
                    'is_superuser': True,
                    'is_active': True,
                }
            )
            admin_user.is_staff = True
            admin_user.is_superuser = True
            admin_user.save()

        messages.success(
            request,
            f"🧹 Database cleared successfully! All projects, tasks, and teams have been purged cleanly. "
            f"Master administrator 'aman' is preserved. "
            f"An automatic safety rollback backup was saved as '{pre_clear_name}'."
        )
    except Exception as e:
        messages.error(request, f"Error clearing database: {str(e)}")

    return redirect('admin:database_manage')


@superuser_required
def database_seed_teams_view(request):
    """Initializes the demo organization team hierarchy structure."""
    if request.method != 'POST':
        return redirect('admin:database_manage')
    try:
        call_command('seed_teams')
        messages.success(request, "🌱 Demo Team structure initialized successfully (Sundar Nadar as lead with direct reports)!")
    except Exception as e:
        messages.error(request, f"Error seeding team structure: {str(e)}")
    return redirect('admin:database_manage')


@superuser_required
def database_seed_projects_view(request):
    """Initializes the demo Indian Standard (INR ₹) project schedules."""
    if request.method != 'POST':
        return redirect('admin:database_manage')
    try:
        call_command('seed_data')
        messages.success(request, "🌱 Sample Indian Standard (INR ₹) projects, tasks, and budgets seeded successfully!")
    except Exception as e:
        messages.error(request, f"Error seeding projects: {str(e)}")
    return redirect('admin:database_manage')

