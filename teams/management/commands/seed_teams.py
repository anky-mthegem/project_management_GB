from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from teams.models import Department, Team, TeamMembership
from projects.models import Project, Task, ProjectMember


class Command(BaseCommand):
    help = 'Seeds team structure configuring Cool Team with Sundar Nadar as lead and Suraj, Swapnil, Amandeep reporting directly to him.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Configuring & Seeding Team structure for 'Cool Team'..."))

        with transaction.atomic():
            # 1. Ensure master admin 'aman' exists strictly as website manager (no teams, no tasks, no project memberships)
            aman, _ = User.objects.get_or_create(
                username='aman',
                defaults={
                    'first_name': 'Aman',
                    'last_name': 'Admin',
                    'email': 'aman@milestonemanagement.local',
                    'is_staff': True,
                    'is_superuser': True,
                    'is_active': True,
                }
            )
            aman.set_password('123456')
            aman.first_name = 'Aman'
            aman.last_name = 'Admin'
            aman.email = 'aman@milestonemanagement.local'
            aman.is_staff = True
            aman.is_superuser = True
            aman.is_active = True
            aman.save()

            # Clean any legacy aman associations
            Task.objects.filter(assignee=aman).update(assignee=None)
            ProjectMember.objects.filter(user=aman).delete()
            TeamMembership.objects.filter(user=aman).delete()
            TeamMembership.objects.filter(reporting_to=aman).update(reporting_to=None)
            Team.objects.filter(lead=aman).update(lead=None)
            Department.objects.filter(head=aman).update(head=None)

            # Helper to create/update team user with specific credentials
            def get_or_create_user(username, first_name, last_name, email, password='Godrej@123'):
                u, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        'first_name': first_name,
                        'last_name': last_name,
                        'email': email,
                        'is_staff': False,
                        'is_active': True
                    }
                )
                u.first_name = first_name
                u.last_name = last_name
                u.email = email
                u.set_password(password)
                u.is_active = True
                u.save()
                return u

            # 2. Ensure the standard personnel exist as per specified credentials
            # Sundar Nadar (Manager / Lead)
            psundar = get_or_create_user('psundar', 'Sundar', 'Nadar', 'psundar@godrej.com')
            # Suraj Hande (Member)
            skhande = get_or_create_user('skhande', 'Suraj', 'Hande', 'skhande@godrej.com')
            # Amandeep Singh (Member)
            amanr = get_or_create_user('amanr', 'Amandeep', 'Singh', 'amanr@godrej.com')
            # Swapnil Mali (Member)
            smali = get_or_create_user('smali', 'Swapnil', 'Mali', 'smali@godrej.com')

            # Clean up old legacy test usernames if they differ
            legacy_usernames = ['sundar', 'suraj', 'swapnil', 'amandeep', 'sarah_pm']
            for leg_u in User.objects.filter(username__in=legacy_usernames):
                # reassign any tasks to the new accounts before deleting
                if leg_u.username == 'sundar':
                    Task.objects.filter(assignee=leg_u).update(assignee=psundar)
                elif leg_u.username == 'suraj':
                    Task.objects.filter(assignee=leg_u).update(assignee=skhande)
                elif leg_u.username == 'amandeep':
                    Task.objects.filter(assignee=leg_u).update(assignee=amanr)
                elif leg_u.username == 'swapnil':
                    Task.objects.filter(assignee=leg_u).update(assignee=smali)
                leg_u.delete()

            # 3. Create / Get Department
            dept_eng = Department.objects.filter(code='eng-delivery').first()
            if not dept_eng:
                dept_eng = Department.objects.create(
                    name='Engineering & Delivery',
                    code='eng-delivery',
                    head=psundar,
                    description='Core application architecture, project development, and milestone delivery.'
                )
            else:
                dept_eng.head = psundar
                dept_eng.save()

            # 4. Target Team: Identify existing team named "cool team" / "Cool Team" or create it
            team_cool = Team.objects.filter(name__iexact='cool team').first()
            if not team_cool:
                team_cool = Team.objects.create(
                    name='Cool Team',
                    code='cool-team',
                    department=dept_eng,
                    lead=psundar,
                    color='#6366f1',
                    description='Primary execution team responsible for development and milestone achievement.'
                )
            else:
                team_cool.department = dept_eng
                team_cool.lead = psundar
                team_cool.save()

            # Clean any old memberships for Cool Team to ensure clean hierarchy
            TeamMembership.objects.filter(team=team_cool).delete()

            # 5. Assign Memberships and UserProfiles with direct reporting to Sundar Nadar (psundar)
            from teams.models import UserProfile, RoleChoices, ApprovalStatus
            
            # Sundar Nadar - Manager
            prof_sundar, _ = UserProfile.objects.get_or_create(user=psundar)
            prof_sundar.role = RoleChoices.MANAGER
            prof_sundar.status = ApprovalStatus.ACTIVE
            prof_sundar.department = dept_eng
            prof_sundar.reporting_to = None
            prof_sundar.save()

            TeamMembership.objects.create(
                team=team_cool,
                user=psundar,
                role=RoleChoices.MANAGER,
                reporting_to=None,
                joined_at=timezone.now().date() - timedelta(days=90)
            )

            # Suraj Hande -> Reports to Sundar Nadar (Team Member)
            prof_suraj, _ = UserProfile.objects.get_or_create(user=skhande)
            prof_suraj.role = RoleChoices.TEAM_MEMBER
            prof_suraj.status = ApprovalStatus.ACTIVE
            prof_suraj.department = dept_eng
            prof_suraj.reporting_to = psundar
            prof_suraj.save()

            TeamMembership.objects.create(
                team=team_cool,
                user=skhande,
                role=RoleChoices.TEAM_MEMBER,
                reporting_to=psundar,
                joined_at=timezone.now().date() - timedelta(days=60)
            )

            # Amandeep Singh -> Reports to Sundar Nadar (Team Member)
            prof_amanr, _ = UserProfile.objects.get_or_create(user=amanr)
            prof_amanr.role = RoleChoices.TEAM_MEMBER
            prof_amanr.status = ApprovalStatus.ACTIVE
            prof_amanr.department = dept_eng
            prof_amanr.reporting_to = psundar
            prof_amanr.save()

            TeamMembership.objects.create(
                team=team_cool,
                user=amanr,
                role=RoleChoices.TEAM_MEMBER,
                reporting_to=psundar,
                joined_at=timezone.now().date() - timedelta(days=30)
            )

            # Swapnil Mali -> Reports to Sundar Nadar (Team Member)
            prof_smali, _ = UserProfile.objects.get_or_create(user=smali)
            prof_smali.role = RoleChoices.TEAM_MEMBER
            prof_smali.status = ApprovalStatus.ACTIVE
            prof_smali.department = dept_eng
            prof_smali.reporting_to = psundar
            prof_smali.save()

            TeamMembership.objects.create(
                team=team_cool,
                user=smali,
                role=RoleChoices.TEAM_MEMBER,
                reporting_to=psundar,
                joined_at=timezone.now().date() - timedelta(days=45)
            )

            # 6. Link Active Projects to Cool Team
            for p in Project.objects.all():
                p.assigned_team = team_cool
                p.save()

            self.stdout.write(self.style.SUCCESS(
                f"Successfully seeded and configured '{team_cool.name}':\n"
                f"- Manager (MGR): Sundar Nadar (@psundar)\n"
                f"- Team Members (TM): Suraj Hande (@skhande), Swapnil Mali (@smali), Amandeep Singh (@amanr) (all reporting directly to Sundar Nadar)\n"
                f"- Admin 'aman' verified completely detached from teams and tasks."
            ))
