"""Development-only, permission-gated viewing of unreviewed price candidates."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from .importer import suggest_product
from .models import PriceCandidate

STATUS_LABELS = {
    'suggested': 'پیشنهاد تطبیق',
    'ambiguous': 'تطبیق مبهم',
    'unmatched': 'بدون تطبیق',
    'invalid': 'اطلاعات نامعتبر',
}
CATEGORY_LABELS = {
    'official_consumer': 'مصرف‌کننده اعلام‌شده',
    'retail': 'خرده‌فروشی',
    'manufacturer': 'تولیدکننده',
    'wholesale': 'عمده‌فروشی',
    'unit': 'واحد',
}
UNIT_LABELS = {
    'package': 'بسته', 'tablet': 'قرص', 'capsule': 'کپسول',
    'ampoule': 'آمپول', 'vial': 'ویال', 'ml': 'میلی‌لیتر',
}


class StaffLoginView(LoginView):
    template_name = 'staff/login.html'
    extra_context = {
        'page_title': 'ورود همکاران | داروبانک',
        'description': 'ورود به بخش داخلی داروبانک.',
        'noindex': True, 'private_staff': True,
    }


class StaffLogoutView(LogoutView):
    next_page = 'home'


def _require_view_permission(user):
    if not user.is_active or not user.is_staff or not user.has_perm('pricing.view_pricecandidate'):
        raise PermissionDenied


def _current_suggestion(candidate):
    """Recalculate against current catalog; malformed stored data fails closed."""
    fields = candidate.source_fields
    required = ('irc', 'manufacturer', 'strength', 'dosage_form', 'package_description')
    if not isinstance(fields, dict) or any(not isinstance(fields.get(key), str) or not fields[key].strip() for key in required):
        return 'invalid', None
    return suggest_product(fields)


@login_required(login_url='staff_login')
@require_safe
def price_candidates(request):
    _require_view_permission(request.user)
    status = request.GET.get('status', '')
    if status and status not in dict(PriceCandidate.MATCH_CHOICES):
        from django.http import HttpResponseBadRequest
        return HttpResponseBadRequest('Invalid filter.')
    stats = {item['match_status']: item['count'] for item in PriceCandidate.objects.values('match_status').annotate(count=Count('id'))}
    rows = PriceCandidate.objects.select_related('suggested_product').order_by('-collected_at', '-pk')
    if status:
        rows = rows.filter(match_status=status)
    page = Paginator(rows, 20).get_page(request.GET.get('page', 1))
    return render(request, 'staff/prices.html', {
        'page_title': 'نامزدهای قیمت | داروبانک', 'description': 'بخش داخلی بررسی داده‌های قیمت.',
        'noindex': True, 'private_staff': True, 'page': page, 'status': status, 'stats': stats,
        'total': sum(stats.values()), 'status_labels': STATUS_LABELS,
    })


@login_required(login_url='staff_login')
@require_safe
def price_candidate_detail(request, pk):
    _require_view_permission(request.user)
    candidate = get_object_or_404(PriceCandidate.objects.select_related('suggested_product'), pk=pk)
    current_status, current_product = _current_suggestion(candidate)
    return render(request, 'staff/price_detail.html', {
        'page_title': 'جزئیات نامزد قیمت | داروبانک', 'description': 'جزئیات داده قیمت برای بررسی داخلی.',
        'noindex': True, 'private_staff': True, 'candidate': candidate, 'current_product': current_product,
        'current_label': STATUS_LABELS[current_status],
        'snapshot_label': STATUS_LABELS.get(candidate.match_status, STATUS_LABELS['invalid']),
        'category_label': CATEGORY_LABELS.get(candidate.price_category, 'نامشخص'),
        'unit_label': UNIT_LABELS.get(candidate.unit, 'نامشخص'),
    })
