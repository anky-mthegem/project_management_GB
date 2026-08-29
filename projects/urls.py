from django.urls import path, include
from projects import views
from projects import admin_panel

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('projects/create/', views.create_project_view, name='create_project'),
    path('projects/<slug:code>/', views.project_gantt_view, name='project_gantt'),
    
    # Master Admin Panel & Governance
    path('admin-panel/', admin_panel.admin_panel_view, name='admin_panel'),
    path('admin/user-governance/', admin_panel.admin_panel_view, name='user_governance'),
    path('admin-panel/create-dept/', admin_panel.admin_create_department_view, name='admin_create_department'),
    path('admin-panel/create-team/', admin_panel.admin_create_team_view, name='admin_create_team'),
    path('admin-panel/seed-teams/', admin_panel.admin_seed_teams_view, name='admin_seed_teams'),
    path('admin-panel/seed-projects/', admin_panel.admin_seed_projects_view, name='admin_seed_projects'),

    path('team/', admin_panel.admin_panel_view, name='team_management'),  # Seamlessly uses simplified admin hub
    path('team/create/', views.create_team_user_view, name='create_team_user'),
    path('team/<int:user_id>/edit/', views.edit_team_user_view, name='edit_team_user'),
    path('team/<int:user_id>/approve/', views.approve_team_user_view, name='approve_team_user'),
    path('team/<int:user_id>/toggle-status/', views.toggle_team_user_status_view, name='toggle_team_user_status'),
    path('team/<int:user_id>/reject/', views.reject_team_user_view, name='reject_team_user'),
    path('team/<int:user_id>/delete/', views.delete_team_user_view, name='delete_team_user'),
    
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('pending-approval/', views.pending_approval_view, name='pending_approval'),
    path('logout/', views.logout_view, name='logout'),
    path('api/', include('projects.api.urls')),
]
