from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.messages.storage.fallback import FallbackStorage
import json

from teams.models import Department, Team, TeamMembership
from projects.models import Project, Task, ProjectMember
from teams.forms import UserRegistrationForm
from projects.views import (
    register_view, login_view, approve_team_user_view, toggle_team_user_status_view, reject_team_user_view
)


class TeamManagerTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='aman',
            email='aman@example.com',
            password='password123'
        )
        self.manager_user = User.objects.create_user(
            username='psundar',
            first_name='Sundar',
            last_name='Nadar',
            email='psundar@godrej.com',
            password='password123'
        )
        self.dev_user = User.objects.create_user(
            username='skhande',
            first_name='Suraj',
            last_name='Hande',
            email='skhande@godrej.com',
            password='password123'
        )
        # Configure 3-Tier roles for test users
        from teams.models import UserProfile, RoleChoices, ApprovalStatus
        p_mgr, _ = UserProfile.objects.get_or_create(user=self.manager_user)
        p_mgr.role = RoleChoices.MANAGER
        p_mgr.status = ApprovalStatus.ACTIVE
        p_mgr.save()

        p_dev, _ = UserProfile.objects.get_or_create(user=self.dev_user)
        p_dev.role = RoleChoices.TEAM_MEMBER
        p_dev.status = ApprovalStatus.ACTIVE
        p_dev.reporting_to = self.manager_user
        p_dev.save()

        self.client.force_login(self.admin_user)

    def _setup_request(self, req, user):
        req.user = user
        setattr(req, 'session', 'session')
        messages = FallbackStorage(req)
        setattr(req, '_messages', messages)
        return req

    def test_department_and_subdepartment_creation(self):
        parent_dept = Department.objects.create(
            name='Engineering',
            code='eng',
            head=self.manager_user
        )
        sub_dept = Department.objects.create(
            name='Platform Engineering',
            code='platform',
            parent=parent_dept
        )
        self.assertEqual(sub_dept.parent, parent_dept)
        self.assertEqual(str(sub_dept), "Engineering / Platform Engineering")

    def test_team_and_subteam_hierarchy(self):
        dept = Department.objects.create(name='Technology', code='tech')
        parent_team = Team.objects.create(
            name='Core Engineering',
            code='core-eng',
            department=dept,
            lead=self.manager_user
        )
        sub_team = Team.objects.create(
            name='Backend Services',
            code='backend-svc',
            department=dept,
            parent_team=parent_team,
            lead=self.manager_user
        )
        self.assertEqual(sub_team.parent_team, parent_team)
        self.assertEqual(parent_team.sub_teams.count(), 1)

    def test_membership_and_reporting_lines(self):
        dept = Department.objects.create(name='Tech', code='tech-dept')
        team = Team.objects.create(name='Dev Team', code='dev-team', department=dept, lead=self.manager_user)
        
        m_lead = TeamMembership.objects.create(
            team=team,
            user=self.manager_user,
            role='MGR',
            reporting_to=None
        )
        m_dev = TeamMembership.objects.create(
            team=team,
            user=self.dev_user,
            role='TM',
            reporting_to=self.manager_user
        )

        self.assertEqual(team.members_count, 2)
        self.assertEqual(m_dev.reporting_to, self.manager_user)
        self.assertEqual(m_lead.direct_reports_count, 1)

    def test_hierarchy_api_excludes_aman(self):
        dept = Department.objects.create(name='Engineering', code='eng-api', head=self.manager_user)
        team = Team.objects.create(name='API Team', code='api-team', department=dept, lead=self.manager_user)
        TeamMembership.objects.create(team=team, user=self.dev_user, role='TM')

        res = self.client.get('/teams/api/hierarchy/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('departments', data)
        self.assertTrue(len(data['departments']) > 0)
        self.assertEqual(data['departments'][0]['name'], 'Engineering')
        for d in data['departments']:
            for t in d['teams']:
                self.assertNotEqual(t['lead']['username'], 'aman')
                for m in t['members']:
                    self.assertNotEqual(m['username'], 'aman')

    def test_org_chart_api_payload(self):
        dept = Department.objects.create(name='Eng', code='eng-oc')
        team = Team.objects.create(name='Web Team', code='web-team', department=dept, lead=self.manager_user)
        TeamMembership.objects.create(team=team, user=self.manager_user, role='MGR')
        TeamMembership.objects.create(team=team, user=self.dev_user, role='TM', reporting_to=self.manager_user)

        res = self.client.get('/teams/api/org-chart/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('nodes', data)
        node_usernames = [n['username'] for n in data['nodes']]
        self.assertIn('psundar', node_usernames)
        self.assertIn('skhande', node_usernames)
        self.assertNotIn('aman', node_usernames)

    def test_update_reporting_api(self):
        dept = Department.objects.create(name='Eng', code='eng-up')
        team = Team.objects.create(name='Team 1', code='team-1', department=dept)
        TeamMembership.objects.create(team=team, user=self.dev_user, role='TM')

        payload = {
            'user_id': self.dev_user.id,
            'reporting_to_id': self.manager_user.id
        }
        res = self.client.post(
            '/teams/api/update-reporting/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        m = TeamMembership.objects.get(user=self.dev_user)
        self.assertEqual(m.reporting_to, self.manager_user)

    def test_aman_cannot_be_added_to_team_membership(self):
        dept = Department.objects.create(name='Operations', code='ops')
        team = Team.objects.create(name='Cool Team', code='cool-team', department=dept)
        with self.assertRaises(ValidationError):
            TeamMembership.objects.create(team=team, user=self.admin_user, role='TM')

    def test_aman_cannot_be_set_as_reporting_manager(self):
        dept = Department.objects.create(name='Operations', code='ops-2')
        team = Team.objects.create(name='Cool Team', code='cool-team-2', department=dept)
        with self.assertRaises(ValidationError):
            TeamMembership.objects.create(team=team, user=self.dev_user, role='TM', reporting_to=self.admin_user)

    def test_aman_cannot_be_team_lead_or_department_head(self):
        dept = Department.objects.create(name='Management', code='mgmt')
        with self.assertRaises(ValidationError):
            dept.head = self.admin_user
            dept.save()

        team = Team.objects.create(name='Executive', code='exec', department=dept)
        with self.assertRaises(ValidationError):
            team.lead = self.admin_user
            team.save()

    def test_aman_cannot_be_assigned_to_task(self):
        project = Project.objects.create(name='Test Proj', code='tst-prj')
        with self.assertRaises(ValidationError):
            Task.objects.create(project=project, name='Task 1', assignee=self.admin_user)

    def test_aman_cannot_be_assigned_to_project_member(self):
        project = Project.objects.create(name='Test Proj 2', code='tst-prj-2')
        with self.assertRaises(ValidationError):
            ProjectMember.objects.create(project=project, user=self.admin_user, role='ADMIN')

    def test_privilege_invariant_regular_user_cannot_manage_teams(self):
        self.client.force_login(self.dev_user)
        res_create = self.client.post('/team/create/', {
            'username': 'new_user',
            'first_name': 'New',
            'last_name': 'User',
            'email': 'new@company.com'
        })
        self.assertEqual(res_create.status_code, 302)
        self.assertFalse(User.objects.filter(username='new_user').exists())

        res_reporting = self.client.post(
            '/teams/api/update-reporting/',
            data=json.dumps({'user_id': self.dev_user.id, 'reporting_to_id': self.manager_user.id}),
            content_type='application/json'
        )
        self.assertEqual(res_reporting.status_code, 403)

    def test_user_registration_creates_pending_approval_user(self):
        from django.contrib.auth.models import AnonymousUser
        req = self._setup_request(self.factory.post('/register/', {
            'name': 'Priya Patel',
            'username': 'priya_patel',
            'email': 'priya@company.com',
            'password': 'secretpassword123',
            'confirm_password': 'secretpassword123'
        }), AnonymousUser())
        res = register_view(req)
        self.assertEqual(res.status_code, 302)
        
        user = User.objects.get(username='priya_patel')
        self.assertEqual(user.first_name, 'Priya')
        self.assertEqual(user.last_name, 'Patel')
        self.assertFalse(user.is_active)  # Inactive / Pending Approval
        self.assertEqual(user.profile.status, 'PENDING_APPROVAL')

    def test_admin_approval_and_provisioning_flow(self):
        from teams.models import RoleChoices, ApprovalStatus
        # 1. Create a pending user
        new_user = User.objects.create_user(
            username='rahul_dev',
            first_name='Rahul',
            last_name='Dev',
            email='rahul@godrej.com',
            password='secretpassword123',
            is_active=False
        )
        self.assertFalse(new_user.is_active)

        dept = Department.objects.create(name='Delivery', code='deliv', head=self.manager_user)
        team = Team.objects.create(name='Cool Team', code='cool-team', department=dept, lead=self.manager_user)

        # 2. Regular user tries to approve -> rejected
        req_denied = self._setup_request(self.factory.post(f'/team/{new_user.id}/approve/'), self.dev_user)
        res_denied = approve_team_user_view(req_denied, new_user.id)
        self.assertEqual(res_denied.status_code, 302)
        new_user.refresh_from_db()
        self.assertFalse(new_user.is_active)

        # 3. Superuser 'aman' approves and provisions team with 3-tier role
        req_approve = self._setup_request(self.factory.post(f'/team/{new_user.id}/approve/', {
            'team_id': team.id,
            'department_id': dept.id,
            'role': RoleChoices.TEAM_MEMBER,
            'reporting_to_id': self.manager_user.id
        }), self.admin_user)
        res_approve = approve_team_user_view(req_approve, new_user.id)
        self.assertEqual(res_approve.status_code, 302)

        new_user.refresh_from_db()
        self.assertTrue(new_user.is_active)
        self.assertEqual(new_user.profile.status, ApprovalStatus.ACTIVE)
        self.assertEqual(new_user.profile.role, RoleChoices.TEAM_MEMBER)
        self.assertEqual(new_user.profile.reporting_to, self.manager_user)
        
        m = TeamMembership.objects.get(user=new_user)
        self.assertEqual(m.team, team)
        self.assertEqual(m.role, RoleChoices.TEAM_MEMBER)
        self.assertEqual(m.reporting_to, self.manager_user)

    def test_3tier_hierarchy_rules(self):
        from teams.models import UserProfile, RoleChoices
        gm_user = User.objects.create_user(username='gm_exec', password='password123')
        gm_user.profile.role = RoleChoices.GENERAL_MANAGER
        gm_user.profile.save()

        # Manager can report to GM
        mgr_profile = self.manager_user.profile
        mgr_profile.role = RoleChoices.MANAGER
        mgr_profile.reporting_to = gm_user
        mgr_profile.save()  # Valid

        # Manager cannot report to Team Member
        with self.assertRaises(ValidationError):
            mgr_profile.reporting_to = self.dev_user
            mgr_profile.save()

        # Team Member cannot report to another Team Member
        with self.assertRaises(ValidationError):
            other_dev = User.objects.create_user(username='other_dev', password='password123')
            other_dev.profile.role = RoleChoices.TEAM_MEMBER
            other_dev.profile.reporting_to = self.dev_user
            other_dev.profile.save()

    def test_admin_can_toggle_user_status(self):
        user = User.objects.create_user(username='test_toggle', password='password123', is_active=True)
        
        req = self._setup_request(self.factory.post(f'/team/{user.id}/toggle-status/'), self.admin_user)
        res = toggle_team_user_status_view(req, user.id)
        self.assertEqual(res.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.profile.status, 'PENDING_APPROVAL')

        res2 = toggle_team_user_status_view(req, user.id)
        self.assertEqual(res2.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.profile.status, 'ACTIVE')

    def test_admin_can_reject_pending_user(self):
        user = User.objects.create_user(username='test_reject', password='password123', is_active=False)
        req = self._setup_request(self.factory.post(f'/team/{user.id}/reject/'), self.admin_user)
        res = reject_team_user_view(req, user.id)
        self.assertEqual(res.status_code, 302)
        self.assertFalse(User.objects.filter(username='test_reject').exists())

    def test_seed_demo_teams_command_configures_cool_team(self):
        from teams.models import RoleChoices
        call_command('seed_teams')
        
        cool_team = Team.objects.filter(name__iexact='cool team').first()
        self.assertIsNotNone(cool_team)
        self.assertEqual(cool_team.lead.username, 'psundar')

        sundar_m = TeamMembership.objects.get(team=cool_team, user__username='psundar')
        self.assertEqual(sundar_m.role, RoleChoices.MANAGER)
        self.assertIsNone(sundar_m.reporting_to)

        for member_username in ['skhande', 'smali', 'amanr']:
            m = TeamMembership.objects.get(team=cool_team, user__username=member_username)
            self.assertEqual(m.role, RoleChoices.TEAM_MEMBER)
            self.assertEqual(m.reporting_to.username, 'psundar')

        self.assertFalse(TeamMembership.objects.filter(user__username='aman').exists())
        self.assertFalse(Task.objects.filter(assignee__username='aman').exists())
        self.assertFalse(ProjectMember.objects.filter(user__username='aman').exists())

    def test_admin_panel_view_accessible_by_aman(self):
        from projects.admin_panel import (
            admin_panel_view, admin_create_department_view,
            admin_create_team_view, admin_seed_teams_view, admin_seed_projects_view
        )
        req = self._setup_request(self.factory.get('/admin-panel/'), self.admin_user)
        res = admin_panel_view(req)
        self.assertEqual(res.status_code, 200)

    def test_admin_panel_view_denied_for_non_admin(self):
        from projects.admin_panel import admin_panel_view
        req = self._setup_request(self.factory.get('/admin-panel/'), self.dev_user)
        res = admin_panel_view(req)
        self.assertEqual(res.status_code, 302)

    def test_admin_create_department_action(self):
        from projects.admin_panel import admin_create_department_view
        req = self._setup_request(
            self.factory.post('/admin-panel/create-dept/', {'name': 'New Department', 'code': 'new-dept'}),
            self.admin_user
        )
        res = admin_create_department_view(req)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Department.objects.filter(name='New Department').exists())

    def test_admin_create_team_action(self):
        from projects.admin_panel import admin_create_team_view
        dept = Department.objects.create(name='Dept X', code='dept-x')
        req = self._setup_request(
            self.factory.post('/admin-panel/create-team/', {
                'name': 'New Alpha Team',
                'code': 'alpha-team',
                'department_id': dept.id,
                'lead_id': self.manager_user.id
            }),
            self.admin_user
        )
        res = admin_create_team_view(req)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Team.objects.filter(name='New Alpha Team').exists())


