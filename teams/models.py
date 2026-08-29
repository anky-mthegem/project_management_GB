from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver


class RoleChoices(models.TextChoices):
    GENERAL_MANAGER = 'GM', 'General Manager'
    MANAGER = 'MGR', 'Manager'
    TEAM_MEMBER = 'TM', 'Team Member'


class ApprovalStatus(models.TextChoices):
    PENDING = 'PENDING_APPROVAL', 'Pending Approval'
    ACTIVE = 'ACTIVE', 'Active'
    REJECTED = 'REJECTED', 'Rejected'


class Department(models.Model):
    name = models.CharField(max_length=120, db_index=True)
    code = models.SlugField(max_length=64, unique=True, blank=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sub_departments'
    )
    description = models.TextField(blank=True, default='')
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='headed_departments'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} / {self.name}"
        return self.name

    def clean(self):
        super().clean()
        if self.head and self.head.username.lower() == 'aman':
            raise ValidationError({'head': "Master administrator 'aman' cannot be assigned as a department head."})

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.code:
            base = slugify(self.name)[:50] or 'dept'
            cand = base
            i = 1
            while Department.objects.filter(code=cand).exclude(pk=self.pk).exists():
                cand = f"{base}-{i}"
                i += 1
            self.code = cand
        super().save(*args, **kwargs)

    @property
    def total_members_count(self):
        return sum(t.memberships.count() for t in self.teams.all())


class Team(models.Model):
    name = models.CharField(max_length=120, db_index=True)
    code = models.SlugField(max_length=64, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teams'
    )
    parent_team = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sub_teams'
    )
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='led_teams'
    )
    color = models.CharField(max_length=20, default='#6366f1', help_text="Badge hex color for UI cards")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Team'
        verbose_name_plural = 'Teams'

    def __str__(self):
        if self.department:
            return f"[{self.department.name}] {self.name}"
        return self.name

    def clean(self):
        super().clean()
        if self.lead and self.lead.username.lower() == 'aman':
            raise ValidationError({'lead': "Master administrator 'aman' cannot be assigned as a team lead."})

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.code:
            base = slugify(self.name)[:50] or 'team'
            cand = base
            i = 1
            while Team.objects.filter(code=cand).exclude(pk=self.pk).exists():
                cand = f"{base}-{i}"
                i += 1
            self.code = cand
        super().save(*args, **kwargs)

    @property
    def members_count(self):
        return self.memberships.count()

    @property
    def direct_members(self):
        return self.memberships.select_related('user', 'reporting_to').all()

    @property
    def active_projects(self):
        return self.assigned_projects.filter(status='ACTIVE')


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    role = models.CharField(
        max_length=10,
        choices=RoleChoices.choices,
        default=RoleChoices.TEAM_MEMBER
    )
    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )
    reporting_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='profile_direct_reports'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['role', 'user__first_name']
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} [{self.get_role_display()}] - {self.get_status_display()}"

    def clean(self):
        super().clean()
        if self.user and self.user.username.lower() == 'aman':
            if self.reporting_to is not None:
                raise ValidationError({'reporting_to': "Master administrator 'aman' cannot have a reporting manager."})

        if self.reporting_to and self.reporting_to.username.lower() == 'aman':
            raise ValidationError({'reporting_to': "Master administrator 'aman' cannot be assigned as a reporting manager."})

        if self.user_id and self.reporting_to_id and self.user_id == self.reporting_to_id:
            raise ValidationError({'reporting_to': "A user cannot report to themselves."})

        # 3-Tier Operational Org Hierarchy:
        # GM -> MGR -> TM
        if self.user and self.user.username.lower() != 'aman':
            if self.role == RoleChoices.TEAM_MEMBER:
                if self.reporting_to_id:
                    rep_prof = UserProfile.objects.filter(user_id=self.reporting_to_id).first()
                    if rep_prof and rep_prof.role not in (RoleChoices.MANAGER, RoleChoices.GENERAL_MANAGER):
                        raise ValidationError({'reporting_to': f"Team Members must report to a Manager (MGR), not {rep_prof.get_role_display()}."})
                if self.user_id and UserProfile.objects.filter(reporting_to_id=self.user_id).exclude(pk=self.pk).exists():
                    raise ValidationError({'role': "Team Members (TM) cannot have direct reports."})

            elif self.role == RoleChoices.MANAGER:
                if self.reporting_to_id:
                    rep_prof = UserProfile.objects.filter(user_id=self.reporting_to_id).first()
                    if rep_prof and rep_prof.role != RoleChoices.GENERAL_MANAGER:
                        raise ValidationError({'reporting_to': f"Managers must report directly to a General Manager (GM), not {rep_prof.get_role_display()}."})

            elif self.role == RoleChoices.GENERAL_MANAGER:
                if self.reporting_to_id:
                    rep_prof = UserProfile.objects.filter(user_id=self.reporting_to_id).first()
                    if rep_prof and rep_prof.role != RoleChoices.GENERAL_MANAGER:
                        raise ValidationError({'reporting_to': f"General Managers can only report to another General Manager (GM), not {rep_prof.get_role_display()}."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class TeamMembership(models.Model):
    ROLE_CHOICES = [
        ('GM', 'General Manager'),
        ('MGR', 'Manager / Team Lead'),
        ('TM', 'Team Member'),
        ('Lead', 'Team Lead / Manager'),
        ('Tech Lead', 'Technical Lead / Architect'),
        ('Senior Developer', 'Senior Developer'),
        ('Developer', 'Software Engineer'),
        ('UI/UX Designer', 'UI/UX Designer'),
        ('Product Manager', 'Product Manager'),
        ('QA Engineer', 'QA / Automation Engineer'),
        ('DevOps Engineer', 'DevOps / SRE Engineer'),
        ('Business Analyst', 'Business Analyst'),
        ('Member', 'Team Contributor / Member'),
    ]

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='team_memberships'
    )
    role = models.CharField(max_length=64, choices=ROLE_CHOICES, default='Member')
    reporting_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='direct_reports'
    )
    joined_at = models.DateField(default=timezone.now)

    class Meta:
        ordering = ['role', 'user__first_name']
        constraints = [
            models.UniqueConstraint(fields=['team', 'user'], name='unique_team_user_membership')
        ]
        verbose_name = 'Team Membership'
        verbose_name_plural = 'Team Memberships'

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.role} ({self.team.name})"

    def clean(self):
        super().clean()
        if self.user and self.user.username.lower() == 'aman':
            raise ValidationError({'user': "Master administrator 'aman' cannot be added as a team member."})
        if self.reporting_to and self.reporting_to.username.lower() == 'aman':
            raise ValidationError({'reporting_to': "Master administrator 'aman' cannot be set as a reporting manager."})
        if self.user_id and self.reporting_to_id and self.user_id == self.reporting_to_id:
            raise ValidationError({'reporting_to': "A team member cannot report to themselves."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def direct_reports_count(self):
        return TeamMembership.objects.filter(reporting_to=self.user).count()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """Automatically ensure a UserProfile exists for every User created."""
    is_aman = (instance.username.lower() == 'aman')
    if created:
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={
                'role': RoleChoices.GENERAL_MANAGER if is_aman else RoleChoices.TEAM_MEMBER,
                'status': ApprovalStatus.ACTIVE if (is_aman or instance.is_active) else ApprovalStatus.PENDING,
            }
        )
    else:
        # If user is updated and profile exists, sync status if needed
        profile = getattr(instance, 'profile', None)
        if profile is None:
            UserProfile.objects.get_or_create(
                user=instance,
                defaults={
                    'role': RoleChoices.GENERAL_MANAGER if is_aman else RoleChoices.TEAM_MEMBER,
                    'status': ApprovalStatus.ACTIVE if (is_aman or instance.is_active) else ApprovalStatus.PENDING,
                }
            )
        elif is_aman:
            profile.status = ApprovalStatus.ACTIVE
            profile.save(update_fields=['status'])
