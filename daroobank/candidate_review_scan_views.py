"""Private server-rendered product and price review scan endpoints."""
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from catalog.intake import MAX_PK, require_staff
from catalog.models import ProductCandidate
from pricing.models import PriceCandidate

from .candidate_review_scan import CATEGORIES, ReviewScanNotFound, inspect_reviews
from .scan_input import parse_scan_after

_PAGES = {
    'product': (ProductCandidate, 'catalog.view_productcandidate', 'staff_product_detail',
                'staff_product_review_inspection', 'فرآورده'),
    'price': (PriceCandidate, 'pricing.view_pricecandidate', 'staff_price_detail',
              'staff_price_review_inspection', 'قیمت'),
}


def scan_response(request, pk, domain):
    model, permission, detail_route, scan_route, title = _PAGES[domain]
    require_staff(request.user, permission)
    if type(pk) is not int or not 1 <= pk <= MAX_PK:
        raise Http404('Candidate not found')
    category = request.GET.get('category', '')
    try:
        after = parse_scan_after(request.GET.get('after', '0'), maximum=MAX_PK)
    except ValueError:
        after = None
    common = {'page_title': 'بازرسی بازبینی نامزد | داروبانک', 'description': 'بازرسی محدود بازبینی‌های ساختگی.',
              'noindex': True, 'private_staff': True, 'candidate_id': pk, 'detail_route': detail_route,
              'scan_route': scan_route, 'domain_title': title}
    if after is None or category not in ('', *CATEGORIES):
        get_object_or_404(model, pk=pk)
        return render(request, 'staff/candidate_review_inspection_error.html', common, status=400)
    try:
        report = inspect_reviews(actor=request.user, domain=domain, candidate_id=pk, after=after, category=category)
    except ReviewScanNotFound:
        raise Http404('Candidate not found')
    return render(request, 'staff/candidate_review_inspection.html', {**common, 'report': report})
