from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from teams.models import Department, Team, TeamMembership


class UserRegistrationForm(forms.Form):
    name = forms.CharField(
        max_length=150,
        required=True,
        label="Full Name",
        widget=forms.TextInput(attrs={
            'class': 'block w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500',
            'placeholder': 'e.g. Rahul Sharma'
        })
    )
    username = forms.CharField(
        max_length=50,
        required=True,
        label="Employee ID / User Handle",
        widget=forms.TextInput(attrs={
            'class': 'block w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500 font-mono',
            'placeholder': 'e.g. rahul_sharma'
        })
    )
    email = forms.EmailField(
        required=True,
        label="Work Email Address",
        widget=forms.EmailInput(attrs={
            'class': 'block w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500',
            'placeholder': 'rahul@company.com'
        })
    )
    password = forms.CharField(
        required=True,
        min_length=6,
        label="Account Password",
        widget=forms.PasswordInput(attrs={
            'class': 'block w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500',
            'placeholder': '••••••••'
        })
    )
    confirm_password = forms.CharField(
        required=True,
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            'class': 'block w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500',
            'placeholder': '••••••••'
        })
    )

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip().lower()
        if not username:
            raise ValidationError("Employee ID / User Handle is required.")
        if username == 'aman':
            raise ValidationError("The username 'aman' is reserved for system administration.")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError(f"A user with ID '@{username}' is already registered.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data

    def save(self):
        name = self.cleaned_data['name'].strip()
        parts = name.split(' ', 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ''
        username = self.cleaned_data['username']
        email = self.cleaned_data['email'].strip()
        password = self.cleaned_data['password']

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_active=False,  # Created in Pending Approval state awaiting admin @aman
            is_staff=False,
            is_superuser=False
        )
        return user


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'parent', 'head', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none',
                'placeholder': 'e.g. Engineering & Technology'
            }),
            'parent': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'head': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none',
                'rows': 2,
                'placeholder': 'Department purpose and objectives...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['head'].queryset = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name', 'department', 'parent_team', 'lead', 'color', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none',
                'placeholder': 'e.g. Core Platform Engineering'
            }),
            'department': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'parent_team': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'lead': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'color': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none h-10',
                'type': 'color'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none',
                'rows': 3,
                'placeholder': 'Team responsibilities, domain, and focus areas...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['lead'].queryset = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')


class TeamMembershipForm(forms.ModelForm):
    class Meta:
        model = TeamMembership
        fields = ['team', 'user', 'role', 'reporting_to']
        widgets = {
            'team': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'user': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'role': forms.Select(choices=TeamMembership.ROLE_CHOICES, attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
            'reporting_to': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:ring-2 focus:ring-brand-500 focus:outline-none'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')
        self.fields['reporting_to'].queryset = User.objects.filter(is_active=True).exclude(username__iexact='aman').order_by('first_name', 'username')
