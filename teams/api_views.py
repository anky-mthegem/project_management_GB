from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_protect
from collections import defaultdict
import json

from teams.models import Department, Team, TeamMembership


def get_user_avatar_initials(user):
    if user.first_name and user.last_name:
        return (user.first_name[0] + user.last_name[0]).upper()
    elif user.first_name:
        return user.first_name[:2].upper()
    return user.username[:2].upper()


@login_required
@require_GET
def team_hierarchy_api(request):
    """
    Returns full nested Department & Team hierarchy with lead, member rosters, and project counts.
    Explicitly excludes master administrative user 'aman'.
    """
    departments = Department.objects.select_related('parent', 'head').prefetch_related('teams__lead', 'teams__memberships__user').all()
    standalone_teams = Team.objects.filter(department__isnull=True).select_related('lead', 'parent_team').prefetch_related('memberships__user')

    dept_tree = []
    dept_map = {}

    for d in departments:
        head_data = None
        if d.head and d.head.username != 'aman':
            head_data = {
                'id': d.head.id,
                'username': d.head.username,
                'name': d.head.get_full_name() or d.head.username,
                'initials': get_user_avatar_initials(d.head),
                'email': d.head.email
            }
        
        dept_data = {
            'id': d.id,
            'name': d.name,
            'code': d.code,
            'description': d.description,
            'head': head_data,
            'teams': [],
            'sub_departments': []
        }
        dept_map[d.id] = dept_data

    # Populate teams inside departments
    for d in departments:
        for t in d.teams.all():
            lead_data = None
            if t.lead and t.lead.username != 'aman':
                lead_data = {
                    'id': t.lead.id,
                    'username': t.lead.username,
                    'name': t.lead.get_full_name() or t.lead.username,
                    'initials': get_user_avatar_initials(t.lead),
                    'email': t.lead.email
                }
            members_list = [
                {
                    'id': m.user.id,
                    'membership_id': m.id,
                    'username': m.user.username,
                    'name': m.user.get_full_name() or m.user.username,
                    'role': m.role,
                    'initials': get_user_avatar_initials(m.user),
                    'email': m.user.email,
                    'reporting_to': m.reporting_to.get_full_name() if (m.reporting_to and m.reporting_to.username != 'aman') else None,
                    'reporting_to_id': m.reporting_to_id if (m.reporting_to and m.reporting_to.username != 'aman') else None
                }
                for m in t.memberships.select_related('user', 'reporting_to').all()
                if m.user.username != 'aman'
            ]
            
            dept_map[d.id]['teams'].append({
                'id': t.id,
                'name': t.name,
                'code': t.code,
                'description': t.description,
                'color': t.color,
                'parent_team_id': t.parent_team_id,
                'lead': lead_data,
                'members_count': len(members_list),
                'members': members_list,
                'projects_count': t.assigned_projects.count() if hasattr(t, 'assigned_projects') else 0
            })

    # Assemble nested departments
    for d in departments:
        if d.parent_id and d.parent_id in dept_map:
            dept_map[d.parent_id]['sub_departments'].append(dept_map[d.id])
        else:
            dept_tree.append(dept_map[d.id])

    # Standalone teams (no department)
    standalone_data = []
    for t in standalone_teams:
        lead_data = None
        if t.lead and t.lead.username != 'aman':
            lead_data = {
                'id': t.lead.id,
                'username': t.lead.username,
                'name': t.lead.get_full_name() or t.lead.username,
                'initials': get_user_avatar_initials(t.lead),
                'email': t.lead.email
            }
        members_list = [
            {
                'id': m.user.id,
                'membership_id': m.id,
                'username': m.user.username,
                'name': m.user.get_full_name() or m.user.username,
                'role': m.role,
                'initials': get_user_avatar_initials(m.user),
                'email': m.user.email,
                'reporting_to': m.reporting_to.get_full_name() if (m.reporting_to and m.reporting_to.username != 'aman') else None,
                'reporting_to_id': m.reporting_to_id if (m.reporting_to and m.reporting_to.username != 'aman') else None
            }
            for m in t.memberships.select_related('user', 'reporting_to').all()
            if m.user.username != 'aman'
        ]
        standalone_data.append({
            'id': t.id,
            'name': t.name,
            'code': t.code,
            'description': t.description,
            'color': t.color,
            'parent_team_id': t.parent_team_id,
            'lead': lead_data,
            'members_count': len(members_list),
            'members': members_list,
            'projects_count': t.assigned_projects.count() if hasattr(t, 'assigned_projects') else 0
        })

    return JsonResponse({
        'departments': dept_tree,
        'standalone_teams': standalone_data
    })


@login_required
@login_required
@require_GET
def org_chart_api(request):
    """
    Returns personnel reporting hierarchy formatted for MS Teams / Workday Org Chart cards.
    Adheres strictly to the 3-Tier Hierarchy (GM -> MGR -> TM).
    Master user 'aman' is strictly excluded from organization teams and org chart.
    """
    from teams.models import UserProfile, RoleChoices, ApprovalStatus
    users = list(User.objects.filter(is_active=True).exclude(username__iexact='aman').select_related('profile', 'profile__department', 'profile__reporting_to').order_by('first_name', 'username'))
    memberships = list(TeamMembership.objects.filter(user__is_active=True).exclude(user__username__iexact='aman').select_related('team', 'team__department', 'user', 'reporting_to').all())
    
    # Map user to their primary team membership
    user_team_map = {}
    for m in memberships:
        if m.user_id not in user_team_map or m.role in ('GM', 'MGR', 'Lead', 'Tech Lead', 'Manager'):
            user_team_map[m.user_id] = m

    # Count direct reports for each user
    direct_reports_count_map = defaultdict(int)
    for u in users:
        p = getattr(u, 'profile', None)
        if p and p.reporting_to_id and p.reporting_to and p.reporting_to.username.lower() != 'aman':
            direct_reports_count_map[p.reporting_to_id] += 1
        elif u.id in user_team_map:
            m = user_team_map[u.id]
            if m.reporting_to_id and m.reporting_to and m.reporting_to.username.lower() != 'aman':
                direct_reports_count_map[m.reporting_to_id] += 1

    # Build node list
    nodes = []
    for u in users:
        p = getattr(u, 'profile', None)
        m = user_team_map.get(u.id)
        has_team = bool(m and m.team)
        team_name = m.team.name if has_team else 'Unassigned'
        team_id = m.team.id if has_team else None
        dept_name = p.department.name if (p and p.department) else ((m.team.department.name if m.team.department else 'General Operations') if has_team else 'Unassigned')
        
        role_code = p.role if p else (m.role if m else RoleChoices.TEAM_MEMBER)
        if role_code == RoleChoices.GENERAL_MANAGER:
            role_name = 'General Manager (GM)'
            tier_level = 1
            tier_badge = 'GM'
            color = '#8b5cf6'  # Purple
        elif role_code == RoleChoices.MANAGER:
            role_name = 'Manager (MGR)'
            tier_level = 2
            tier_badge = 'MGR'
            color = '#3b82f6'  # Blue
        else:
            role_name = 'Team Member (TM)'
            tier_level = 3
            tier_badge = 'TM'
            color = '#10b981' if has_team else '#94a3b8'  # Emerald / Slate

        manager_id = p.reporting_to_id if (p and p.reporting_to_id and p.reporting_to and p.reporting_to.username.lower() != 'aman') else (m.reporting_to_id if (m and m.reporting_to_id and m.reporting_to and m.reporting_to.username.lower() != 'aman') else None)
        is_lead = (tier_level <= 2) or bool(m and m.team and m.team.lead_id == u.id)

        nodes.append({
            'id': u.id,
            'username': u.username,
            'name': u.get_full_name() or u.username,
            'email': u.email or f"{u.username}@company.local",
            'role': role_name,
            'role_code': role_code,
            'tier_level': tier_level,
            'tier_badge': tier_badge,
            'team_name': team_name,
            'team_id': team_id,
            'department_name': dept_name,
            'color': color,
            'initials': get_user_avatar_initials(u),
            'parent_id': manager_id,
            'direct_reports_count': direct_reports_count_map[u.id],
            'has_team': has_team,
            'is_lead': is_lead,
            'is_master': False
        })

    return JsonResponse({
        'nodes': nodes,
        'total_count': len(nodes)
    })


@login_required
@require_POST
@csrf_protect
def update_reporting_api(request):
    """
    AJAX endpoint to update direct reporting line for a team member.
    Enforces 3-tier rules (MGR -> GM, TM -> MGR).
    Only superuser / 'aman' has permission to update reporting lines.
    """
    if not (request.user.is_superuser or request.user.username.lower() == 'aman'):
        return JsonResponse({'status': 'error', 'message': "Permission Denied: Only master administrator 'aman' can update reporting lines."}, status=403)

    try:
        from teams.models import UserProfile, RoleChoices
        data = json.loads(request.body)
        user_id = data.get('user_id')
        reporting_to_id = data.get('reporting_to_id')

        if not user_id:
            return JsonResponse({'status': 'error', 'message': 'user_id is required'}, status=400)

        user = User.objects.filter(id=user_id).first()
        if not user or user.username.lower() == 'aman':
            return JsonResponse({'status': 'error', 'message': 'Invalid user or administrative user cannot be modified.'}, status=400)

        if user_id == reporting_to_id:
            return JsonResponse({'status': 'error', 'message': 'A member cannot report to themselves.'}, status=400)

        if reporting_to_id and User.objects.filter(id=reporting_to_id, username__iexact='aman').exists():
            return JsonResponse({'status': 'error', 'message': "Master administrator 'aman' cannot be assigned as a reporting manager."}, status=400)

        manager = User.objects.filter(id=reporting_to_id).exclude(username__iexact='aman').first() if reporting_to_id else None

        # 3-Tier validation check
        user_prof, _ = UserProfile.objects.get_or_create(user=user)
        if manager:
            mgr_prof = getattr(manager, 'profile', None)
            if user_prof.role == RoleChoices.MANAGER and mgr_prof and mgr_prof.role != RoleChoices.GENERAL_MANAGER:
                return JsonResponse({'status': 'error', 'message': "3-Tier Rule: A Manager (MGR) can only report directly to a General Manager (GM)."}, status=400)
            if user_prof.role == RoleChoices.TEAM_MEMBER and mgr_prof and mgr_prof.role not in (RoleChoices.MANAGER, RoleChoices.GENERAL_MANAGER):
                return JsonResponse({'status': 'error', 'message': "3-Tier Rule: A Team Member (TM) must report to a Manager (MGR)."}, status=400)

        user_prof.reporting_to = manager
        user_prof.save()

        TeamMembership.objects.filter(user_id=user_id).update(reporting_to=manager)

        return JsonResponse({
            'status': 'success',
            'message': f'Reporting line updated successfully for {user.get_full_name() or user.username}.'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
