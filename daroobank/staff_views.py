"""Read-only navigation for the development-only staff workspace."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_safe

from ingestion.receipts import visible_kinds
from ingestion.staff_views import VIEW_PERMS as WINDOW_VIEW_PERMS


@login_required(login_url='staff_login')
@require_safe
def workspace(request):
    user = request.user
    if not user.is_active or not user.is_staff:
        raise PermissionDenied
    # Navigation is only a convenience: each destination enforces its own
    # authorization and the staff middleware independently gates all /staff/.
    destinations = [
        ('catalog.view_productcandidate', 'staff_products', 'نامزدهای فرآورده', 'داده‌های مرحله‌ای برای بررسی اولیه.'),
        ('pricing.view_pricecandidate', 'staff_prices', 'نامزدهای قیمت', 'داده‌های مرحله‌ای قیمت، بدون انتشار.'),
        ('sources.view_sourceclaim', 'staff_sources', 'ادعاهای منبع', 'ادعاهای داخلی درباره منابع و مجوزها.'),
        ('clinical.view_clinicaldraft', 'staff_clinical_drafts', 'پیش‌نویس‌های علمی', 'گزاره‌های ساختگی و بررسی مقدماتی.'),
        ('catalog.view_identityworkspace', 'staff_identity_list', 'هویت ساختگی کاتالوگ', 'ساختار آزمایشی ماده، فرآورده و بسته.'),
        ('catalog.view_productpresentation', 'staff_catalog_quality', 'بازرسی کاتالوگ', 'بررسی محدود فنی رکوردهای کاتالوگ.'),
    ]
    links = [{'route': route, 'label': label, 'description': description}
             for permission, route, label, description in destinations if user.has_perm(permission)]
    if visible_kinds(user):
        links.append({'route': 'staff_import_receipts', 'label': 'رسیدهای ورود فایل',
                      'description': 'خلاصه ورودهای قابل مشاهده بر اساس دسترسی.'})
    if any(user.has_perm(permission) for permission in WINDOW_VIEW_PERMS):
        links.append({'route': 'staff_ingestion_window', 'label': 'پنجره جمع‌آوری',
                      'description': 'محاسبه آزمایشی زمان؛ بدون اجرای جمع‌آوری.'})
    return render(request, 'staff/workspace.html', {
        'page_title': 'فضای داخلی | داروبانک', 'description': 'راهنمای بخش‌های داخلی آزمایشی.',
        'private_staff': True, 'noindex': True, 'links': links,
    })
