"""Development-only identity workspace; never publish or establish equivalence."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from daroobank.validation import valid_review_reason
from .identity import (ADD, VIEW, REVIEW, MAX_ID, INGREDIENT_FIELDS, FORMULATION_FIELDS, PRODUCT_FIELDS, PACKAGE_FIELDS,
    IdentityConflict, IdentityError, create_ingredient, create_formulation, create_product, create_package,
    digest, valid_review_snapshot, ingredient_snapshot, formulation_snapshot, product_snapshot, package_snapshot, require_staff, review_package, safe_snapshot)
from .identity_forms import ComponentFormSet, FormulationForm, IngredientForm, PackageForm, ProductForm, IdentityReviewForm
from .models import IngredientDraft, FormulationDraft, IdentityProductDraft, IdentityPackageDraft, IdentityPackageReview

REVIEW_PAGE_SIZE = 25

KINDS = {
    'ingredient': (IngredientDraft, IngredientForm, INGREDIENT_FIELDS, ingredient_snapshot, 'ماده مؤثره'),
    'formulation': (FormulationDraft, FormulationForm, FORMULATION_FIELDS, formulation_snapshot, 'فرمولاسیون ژنریک'),
    'product': (IdentityProductDraft, ProductForm, PRODUCT_FIELDS, product_snapshot, 'فرآورده'),
    'package': (IdentityPackageDraft, PackageForm, PACKAGE_FIELDS, package_snapshot, 'بسته‌بندی'),
}


def _kind(kind):
    if kind not in KINDS: raise Http404('Not found')
    return KINDS[kind]


def _object(kind, pk):
    model = _kind(kind)[0]
    if not 1 <= pk <= MAX_ID: raise Http404('Not found')
    queryset = model.objects.all()
    if kind == 'package': queryset = queryset.select_related('product__formulation')
    elif kind == 'product': queryset = queryset.select_related('formulation')
    return get_object_or_404(queryset, pk=pk)


def _authors(graph):
    product = graph['product']; form = product['formulation']
    return {graph['recorded_by_id'], product['recorded_by_id'], form['recorded_by_id'],
            *(ingredient['recorded_by_id'] for ingredient in form['ingredients'])}


@login_required(login_url='staff_login')
@require_safe
def listing(request):
    require_staff(request.user, VIEW)
    kind = request.GET.get('kind', 'ingredient')
    if kind not in KINDS: return HttpResponseBadRequest('Invalid category.')
    model, _, _, snapshot, label = _kind(kind)
    queryset = model.objects.order_by('-pk')
    if kind == 'package': queryset = queryset.select_related('product__formulation')
    elif kind == 'product': queryset = queryset.select_related('formulation')
    page = Paginator(queryset, 20).get_page(request.GET.get('page', 1))
    for item in page.object_list:
        item.snapshot = safe_snapshot(item, snapshot)
        item.title = (item.snapshot.get('name_fa') or item.snapshot.get('name') or item.snapshot.get('description')) if item.snapshot else ''
    return render(request, 'staff/identity_list.html', {'page_title': 'هویت ساختگی کاتالوگ | داروبانک',
        'description': 'ساختار خصوصی کاتالوگ.', 'private_staff': True, 'noindex': True, 'page': page,
        'kind': kind, 'label': label, 'can_add': request.user.has_perm(ADD)})


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def create(request, kind):
    require_staff(request.user, VIEW, ADD)
    _, form_class, fields, _, label = _kind(kind)
    form = form_class(request.POST if request.method == 'POST' else None)
    parts = ComponentFormSet(request.POST if request.method == 'POST' else None, prefix='parts') if kind == 'formulation' else None
    status = 200
    if request.method == 'POST':
        valid = form.is_valid()
        parts_valid = parts.is_valid() if parts is not None else True
        if valid and parts_valid:
            data = {key: form.cleaned_data[key] for key in fields}
            try:
                if kind == 'ingredient': obj = create_ingredient(actor=request.user, data=data)
                elif kind == 'formulation': obj = create_formulation(actor=request.user, data=data,
                    components=[part.cleaned_data for part in parts if part.cleaned_data])
                elif kind == 'product': obj = create_product(actor=request.user, data=data, formulation_id=form.cleaned_data['formulation_id'])
                else: obj = create_package(actor=request.user, data=data, product_id=form.cleaned_data['product_id'])
                return redirect('staff_identity_detail', kind=kind, pk=obj.pk)
            except IdentityError as exc:
                form.add_error(None, str(exc))
            except IdentityConflict as exc:
                form.add_error(None, str(exc)); status = 409
    return render(request, 'staff/identity_form.html', {'page_title': 'ثبت هویت ساختگی | داروبانک',
        'description': 'ثبت ساختار خصوصی.', 'private_staff': True, 'noindex': True, 'form': form,
        'parts': parts, 'has_parts': parts is not None, 'kind': kind, 'label': label}, status=status)


def _review_cursor(request):
    # Cursor is an ordering position, not an authorization token or a snapshot.
    value = request.GET.get('before', '') if request.method in ('GET', 'HEAD') else ''
    if not value:
        return None
    if len(value) > 19 or not value.isascii() or not value.isdigit():
        raise ValueError('Invalid review cursor')
    number = int(value)
    if not 1 <= number <= MAX_ID:
        raise ValueError('Invalid review cursor')
    return number


def _detail(request, kind, obj, *, review_form=None, status=200):
    snapshot = safe_snapshot(obj, _kind(kind)[3])
    reviews, can_review, next_before = [], False, None
    before = None
    if kind == 'package':
        try:
            before = _review_cursor(request)
        except ValueError:
            return HttpResponseBadRequest('Invalid review cursor.')
    if kind == 'package' and snapshot:
        queryset = obj.reviews.order_by('-pk')
        if before is not None:
            queryset = queryset.filter(pk__lt=before)
        rows = list(queryset[:REVIEW_PAGE_SIZE + 1])
        reviews = rows[:REVIEW_PAGE_SIZE]
        if len(rows) > REVIEW_PAGE_SIZE:
            next_before = reviews[-1].pk
        graph_hash = digest(snapshot)
        can_review = request.user.has_perm(REVIEW) and request.user.pk not in _authors(snapshot)
        if can_review and before is None and review_form is None and status != 409:
            # Use the newest review actually rendered, never a later unseen insert.
            latest_shown = reviews[0].pk if reviews else 0
            review_form = IdentityReviewForm(initial={'expected_review': latest_shown, 'expected_graph_hash': graph_hash})
        for review in reviews:
            try:
                review.safe = (valid_review_snapshot(review.graph_snapshot, obj.pk)
                               and digest(review.graph_snapshot) == review.graph_sha256
                               and review.decision in dict(IdentityPackageReview.DECISIONS)
                               and valid_review_reason(review.reason)
                               and review.reviewer_id not in _authors(review.graph_snapshot))
                review.is_current = review.safe and review.graph_sha256 == graph_hash
            except (TypeError, ValueError, UnicodeError):
                review.safe = False
    return render(request, 'staff/identity_detail.html', {'page_title': 'جزئیات هویت ساختگی | داروبانک',
        'description': 'زنجیره ادعایی کاتالوگ.', 'private_staff': True, 'noindex': True, 'kind': kind,
        'label': _kind(kind)[4], 'obj': obj, 'snapshot': snapshot, 'reviews': reviews,
        'review_before': before, 'next_before': next_before, 'review_conflict': status == 409,
        'can_review': can_review, 'review_form': review_form, 'can_add': request.user.has_perm(ADD)}, status=status)


@login_required(login_url='staff_login')
@require_safe
def detail(request, kind, pk):
    require_staff(request.user, VIEW)
    return _detail(request, kind, _object(kind, pk))


@login_required(login_url='staff_login')
@require_POST
def review(request, pk):
    require_staff(request.user, VIEW, REVIEW)
    package = _object('package', pk)
    form = IdentityReviewForm(request.POST)
    if not form.is_valid(): return _detail(request, 'package', package, review_form=form, status=400)
    try:
        review_package(actor=request.user, package_id=pk, **form.cleaned_data)
    except IdentityConflict as exc:
        form.add_error(None, str(exc))
        try:
            package.refresh_from_db()
        except IdentityPackageDraft.DoesNotExist:
            raise Http404('Not found')
        return _detail(request, 'package', package, review_form=form, status=409)
    except IdentityPackageDraft.DoesNotExist:
        return HttpResponseBadRequest('Package no longer exists.')
    return redirect('staff_identity_detail', kind='package', pk=pk)
