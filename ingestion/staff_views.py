"""Read-only local schedule inspection, not an operational control."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils.timezone import now
from django.views.decorators.http import require_safe

from .forms import WindowForm
from .schedule import ScheduleError, inspect_window

VIEW_PERMS = ('catalog.view_productcandidate', 'pricing.view_pricecandidate', 'sources.view_sourceclaim')


@login_required(login_url='staff_login')
@require_safe
def window(request):
    user = request.user
    if not user.is_active or not user.is_staff or not any(user.has_perm(perm) for perm in VIEW_PERMS):
        raise PermissionDenied
    form = WindowForm(request.GET if request.GET else None)
    plan = None
    planning_error = ''
    if not request.GET or form.is_valid():
        try:
            plan = inspect_window(at=now(), **(form.cleaned_data if request.GET else {}))
        except ScheduleError as exc:
            if request.GET:
                form.add_error(None, str(exc))
            else:
                planning_error = str(exc)
    return render(request, 'staff/ingestion_window.html', {
        'page_title': 'بررسی پنجره جمع‌آوری | داروبانک', 'description': 'محاسبه آزمایشی پنجره زمانی.',
        'noindex': True, 'private_staff': True, 'form': form,
        'plan': plan.as_dict() if plan else None, 'planning_error': planning_error,
        'can_products': user.has_perm(VIEW_PERMS[0]), 'can_prices': user.has_perm(VIEW_PERMS[1]),
        'can_sources': user.has_perm(VIEW_PERMS[2]),
    })


@login_required(login_url='staff_login')
@require_safe
def receipts(request):
    from django.core.paginator import Paginator
    from django.http import HttpResponseBadRequest
    from .models import ImportReceipt
    from .receipts import visible_kinds

    kinds = visible_kinds(request.user)
    if not kinds:
        raise PermissionDenied
    selected = request.GET.get('kind', '')
    if selected not in ('', ImportReceipt.PRODUCT, ImportReceipt.PRICE):
        return HttpResponseBadRequest('Invalid filter.')
    if selected and selected not in kinds:
        raise PermissionDenied
    rows = ImportReceipt.objects.filter(kind__in=[selected] if selected else kinds).select_related('actor').order_by('-pk')
    page = Paginator(rows, 20).get_page(request.GET.get('page', 1))
    return render(request, 'staff/import_receipts.html', {
        'page_title': 'رسیدهای ورود فایل | داروبانک', 'description': 'خلاصه ثبت‌های داخلی فایل.',
        'noindex': True, 'private_staff': True, 'page': page, 'kind': selected,
        'can_products': ImportReceipt.PRODUCT in kinds, 'can_prices': ImportReceipt.PRICE in kinds,
    })


@login_required(login_url='staff_login')
@require_safe
def receipt_detail(request, pk):
    from django.http import Http404
    from django.shortcuts import get_object_or_404
    from .models import ImportReceipt
    from .receipts import manifest_context, visible_kinds

    kinds = visible_kinds(request.user)
    if not kinds:
        raise PermissionDenied
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Receipt not found')
    receipt = get_object_or_404(ImportReceipt.objects.select_related('actor').filter(kind__in=kinds), pk=pk)
    return render(request, 'staff/import_receipt_detail.html', {
        'page_title': 'رسید ورود فایل | داروبانک', 'description': 'خلاصه یک ثبت داخلی.',
        'noindex': True, 'private_staff': True, 'receipt': receipt,
        'manifest': manifest_context(receipt, request.GET.get('page', 1)),
    })
