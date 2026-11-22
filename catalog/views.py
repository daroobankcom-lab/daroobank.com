from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe
from .services import MAX_QUERY_LENGTH, MAX_RESULTS, search_products

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
    results = search_products(query)
    response = render_page(request, 'search.html', title='جست‌وجوی دارو | داروبانک', description='جست‌وجو در اطلاعات دارویی منتشرشده داروبانک.', noindex=True, query=query, results=results)
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
    data = [{
        'id': p.pk, 'name_fa': p.name_fa, 'name_en': p.name_en,
        'manufacturer': p.manufacturer, 'strength': p.strength,
        'dosage_form': p.dosage_form, 'package_description': p.package_description,
        'irc': p.irc or None, 'source': {'name': p.source_name, 'url': p.source_url,
                                      'verified_at': p.verified_at.isoformat()},
    } for p in search_products(query)]
    response = JsonResponse({'data': data, 'meta': {'limit': MAX_RESULTS, 'pagination_available': False}})
    response['X-Robots-Tag'] = 'noindex, follow'
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response
