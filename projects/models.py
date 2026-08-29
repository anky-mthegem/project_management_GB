from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.utils import timezone
from datetime import timedelta, date, datetime


class ProjectStatus(models.TextChoices):
    PLANNING = 'PLANNING', 'Planning'
    ACTIVE = 'ACTIVE', 'Active'
    ON_HOLD = 'ON_HOLD', 'On Hold'
    COMPLETED = 'COMPLETED', 'Completed'


class ProjectRole(models.TextChoices):
    ADMIN = 'ADMIN', 'Admin'
    MANAGER = 'MANAGER', 'Manager'
    MEMBER = 'MEMBER', 'Member'


class TaskStatus(models.TextChoices):
    NOT_STARTED = 'NOT_STARTED', 'Not Started'
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
    COMPLETE = 'COMPLETE', 'Complete'
    DELAYED = 'DELAYED', 'Delayed'


class TaskPriority(models.TextChoices):
    LOW = 'LOW', 'Low'
    MEDIUM = 'MEDIUM', 'Medium'
    HIGH = 'HIGH', 'High'
    CRITICAL = 'CRITICAL', 'Critical'


class DependencyType(models.TextChoices):
    FINISH_TO_START = 'FS', 'Finish-to-Start (FS)'
    START_TO_START = 'SS', 'Start-to-Start (SS)'
    FINISH_TO_FINISH = 'FF', 'Finish-to-Finish (FF)'
    START_TO_FINISH = 'SF', 'Start-to-Finish (SF)'


def get_default_master_user_id():
    """Returns the primary key for the master user 'aman', creating if missing."""
    user, created = User.objects.get_or_create(
        username='aman',
        defaults={
            'first_name': 'Aman',
            'last_name': 'Admin',
            'email': 'aman@ganttexcel.local',
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
        }
    )
    if created:
        user.set_password('123456')
        user.save()
    return user.id


class Project(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    code = models.SlugField(max_length=64, unique=True, db_index=True)
    description = models.TextField(blank=True, default='')
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=20,
        choices=ProjectStatus.choices,
        default=ProjectStatus.PLANNING,
        db_index=True
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='owned_projects',
        default=get_default_master_user_id
    )
    exclude_weekends = models.BooleanField(default=False, help_text="Exclude weekends in duration calculations")
    assigned_team = models.ForeignKey(
        'teams.Team',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_projects'
    )
    baseline_saved_at = models.DateTimeField(null=True, blank=True)
    budget = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, help_text="Total authorized budget in INR (₹)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['status', 'start_date']),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        if not self.code:
            base_slug = slugify(self.name)[:50] or 'prj'
            candidate = base_slug
            counter = 1
            while Project.objects.filter(code=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base_slug}-{counter}"
                counter += 1
            self.code = candidate
        
        # Keep project start/end in sync with tasks if tasks exist
        if self.pk:
            tasks = self.tasks.all()
            if tasks.exists():
                min_start = min((t.start_date for t in tasks if t.start_date), default=None)
                max_end = max((t.end_date for t in tasks if t.end_date), default=None)
                if min_start and min_start < self.start_date:
                    self.start_date = min_start
                if max_end and max_end > self.end_date:
                    self.end_date = max_end

        super().save(*args, **kwargs)

    @property
    def progress(self):
        """Calculate weighted or average progress of root tasks."""
        root_tasks = self.tasks.filter(parent_task__isnull=True)
        if not root_tasks.exists():
            return 0
        total_duration = sum(t.duration_days for t in root_tasks)
        if total_duration > 0:
            weighted_sum = sum(t.progress * t.duration_days for t in root_tasks)
            return round(weighted_sum / total_duration)
        return round(sum(t.progress for t in root_tasks) / root_tasks.count())

    @property
    def total_tasks_count(self):
        return self.tasks.count()

    @property
    def completed_tasks_count(self):
        return self.tasks.filter(status=TaskStatus.COMPLETE).count()

    @property
    def total_estimated_cost(self):
        return sum(t.estimated_cost for t in self.tasks.all())

    @property
    def total_actual_cost(self):
        return sum(t.actual_cost for t in self.tasks.all())

    @property
    def total_estimated_hours(self):
        return sum(t.estimated_hours for t in self.tasks.all())

    @property
    def total_actual_hours(self):
        return sum(t.actual_hours for t in self.tasks.all())


class ProjectMember(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='project_memberships'
    )
    role = models.CharField(
        max_length=20,
        choices=ProjectRole.choices,
        default=ProjectRole.MEMBER
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('project', 'user')
        indexes = [
            models.Index(fields=['project', 'role']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.project.name} ({self.role})"

    def clean(self):
        if self.user and self.user.username.lower() == 'aman':
            raise ValidationError({'user': "Master administrator 'aman' cannot be assigned to project memberships."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Task(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    parent_task = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subtasks'
    )
    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True, default='')
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(default=timezone.now)
    duration_days = models.PositiveIntegerField(default=1)
    progress = models.PositiveSmallIntegerField(default=0)  # 0 to 100
    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.NOT_STARTED,
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=TaskPriority.choices,
        default=TaskPriority.MEDIUM,
        db_index=True
    )
    is_milestone = models.BooleanField(default=False)
    assignee = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks'
    )
    sort_order = models.PositiveIntegerField(default=0, db_index=True)

    # Baseline Tracking
    baseline_start_date = models.DateField(null=True, blank=True)
    baseline_end_date = models.DateField(null=True, blank=True)
    baseline_duration_days = models.PositiveIntegerField(null=True, blank=True)

    # Critical Path & Float
    is_critical = models.BooleanField(default=False, db_index=True)
    total_float_days = models.IntegerField(default=0)
    early_start = models.DateField(null=True, blank=True)
    early_finish = models.DateField(null=True, blank=True)
    late_start = models.DateField(null=True, blank=True)
    late_finish = models.DateField(null=True, blank=True)

    # Financials (INR ₹) & Effort (Man-Hours)
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, help_text="Estimated cost in INR (₹)")
    actual_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, help_text="Realized cost in INR (₹)")
    estimated_hours = models.PositiveIntegerField(default=0, help_text="Estimated effort in man-hours")
    actual_hours = models.PositiveIntegerField(default=0, help_text="Realized effort in man-hours")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'start_date', 'id']
        indexes = [
            models.Index(fields=['project', 'parent_task', 'sort_order']),
            models.Index(fields=['project', 'status']),
            models.Index(fields=['project', 'start_date', 'end_date']),
            models.Index(fields=['project', 'is_critical']),
        ]

    def __str__(self):
        return f"[{self.project.code}] {self.name}"

    def clean(self):
        if self.assignee and self.assignee.username == 'aman':
            raise ValidationError({'assignee': "Master user 'aman' is reserved for administration only and cannot be assigned to tasks."})

        s_date = self.start_date.date() if isinstance(self.start_date, (timezone.datetime, datetime)) else self.start_date
        e_date = self.end_date.date() if isinstance(self.end_date, (timezone.datetime, datetime)) else self.end_date

        if self.assignee and self.assignee.username.lower() == 'aman':
            raise ValidationError({'assignee': "Master administrator 'aman' is reserved for administration only and cannot be assigned to tasks."})

        if s_date and e_date and e_date < s_date:
            raise ValidationError({'end_date': "End date cannot be earlier than start date."})

        if self.parent_task:
            if self.parent_task_id == self.id:
                raise ValidationError({'parent_task': "A task cannot be its own parent."})
            if self.parent_task.project_id != self.project_id:
                raise ValidationError({'parent_task': "Parent task must belong to the same project."})
            
            # Check ancestor loop
            ancestor = self.parent_task
            visited = {self.id} if self.id else set()
            while ancestor:
                if ancestor.id in visited:
                    raise ValidationError({'parent_task': "Circular parent hierarchy detected."})
                visited.add(ancestor.id)
                ancestor = ancestor.parent_task

    def save(self, *args, **kwargs):
        if self.assignee and self.assignee.username.lower() == 'aman':
            raise ValidationError("Master administrator 'aman' is reserved for administration only and cannot be assigned to tasks.")

        s_date = self.start_date.date() if isinstance(self.start_date, (timezone.datetime, datetime)) else self.start_date
        e_date = self.end_date.date() if isinstance(self.end_date, (timezone.datetime, datetime)) else self.end_date

        # Calculate duration
        if s_date and e_date:
            self.duration_days = max(1, (e_date - s_date).days + 1)
        elif not self.duration_days:
            self.duration_days = 1

        if self.is_milestone:
            if self.start_date:
                self.end_date = self.start_date
            self.duration_days = 1

        # Adjust status automatically
        if self.progress == 100 and self.status != TaskStatus.COMPLETE:
            self.status = TaskStatus.COMPLETE
        elif self.progress > 0 and self.progress < 100 and self.status == TaskStatus.NOT_STARTED:
            self.status = TaskStatus.IN_PROGRESS
        elif self.progress == 0 and self.status == TaskStatus.COMPLETE:
            self.status = TaskStatus.NOT_STARTED

        # Overdue check
        today = date.today()
        if e_date and e_date < today and self.progress < 100:
            if self.status != TaskStatus.COMPLETE:
                self.status = TaskStatus.DELAYED

        super().save(*args, **kwargs)

    @property
    def is_parent(self):
        return self.subtasks.exists()

    @property
    def schedule_variance_days(self):
        """Variance against baseline end date (positive = behind schedule)."""
        if self.baseline_end_date and self.end_date:
            return (self.end_date - self.baseline_end_date).days
        return 0

    @property
    def wbs_code(self):
        """Calculate dynamic WBS hierarchical index (e.g. 1, 1.1, 1.1.1, 2, 2.1)."""
        if hasattr(self, '_computed_wbs') and self._computed_wbs:
            return self._computed_wbs
        if not self.parent_task_id:
            siblings = Task.objects.filter(project_id=self.project_id, parent_task__isnull=True).order_by('sort_order', 'id')
            ids = list(siblings.values_list('id', flat=True))
            try:
                idx = ids.index(self.id) + 1
                return f"{idx}"
            except ValueError:
                return "1"
        else:
            parent = self.parent_task
            parent_code = parent.wbs_code if parent else "1"
            siblings = Task.objects.filter(project_id=self.project_id, parent_task_id=self.parent_task_id).order_by('sort_order', 'id')
            ids = list(siblings.values_list('id', flat=True))
            try:
                idx = ids.index(self.id) + 1
                return f"{parent_code}.{idx}"
            except ValueError:
                return f"{parent_code}.1"

    @property
    def depth(self):
        """Hierarchical nesting depth (0 = root task, 1 = subtask, 2 = sub-subtask)."""
        if hasattr(self, '_computed_depth'):
            return self._computed_depth
        d = 0
        p = self.parent_task
        while p and d < 10:
            d += 1
            p = p.parent_task
        return d

    def recalculate_from_subtasks(self):
        """Roll up dates, progress, and costs from children subtasks."""
        children = self.subtasks.all()
        if not children.exists():
            return
        
        min_start = min((c.start_date for c in children if c.start_date), default=None)
        max_end = max((c.end_date for c in children if c.end_date), default=None)
        
        if min_start and max_end:
            self.start_date = min_start
            self.end_date = max_end
            self.duration_days = max(1, (max_end - min_start).days + 1)
        
        total_child_duration = sum(c.duration_days for c in children)
        if total_child_duration > 0:
            weighted_sum = sum(c.progress * c.duration_days for c in children)
            self.progress = round(weighted_sum / total_child_duration)
        else:
            self.progress = round(sum(c.progress for c in children) / children.count())
        
        # Roll up costs and hours
        self.estimated_cost = sum(c.estimated_cost for c in children)
        self.actual_cost = sum(c.actual_cost for c in children)
        self.estimated_hours = sum(c.estimated_hours for c in children)
        self.actual_hours = sum(c.actual_hours for c in children)

        if self.progress == 100:
            self.status = TaskStatus.COMPLETE
        elif self.progress > 0:
            self.status = TaskStatus.IN_PROGRESS
        else:
            self.status = TaskStatus.NOT_STARTED
            
        Task.objects.filter(pk=self.pk).update(
            start_date=self.start_date,
            end_date=self.end_date,
            duration_days=self.duration_days,
            progress=self.progress,
            status=self.status,
            estimated_cost=self.estimated_cost,
            actual_cost=self.actual_cost,
            estimated_hours=self.estimated_hours,
            actual_hours=self.actual_hours,
            updated_at=timezone.now()
        )
        
        if self.parent_task:
            self.parent_task.recalculate_from_subtasks()


class TaskDependency(models.Model):
    from_task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='successors'
    )  # Predecessor task
    to_task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='predecessors'
    )  # Dependent successor task
    dependency_type = models.CharField(
        max_length=4,
        choices=DependencyType.choices,
        default=DependencyType.FINISH_TO_START
    )
    lag_days = models.IntegerField(default=0, help_text="Lag in days between tasks (can be negative for lead)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_task', 'to_task')
        indexes = [
            models.Index(fields=['from_task', 'to_task']),
        ]

    def __str__(self):
        return f"{self.from_task.name} -> {self.to_task.name} ({self.dependency_type})"

    def clean(self):
        if self.from_task_id == self.to_task_id:
            raise ValidationError("A task cannot depend on itself.")
        
        if self.from_task.project_id != self.to_task.project_id:
            raise ValidationError("Dependencies can only exist between tasks in the same project.")
        
        from projects.services.scheduler import check_dependency_cycle
        if check_dependency_cycle(self.from_task_id, self.to_task_id):
            raise ValidationError("Circular dependency detected! This link creates an infinite scheduling loop.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class TaskComment(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='task_comments'
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on {self.task.name}"


class TaskAttachment(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    file = models.FileField(upload_to='attachments/%Y/%m/')
    filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='uploaded_attachments'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.task.name})"


class ActivityLog(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='activity_logs'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    action = models.CharField(max_length=100)
    details = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.project.code}] {self.user.username}: {self.action}"
