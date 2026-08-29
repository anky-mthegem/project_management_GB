from rest_framework import serializers
from django.contrib.auth.models import User
from projects.models import (
    Project, ProjectMember, Task, TaskDependency, TaskComment,
    TaskAttachment, ActivityLog,
    ProjectStatus, TaskStatus, TaskPriority, DependencyType, ProjectRole
)
from projects.services.scheduler import check_dependency_cycle


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    initials = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'full_name', 'initials']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_initials(self, obj):
        name = obj.get_full_name() or obj.username
        parts = name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return name[:2].upper()


class ProjectMemberSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user', read_only=True)

    class Meta:
        model = ProjectMember
        fields = ['id', 'project', 'user', 'user_detail', 'role', 'created_at']

    def validate_user(self, value):
        if value and value.username.lower() == 'aman':
            raise serializers.ValidationError("Master administrator 'aman' cannot be assigned to project memberships.")
        return value


class TaskCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_username = serializers.CharField(source='author.username', read_only=True)
    author_initials = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = ['id', 'task', 'author', 'author_name', 'author_username', 'author_initials', 'text', 'created_at']
        read_only_fields = ['author']

    def get_author_name(self, obj):
        if not obj.author:
            return "Anonymous"
        return obj.author.get_full_name() or obj.author.username

    def get_author_initials(self, obj):
        if not obj.author:
            return "SY"
        name = obj.author.get_full_name() or obj.author.username
        parts = name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return name[:2].upper()


class TaskAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = TaskAttachment
        fields = ['id', 'task', 'file', 'filename', 'file_size', 'uploaded_by', 'uploaded_by_name', 'created_at']
        read_only_fields = ['uploaded_by', 'file_size']

    def get_uploaded_by_name(self, obj):
        if not obj.uploaded_by:
            return "System"
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.username


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = ActivityLog
        fields = ['id', 'project', 'task', 'user', 'user_name', 'username', 'action', 'details', 'created_at']

    def get_user_name(self, obj):
        if not obj.user:
            return "System"
        return obj.user.get_full_name() or obj.user.username


class TaskDependencySerializer(serializers.ModelSerializer):
    from_task_name = serializers.CharField(source='from_task.name', read_only=True)
    to_task_name = serializers.CharField(source='to_task.name', read_only=True)

    class Meta:
        model = TaskDependency
        fields = [
            'id', 'from_task', 'to_task', 'from_task_name',
            'to_task_name', 'dependency_type', 'lag_days', 'created_at'
        ]

    def validate(self, attrs):
        from_task = attrs.get('from_task')
        to_task = attrs.get('to_task')

        if from_task and to_task:
            if from_task.id == to_task.id:
                raise serializers.ValidationError("A task cannot depend on itself.")
            if from_task.project_id != to_task.project_id:
                raise serializers.ValidationError("Dependencies must be within the same project.")
            if check_dependency_cycle(from_task.id, to_task.id):
                raise serializers.ValidationError("Circular dependency detected! This link creates an infinite loop.")

        return attrs


class TaskSerializer(serializers.ModelSerializer):
    wbs_code = serializers.CharField(read_only=True)
    depth = serializers.IntegerField(read_only=True)
    is_parent = serializers.BooleanField(read_only=True)
    schedule_variance_days = serializers.IntegerField(read_only=True)
    assignee_detail = UserSerializer(source='assignee', read_only=True)
    predecessors_list = serializers.SerializerMethodField()
    successors_list = serializers.SerializerMethodField()
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    attachments_count = serializers.IntegerField(source='attachments.count', read_only=True)

    class Meta:
        model = Task
        fields = [
            'id', 'project', 'parent_task', 'name', 'description',
            'start_date', 'end_date', 'duration_days', 'progress',
            'status', 'priority', 'is_milestone', 'assignee', 'assignee_detail',
            'sort_order', 'wbs_code', 'depth', 'is_parent', 'is_critical',
            'total_float_days', 'early_start', 'early_finish', 'late_start', 'late_finish',
            'baseline_start_date', 'baseline_end_date', 'baseline_duration_days',
            'schedule_variance_days', 'estimated_cost', 'actual_cost',
            'estimated_hours', 'actual_hours', 'comments_count', 'attachments_count',
            'predecessors_list', 'successors_list', 'created_at', 'updated_at'
        ]

    def get_predecessors_list(self, obj):
        deps = obj.predecessors.select_related('from_task').all()
        return [
            {
                'id': d.id,
                'predecessor_id': d.from_task.id,
                'predecessor_name': d.from_task.name,
                'dependency_type': d.dependency_type,
                'lag_days': d.lag_days
            }
            for d in deps
        ]

    def get_successors_list(self, obj):
        deps = obj.successors.select_related('to_task').all()
        return [
            {
                'id': d.id,
                'successor_id': d.to_task.id,
                'successor_name': d.to_task.name,
                'dependency_type': d.dependency_type,
                'lag_days': d.lag_days
            }
            for d in deps
        ]

    def validate_assignee(self, value):
        if value and value.username.lower() == 'aman':
            raise serializers.ValidationError("Master administrator 'aman' is reserved for administration only and cannot be assigned to tasks.")
        return value

    def validate(self, attrs):
        assignee = attrs.get('assignee', self.instance.assignee if self.instance else None)
        if assignee and assignee.username.lower() == 'aman':
            raise serializers.ValidationError({"assignee": "Master administrator 'aman' is reserved for administration only and cannot be assigned to tasks."})

        start_date = attrs.get('start_date', self.instance.start_date if self.instance else None)
        end_date = attrs.get('end_date', self.instance.end_date if self.instance else None)

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"end_date": "End date cannot be earlier than start date."})

        parent = attrs.get('parent_task', self.instance.parent_task if self.instance else None)
        if parent and self.instance:
            if parent.id == self.instance.id:
                raise serializers.ValidationError({"parent_task": "A task cannot be its own parent."})
            
            ancestor = parent
            visited = {self.instance.id}
            while ancestor:
                if ancestor.id in visited:
                    raise serializers.ValidationError({"parent_task": "Circular parent task relationship detected."})
                visited.add(ancestor.id)
                ancestor = ancestor.parent_task

        return attrs


class GanttTaskItemSerializer(serializers.ModelSerializer):
    """
    Formatted specifically for Gantt chart JSON consumption with baseline and critical path metadata.
    """
    id = serializers.SerializerMethodField()
    name = serializers.CharField()
    start = serializers.SerializerMethodField()
    end = serializers.SerializerMethodField()
    progress = serializers.IntegerField()
    dependencies = serializers.SerializerMethodField()
    custom_class = serializers.SerializerMethodField()
    wbs = serializers.CharField(source='wbs_code', read_only=True)
    assignee_name = serializers.SerializerMethodField()
    assignee_initials = serializers.SerializerMethodField()
    is_parent = serializers.BooleanField(read_only=True)
    parent = serializers.IntegerField(source='parent_task_id', allow_null=True)
    baseline_start = serializers.SerializerMethodField()
    baseline_end = serializers.SerializerMethodField()
    variance_days = serializers.IntegerField(source='schedule_variance_days', read_only=True)

    class Meta:
        model = Task
        fields = [
            'id', 'name', 'start', 'end', 'progress', 'dependencies',
            'custom_class', 'wbs', 'priority', 'status', 'assignee_name',
            'assignee_initials', 'is_milestone', 'is_parent', 'parent',
            'duration_days', 'description', 'is_critical', 'total_float_days',
            'baseline_start', 'baseline_end', 'variance_days',
            'estimated_cost', 'actual_cost', 'estimated_hours', 'actual_hours'
        ]

    def get_id(self, obj):
        return str(obj.id)

    def get_start(self, obj):
        return obj.start_date.strftime('%Y-%m-%d') if obj.start_date else ''

    def get_end(self, obj):
        return obj.end_date.strftime('%Y-%m-%d') if obj.end_date else ''

    def get_baseline_start(self, obj):
        return obj.baseline_start_date.strftime('%Y-%m-%d') if obj.baseline_start_date else None

    def get_baseline_end(self, obj):
        return obj.baseline_end_date.strftime('%Y-%m-%d') if obj.baseline_end_date else None

    def get_dependencies(self, obj):
        preds = obj.predecessors.values_list('from_task_id', flat=True)
        return ", ".join(str(p) for p in preds)

    def get_custom_class(self, obj):
        classes = []
        if obj.is_milestone:
            classes.append('bar-milestone')
        if obj.is_parent:
            classes.append('bar-parent')
        if obj.is_critical:
            classes.append('bar-critical-path')

        if obj.status == TaskStatus.COMPLETE:
            classes.append('bar-completed')
        elif obj.status == TaskStatus.DELAYED:
            classes.append('bar-delayed')
        elif obj.priority == TaskPriority.CRITICAL:
            classes.append('bar-critical')
        elif obj.priority == TaskPriority.HIGH:
            classes.append('bar-high')
        elif obj.priority == TaskPriority.LOW:
            classes.append('bar-low')
        else:
            classes.append('bar-medium')

        return " ".join(classes)

    def get_assignee_name(self, obj):
        if obj.assignee:
            return obj.assignee.get_full_name() or obj.assignee.username
        return None

    def get_assignee_initials(self, obj):
        if not obj.assignee:
            return None
        name = obj.assignee.get_full_name() or obj.assignee.username
        parts = name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return name[:2].upper()


class ProjectSerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    progress = serializers.IntegerField(read_only=True)
    total_tasks_count = serializers.IntegerField(read_only=True)
    completed_tasks_count = serializers.IntegerField(read_only=True)
    total_estimated_cost = serializers.FloatField(read_only=True)
    total_actual_cost = serializers.FloatField(read_only=True)

    class Meta:
        model = Project
        fields = [
            'id', 'name', 'code', 'description', 'status',
            'start_date', 'end_date', 'budget', 'owner', 'owner_name',
            'progress', 'total_tasks_count', 'completed_tasks_count',
            'total_estimated_cost', 'total_actual_cost',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['owner', 'code']

    def get_owner_name(self, obj):
        if not obj.owner:
            return "System"
        return obj.owner.get_full_name() or obj.owner.username


class ProjectDetailSerializer(ProjectSerializer):
    tasks = TaskSerializer(many=True, read_only=True)
    memberships = ProjectMemberSerializer(many=True, read_only=True)

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + ['tasks', 'memberships']
