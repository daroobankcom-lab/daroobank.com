"""Development-only identity workspace; never publish or establish equivalence."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from daroobank.account_checks import current_accounts
from daroobank.review_content_bounds import bounded_review_fields, materialize_review_fields

from .identity import (
    ADD, VIEW, REVIEW, MAX_ID, INGREDIENT_FIELDS, FORMULATION_FIELDS, PRODUCT_FIELDS, PACKAGE_FIELDS, COMPONENT_FIELDS,
    IdentityConflict, IdentityError, create_ingredient, create_formulation, create_product, create_package,
    digest, valid_package_revision, revise_package, valid_identity_revision, revise_identity, review_is_consistent,
    graph_authors, ingredient_snapshot, formulation_snapshot, product_snapshot, package_snapshot, require_staff,
    review_package, safe_snapshot,
)
from .identity_lineage import inspect_lineage, InvalidLineageCursor, LineageNotFound
from .revision_read import bounded_revision_reasons, materialize_revision_reason
from .identity_forms import (
    ComponentFormSet, FormulationForm, IngredientForm, PackageForm, ProductForm, IdentityReviewForm,
    PackageRevisionForm, IngredientRevisionForm, FormulationRevisionForm, ProductRevisionForm, RevisionComponentFormSet,
)
from .models import (
    IngredientDraft, FormulationDraft, IdentityProductDraft, IdentityPackageDraft, IdentityPackageReview,
    IdentityPackageRevision, IngredientRevision, FormulationRevision, ProductRevision,
)

REVIEW_PAGE_SIZE = 25
REVISION_PAGE_SIZE = 10
COMPONENT_LINKS = {'ingredient': IngredientRevision, 'formulation': FormulationRevision, 'product': ProductRevision}
COMPONENT_REVISION_FORMS = {'ingredient': IngredientRevisionForm, 'formulation': FormulationRevisionForm, 'product': ProductRevisionForm}

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


def _cursor(request, name):
    # Cursor is an ordering position, not an authorization token or a snapshot.
    value = request.GET.get(name, '') if request.method in ('GET', 'HEAD') else ''
    if not value:
        return None
    if len(value) > 19 or not value.isascii() or not value.isdigit():
        raise ValueError('Invalid cursor')
    number = int(value)
    if not 1 <= number <= MAX_ID:
        raise ValueError('Invalid cursor')
    return number


def _check_review(review, package_id, graph_hash):
    materialize_review_fields(review, snapshot_field='graph_snapshot')
    review.safe = not review.content_oversized and review_is_consistent(review, package_id)
    review.is_current = review.safe and review.graph_sha256 == graph_hash
    return review


def _detail(request, kind, obj, *, review_form=None, status=200):
    snapshot = safe_snapshot(obj, _kind(kind)[3])
    reviews, can_review, next_before = [], False, None
    parent_link, child_links, next_revision_before = None, [], None
    before, revisions_before = None, None
    try:
        if kind == 'package': before = _cursor(request, 'before')
        revisions_before = _cursor(request, 'revisions_before')
    except ValueError:
        return HttpResponseBadRequest('Invalid cursor.')
    if snapshot:
        if kind == 'package':
            links = IdentityPackageRevision.objects.select_related('parent__product__formulation', 'child__product__formulation')
        else:
            links = COMPONENT_LINKS[kind].objects.select_related('parent', 'child')
            if kind == 'product': links = links.select_related('parent__formulation', 'child__formulation')
        links = bounded_revision_reasons(links)
        parent_link = links.filter(child_id=obj.pk).first()
        if parent_link:
            materialize_revision_reason(parent_link)
            parent_link.safe = (valid_package_revision(parent_link, obj.pk) if kind == 'package'
                                else valid_identity_revision(kind, parent_link, obj.pk))
        children = links.filter(parent_id=obj.pk).order_by('-pk')
        if revisions_before is not None:
            children = children.filter(pk__lt=revisions_before)
        child_rows = list(children[:REVISION_PAGE_SIZE + 1])
        child_links = child_rows[:REVISION_PAGE_SIZE]
        if len(child_rows) > REVISION_PAGE_SIZE:
            next_revision_before = child_links[-1].pk
        for link in child_links:
            materialize_revision_reason(link)
            link.safe = (valid_package_revision(link, link.child_id) if kind == 'package'
                         else valid_identity_revision(kind, link, link.child_id))
    if kind == 'package' and snapshot:
        queryset = obj.reviews.order_by('-pk')
        if before is not None:
            queryset = queryset.filter(pk__lt=before)
        rows = list(bounded_review_fields(queryset, snapshot_field='graph_snapshot')[:REVIEW_PAGE_SIZE + 1])
        reviews = rows[:REVIEW_PAGE_SIZE]
        if len(rows) > REVIEW_PAGE_SIZE:
            next_before = reviews[-1].pk
        graph_hash = digest(snapshot)
        can_review = request.user.has_perm(REVIEW) and request.user.pk not in graph_authors(snapshot)
        if can_review and before is None and review_form is None and status != 409:
            # Use the newest review actually rendered, never a later unseen insert.
            latest_shown = reviews[0].pk if reviews else 0
            review_form = IdentityReviewForm(initial={'expected_review': latest_shown, 'expected_graph_hash': graph_hash})
        reviewers = current_accounts([review.reviewer_id for review in reviews], using=queryset.db)
        for review in reviews:
            review.display_reviewer = reviewers.get(review.reviewer_id)
            _check_review(review, obj.pk, graph_hash)
    return render(request, 'staff/identity_detail.html', {'page_title': 'جزئیات هویت ساختگی | داروبانک',
        'description': 'زنجیره ادعایی کاتالوگ.', 'private_staff': True, 'noindex': True, 'kind': kind,
        'label': _kind(kind)[4], 'obj': obj, 'snapshot': snapshot, 'reviews': reviews,
        'review_before': before, 'next_before': next_before, 'review_conflict': status == 409,
        'parent_link': parent_link, 'child_links': child_links, 'revisions_before': revisions_before,
        'next_revision_before': next_revision_before,
        'can_review': can_review, 'review_form': review_form, 'can_add': request.user.has_perm(ADD)}, status=status)


@login_required(login_url='staff_login')
@require_safe
def detail(request, kind, pk):
    require_staff(request.user, VIEW)
    return _detail(request, kind, _object(kind, pk))


@login_required(login_url='staff_login')
@require_safe
def lineage(request, kind, pk):
    try:
        report = inspect_lineage(actor=request.user, kind=kind, anchor_id=pk, cursor=request.GET.get('cursor', ''))
    except LineageNotFound:
        raise Http404('Not found')
    except InvalidLineageCursor:
        return HttpResponseBadRequest('Invalid or stale cursor; restart the inspection.')
    return render(request, 'staff/identity_lineage.html', {'page_title': 'بررسی زنجیره اصلاح | داروبانک',
        'description': 'بازرسی خصوصی پیوندهای اصلاح.', 'private_staff': True, 'noindex': True,
        'label': _kind(kind)[4], 'report': report})


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def revise_component(request, kind, pk):
    require_staff(request.user, VIEW, ADD)
    if kind not in COMPONENT_REVISION_FORMS: raise Http404('Not found')
    parent = _object(kind, pk)
    _, _, fields, snapshot_fn, label = _kind(kind)
    graph = safe_snapshot(parent, snapshot_fn)
    initial = {field: getattr(parent, field) for field in fields} if graph else {}
    initial['expected_graph_hash'] = digest(graph) if graph else None
    form = COMPONENT_REVISION_FORMS[kind](request.POST if request.method == 'POST' else None, initial=initial)
    parts = None
    if kind == 'formulation' and graph:
        part_initial = [{key: row[key] for key in COMPONENT_FIELDS} for row in graph['components']]
        parts = RevisionComponentFormSet(request.POST if request.method == 'POST' else None,
            prefix='parts', initial=part_initial, expected_initial=len(part_initial))
    status = 200
    if request.method == 'POST' and graph:
        form_valid = form.is_valid()
        parts_valid = parts.is_valid() if parts is not None else True
        if form_valid and parts_valid:
            try:
                child = revise_identity(actor=request.user, kind=kind, parent_id=parent.pk,
                    data={field: form.cleaned_data[field] for field in fields},
                    components=[part.cleaned_data for part in parts if part.cleaned_data] if parts is not None else None,
                    change_reason=form.cleaned_data['change_reason'], expected_graph_hash=form.cleaned_data['expected_graph_hash'])
                return redirect('staff_identity_detail', kind=kind, pk=child.pk)
            except IdentityError as exc:
                form.add_error(None, str(exc))
            except IdentityConflict as exc:
                form.add_error(None, str(exc)); status = 409
    return render(request, 'staff/identity_component_revision.html', {'page_title': 'اصلاح هویت ساختگی | داروبانک',
        'description': 'نسخه اصلاحی خصوصی.', 'private_staff': True, 'noindex': True,
        'parent': parent, 'graph': graph, 'kind': kind, 'label': label, 'form': form,
        'parts': parts, 'has_parts': parts is not None, 'conflict': status == 409}, status=status)


def _latest_review_for_revision(package, graph_hash):
    item = bounded_review_fields(package.reviews.order_by('-pk'), snapshot_field='graph_snapshot').first()
    if item:
        item.display_reviewer = current_accounts([item.reviewer_id], using=item._state.db).get(item.reviewer_id)
        _check_review(item, package.pk, graph_hash)
    return item


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def revise(request, pk):
    require_staff(request.user, VIEW, ADD)
    parent = _object('package', pk)
    graph = safe_snapshot(parent, package_snapshot)
    graph_hash = digest(graph) if graph else None
    latest = _latest_review_for_revision(parent, graph_hash) if graph else None
    initial = {key: getattr(parent, key) for key in PACKAGE_FIELDS} if graph else {}
    initial.update(expected_graph_hash=graph_hash, expected_review=latest.pk if latest else 0)
    form = PackageRevisionForm(request.POST if request.method == 'POST' else None, initial=initial)
    status = 200
    if request.method == 'POST' and graph and form.is_valid():
        try:
            child = revise_package(actor=request.user, parent_id=parent.pk,
                data={key: form.cleaned_data[key] for key in PACKAGE_FIELDS},
                change_reason=form.cleaned_data['change_reason'], expected_graph_hash=form.cleaned_data['expected_graph_hash'],
                expected_review=form.cleaned_data['expected_review'])
            return redirect('staff_identity_detail', kind='package', pk=child.pk)
        except IdentityError as exc:
            form.add_error(None, str(exc))
        except IdentityConflict as exc:
            form.add_error(None, str(exc)); status = 409
    return render(request, 'staff/identity_revision.html', {'page_title': 'اصلاح بسته ساختگی | داروبانک',
        'description': 'نسخه اصلاحی خصوصی.', 'private_staff': True, 'noindex': True, 'parent': parent,
        'graph': graph, 'latest': latest, 'form': form, 'conflict': status == 409}, status=status)


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
