from django.urls import path
from catalog import views
from pricing import staff_views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('api/v1/search/', views.search_api, name='search_api'),
    path('prices/', views.prices, name='prices'),
    path('about/', views.about, name='about'),
    path('staff/login/', staff_views.StaffLoginView.as_view(), name='staff_login'),
    path('staff/logout/', staff_views.StaffLogoutView.as_view(), name='staff_logout'),
    path('staff/prices/', staff_views.price_candidates, name='staff_prices'),
    path('staff/prices/import/', staff_views.price_upload, name='staff_price_upload'),
    path('staff/prices/<int:pk>/review/', staff_views.price_review, name='staff_price_review'),
    path('staff/prices/<int:pk>/', staff_views.price_candidate_detail, name='staff_price_detail'),
    path('robots.txt', views.robots, name='robots'),
    path('sitemap.xml', views.sitemap, name='sitemap'),
]
