from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction

from teams.models import Department, Team, TeamMembership
from teams.forms import DepartmentForm, TeamForm, TeamMembershipForm
from projects.models import Project, Task


@login_required
def team_hierarchy_view(request):
    """
    Main Team Manager dashboard featuring:
    1. MS Teams / Workday style Org Chart View
    2. Interactive Collapsible Tree View
    3. Teams & Resource Directory View
    """
    departments = Department.objects.select_related('parent', 'head').prefetch_related('teams__lead', 'teams__memberships__user').all()
    teams = Team.objects.select_related('department', 'parent_team', 'lead').prefetch_related('memberships__user', 'assigned_projects').all()
    all_users = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')
    total_members = all_users.count()
    total_teams = teams.count()
    total_depts = departments.count()
    total_leads = Team.objects.filter(lead__isnull=False).exclude(lead__username__iexact='aman').values('lead').distinct().count()

    team_form = TeamForm()
    dept_form = DepartmentForm()
    membership_form = TeamMembershipForm()

    context = {
        'departments': departments,
        'teams': teams,
        'all_users': all_users,
        'total_members': total_members,
        'total_teams': total_teams,
        'total_depts': total_depts,
        'total_leads': total_leads,
        'team_form': team_form,
        'dept_form': dept_form,
        'membership_form': membership_form,
        'role_choices': TeamMembership.ROLE_CHOICES,
        'is_admin_user': request.user.is_superuser or request.user.username.lower() == 'aman',
    }
    return render(request, 'teams/team_hierarchy.html', context)


@login_required
def team_detail_view(request, pk):
    """
    Team detail view with member list, reporting hierarchy, sub-teams, and assigned projects.
    """
    team = get_object_or_404(
        Team.objects.select_related('department', 'parent_team', 'lead')
        .prefetch_related('memberships__user', 'memberships__reporting_to', 'sub_teams__lead', 'assigned_projects'),
        pk=pk
    )
    memberships = team.memberships.exclude(user__username__iexact='aman').select_related('user', 'reporting_to').all()
    sub_teams = team.sub_teams.select_related('lead').prefetch_related('memberships').all()
    assigned_projects = team.assigned_projects.all()
    all_users = User.objects.filter(is_active=True).exclude(username__iexact='aman').exclude(team_memberships__team=team).order_by('first_name', 'username')

    context = {
        'team': team,
        'memberships': memberships,
        'sub_teams': sub_teams,
        'assigned_projects': assigned_projects,
        'all_users': all_users,
        'role_choices': TeamMembership.ROLE_CHOICES,
        'is_admin_user': request.user.is_superuser or request.user.username.lower() == 'aman',
    }
    return render(request, 'teams/team_detail.html', context)


@login_required
def team_create_view(request):
    """
    Create a new team via standalone form or modal.
    Only superuser 'aman' has permission to create teams.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can create teams.")
        return redirect('teams:team_hierarchy')

    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save()
            messages.success(request, f"Team '{team.name}' created successfully!")
            return redirect('teams:team_detail', pk=team.pk)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.capitalize()}: {error}")
    else:
        form = TeamForm()

    return render(request, 'teams/team_form.html', {'form': form, 'title': 'Create New Team'})


@login_required
def team_edit_view(request, pk):
    """
    Edit existing team properties.
    Only superuser 'aman' has permission to edit teams.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can edit teams.")
        return redirect('teams:team_hierarchy')

    team = get_object_or_404(Team, pk=pk)
    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            team = form.save()
            messages.success(request, f"Team '{team.name}' updated successfully.")
            return redirect('teams:team_detail', pk=team.pk)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.capitalize()}: {error}")
    else:
        form = TeamForm(instance=team)

    return render(request, 'teams/team_form.html', {'form': form, 'team': team, 'title': f'Edit Team: {team.name}'})


@login_required
@require_POST
def team_delete_view(request, pk):
    """
    Delete a team and reassign/cleanup memberships.
    Only superuser 'aman' has permission to delete teams.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can delete teams.")
        return redirect('teams:team_hierarchy')

    team = get_object_or_404(Team, pk=pk)
    team_name = team.name
    team.delete()
    messages.success(request, f"Team '{team_name}' was deleted.")
    return redirect('teams:team_hierarchy')


@login_required
@require_POST
def team_member_add_view(request, pk):
    """
    Assign a member to a team with a role and optional reporting manager.
    Only superuser 'aman' has permission to assign roles and members.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can assign members and roles.")
        return redirect('teams:team_detail', pk=pk)

    team = get_object_or_404(Team, pk=pk)
    user_id = request.POST.get('user_id')
    role = request.POST.get('role', 'Member')
    reporting_to_id = request.POST.get('reporting_to_id') or None

    if not user_id:
        messages.error(request, "Please select a user to add.")
        return redirect('teams:team_detail', pk=team.pk)

    user = get_object_or_404(User, pk=user_id)
    if user.username.lower() == 'aman':
        messages.error(request, "Master administrator 'aman' is reserved for system governance only and cannot be assigned to teams.")
        return redirect('teams:team_detail', pk=team.pk)

    if reporting_to_id and User.objects.filter(id=reporting_to_id, username__iexact='aman').exists():
        messages.error(request, "Master administrator 'aman' cannot be set as a reporting manager.")
        return redirect('teams:team_detail', pk=team.pk)

    reporting_to = User.objects.filter(pk=reporting_to_id).exclude(username__iexact='aman').first() if reporting_to_id else None
    if role == 'GM':
        reporting_to = None

    membership, created = TeamMembership.objects.get_or_create(
        team=team,
        user=user,
        defaults={
            'role': role,
            'reporting_to': reporting_to
        }
    )
    if not created:
        membership.role = role
        membership.reporting_to = reporting_to
        membership.save()
        messages.info(request, f"Updated role for {user.get_full_name() or user.username} in {team.name}.")
    else:
        messages.success(request, f"Added {user.get_full_name() or user.username} to {team.name}.")

    return redirect('teams:team_detail', pk=team.pk)


@login_required
@require_POST
def team_member_remove_view(request, pk, user_id):
    """
    Remove a member from a team.
    Only superuser 'aman' has permission to remove members.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can remove members from teams.")
        return redirect('teams:team_detail', pk=pk)

    team = get_object_or_404(Team, pk=pk)
    membership = get_object_or_404(TeamMembership, team=team, user_id=user_id)
    user_name = membership.user.get_full_name() or membership.user.username
    membership.delete()
    messages.success(request, f"Removed {user_name} from team {team.name}.")
    return redirect('teams:team_detail', pk=team.pk)


@login_required
@require_POST
def department_create_view(request):
    """
    Create a new department.
    Only superuser 'aman' has permission to create departments.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can create departments.")
        return redirect('teams:team_hierarchy')

    form = DepartmentForm(request.POST)
    if form.is_valid():
        dept = form.save()
        messages.success(request, f"Department '{dept.name}' created.")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field.capitalize()}: {error}")
    return redirect('teams:team_hierarchy')


@login_required
@require_POST
def department_delete_view(request, pk):
    """
    Delete a department.
    Only superuser 'aman' has permission to delete departments.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can delete departments.")
        return redirect('teams:team_hierarchy')

    dept = get_object_or_404(Department, pk=pk)
    dept_name = dept.name
    dept.delete()
    messages.success(request, f"Department '{dept_name}' removed.")
    return redirect('teams:team_hierarchy')


@login_required
@require_POST
def seed_demo_teams_view(request):
    """
    One-click action to initialize demo organization hierarchy structure.
    Only superuser 'aman' has permission to seed demo data.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        messages.error(request, "Permission Denied: Only master administrator 'aman' can seed demo structures.")
        return redirect('teams:team_hierarchy')

    from django.core.management import call_command
    try:
        call_command('seed_teams')
        messages.success(request, "🌱 Demo Team structure initialized successfully with Cool Team, Sundar Nadar as lead, and direct reporting hierarchy!")
    except Exception as e:
        messages.error(request, f"Error initializing team structure: {str(e)}")
    return redirect('teams:team_hierarchy')
