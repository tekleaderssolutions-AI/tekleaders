from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/health', views.api_health, name='api_health'),
    path('health', views.api_health, name='health'),
    path('init-db', views.init_db, name='init_db'),
    path('jd/analyze/pdf', views.analyze_jd_pdf, name='analyze_jd_pdf'),
    path('resumes/upload', views.upload_resumes, name='upload_resumes'),
    path('match/top-by-role', views.get_top_matches_by_role, name='match_top_by_role'),
]
