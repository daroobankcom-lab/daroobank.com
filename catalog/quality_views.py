"""Private, read-only development catalog diagnostics."""
import re
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .intake import require_staff
from .quality import ISSUE_LABELS, MAX_PK, inspect_batch


@login_required(login_url='staff_login')
@require_safe
def quality(request):
    require_staff(request.user, 'catalog.view_productpresentation')
    raw = request.GET.get('after', '0')
    if not re.fullmatch(r'[0-9]{1,19}', raw) or int(raw) > MAX_PK:
        return HttpResponseBadRequest('Invalid starting ID.')
    report = inspect_batch(after=int(raw))
    for item in report['rows']:
        item['issue_labels'] = [ISSUE_LABELS[code] for code in item['issues']]
    return render(request, 'staff/catalog_quality.html', {
        'page_title': 'بازرسی کاتالوگ | داروبانک', 'description': 'بازرسی داخلی و آزمایشی داده‌ها.',
        'private_staff': True, 'noindex': True, 'report': report,
        'can_candidates': request.user.has_perm('catalog.view_productcandidate'),
    })
