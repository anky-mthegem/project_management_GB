import json
from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.core.management import call_command
from django.utils.text import slugify

from projects.models import (
    Project, ProjectMember, Task, ActivityLog, ProjectStatus, ProjectRole
)
from teams.models import Department, Team, TeamMembership
from projects.admin_database import get_database_stats, list_backups


@login_required
def admin_panel_view(request):
    """
    Simplified, unified Master Admin Panel for 'aman' (Superuser).
    Includes:
    - User Approvals & 3-Tier Governance (Instant approve, provision, edit, status toggle)
    - Department & Team Organization
    - Project Portfolio Overview
    - Database Backup, Restore & Maintenance tools
    - System Audit Logs
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Master Admin Panel is restricted to administrator 'aman'.")
        return redirect('dashboard')

    # 1. Users & Approvals
    from teams.models import UserProfile, RoleChoices, ApprovalStatus
    users = User.objects.select_related('profile', 'profile__department', 'profile__reporting_to').all().order_by('-date_joined')
    user_list = []
    pending_approval_list = []
    pending_approval_count = 0
    active_roles_count = 0
    unassigned_dept_count = 0
    no_team_count = 0

    for u in users:
        tasks = Task.objects.filter(assignee=u)
        total_tasks = tasks.count()
        completed_tasks = tasks.filter(status='COMPLETE').count()
        total_hours = sum(t.estimated_hours for t in tasks)
        actual_hours = sum(t.actual_hours for t in tasks)

        profile = getattr(u, 'profile', None)
        membership = TeamMembership.objects.filter(user=u).select_related('team', 'team__department', 'reporting_to').first()
        is_aman = (u.username.lower() == 'aman')

        team = membership.team if membership else None
        department = profile.department if (profile and profile.department) else (team.department if (team and team.department) else None)
        reporting_to = profile.reporting_to if (profile and profile.reporting_to) else (membership.reporting_to if membership else None)

        is_approved = u.is_active and (profile.status == ApprovalStatus.ACTIVE if profile else True)
        is_pending_approval = (not u.is_active) or (profile and profile.status == ApprovalStatus.PENDING)
        is_pending_approval = is_pending_approval and (not is_aman)
        needs_dept = (not is_aman) and (department is None) and is_approved
        has_no_team = (not is_aman) and (team is None) and is_approved
        is_pending = (needs_dept or has_no_team or is_pending_approval) and (not is_aman)

        role_code = profile.role if profile else (membership.role if membership else RoleChoices.TEAM_MEMBER)
        if is_pending_approval:
            role_title = 'Pending Approval'
            pending_approval_count += 1
        elif is_aman:
            role_title = 'Master Admin'
        elif role_code == RoleChoices.GENERAL_MANAGER:
            role_title = 'General Manager (GM)'
        elif role_code == RoleChoices.MANAGER:
            role_title = 'Manager (MGR)'
        elif role_code == RoleChoices.TEAM_MEMBER:
            role_title = 'Team Member (TM)'
        else:
            role_title = profile.get_role_display() if profile else (membership.role if membership else 'Team Member')

        if needs_dept:
            unassigned_dept_count += 1
        if has_no_team:
            no_team_count += 1
        if is_approved and not is_aman:
            active_roles_count += 1

        initials = (u.first_name[:1] + u.last_name[:1]).upper() if u.first_name and u.last_name else u.username[:2].upper()

        clean_dict = {
            'id': u.id,
            'username': u.username,
            'full_name': u.get_full_name() or u.username,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email or '',
            'is_active': u.is_active,
            'is_approved': is_approved,
            'is_pending_approval': is_pending_approval,
            'needs_dept': needs_dept,
            'no_team': has_no_team,
            'is_pending': is_pending,
            'status': profile.status if profile else ('ACTIVE' if u.is_active else 'PENDING_APPROVAL'),
            'team_id': team.id if team else '',
            'team_name': team.name if team else 'No Team',
            'department_id': department.id if department else '',
            'department_name': department.name if department else 'Unassigned',
            'role_title': role_title,
            'role_code': role_code,
            'reporting_to_id': reporting_to.id if reporting_to else '',
            'reporting_to_name': (reporting_to.get_full_name() or reporting_to.username) if reporting_to else 'None',
            'is_aman': is_aman,
        }

        user_data = {
            'id': u.id,
            'user': u,
            'username': u.username,
            'full_name': u.get_full_name() or u.username,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email or 'N/A',
            'initials': initials,
            'is_active': u.is_active,
            'is_approved': is_approved,
            'is_pending_approval': is_pending_approval,
            'status': profile.status if profile else ('ACTIVE' if u.is_active else 'PENDING_APPROVAL'),
            'team': team,
            'team_id': team.id if team else '',
            'team_name': team.name if team else 'No Team',
            'department': department,
            'department_id': department.id if department else '',
            'department_name': department.name if department else 'Unassigned',
            'role_title': role_title,
            'role_code': role_code,
            'reporting_to': reporting_to,
            'reporting_to_id': reporting_to.id if reporting_to else '',
            'reporting_to_name': (reporting_to.get_full_name() or reporting_to.username) if reporting_to else 'None',
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'estimated_hours': total_hours,
            'actual_hours': actual_hours,
            'is_aman': is_aman,
            'needs_dept': needs_dept,
            'no_team': has_no_team,
            'is_pending': is_pending,
            'date_joined': u.date_joined,
            'json_str': json.dumps(clean_dict)
        }
        user_list.append(user_data)
        if is_pending_approval:
            pending_approval_list.append(user_data)

    # 2. Departments & Teams
    departments = Department.objects.select_related('parent', 'head').prefetch_related('teams__lead', 'teams__memberships__user').all()
    teams = Team.objects.select_related('department', 'parent_team', 'lead').prefetch_related('memberships__user', 'assigned_projects').all()
    
    # 3. Projects Portfolio
    projects = Project.objects.select_related('owner').prefetch_related('tasks', 'memberships').order_by('-updated_at')
    project_list = []
    for p in projects:
        t_count = p.tasks.count()
        c_count = p.tasks.filter(status='COMPLETE').count()
        crit_count = p.tasks.filter(is_critical=True).count()
        project_list.append({
            'id': p.id,
            'code': p.code,
            'name': p.name,
            'status': p.status,
            'status_display': p.get_status_display(),
            'progress': p.progress,
            'budget': p.budget,
            'start_date': p.start_date,
            'end_date': p.end_date,
            'owner': p.owner,
            'owner_name': (p.owner.get_full_name() or p.owner.username) if p.owner else 'Unassigned',
            'total_tasks': t_count,
            'completed_tasks': c_count,
            'critical_tasks': crit_count,
            'members_count': p.memberships.count(),
        })

    # 4. Database & Backups
    try:
        db_stats = get_database_stats()
        backups = list_backups()
    except Exception:
        db_stats = None
        backups = []

    # 5. Activity Logs
    recent_logs = ActivityLog.objects.select_related('project', 'user', 'task').order_by('-created_at')[:30]

    potential_managers = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')
    general_managers = [
        {'id': u.id, 'name': u.get_full_name() or u.username, 'username': u.username}
        for u in User.objects.filter(profile__role=RoleChoices.GENERAL_MANAGER, is_active=True).exclude(username__iexact='aman')
    ]
    managers = [
        {'id': u.id, 'name': u.get_full_name() or u.username, 'username': u.username}
        for u in User.objects.filter(profile__role=RoleChoices.MANAGER, is_active=True).exclude(username__iexact='aman')
    ]

    tier_role_choices = [
        ('GM', 'General Manager (GM)'),
        ('MGR', 'Manager (MGR)'),
        ('TM', 'Team Member (TM)'),
    ]

    context = {
        'team_users': user_list,
        'pending_approvals': pending_approval_list,
        'total_members': len(user_list),
        'pending_approval_count': pending_approval_count,
        'active_roles_count': active_roles_count,
        'unassigned_dept_count': unassigned_dept_count,
        'no_team_count': no_team_count,
        
        'departments': departments,
        'teams': teams,
        'projects': project_list,
        'total_projects': len(project_list),
        'db_stats': db_stats,
        'backups': backups,
        'recent_logs': recent_logs,
        
        'role_choices': tier_role_choices,
        'potential_managers': potential_managers,
        'general_managers': general_managers,
        'managers': managers,
        'is_admin_user': True,
    }
    return render(request, 'admin/simplified_admin_panel.html', context)


@login_required
@require_POST
def admin_create_department_view(request):
    """Creates a new Department."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master admin can create departments.")
        return redirect('admin_panel')

    name = request.POST.get('name', '').strip()
    raw_code = request.POST.get('code', '').strip() or name
    code = slugify(raw_code)[:50] or 'dept'
    head_id = request.POST.get('head_id')
    parent_id = request.POST.get('parent_id')

    if not name:
        messages.error(request, "Department name is required.")
        return redirect('admin_panel')

    head_user = None
    if head_id:
        head_user = User.objects.filter(id=head_id).exclude(username__iexact='aman').first()

    parent_dept = None
    if parent_id:
        parent_dept = Department.objects.filter(id=parent_id).first()

    Department.objects.create(
        name=name,
        code=code,
        head=head_user,
        parent=parent_dept
    )
    messages.success(request, f"Department '{name}' created successfully.")
    return redirect('admin_panel')


@login_required
@require_POST
def admin_create_team_view(request):
    """Creates a new Team."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master admin can create teams.")
        return redirect('admin_panel')

    name = request.POST.get('name', '').strip()
    raw_code = request.POST.get('code', '').strip() or name
    code = slugify(raw_code)[:50] or 'team'
    department_id = request.POST.get('department_id')
    lead_id = request.POST.get('lead_id')
    description = request.POST.get('description', '').strip()

    if not name:
        messages.error(request, "Team name is required.")
        return redirect('admin_panel')

    dept = Department.objects.filter(id=department_id).first() if department_id else None
    lead_user = User.objects.filter(id=lead_id).exclude(username__iexact='aman').first() if lead_id else None

    with transaction.atomic():
        team = Team.objects.create(
            name=name,
            code=code,
            department=dept,
            lead=lead_user,
            description=description
        )

        if lead_user:
            TeamMembership.objects.get_or_create(
                team=team,
                user=lead_user,
                defaults={'role': 'Lead', 'reporting_to': None}
            )

    messages.success(request, f"Team '{name}' created successfully.")
    return redirect('admin_panel')


@login_required
@require_POST
def admin_seed_teams_view(request):
    """Re-seeds demo teams ('Cool Team' with psundar, skhande, smali, amanr)."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master admin can seed data.")
        return redirect('admin_panel')

    call_command('seed_teams')
    messages.success(request, "Demo team structure ('Cool Team') re-seeded successfully.")
    return redirect('admin_panel')


@login_required
@require_POST
def admin_seed_projects_view(request):
    """Re-seeds demo projects and tasks."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master admin can seed data.")
        return redirect('admin_panel')

    call_command('seed_data')
    messages.success(request, "Demo projects and Gantt tasks re-seeded successfully.")
    return redirect('admin_panel')
