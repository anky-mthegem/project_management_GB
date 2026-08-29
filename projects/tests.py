from django.test import TestCase, RequestFactory, Client
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date, timedelta

from projects.models import (
    Project, ProjectMember, Task, TaskDependency, TaskComment,
    ActivityLog, ProjectStatus, TaskStatus, TaskPriority, DependencyType, ProjectRole
)
from projects.views import (
    team_management_view, create_team_user_view, edit_team_user_view, delete_team_user_view
)
from projects.services.scheduler import (
    check_dependency_cycle, cascade_reschedule, calculate_critical_path,
    save_project_baseline, calculate_evm_metrics, calculate_resource_workload
)
from projects.services.excel_service import export_project_to_excel


class GanttProjectTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='aman',
            password='123456',
            first_name='Aman',
            last_name='Admin',
            is_staff=True,
            is_superuser=True
        )
        self.member = User.objects.create_user(
            username='psundar',
            password='Godrej@123',
            first_name='Sundar',
            last_name='Nadar',
            email='psundar@godrej.com'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.force_login(self.user)

        self.today = date(2026, 1, 1)
        self.project = Project.objects.create(
            name='Test Automation Project',
            code='test-auto-prj',
            status=ProjectStatus.ACTIVE,
            owner=self.user,
            start_date=self.today,
            end_date=self.today + timedelta(days=30),
            budget=50000.00
        )
        ProjectMember.objects.get_or_create(
            project=self.project,
            user=self.member,
            defaults={'role': ProjectRole.MEMBER}
        )

    def test_task_duration_calculation(self):
        task = Task.objects.create(
            project=self.project,
            name='Test Task 1',
            start_date=self.today,
            end_date=self.today + timedelta(days=4)
        )
        self.assertEqual(task.duration_days, 5)

    def test_parent_task_rollup(self):
        parent = Task.objects.create(
            project=self.project,
            name='Parent Phase',
            start_date=self.today,
            end_date=self.today + timedelta(days=1)
        )
        child1 = Task.objects.create(
            project=self.project,
            parent_task=parent,
            name='Child 1',
            start_date=self.today,
            end_date=self.today + timedelta(days=5),
            progress=100,
            estimated_cost=5000,
            actual_cost=4500
        )
        child2 = Task.objects.create(
            project=self.project,
            parent_task=parent,
            name='Child 2',
            start_date=self.today + timedelta(days=6),
            end_date=self.today + timedelta(days=10),
            progress=50,
            estimated_cost=5000,
            actual_cost=2500
        )
        parent.recalculate_from_subtasks()
        parent.refresh_from_db()

        self.assertEqual(parent.start_date, self.today)
        self.assertEqual(parent.end_date, self.today + timedelta(days=10))
        self.assertTrue(parent.progress > 0)
        self.assertEqual(parent.estimated_cost, 10000)

    def test_circular_dependency_detection(self):
        t1 = Task.objects.create(
            project=self.project,
            name='Task A',
            start_date=self.today,
            end_date=self.today + timedelta(days=2)
        )
        t2 = Task.objects.create(
            project=self.project,
            name='Task B',
            start_date=self.today + timedelta(days=3),
            end_date=self.today + timedelta(days=5)
        )
        t3 = Task.objects.create(
            project=self.project,
            name='Task C',
            start_date=self.today + timedelta(days=6),
            end_date=self.today + timedelta(days=8)
        )

        TaskDependency.objects.create(from_task=t1, to_task=t2, dependency_type=DependencyType.FINISH_TO_START)
        TaskDependency.objects.create(from_task=t2, to_task=t3, dependency_type=DependencyType.FINISH_TO_START)

        self.assertTrue(check_dependency_cycle(t3.id, t1.id))

        with self.assertRaises(ValidationError):
            dep_cycle = TaskDependency(from_task=t3, to_task=t1, dependency_type=DependencyType.FINISH_TO_START)
            dep_cycle.clean()

    def test_cascade_rescheduling(self):
        t1 = Task.objects.create(
            project=self.project,
            name='Task A',
            start_date=self.today,
            end_date=self.today + timedelta(days=4),
            duration_days=5
        )
        t2 = Task.objects.create(
            project=self.project,
            name='Task B',
            start_date=self.today + timedelta(days=5),
            end_date=self.today + timedelta(days=9),
            duration_days=5
        )
        TaskDependency.objects.create(from_task=t1, to_task=t2, dependency_type=DependencyType.FINISH_TO_START)

        t1.start_date = self.today + timedelta(days=5)
        t1.end_date = self.today + timedelta(days=9)
        t1.save()

        cascade_reschedule(t1)
        t2.refresh_from_db()

        self.assertEqual(t2.start_date, self.today + timedelta(days=10))
        self.assertEqual(t2.end_date, self.today + timedelta(days=14))

    def test_critical_path_method_cpm(self):
        t1 = Task.objects.create(project=self.project, name='Task 1', start_date=self.today, end_date=self.today + timedelta(days=5), duration_days=6)
        t2 = Task.objects.create(project=self.project, name='Task 2', start_date=self.today + timedelta(days=6), end_date=self.today + timedelta(days=12), duration_days=7)
        t3_parallel = Task.objects.create(project=self.project, name='Parallel Short Task', start_date=self.today, end_date=self.today + timedelta(days=2), duration_days=3)

        TaskDependency.objects.create(from_task=t1, to_task=t2, dependency_type=DependencyType.FINISH_TO_START)

        cpm = calculate_critical_path(self.project)
        t1.refresh_from_db()
        t2.refresh_from_db()
        t3_parallel.refresh_from_db()

        self.assertTrue(t1.is_critical)
        self.assertTrue(t2.is_critical)
        self.assertFalse(t3_parallel.is_critical)
        self.assertTrue(t3_parallel.total_float_days > 0)

    def test_baseline_snapshot_and_variance(self):
        t1 = Task.objects.create(project=self.project, name='Task 1', start_date=self.today, end_date=self.today + timedelta(days=5), duration_days=6)
        save_project_baseline(self.project)
        t1.refresh_from_db()

        self.assertEqual(t1.baseline_start_date, self.today)
        self.assertEqual(t1.baseline_end_date, self.today + timedelta(days=5))

        # Push task by 3 days
        t1.end_date = self.today + timedelta(days=8)
        t1.save()
        self.assertEqual(t1.schedule_variance_days, 3)

    def test_evm_metrics_calculation(self):
        Task.objects.create(project=self.project, name='Task 1', start_date=self.today, end_date=self.today + timedelta(days=5), progress=100, estimated_cost=1000, actual_cost=900)
        Task.objects.create(project=self.project, name='Task 2', start_date=self.today, end_date=self.today + timedelta(days=5), progress=50, estimated_cost=2000, actual_cost=1200)

        evm = calculate_evm_metrics(self.project)
        self.assertEqual(evm['planned_value'], 3000.0)
        self.assertEqual(evm['earned_value'], 2000.0) # 1000*1.0 + 2000*0.5
        self.assertEqual(evm['actual_cost'], 2100.0) # 900 + 1200
        self.assertTrue(evm['cpi'] > 0)

    def test_excel_export_generation(self):
        Task.objects.create(project=self.project, name='Exportable Task', start_date=self.today, end_date=self.today + timedelta(days=5), progress=70)
        output_buffer = export_project_to_excel(self.project)
        self.assertTrue(len(output_buffer.getvalue()) > 0)

    def test_task_comments_and_kanban_status_api(self):
        t1 = Task.objects.create(project=self.project, name='Kanban Task', start_date=self.today, end_date=self.today + timedelta(days=3))
        
        # Test Comment API
        response = self.client.post(f'/api/tasks/{t1.id}/comments/', {'text': 'Discussing requirements'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(t1.comments.count(), 1)

        # Test Kanban Status Update
        response = self.client.patch(f'/api/tasks/{t1.id}/update-status/', {'status': 'COMPLETE'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        t1.refresh_from_db()
        self.assertEqual(t1.status, TaskStatus.COMPLETE)
        self.assertEqual(t1.progress, 100)

    def test_team_user_management_flow(self):
        factory = RequestFactory()

        # Helper to attach user and messages
        def setup_request(req):
            req.user = self.user
            setattr(req, 'session', 'session')
            messages = FallbackStorage(req)
            setattr(req, '_messages', messages)
            return req

        # 1. Test Creating User Sarah Jenkins (@sarah_pm)
        req = setup_request(factory.post('/team/create/', {
            'username': 'sarah_pm',
            'first_name': 'Sarah',
            'last_name': 'Jenkins',
            'email': 'sarah.jenkins@ganttexcel.local',
            'password': 'password123',
            'role': 'MANAGER'
        }))
        res = create_team_user_view(req)
        self.assertEqual(res.status_code, 302)

        sarah = User.objects.filter(username='sarah_pm').first()
        self.assertIsNotNone(sarah)
        self.assertEqual(sarah.first_name, 'Sarah')
        self.assertEqual(sarah.last_name, 'Jenkins')

        # 2. Assign task to Sarah
        t1 = Task.objects.create(
            project=self.project,
            name='Sarah Assigned Task',
            start_date=self.today,
            end_date=self.today + timedelta(days=4),
            assignee=sarah,
            estimated_hours=20
        )
        self.assertEqual(t1.assignee, sarah)

        # 3. Edit Sarah's info
        req_edit = setup_request(factory.post(f'/team/{sarah.id}/edit/', {
            'first_name': 'Sarah Edited',
            'last_name': 'Jenkins',
            'email': 'sarah.new@ganttexcel.local',
            'role': 'ADMIN'
        }))
        res_edit = edit_team_user_view(req_edit, sarah.id)
        self.assertEqual(res_edit.status_code, 302)
        sarah.refresh_from_db()
        self.assertEqual(sarah.first_name, 'Sarah Edited')

        # 4. Delete Sarah safely (tasks should become unassigned)
        req_del = setup_request(factory.post(f'/team/{sarah.id}/delete/'))
        res_del = delete_team_user_view(req_del, sarah.id)
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(User.objects.filter(username='sarah_pm').exists())
        t1.refresh_from_db()
        self.assertIsNone(t1.assignee)

        # 5. Verify aman cannot be deleted via view
        req_del_admin = setup_request(factory.post(f'/team/{self.user.id}/delete/'))
        res_del_admin = delete_team_user_view(req_del_admin, self.user.id)
        self.assertEqual(res_del_admin.status_code, 302)
        self.assertTrue(User.objects.filter(username='aman').exists())

    def test_master_user_cannot_be_deleted_orm(self):
        """Verify ORM .delete() on 'aman' is blocked by ProtectedError and pre_delete signal."""
        # 1. Blocked when project references aman
        with transaction.atomic():
            with self.assertRaises((ProtectedError, ValidationError)):
                self.user.delete()
        self.assertTrue(User.objects.filter(username='aman').exists())

        # 2. Blocked by pre_delete signal even if project is deleted
        Project.objects.all().delete()
        with transaction.atomic():
            with self.assertRaises(ValidationError):
                self.user.delete()
        self.assertTrue(User.objects.filter(username='aman').exists())

    def test_master_user_cannot_be_renamed(self):
        """Verify renaming 'aman' is prevented by pre_save signal."""
        self.user.username = 'aman_renamed'
        with transaction.atomic():
            with self.assertRaises(ValidationError):
                self.user.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'aman')

    def test_master_user_superuser_staff_enforced(self):
        """Verify is_staff and is_superuser are always True for aman."""
        self.user.is_staff = False
        self.user.is_superuser = False
        self.user.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)
        self.assertTrue(self.user.is_superuser)

    def test_master_user_cannot_be_assigned_to_project(self):
        """Verify aman cannot be added to any project memberships."""
        with transaction.atomic():
            with self.assertRaises(ValidationError):
                ProjectMember.objects.create(project=self.project, user=self.user, role=ProjectRole.ADMIN)

    def test_cannot_assign_task_to_master_user_model(self):
        """Verify Task.clean() and Task.save() prevent assigning tasks to master user 'aman'."""
        task = Task(
            project=self.project,
            name='Forbidden Task',
            start_date=self.today,
            end_date=self.today + timedelta(days=2),
            assignee=self.user
        )
        with self.assertRaises(ValidationError):
            task.clean()

        with self.assertRaises(ValidationError):
            task.save()

    def test_cannot_assign_task_to_master_user_serializer_and_api(self):
        """Verify TaskSerializer and REST API reject creating or updating tasks with aman as assignee."""
        from projects.api.serializers import TaskSerializer
        serializer = TaskSerializer(data={
            'project': self.project.id,
            'name': 'API Forbidden Task',
            'start_date': self.today.isoformat(),
            'end_date': (self.today + timedelta(days=3)).isoformat(),
            'assignee': self.user.id
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('assignee', serializer.errors)

        # Direct REST API POST
        response = self.client.post('/api/tasks/', {
            'project': self.project.id,
            'name': 'API Post Task',
            'start_date': self.today.isoformat(),
            'end_date': (self.today + timedelta(days=3)).isoformat(),
            'assignee': self.user.id
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_gantt_data_and_users_api_exclude_master_user(self):
        """Verify master user 'aman' is excluded from assignable user listings."""
        response = self.client.get(f'/api/projects/{self.project.id}/gantt-data/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user_list = response.data.get('users', [])
        usernames = [u['username'] for u in user_list]
        self.assertNotIn('aman', usernames)

        # ReadOnly Users API endpoint
        users_resp = self.client.get('/api/users/')
        self.assertEqual(users_resp.status_code, status.HTTP_200_OK)
        results = users_resp.data.get('results', users_resp.data) if isinstance(users_resp.data, dict) else users_resp.data
        api_usernames = [u['username'] for u in results]
        self.assertNotIn('aman', api_usernames)

    def test_resource_workload_excludes_master_user(self):
        """Verify calculate_resource_workload does not include master admin 'aman'."""
        workload = calculate_resource_workload(self.project)
        workload_usernames = [w['username'] for w in workload]
        self.assertNotIn('aman', workload_usernames)


class DatabaseBackupAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username='aman',
            password='password123',
            email='aman@milestonemanagement.local'
        )
        self.regular_user = User.objects.create_user(
            username='regular_staff',
            password='password123',
            is_staff=True,
            is_superuser=False
        )
        self.project = Project.objects.create(
            name='Test DB Backup Project',
            code='PRJ-DB-001',
            start_date=date.today(),
            end_date=date.today() + timedelta(days=30),
            owner=self.superuser
        )

    def _setup_request(self, req, user):
        req.user = user
        setattr(req, 'session', 'session')
        messages = FallbackStorage(req)
        setattr(req, '_messages', messages)
        return req

    def test_database_manage_view_superuser_access(self):
        """Superusers should have access to the database manage dashboard."""
        from projects.admin_database import database_manage_view
        req = self._setup_request(self.factory.get('/admin/database-manage/'), self.superuser)
        response = database_manage_view(req)
        self.assertEqual(response.status_code, 200)

    def test_database_manage_view_denies_non_superuser(self):
        """Non-superusers must receive PermissionDenied."""
        from django.core.exceptions import PermissionDenied
        from projects.admin_database import database_manage_view
        req = self._setup_request(self.factory.get('/admin/database-manage/'), self.regular_user)
        with self.assertRaises(PermissionDenied):
            database_manage_view(req)

    def test_database_export_streams_sqlite_file(self):
        """Superuser export downloads a valid SQLite binary file."""
        from projects.admin_database import database_export_view
        req = self._setup_request(self.factory.get('/admin/database-export/'), self.superuser)
        response = database_export_view(req)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/x-sqlite3')
        self.assertTrue('attachment' in response['Content-Disposition'])
        self.assertTrue(response['Content-Disposition'].endswith('.sqlite3"'))

    def test_database_clear_aborts_without_exact_confirmation(self):
        """Must reject clear operation if confirm_text is not 'CLEAR'."""
        from projects.admin_database import database_clear_view
        req = self._setup_request(self.factory.post('/admin/database-clear/', {'confirm_text': 'wrong_word'}), self.superuser)
        response = database_clear_view(req)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Project.objects.filter(id=self.project.id).exists())

    def test_database_clear_purges_records_and_preserves_master_user(self):
        """Valid clear deletes project records, keeps user aman, and auto-saves rollback backup."""
        from projects.admin_database import database_clear_view
        req = self._setup_request(self.factory.post('/admin/database-clear/', {'confirm_text': 'CLEAR', 'remove_non_admin_users': '1'}), self.superuser)
        response = database_clear_view(req)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Project.objects.count(), 0)
        self.assertEqual(Task.objects.count(), 0)
        self.assertTrue(User.objects.filter(username='aman', is_superuser=True).exists())
        self.assertFalse(User.objects.filter(username='regular_staff').exists())

    def test_wbs_hierarchy_order_and_subtask_numbering(self):
        """A subtask under Task 2 must have WBS 2.1 and be ordered directly below Task 2."""
        from projects.services.scheduler import get_hierarchical_task_list

        t1 = Task.objects.create(project=self.project, name='Task 1', sort_order=0)
        t2 = Task.objects.create(project=self.project, name='Task 2', sort_order=1)
        sub2_1 = Task.objects.create(project=self.project, parent_task=t2, name='Subtask 2.1', sort_order=2)
        sub2_2 = Task.objects.create(project=self.project, parent_task=t2, name='Subtask 2.2', sort_order=3)
        sub1_1 = Task.objects.create(project=self.project, parent_task=t1, name='Subtask 1.1', sort_order=4)

        ordered = get_hierarchical_task_list(self.project)
        ordered_names = [t.name for t in ordered]
        ordered_wbs = [t.wbs_code for t in ordered]

        # Tree order must be: Task 1 -> Subtask 1.1 -> Task 2 -> Subtask 2.1 -> Subtask 2.2
        self.assertEqual(ordered_names, ['Task 1', 'Subtask 1.1', 'Task 2', 'Subtask 2.1', 'Subtask 2.2'])
        self.assertEqual(ordered_wbs, ['1', '1.1', '2', '2.1', '2.2'])

    def test_task_move_up_and_down_actions(self):
        """Move up and down endpoints properly adjust sort_order among siblings."""
        self.client.login(username='aman', password='password123')
        t1 = Task.objects.create(project=self.project, name='Task 1', sort_order=0)
        t2 = Task.objects.create(project=self.project, name='Task 2', sort_order=1)

        # Move Task 2 up
        res = self.client.post(f'/api/tasks/{t2.id}/move-up/')
        self.assertEqual(res.status_code, 200)
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertTrue(t2.sort_order <= t1.sort_order)

        # Move Task 2 down
        res = self.client.post(f'/api/tasks/{t2.id}/move-down/')
        self.assertEqual(res.status_code, 200)
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertTrue(t2.sort_order >= t1.sort_order)





