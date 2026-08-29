from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from projects.models import Project, ProjectMember, Task
from teams.models import Department, Team, TeamMembership


MASTER_USERNAME = 'aman'


def ensure_master_user():
    """Ensures the master user 'aman' exists with full superuser privileges."""
    user, created = User.objects.get_or_create(
        username=MASTER_USERNAME,
        defaults={
            'email': 'aman@ganttexcel.local',
            'first_name': 'Aman',
            'last_name': 'Admin',
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
        }
    )
    needs_save = False
    if not user.is_superuser or not user.is_staff or not user.is_active:
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        needs_save = True
    if created or not user.has_usable_password():
        user.set_password('123456')
        needs_save = True
    if needs_save:
        user.save()
    return user


@receiver(pre_delete, sender=User)
def protect_master_user_delete(sender, instance, **kwargs):
    """Prevents deleting the master administrator 'aman' under any circumstances."""
    if instance.username.lower() == MASTER_USERNAME.lower():
        raise ValidationError(f"The master administrator '{MASTER_USERNAME}' is permanently protected and cannot be deleted.")


@receiver(pre_save, sender=User)
def protect_master_user_save(sender, instance, **kwargs):
    """Enforces that master user 'aman' remains active, staff, superuser, and cannot be renamed."""
    if instance.pk:
        try:
            original = User.objects.get(pk=instance.pk)
            if original.username.lower() == MASTER_USERNAME.lower() and instance.username.lower() != MASTER_USERNAME.lower():
                raise ValidationError(f"The master administrator '{MASTER_USERNAME}' cannot be renamed.")
        except User.DoesNotExist:
            pass

    if instance.username.lower() == MASTER_USERNAME.lower():
        instance.is_staff = True
        instance.is_superuser = True
        instance.is_active = True


@receiver(pre_save, sender=ProjectMember)
def protect_master_project_member_save(sender, instance, **kwargs):
    """Prevents assigning master user 'aman' to any project memberships."""
    if instance.user and instance.user.username.lower() == MASTER_USERNAME.lower():
        raise ValidationError(f"Master administrator '{MASTER_USERNAME}' cannot be assigned to project memberships.")


@receiver(pre_save, sender=Task)
def protect_master_user_from_task_assignment(sender, instance, **kwargs):
    """Enforces that master user 'aman' cannot be assigned to project tasks."""
    if instance.assignee and instance.assignee.username.lower() == MASTER_USERNAME.lower():
        raise ValidationError(f"Master administrator '{MASTER_USERNAME}' is reserved for platform administration only and cannot be assigned to tasks.")


@receiver(pre_save, sender=TeamMembership)
def protect_master_user_from_team_membership(sender, instance, **kwargs):
    """Enforces that master user 'aman' cannot be added to teams or set as reporting manager."""
    if instance.user and instance.user.username.lower() == MASTER_USERNAME.lower():
        raise ValidationError(f"Master administrator '{MASTER_USERNAME}' is reserved for platform administration only and cannot be added to teams.")
    if instance.reporting_to and instance.reporting_to.username.lower() == MASTER_USERNAME.lower():
        raise ValidationError(f"Master administrator '{MASTER_USERNAME}' cannot be set as a reporting manager.")


@receiver(pre_save, sender=Team)
def protect_master_user_from_team_lead(sender, instance, **kwargs):
    """Enforces that master user 'aman' cannot be assigned as a team lead."""
    if instance.lead and instance.lead.username.lower() == MASTER_USERNAME.lower():
        raise ValidationError(f"Master administrator '{MASTER_USERNAME}' cannot be assigned as a team lead.")


@receiver(pre_save, sender=Department)
def protect_master_user_from_department_head(sender, instance, **kwargs):
    """Enforces that master user 'aman' cannot be assigned as a department head."""
    if instance.head and instance.head.username.lower() == MASTER_USERNAME.lower():
        raise ValidationError(f"Master administrator '{MASTER_USERNAME}' cannot be assigned as a department head.")
