import json
from pathlib import Path

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe
from .services import (MAX_QUERY_LENGTH, MAX_RESULTS, MAX_SEARCH_CANDIDATES, InvalidSearchCursor, InvalidSearchQuery,
                       get_public_presentation, search_product_page, serialize_presentation)

SITE_URL = 'https://daroobank.com'

def render_page(request, template, *, title, description, canonical=None, noindex=False, **context):
    response = render(request, template, {'page_title': title, 'description': description, 'canonical': canonical, 'noindex': noindex, **context})
    if noindex:
        response['X-Robots-Tag'] = 'noindex, follow'
    return response

@require_safe
def home(request):
    return render_page(request, 'home.html', title='داروبانک | مرجع اطلاعات دارویی', description='داروبانک، بستری در حال توسعه برای اطلاعات دارویی و داده‌های قابل پیگیری بازار دارو.', canonical=SITE_URL + '/')

@require_safe
def search(request):
    query = request.GET.get('q', '').strip()[:MAX_QUERY_LENGTH]
    try:
        results, next_cursor = search_product_page(query, request.GET.get('cursor', ''))
        response = render_page(request, 'search.html', title='جست‌وجوی دارو | داروبانک', description='جست‌وجو در اطلاعات دارویی منتشرشده داروبانک.', noindex=True, query=query, results=results, next_cursor=next_cursor)
    except InvalidSearchQuery:
        response = render(request, 'search_query_error.html', {
            'page_title': 'عبارت نامعتبر | داروبانک', 'description': 'عبارت جست‌وجو قابل پردازش نیست.',
            'noindex': True,
        }, status=400)
        response['X-Robots-Tag'] = 'noindex, follow'
    except InvalidSearchCursor:
        response = render(request, 'search_cursor_error.html', {
            'page_title': 'ادامه جست‌وجو | داروبانک', 'description': 'ادامه جست‌وجو در دسترس نیست.',
            'noindex': True, 'query': query,
        }, status=400)
        response['X-Robots-Tag'] = 'noindex, follow'
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response

@require_safe
def prices(request):
    return render_page(request, 'prices.html', title='قیمت دارو | داروبانک', description='وضعیت توسعه و انتشار قیمت دارو در داروبانک.', noindex=True)

@require_safe
def about(request):
    return render_page(request, 'about.html', title='درباره داروبانک', description='درباره رویکرد داروبانک به اطلاعات دارویی و شفافیت منابع.', canonical=SITE_URL + '/about/')

@require_safe
def robots(request):
    return HttpResponse('User-agent: *\nAllow: /\nSitemap: https://daroobank.com/sitemap.xml\n', content_type='text/plain; charset=utf-8')

@require_safe
def sitemap(request):
    # Only substantive, stable pages; search and coming-soon pages are noindex.
    return HttpResponse('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://daroobank.com/</loc></url><url><loc>https://daroobank.com/about/</loc></url></urlset>', content_type='application/xml; charset=utf-8')

@require_safe
def search_api(request):
    query = request.GET.get('q', '').strip()[:MAX_QUERY_LENGTH]
    try:
        results, next_cursor = search_product_page(query, request.GET.get('cursor', ''))
        data = [serialize_presentation(product) for product in results]
        response = JsonResponse({'data': data, 'meta': {
            'limit': MAX_RESULTS, 'candidate_scan_limit': MAX_SEARCH_CANDIDATES,
            'pagination_available': True, 'next_cursor': next_cursor,
        }})
    except InvalidSearchQuery:
        response = JsonResponse({'error': {'code': 'invalid_query', 'message': 'Search query contains unsupported characters.'}}, status=400)
    except InvalidSearchCursor:
        response = JsonResponse({'error': {'code': 'invalid_cursor', 'message': 'Search cursor is invalid or expired; restart the search.'}}, status=400)
    response['X-Robots-Tag'] = 'noindex, follow'
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@require_safe
def presentation_detail(request, pk):
    try:
        product = get_public_presentation(pk)
    except Http404:
        response = render(request, 'presentation_not_found.html', {
            'page_title': 'فرآورده یافت نشد | داروبانک', 'description': 'صفحه در دسترس نیست.', 'noindex': True,
        }, status=404)
        response['X-Robots-Tag'] = 'noindex, follow'
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response
    response = render_page(
        request, 'presentation_detail.html', title=f'{product.name_fa} | داروبانک',
        description='مشخصات فرآورده و بسته‌بندی و منبع ثبت‌شده در داروبانک.',
        noindex=True, product=product,
    )
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@require_safe
def presentation_api(request, pk):
    try:
        product = get_public_presentation(pk)
        response = JsonResponse({'data': serialize_presentation(product)})
    except Http404:
        response = JsonResponse({'error': {'code': 'not_found', 'message': 'Presentation not found.'}}, status=404)
    response['X-Robots-Tag'] = 'noindex, follow'
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@require_safe
def openapi_document(request):
    # Bundled, static contract for implemented public endpoints only.
    path = Path(__file__).resolve().parent.parent / 'docs' / 'openapi.json'
    with path.open(encoding='utf-8') as stream:
        document = json.load(stream)
    response = JsonResponse(document)
    response['X-Robots-Tag'] = 'noindex, follow'
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response
