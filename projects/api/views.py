from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction, models
from django.db.models import F, Max
from django.contrib.auth.models import User
from django.http import HttpResponse
from datetime import datetime
from decimal import Decimal

from projects.models import (
    Project, ProjectMember, Task, TaskDependency, TaskComment,
    TaskAttachment, ActivityLog,
    ProjectStatus, TaskStatus, TaskPriority, DependencyType, ProjectRole
)
from projects.api.serializers import (
    ProjectSerializer, ProjectDetailSerializer, TaskSerializer,
    TaskDependencySerializer, GanttTaskItemSerializer, UserSerializer,
    ProjectMemberSerializer, TaskCommentSerializer, TaskAttachmentSerializer,
    ActivityLogSerializer
)
from projects.services.scheduler import (
    cascade_reschedule, check_dependency_cycle, compute_wbs_hierarchy,
    calculate_critical_path, save_project_baseline, calculate_evm_metrics,
    calculate_resource_workload, get_hierarchical_task_list
)
from projects.services.excel_service import (
    export_project_to_excel, import_project_from_excel
)


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all().select_related('owner').prefetch_related('tasks', 'memberships')
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['retrieve']:
            return ProjectDetailSerializer
        return ProjectSerializer

    def perform_create(self, serializer):
        owner = self.request.user if (self.request.user and self.request.user.is_authenticated) else User.objects.get(username='aman')
        project = serializer.save(owner=owner)
        if self.request.user and self.request.user.is_authenticated and self.request.user.username.lower() != 'aman':
            ProjectMember.objects.get_or_create(
                project=project,
                user=self.request.user,
                defaults={'role': ProjectRole.ADMIN}
            )
        ActivityLog.objects.create(
            project=project,
            user=self.request.user if (self.request.user and self.request.user.is_authenticated) else User.objects.filter(username='aman').first(),
            action="Created Project",
            details=f"Project '{project.name}' initialized."
        )

    @action(detail=True, methods=['get'], url_path='gantt-data')
    def gantt_data(self, request, pk=None):
        project = self.get_object()
        calculate_critical_path(project)

        tasks = get_hierarchical_task_list(project)
        
        gantt_tasks = GanttTaskItemSerializer(tasks, many=True).data
        full_tasks = TaskSerializer(tasks, many=True).data

        deps = TaskDependency.objects.filter(
            from_task__project=project
        ).select_related('from_task', 'to_task')
        dependencies_data = TaskDependencySerializer(deps, many=True).data

        users = User.objects.filter(is_active=True).exclude(username='aman').values('id', 'username', 'first_name', 'last_name', 'email')
        evm = calculate_evm_metrics(project)
        workload = calculate_resource_workload(project)

        return Response({
            'project': {
                'id': project.id,
                'name': project.name,
                'code': project.code,
                'description': project.description,
                'status': project.status,
                'progress': project.progress,
                'start_date': project.start_date.strftime('%Y-%m-%d'),
                'end_date': project.end_date.strftime('%Y-%m-%d'),
                'baseline_saved_at': project.baseline_saved_at.isoformat() if project.baseline_saved_at else None,
                'total_tasks': project.total_tasks_count,
                'completed_tasks': project.completed_tasks_count,
                'exclude_weekends': project.exclude_weekends,
            },
            'gantt_tasks': gantt_tasks,
            'tasks': full_tasks,
            'dependencies': dependencies_data,
            'users': list(users),
            'evm': evm,
            'workload': workload,
        })

    @action(detail=True, methods=['post'], url_path='save-baseline')
    def save_baseline(self, request, pk=None):
        project = self.get_object()
        count = save_project_baseline(project)
        ActivityLog.objects.create(
            project=project,
            user=request.user,
            action="Saved Project Baseline",
            details=f"Snapshot created for {count} tasks."
        )
        return Response({'status': 'success', 'message': f'Baseline saved for {count} tasks.', 'saved_at': project.baseline_saved_at})

    @action(detail=True, methods=['post'], url_path='calculate-critical-path')
    def calculate_cpm(self, request, pk=None):
        project = self.get_object()
        cpm_result = calculate_critical_path(project)
        return Response({'status': 'success', 'critical_path': cpm_result})

    @action(detail=True, methods=['get'], url_path='export-excel')
    def export_excel(self, request, pk=None):
        project = self.get_object()
        calculate_critical_path(project)
        excel_buffer = export_project_to_excel(project)

        response = HttpResponse(
            excel_buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="GanttExcel_{project.code}_{datetime.now().strftime("%Y%m%d")}.xlsx"'
        return response

    @action(detail=True, methods=['post'], url_path='import-excel')
    def import_excel(self, request, pk=None):
        project = self.get_object()
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        count = import_project_from_excel(file_obj, project)
        calculate_critical_path(project)
        ActivityLog.objects.create(
            project=project,
            user=request.user,
            action="Imported Excel Schedule",
            details=f"Imported {count} tasks from file {file_obj.name}."
        )
        return Response({'status': 'success', 'imported_count': count})

    @action(detail=True, methods=['get'], url_path='workload')
    def workload(self, request, pk=None):
        project = self.get_object()
        data = calculate_resource_workload(project)
        return Response(data)

    @action(detail=True, methods=['get'], url_path='evm-stats')
    def evm_stats(self, request, pk=None):
        project = self.get_object()
        data = calculate_evm_metrics(project)
        return Response(data)

    @action(detail=True, methods=['get'], url_path='activity-logs')
    def activity_logs(self, request, pk=None):
        project = self.get_object()
        logs = project.activity_logs.select_related('user').order_by('-created_at')[:50]
        return Response(ActivityLogSerializer(logs, many=True).data)

    @action(detail=True, methods=['post'], url_path='recalculate')
    def recalculate(self, request, pk=None):
        project = self.get_object()
        root_tasks = project.tasks.filter(parent_task__isnull=True)
        
        with transaction.atomic():
            for t in root_tasks:
                if t.is_parent:
                    t.recalculate_from_subtasks()
                cascade_reschedule(t)
            calculate_critical_path(project)
            project.save()

        ActivityLog.objects.create(
            project=project,
            user=request.user,
            action="Recalculated Schedules",
            details="Synchronized dependencies and CPM critical path."
        )
        return Response({'status': 'success', 'message': 'Project schedules successfully synchronized.'})


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().select_related('project', 'assignee', 'parent_task').prefetch_related('comments', 'attachments')
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs.order_by('sort_order', 'id')

    def perform_create(self, serializer):
        insert_after_id = self.request.data.get('insert_after_task_id')
        
        with transaction.atomic():
            task = serializer.save()
            project = task.project

            if insert_after_id:
                try:
                    ref_task = Task.objects.get(pk=insert_after_id, project=project)
                    Task.objects.filter(project=project, sort_order__gt=ref_task.sort_order).exclude(pk=task.id).update(sort_order=F('sort_order') + 1)
                    task.sort_order = ref_task.sort_order + 1
                    task.save(update_fields=['sort_order'])
                except (Task.DoesNotExist, ValueError):
                    pass
            elif task.parent_task:
                last_sibling = Task.objects.filter(project=project, parent_task=task.parent_task).exclude(pk=task.id).order_by('-sort_order').first()
                if last_sibling:
                    ref_order = last_sibling.sort_order
                else:
                    ref_order = task.parent_task.sort_order
                Task.objects.filter(project=project, sort_order__gt=ref_order).exclude(pk=task.id).update(sort_order=F('sort_order') + 1)
                task.sort_order = ref_order + 1
                task.save(update_fields=['sort_order'])
            elif not task.sort_order:
                max_order = Task.objects.filter(project=project).exclude(pk=task.id).aggregate(m=Max('sort_order'))['m'] or 0
                task.sort_order = max_order + 1
                task.save(update_fields=['sort_order'])

            if task.parent_task:
                task.parent_task.recalculate_from_subtasks()
            cascade_reschedule(task)
            calculate_critical_path(task.project)
            task.project.save()

            ActivityLog.objects.create(
                project=task.project,
                task=task,
                user=self.request.user,
                action="Created Task",
                details=f"Task '[{task.wbs_code}] {task.name}' created."
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            task = serializer.save()
            if task.parent_task:
                task.parent_task.recalculate_from_subtasks()
            cascade_reschedule(task)
            calculate_critical_path(task.project)
            task.project.save()

            ActivityLog.objects.create(
                project=task.project,
                task=task,
                user=self.request.user,
                action="Updated Task",
                details=f"Task '[{task.wbs_code}] {task.name}' details updated."
            )

    def perform_destroy(self, instance):
        parent = instance.parent_task
        project = instance.project
        with transaction.atomic():
            ActivityLog.objects.create(
                project=project,
                user=self.request.user,
                action="Deleted Task",
                details=f"Task '{instance.name}' deleted."
            )
            instance.delete()
            if parent:
                parent.recalculate_from_subtasks()
            calculate_critical_path(project)
            project.save()

    @action(detail=True, methods=['post'], url_path='move-up')
    def move_up(self, request, pk=None):
        task = self.get_object()
        siblings = list(Task.objects.filter(
            project=task.project,
            parent_task_id=task.parent_task_id
        ).order_by('sort_order', 'id'))
        
        idx = next((i for i, t in enumerate(siblings) if t.id == task.id), None)
        if idx is not None and idx > 0:
            prev_task = siblings[idx - 1]
            t_order = task.sort_order
            p_order = prev_task.sort_order
            if t_order == p_order or t_order <= p_order:
                task.sort_order = max(0, p_order - 1)
            else:
                task.sort_order, prev_task.sort_order = p_order, t_order
            with transaction.atomic():
                task.save(update_fields=['sort_order'])
                prev_task.save(update_fields=['sort_order'])
                calculate_critical_path(task.project)
            return Response({'status': 'success', 'message': f"Task '{task.name}' moved up."})
        return Response({'status': 'noop', 'message': 'Task is already at the top of its level.'})

    @action(detail=True, methods=['post'], url_path='move-down')
    def move_down(self, request, pk=None):
        task = self.get_object()
        siblings = list(Task.objects.filter(
            project=task.project,
            parent_task_id=task.parent_task_id
        ).order_by('sort_order', 'id'))
        
        idx = next((i for i, t in enumerate(siblings) if t.id == task.id), None)
        if idx is not None and idx < len(siblings) - 1:
            next_task = siblings[idx + 1]
            t_order = task.sort_order
            n_order = next_task.sort_order
            if t_order == n_order or t_order >= n_order:
                task.sort_order = n_order + 1
            else:
                task.sort_order, next_task.sort_order = n_order, t_order
            with transaction.atomic():
                task.save(update_fields=['sort_order'])
                next_task.save(update_fields=['sort_order'])
                calculate_critical_path(task.project)
            return Response({'status': 'success', 'message': f"Task '{task.name}' moved down."})
        return Response({'status': 'noop', 'message': 'Task is already at the bottom of its level.'})

    @action(detail=True, methods=['patch'], url_path='reschedule')
    def reschedule(self, request, pk=None):
        task = self.get_object()
        data = request.data

        with transaction.atomic():
            if 'start_date' in data and data['start_date']:
                if isinstance(data['start_date'], str):
                    task.start_date = datetime.strptime(data['start_date'][:10], '%Y-%m-%d').date()
                else:
                    task.start_date = data['start_date']

            if 'end_date' in data and data['end_date']:
                if isinstance(data['end_date'], str):
                    task.end_date = datetime.strptime(data['end_date'][:10], '%Y-%m-%d').date()
                else:
                    task.end_date = data['end_date']

            if 'progress' in data and data['progress'] is not None:
                task.progress = max(0, min(100, int(data['progress'])))

            if 'status' in data and data['status']:
                task.status = data['status']

            if 'priority' in data and data['priority']:
                task.priority = data['priority']

            if 'is_milestone' in data:
                task.is_milestone = bool(data['is_milestone'])

            if 'estimated_cost' in data:
                task.estimated_cost = Decimal(str(data['estimated_cost']))

            if 'actual_cost' in data:
                task.actual_cost = Decimal(str(data['actual_cost']))

            if 'estimated_hours' in data:
                task.estimated_hours = int(data['estimated_hours'])

            if 'actual_hours' in data:
                task.actual_hours = int(data['actual_hours'])

            task.save()

            affected_task_ids = cascade_reschedule(task)

            if task.parent_task:
                task.parent_task.recalculate_from_subtasks()
            
            calculate_critical_path(task.project)
            task.project.save()

        all_project_tasks = Task.objects.filter(project=task.project).select_related('assignee', 'parent_task')
        gantt_data = GanttTaskItemSerializer(all_project_tasks, many=True).data

        return Response({
            'status': 'success',
            'task': TaskSerializer(task).data,
            'affected_task_ids': affected_task_ids,
            'gantt_tasks': gantt_data,
            'project_progress': task.project.progress
        })

    @action(detail=True, methods=['patch'], url_path='update-status')
    def update_status(self, request, pk=None):
        """Used for instant Kanban Board drag-and-drop columns."""
        task = self.get_object()
        new_status = request.data.get('status')
        if new_status in TaskStatus.values:
            task.status = new_status
            if new_status == TaskStatus.COMPLETE:
                task.progress = 100
            elif new_status == TaskStatus.NOT_STARTED:
                task.progress = 0
            task.save()
            if task.parent_task:
                task.parent_task.recalculate_from_subtasks()
            task.project.save()

            ActivityLog.objects.create(
                project=task.project,
                task=task,
                user=request.user,
                action="Status Changed (Kanban)",
                details=f"Task moved to '{task.get_status_display()}'."
            )
            return Response({'status': 'success', 'task': TaskSerializer(task).data})
        return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get', 'post'], url_path='comments')
    def comments(self, request, pk=None):
        task = self.get_object()
        if request.method == 'POST':
            text = request.data.get('text', '').strip()
            if not text:
                return Response({'error': 'Comment text required'}, status=status.HTTP_400_BAD_REQUEST)
            comment = TaskComment.objects.create(
                task=task,
                author=request.user,
                text=text
            )
            ActivityLog.objects.create(
                project=task.project,
                task=task,
                user=request.user,
                action="Added Comment",
                details=f"Comment: '{text[:50]}...'"
            )
            return Response(TaskCommentSerializer(comment).data, status=status.HTTP_201_CREATED)
        
        comments = task.comments.select_related('author').order_by('-created_at')
        return Response(TaskCommentSerializer(comments, many=True).data)

    @action(detail=True, methods=['get', 'post'], url_path='attachments')
    def attachments(self, request, pk=None):
        task = self.get_object()
        if request.method == 'POST':
            file_obj = request.FILES.get('file')
            if not file_obj:
                return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
            attachment = TaskAttachment.objects.create(
                task=task,
                file=file_obj,
                filename=file_obj.name,
                file_size=file_obj.size,
                uploaded_by=request.user
            )
            ActivityLog.objects.create(
                project=task.project,
                task=task,
                user=request.user,
                action="Uploaded Attachment",
                details=f"File: '{file_obj.name}'"
            )
            return Response(TaskAttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)
        
        attachments = task.attachments.select_related('uploaded_by').order_by('-created_at')
        return Response(TaskAttachmentSerializer(attachments, many=True).data)


class TaskDependencyViewSet(viewsets.ModelViewSet):
    queryset = TaskDependency.objects.all().select_related('from_task', 'to_task')
    serializer_class = TaskDependencySerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        with transaction.atomic():
            dependency = serializer.save()
            cascade_reschedule(dependency.from_task)
            calculate_critical_path(dependency.from_task.project)
            dependency.from_task.project.save()

            ActivityLog.objects.create(
                project=dependency.from_task.project,
                user=self.request.user,
                action="Added Dependency",
                details=f"Linked '{dependency.from_task.name}' -> '{dependency.to_task.name}' ({dependency.dependency_type})."
            )

    def perform_destroy(self, instance):
        project = instance.from_task.project
        with transaction.atomic():
            ActivityLog.objects.create(
                project=project,
                user=self.request.user,
                action="Removed Dependency",
                details=f"Unlinked '{instance.from_task.name}' -> '{instance.to_task.name}'."
            )
            instance.delete()
            calculate_critical_path(project)
            project.save()


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.filter(is_active=True).exclude(username='aman').order_by('username')
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
