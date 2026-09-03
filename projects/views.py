import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import date
from django.db import transaction

from projects.models import (
    Project, ProjectMember, Task, TaskDependency,
    ProjectStatus, TaskStatus, TaskPriority, DependencyType, ProjectRole, ActivityLog
)
from teams.models import Department, Team, TeamMembership, UserProfile, RoleChoices, ApprovalStatus
from teams.forms import UserRegistrationForm


def pending_approval_view(request):
    """Friendly landing screen for newly registered applicants awaiting admin provisioning."""
    username = request.GET.get('username', '')
    return render(request, 'auth/pending_approval.html', {'pending_username': username})


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                f"Registration request for '{user.get_full_name() or user.username}' (@{user.username}) submitted successfully! "
                f"Your account is in 'Pending Approval' state and awaiting provisioning by system administrator @aman. "
                f"You will be able to log in once approved."
            )
            return redirect(f'/pending-approval/?username={user.username}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.replace('_', ' ').capitalize()}: {error}")
    else:
        form = UserRegistrationForm()
    
    return render(request, 'auth/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            profile = getattr(user, 'profile', None)
            is_aman = (user.username.lower() == 'aman')

            # Master admin bypass
            if is_aman:
                login(request, user)
                messages.success(request, f"Welcome back, Master Administrator {user.get_full_name() or user.username}!")
                next_url = request.GET.get('next', 'admin_panel')
                return redirect(next_url)

            # Check profile status
            if profile and profile.status == ApprovalStatus.REJECTED:
                messages.error(request, "Your account registration was not approved. Please contact system administrator @aman.")
                return render(request, 'auth/login.html', {'form': form})

            if not user.is_active or (profile and profile.status == ApprovalStatus.PENDING):
                return redirect(f'/pending-approval/?username={user.username}')

            login(request, user)
            messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
        else:
            username_attempt = request.POST.get('username', '').strip()
            user_exists = User.objects.filter(username__iexact=username_attempt).first()
            if user_exists and user_exists.check_password(request.POST.get('password', '')):
                profile = getattr(user_exists, 'profile', None)
                if profile and profile.status == ApprovalStatus.REJECTED:
                    messages.error(request, "Your account registration was not approved. Please contact system administrator @aman.")
                elif not user_exists.is_active or (profile and profile.status == ApprovalStatus.PENDING):
                    return redirect(f'/pending-approval/?username={user_exists.username}')
                else:
                    messages.error(request, "Invalid username or password.")
            else:
                messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()

    return render(request, 'auth/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')


@login_required
def change_password_view(request):
    """Allows authenticated users to securely change their own password from the app."""
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.content_type == 'application/json' or
        request.POST.get('format') == 'json' or
        'application/json' in request.headers.get('accept', '')
    )

    if request.method == 'POST':
        data = request.POST.copy()
        if request.content_type == 'application/json':
            try:
                body_data = json.loads(request.body)
                data = body_data
            except Exception:
                data = {}

        # Handle alias key variations
        if 'new_password' in data and 'new_password1' not in data:
            data['new_password1'] = data['new_password']
        if 'confirm_password' in data and 'new_password2' not in data:
            data['new_password2'] = data['confirm_password']
        if 'current_password' in data and 'old_password' not in data:
            data['old_password'] = data['current_password']

        form = PasswordChangeForm(user=request.user, data=data)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            success_msg = "Your password has been changed successfully!"
            if is_ajax:
                return JsonResponse({'status': 'success', 'message': success_msg})
            messages.success(request, success_msg)
            next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard'
            return redirect(next_url)
        else:
            errors = []
            for field, err_list in form.errors.items():
                for err in err_list:
                    errors.append(str(err))
            error_msg = " ".join(errors) if errors else "Password change failed. Please check your inputs."
            if is_ajax:
                return JsonResponse({
                    'status': 'error',
                    'message': error_msg,
                    'errors': form.errors.get_json_data()
                }, status=400)
            messages.error(request, error_msg)
            return render(request, 'auth/change_password.html', {'form': form})
    else:
        form = PasswordChangeForm(user=request.user)
        return render(request, 'auth/change_password.html', {'form': form})


@login_required
def dashboard_view(request):
    projects = Project.objects.all().select_related('owner').prefetch_related('tasks').order_by('-updated_at')
    
    total_projects = projects.count()
    active_projects = projects.filter(status=ProjectStatus.ACTIVE).count()
    completed_projects = projects.filter(status=ProjectStatus.COMPLETED).count()
    
    # User's assigned tasks
    my_tasks = Task.objects.filter(
        assignee=request.user
    ).select_related('project').order_by('end_date')[:10]

    all_users = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('username')
    
    context = {
        'projects': projects,
        'total_projects': total_projects,
        'active_projects': active_projects,
        'completed_projects': completed_projects,
        'my_tasks': my_tasks,
        'all_users': all_users,
        'project_statuses': ProjectStatus.choices,
        'statuses': ProjectStatus.choices
    }
    return render(request, 'projects/dashboard.html', context)


@login_required
def project_gantt_view(request, code):
    project = get_object_or_404(Project, code=code)
    
    # Exclude master admin aman from task assignees
    all_users = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')
    all_projects = Project.objects.all().order_by('name')
    
    context = {
        'project': project,
        'all_projects': all_projects,
        'all_users': all_users,
        'statuses': TaskStatus.choices,
        'priorities': TaskPriority.choices,
        'dep_types': DependencyType.choices,
    }
    return render(request, 'projects/gantt_view.html', context)


@login_required
@require_POST
def create_project_view(request):
    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    budget = request.POST.get('budget', '0')
    start_date = request.POST.get('start_date') or date.today().isoformat()
    end_date = request.POST.get('end_date') or date.today().isoformat()
    status = request.POST.get('status', '').strip() or ProjectStatus.PLANNING

    valid_statuses = dict(ProjectStatus.choices)
    if status not in valid_statuses:
        status = ProjectStatus.PLANNING

    if not name:
        messages.error(request, "Project name is required.")
        return redirect('dashboard')

    owner = request.user

    with transaction.atomic():
        project = Project.objects.create(
            name=name,
            description=description,
            budget=budget,
            start_date=start_date,
            end_date=end_date,
            owner=owner,
            status=status
        )

        if owner.username.lower() != 'aman':
            ProjectMember.objects.get_or_create(
                project=project,
                user=owner,
                defaults={'role': ProjectRole.ADMIN}
            )

    messages.success(request, f"Project '{project.name}' created successfully!")
    return redirect('project_gantt', code=project.code)


# =========================================================================
# TEAM & USER MANAGEMENT / GOVERNANCE VIEWS (Add, Edit, Approve, Provision, Delete)
# =========================================================================

@login_required
def team_management_view(request):
    """Admin User Governance, Approval Queue & Provisioning Dashboard."""
    users = User.objects.all().order_by('-date_joined')
    
    user_list = []
    pending_approval_list = []
    unassigned_dept_count = 0
    no_team_count = 0
    pending_onboarding_count = 0
    pending_approval_count = 0
    active_roles_count = 0

    for u in users:
        tasks = Task.objects.filter(assignee=u)
        total_tasks = tasks.count()
        active_tasks = tasks.filter(status__in=['NOT_STARTED', 'IN_PROGRESS', 'DELAYED']).count()
        completed_tasks = tasks.filter(status='COMPLETE').count()
        total_hours = sum(t.estimated_hours for t in tasks)
        actual_hours = sum(t.actual_hours for t in tasks)

        # Retrieve primary team membership
        membership = TeamMembership.objects.filter(user=u).select_related('team', 'team__department', 'reporting_to').first()
        is_aman = (u.username.lower() == 'aman')
        
        team = membership.team if membership else None
        department = team.department if (team and team.department) else None
        reporting_to = membership.reporting_to if membership else None

        is_approved = u.is_active
        is_pending_approval = (not u.is_active) and (not is_aman)
        needs_dept = (not is_aman) and (department is None) and is_approved
        has_no_team = (not is_aman) and (team is None) and is_approved
        is_pending = (needs_dept or has_no_team or is_pending_approval) and (not is_aman)

        if is_pending_approval:
            role_title = 'Pending Approval'
            pending_approval_count += 1
        elif is_aman:
            role_title = 'Master Admin'
        elif membership:
            role_title = membership.role
        else:
            role_title = 'Unassigned'

        if needs_dept:
            unassigned_dept_count += 1
        if has_no_team:
            no_team_count += 1
        if is_pending and not is_aman:
            pending_onboarding_count += 1
        if is_approved and not is_aman and not has_no_team and not needs_dept:
            active_roles_count += 1

        initials = (u.first_name[:1] + u.last_name[:1]).upper() if u.first_name and u.last_name else u.username[:2].upper()

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
            'team': team,
            'team_id': team.id if team else '',
            'team_name': team.name if team else 'No Team',
            'department': department,
            'department_id': department.id if department else '',
            'department_name': department.name if department else 'Unassigned',
            'role_title': role_title,
            'role_code': membership.role if membership else 'Member',
            'reporting_to': reporting_to,
            'reporting_to_id': reporting_to.id if reporting_to else '',
            'reporting_to_name': (reporting_to.get_full_name() or reporting_to.username) if reporting_to else 'None',
            'total_tasks': total_tasks,
            'active_tasks': active_tasks,
            'completed_tasks': completed_tasks,
            'estimated_hours': total_hours,
            'actual_hours': actual_hours,
            'is_aman': is_aman,
            'needs_dept': needs_dept,
            'no_team': has_no_team,
            'is_pending': is_pending,
            'date_joined': u.date_joined
        }
        user_list.append(user_data)
        if is_pending_approval:
            pending_approval_list.append(user_data)

    all_departments = Department.objects.all().order_by('name')
    all_teams = Team.objects.all().order_by('name')
    potential_managers = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')

    context = {
        'team_users': user_list,
        'pending_approvals': pending_approval_list,
        'total_members': len(user_list),
        'pending_approval_count': pending_approval_count,
        'unassigned_dept_count': unassigned_dept_count,
        'no_team_count': no_team_count,
        'pending_onboarding_count': pending_onboarding_count,
        'active_roles_count': active_roles_count,
        'all_departments': all_departments,
        'all_teams': all_teams,
        'role_choices': TeamMembership.ROLE_CHOICES,
        'potential_managers': potential_managers,
        'is_admin_user': request.user.is_superuser or request.user.username.lower() == 'aman',
    }
    return render(request, 'users/team_management.html', context)


@login_required
@require_POST
def create_team_user_view(request):
    """Creates a new user and provisions Department, Team, Role, and Reporting Line."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can create and provision users.")
        return redirect('team_management')

    username = request.POST.get('username', '').strip().lower()
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    email = request.POST.get('email', '').strip()
    password = request.POST.get('password', '').strip() or '123456'
    
    department_id = request.POST.get('department_id')
    team_id = request.POST.get('team_id')
    role = request.POST.get('role', 'Member')
    reporting_to_id = request.POST.get('reporting_to_id')

    if not username:
        messages.error(request, "User ID / Username is required.")
        return redirect('team_management')

    if username == 'aman':
        messages.error(request, "Username 'aman' is reserved for system administration.")
        return redirect('team_management')

    if User.objects.filter(username__iexact=username).exists():
        messages.error(request, f"User with username '@{username}' already exists.")
        return redirect('team_management')

    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_active=True
        )

        # Handle team and reporting manager assignment
        if team_id:
            team = Team.objects.filter(id=team_id).first()
            if team:
                reporting_user = None
                if role not in ('GM', 'General Manager') and reporting_to_id:
                    reporting_user = User.objects.filter(id=reporting_to_id).exclude(username__iexact='aman').first()
                
                TeamMembership.objects.create(
                    team=team,
                    user=user,
                    role=role,
                    reporting_to=reporting_user
                )

        # Enroll in active projects (excluding aman)
        for p in Project.objects.all():
            ProjectMember.objects.get_or_create(project=p, user=user, defaults={'role': ProjectRole.MEMBER})

    messages.success(request, f"User '{user.get_full_name() or user.username}' (@{user.username}) created and provisioned successfully.")
    return redirect('team_management')


@login_required
@require_POST
def approve_team_user_view(request, user_id):
    """Approves a pending user account and provisions Department, Team, 3-Tier Role, and Reporting line."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can approve user accounts.")
        return redirect('team_management')

    user = get_object_or_404(User, id=user_id)
    if user.username.lower() == 'aman':
        messages.error(request, "Cannot alter master administrator status.")
        return redirect('team_management')

    department_id = request.POST.get('department_id')
    team_id = request.POST.get('team_id')
    role_input = request.POST.get('role', 'TM')
    reporting_to_id = request.POST.get('reporting_to_id')

    # Map role input to RoleChoices (GM, MGR, TM)
    if role_input in ('GM', 'General Manager'):
        role_choice = RoleChoices.GENERAL_MANAGER
    elif role_input in ('MGR', 'Manager', 'Lead', 'Team Lead / Manager', 'Tech Lead'):
        role_choice = RoleChoices.MANAGER
    else:
        role_choice = RoleChoices.TEAM_MEMBER

    with transaction.atomic():
        user.is_active = True
        user.save()

        dept = Department.objects.filter(id=department_id).first() if department_id else None
        reporting_user = None
        if role_choice != RoleChoices.GENERAL_MANAGER and reporting_to_id:
            reporting_user = User.objects.filter(id=reporting_to_id).exclude(username__iexact='aman').exclude(id=user.id).first()

        # Update UserProfile (3-Tier Authority Source)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role_choice
        profile.status = ApprovalStatus.ACTIVE
        profile.department = dept
        profile.reporting_to = reporting_user
        profile.save()

        # Only assign team if explicitly provided in request
        if team_id:
            team = Team.objects.filter(id=team_id).first()
            if team:
                if dept and not team.department:
                    team.department = dept
                    team.save()

                membership, _ = TeamMembership.objects.get_or_create(team=team, user=user)
                membership.role = role_choice
                membership.reporting_to = reporting_user
                membership.save()
                TeamMembership.objects.filter(user=user).exclude(id=membership.id).delete()

        # Enroll in projects if not already member
        for p in Project.objects.all():
            ProjectMember.objects.get_or_create(project=p, user=user, defaults={'role': ProjectRole.MEMBER})

    messages.success(
        request,
        f"User '{user.get_full_name() or user.username}' (@{user.username}) approved as {profile.get_role_display()} and activated successfully!"
    )
    return redirect('team_management')


@login_required
@require_POST
def toggle_team_user_status_view(request, user_id):
    """Toggles active/inactive status of a user."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can alter user activation status.")
        return redirect('team_management')

    user = get_object_or_404(User, id=user_id)
    if user.username.lower() == 'aman':
        messages.error(request, "Cannot alter master administrator status.")
        return redirect('team_management')

    user.is_active = not user.is_active
    user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.status = ApprovalStatus.ACTIVE if user.is_active else ApprovalStatus.PENDING
    profile.save(update_fields=['status'])

    status_str = "Activated" if user.is_active else "Deactivated / Pending Approval"
    messages.success(request, f"User @{user.username} account status set to: {status_str}.")
    return redirect('team_management')


@login_required
@require_POST
def reject_team_user_view(request, user_id):
    """Rejects/Deletes a pending user registration request."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can reject user accounts.")
        return redirect('team_management')

    user = get_object_or_404(User, id=user_id)
    if user.username.lower() == 'aman':
        messages.error(request, "Cannot delete master administrator account.")
        return redirect('team_management')

    username = user.username
    full_name = user.get_full_name() or username
    user.delete()
    messages.info(request, f"Registration request for '{full_name}' (@{username}) was rejected and removed.")
    return redirect('team_management')


@login_required
@require_POST
def edit_team_user_view(request, user_id):
    """Provisions or updates an existing team member's details, department, team, role, and reporting manager."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can assign roles, departments, or reporting lines.")
        return redirect('team_management')

    user = get_object_or_404(User, id=user_id)
    
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    email = request.POST.get('email', '').strip()
    new_password = request.POST.get('new_password', '').strip()
    is_active_flag = request.POST.get('is_active')
    
    department_id = request.POST.get('department_id')
    team_id = request.POST.get('team_id')
    role_input = request.POST.get('role', 'TM')
    reporting_to_id = request.POST.get('reporting_to_id')

    if user.username.lower() == 'aman':
        # Master user protection
        user.first_name = first_name or 'Aman'
        user.last_name = last_name or 'Admin'
        user.email = email or 'aman@milestonemanagement.local'
        if new_password:
            user.set_password(new_password)
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save()
        messages.success(request, "Master administrator 'aman' profile updated.")
        return redirect('team_management')

    # Map role input to RoleChoices
    if role_input in ('GM', 'General Manager'):
        role_choice = RoleChoices.GENERAL_MANAGER
    elif role_input in ('MGR', 'Manager', 'Lead', 'Team Lead / Manager', 'Tech Lead'):
        role_choice = RoleChoices.MANAGER
    else:
        role_choice = RoleChoices.TEAM_MEMBER

    with transaction.atomic():
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        if new_password:
            user.set_password(new_password)
        if is_active_flag is not None:
            user.is_active = (is_active_flag == '1' or is_active_flag == 'true' or is_active_flag == 'on')
        user.save()

        dept = Department.objects.filter(id=department_id).first() if department_id else None
        reporting_user = None
        if role_choice != RoleChoices.GENERAL_MANAGER and reporting_to_id:
            reporting_user = User.objects.filter(id=reporting_to_id).exclude(username__iexact='aman').exclude(id=user.id).first()

        # Update UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role_choice
        profile.department = dept
        profile.reporting_to = reporting_user
        profile.status = ApprovalStatus.ACTIVE if user.is_active else ApprovalStatus.PENDING
        profile.save()

        # Update Team Membership & Reporting Line
        if team_id:
            team = Team.objects.filter(id=team_id).first()
            if team:
                if dept and not team.department:
                    team.department = dept
                    team.save()

                membership, _ = TeamMembership.objects.get_or_create(team=team, user=user)
                membership.role = role_choice
                membership.reporting_to = reporting_user
                membership.save()
                TeamMembership.objects.filter(user=user).exclude(id=membership.id).delete()
        else:
            # Removed from team if team_id explicitly cleared
            TeamMembership.objects.filter(user=user).delete()

    messages.success(request, f"Updated profile and 3-tier organizational allocation for '{user.get_full_name() or user.username}'.")
    return redirect('team_management')


@login_required
@require_POST
def delete_team_user_view(request, user_id):
    """Safely deletes a team member, reassigning their tasks to Unassigned."""
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can delete user accounts.")
        return redirect('team_management')

    user_to_delete = get_object_or_404(User, id=user_id)

    # Protect master admin
    if user_to_delete.username.lower() == 'aman':
        messages.error(request, "Cannot delete master administrator account 'aman'.")
        return redirect('team_management')

    if user_to_delete == request.user:
        messages.error(request, "You cannot delete your own currently logged-in account.")
        return redirect('team_management')

    username = user_to_delete.username
    full_name = user_to_delete.get_full_name() or username

    with transaction.atomic():
        # Unassign tasks before deletion to preserve tasks
        Task.objects.filter(assignee=user_to_delete).update(assignee=None)
        TeamMembership.objects.filter(reporting_to=user_to_delete).update(reporting_to=None)
        TeamMembership.objects.filter(user=user_to_delete).delete()
        ProjectMember.objects.filter(user=user_to_delete).delete()
        user_to_delete.delete()

    messages.success(request, f"User '{full_name}' (@{username}) was successfully removed.")
    return redirect('team_management')
