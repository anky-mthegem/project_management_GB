from django.urls import path
from teams import views, api_views

app_name = 'teams'

urlpatterns = [
    # Dashboard & Dual-View Org Chart
    path('', views.team_hierarchy_view, name='team_hierarchy'),
    
    # Team CRUD
    path('create/', views.team_create_view, name='team_create'),
    path('<int:pk>/', views.team_detail_view, name='team_detail'),
    path('<int:pk>/edit/', views.team_edit_view, name='team_edit'),
    path('<int:pk>/delete/', views.team_delete_view, name='team_delete'),
    
    # Member assignment
    path('<int:pk>/members/add/', views.team_member_add_view, name='team_member_add'),
    path('<int:pk>/members/<int:user_id>/remove/', views.team_member_remove_view, name='team_member_remove'),
    
    # Department CRUD
    path('departments/create/', views.department_create_view, name='department_create'),
    path('departments/<int:pk>/delete/', views.department_delete_view, name='department_delete'),
    
    # Quick Seed Demo Data
    path('seed-demo/', views.seed_demo_teams_view, name='seed_demo'),
    
    # JSON API Endpoints
    path('api/hierarchy/', api_views.team_hierarchy_api, name='api_team_hierarchy'),
    path('api/org-chart/', api_views.org_chart_api, name='api_org_chart'),
    path('api/update-reporting/', api_views.update_reporting_api, name='api_update_reporting'),
]
