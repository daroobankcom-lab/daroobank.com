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
