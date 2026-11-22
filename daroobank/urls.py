from django.urls import path
from catalog import views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('api/v1/search/', views.search_api, name='search_api'),
    path('prices/', views.prices, name='prices'),
    path('about/', views.about, name='about'),
    path('robots.txt', views.robots, name='robots'),
    path('sitemap.xml', views.sitemap, name='sitemap'),
]
