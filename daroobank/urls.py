from django.urls import path
from catalog import views, staff_views as product_staff_views, quality_views, identity_views
from pricing import staff_views
from sources import staff_views as source_staff_views
from ingestion import staff_views as ingestion_staff_views
from clinical import staff_views as clinical_staff_views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('api/v1/search/', views.search_api, name='search_api'),
    path('api/v1/openapi.json', views.openapi_document, name='openapi_document'),
    path('products/<int:pk>/', views.presentation_detail, name='presentation_detail'),
    path('api/v1/products/<int:pk>/', views.presentation_api, name='presentation_api'),
    path('prices/', views.prices, name='prices'),
    path('about/', views.about, name='about'),
    path('staff/login/', staff_views.StaffLoginView.as_view(), name='staff_login'),
    path('staff/logout/', staff_views.StaffLogoutView.as_view(), name='staff_logout'),
    path('staff/operations/window/', ingestion_staff_views.window, name='staff_ingestion_window'),
    path('staff/operations/imports/', ingestion_staff_views.receipts, name='staff_import_receipts'),
    path('staff/operations/imports/<int:pk>/', ingestion_staff_views.receipt_detail, name='staff_import_receipt_detail'),
    path('staff/clinical/', clinical_staff_views.drafts, name='staff_clinical_drafts'),
    path('staff/clinical/new/', clinical_staff_views.create, name='staff_clinical_create'),
    path('staff/clinical/<int:pk>/revise/', clinical_staff_views.revise, name='staff_clinical_revise'),
    path('staff/clinical/<int:pk>/references/new/', clinical_staff_views.reference_create, name='staff_clinical_reference_create'),
    path('staff/clinical/<int:pk>/review/', clinical_staff_views.review, name='staff_clinical_review'),
    path('staff/clinical/<int:pk>/', clinical_staff_views.detail, name='staff_clinical_detail'),
    path('staff/sources/', source_staff_views.claims, name='staff_sources'),
    path('staff/sources/new/', source_staff_views.create, name='staff_source_create'),
    path('staff/sources/<int:pk>/review/', source_staff_views.review, name='staff_source_review'),
    path('staff/sources/<int:pk>/', source_staff_views.detail, name='staff_source_detail'),
    path('staff/catalog/identity/', identity_views.listing, name='staff_identity_list'),
    path('staff/catalog/identity/new/<str:kind>/', identity_views.create, name='staff_identity_create'),
    path('staff/catalog/identity/package/<int:pk>/revise/', identity_views.revise, name='staff_identity_revise'),
    path('staff/catalog/identity/package/<int:pk>/review/', identity_views.review, name='staff_identity_review'),
    path('staff/catalog/identity/<str:kind>/<int:pk>/', identity_views.detail, name='staff_identity_detail'),
    path('staff/catalog/quality/', quality_views.quality, name='staff_catalog_quality'),
    path('staff/catalog/quality/<int:pk>/irc/', quality_views.quality_irc, name='staff_catalog_quality_irc'),
    path('staff/products/', product_staff_views.candidates, name='staff_products'),
    path('staff/products/import/', product_staff_views.upload, name='staff_product_upload'),
    path('staff/products/<int:pk>/review/', product_staff_views.review, name='staff_product_review'),
    path('staff/products/<int:pk>/', product_staff_views.detail, name='staff_product_detail'),
    path('staff/prices/', staff_views.price_candidates, name='staff_prices'),
    path('staff/prices/import/', staff_views.price_upload, name='staff_price_upload'),
    path('staff/prices/<int:pk>/review/', staff_views.price_review, name='staff_price_review'),
    path('staff/prices/<int:pk>/', staff_views.price_candidate_detail, name='staff_price_detail'),
    path('robots.txt', views.robots, name='robots'),
    path('sitemap.xml', views.sitemap, name='sitemap'),
]
