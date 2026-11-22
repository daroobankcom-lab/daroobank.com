"""Private synthetic catalog identity assertions; never clinical approval or publication."""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction

from catalog.normalization import normalize_search
from daroobank.validation import valid_private_source_url, valid_review_reason
from .models import (IngredientDraft, FormulationDraft, FormulationComponent,
                     IdentityProductDraft, IdentityPackageDraft, IdentityPackageReview)

VIEW = 'catalog.view_identityworkspace'
ADD = 'catalog.add_identityworkspace'
REVIEW = 'catalog.review_identityworkspace'
MAX_COMPONENTS = 5
MAX_ID = 9_223_372_036_854_775_807
MAX_QUANTITY = Decimal('99999999.9999')
HASH = re.compile(r'^[0-9a-f]{64}$')
COMMON = ('source_name', 'source_url')
INGREDIENT_FIELDS = ('name_fa', 'name_en') + COMMON
FORMULATION_FIELDS = ('name', 'dosage_form', 'route') + COMMON
PRODUCT_FIELDS = ('name', 'brand', 'manufacturer') + COMMON
PACKAGE_FIELDS = ('description', 'quantity', 'quantity_unit', 'irc') + COMMON
COMPONENT_FIELDS = ('ingredient_id', 'numerator', 'numerator_unit', 'denominator', 'denominator_unit')
LIMITS = {'name_fa': 200, 'name_en': 200, 'name': 200, 'dosage_form': 100, 'route': 100,
          'brand': 200, 'manufacturer': 200, 'description': 200, 'quantity_unit': 50, 'irc': 80,
          'numerator_unit': 50, 'denominator_unit': 50, 'source_name': 200}
OPTIONAL = {'name_en', 'brand', 'irc'}


class IdentityError(ValueError):
    pass


class IdentityConflict(ValueError):
    pass


def require_staff(actor, *permissions):
    if not actor or not actor.is_authenticated or not actor.is_active or not actor.is_staff or any(
            not actor.has_perm(permission) for permission in permissions):
        raise PermissionDenied


def _valid_id(value):
    return type(value) is int and 1 <= value <= MAX_ID


def validate_data(data, fields):
    if not isinstance(data, dict) or set(data) != set(fields):
        raise IdentityError('ساختار داده معتبر نیست.')
    for key, value in data.items():
        if key == 'source_url':
            if not valid_private_source_url(value):
                raise IdentityError('نشانی منبع باید HTTPS و بدون اطلاعات محرمانه باشد.')
        elif key in ('quantity', 'numerator', 'denominator'):
            try:
                if (not isinstance(value, Decimal) or not value.is_finite() or value <= 0 or value > MAX_QUANTITY
                        or value != value.quantize(Decimal('0.0001'))):
                    raise IdentityError('مقدار باید مثبت و حداکثر چهار رقم اعشار داشته باشد.')
            except InvalidOperation as exc:
                raise IdentityError('مقدار معتبر نیست.') from exc
        elif key == 'ingredient_id':
            if not _valid_id(value):
                raise IdentityError('شناسه ماده معتبر نیست.')
        elif (not isinstance(value, str) or value != value.strip() or len(value) > LIMITS[key]
              or any(unicodedata.category(c) in ('Cc', 'Cs') for c in value)
              or (key not in OPTIONAL and not normalize_search(value))
              or (value and not normalize_search(value))):
            raise IdentityError('متن واردشده معتبر نیست.')


def canonical(data):
    return {key: format(value, '.4f') if isinstance(value, Decimal) else value for key, value in data.items()}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def values(obj, fields):
    return {field: getattr(obj, field) for field in fields}


def _is_hash(value):
    return isinstance(value, str) and bool(HASH.fullmatch(value))


def ingredient_payload(item):
    data = values(item, INGREDIENT_FIELDS)
    validate_data(data, INGREDIENT_FIELDS)
    if not _valid_id(item.recorded_by_id): raise IdentityError('ثبت‌کننده معتبر نیست.')
    return {**data, 'recorded_by_id': item.recorded_by_id}


def ingredient_snapshot(item):
    payload = ingredient_payload(item)
    if not _is_hash(item.payload_sha256) or digest(payload) != item.payload_sha256: raise IdentityError('ماده ناسازگار است.')
    return {'id': item.pk, 'payload_sha256': item.payload_sha256, **payload}


def formulation_payload(item):
    data = values(item, FORMULATION_FIELDS)
    validate_data(data, FORMULATION_FIELDS)
    if not _valid_id(item.recorded_by_id): raise IdentityError('ثبت‌کننده معتبر نیست.')
    components = list(item.components.select_related('ingredient').order_by('ordinal')[:MAX_COMPONENTS + 1])
    if not 1 <= len(components) <= MAX_COMPONENTS or [c.ordinal for c in components] != list(range(1, len(components) + 1)):
        raise IdentityError('اجزای فرمولاسیون ناسازگارند.')
    payload_components = []
    seen = set()
    for c in components:
        component = values(c, COMPONENT_FIELDS)
        validate_data(component, COMPONENT_FIELDS)
        if c.ingredient_id in seen: raise IdentityError('ماده تکراری است.')
        seen.add(c.ingredient_id)
        ingredient = ingredient_snapshot(c.ingredient)
        if c.ingredient_sha256 != ingredient['payload_sha256']: raise IdentityError('ماده تغییر کرده است.')
        payload_components.append({**canonical(component), 'ingredient_sha256': c.ingredient_sha256})
    return {**data, 'recorded_by_id': item.recorded_by_id, 'components': payload_components}


def formulation_snapshot(item):
    payload = formulation_payload(item)
    if not _is_hash(item.payload_sha256) or digest(payload) != item.payload_sha256: raise IdentityError('فرمولاسیون ناسازگار است.')
    components = list(item.components.select_related('ingredient').order_by('ordinal')[:MAX_COMPONENTS + 1])
    # Validate once more, since a concurrent out-of-band write may happen between reads.
    if len(components) != len(payload['components']): raise IdentityError('اجزا تغییر کردند.')
    ingredients = [ingredient_snapshot(component.ingredient) for component in components]
    if any(ingredient['id'] != payload['components'][i]['ingredient_id'] or
           ingredient['payload_sha256'] != payload['components'][i]['ingredient_sha256']
           for i, ingredient in enumerate(ingredients)):
        raise IdentityError('مواد تغییر کردند.')
    return {'id': item.pk, 'payload_sha256': item.payload_sha256, **payload, 'ingredients': ingredients}


def product_payload(item):
    data = values(item, PRODUCT_FIELDS)
    validate_data(data, PRODUCT_FIELDS)
    if not _valid_id(item.recorded_by_id): raise IdentityError('ثبت‌کننده معتبر نیست.')
    formulation = formulation_snapshot(item.formulation)
    if item.formulation_sha256 != formulation['payload_sha256']: raise IdentityError('فرمولاسیون تغییر کرده است.')
    return {**data, 'recorded_by_id': item.recorded_by_id, 'formulation_id': item.formulation_id,
            'formulation_sha256': item.formulation_sha256}


def product_snapshot(item):
    payload = product_payload(item)
    if not _is_hash(item.payload_sha256) or digest(payload) != item.payload_sha256: raise IdentityError('فرآورده ناسازگار است.')
    formulation = formulation_snapshot(item.formulation)
    if formulation['payload_sha256'] != payload['formulation_sha256']: raise IdentityError('فرمولاسیون تغییر کرده است.')
    return {'id': item.pk, 'payload_sha256': item.payload_sha256, **payload, 'formulation': formulation}


def package_payload(item):
    data = values(item, PACKAGE_FIELDS)
    validate_data(data, PACKAGE_FIELDS)
    if not _valid_id(item.recorded_by_id): raise IdentityError('ثبت‌کننده معتبر نیست.')
    product = product_snapshot(item.product)
    if item.product_sha256 != product['payload_sha256']: raise IdentityError('فرآورده تغییر کرده است.')
    return {**canonical(data), 'recorded_by_id': item.recorded_by_id, 'product_id': item.product_id,
            'product_sha256': item.product_sha256}


def package_snapshot(item):
    payload = package_payload(item)
    if not _is_hash(item.payload_sha256) or digest(payload) != item.payload_sha256: raise IdentityError('بسته‌بندی ناسازگار است.')
    product = product_snapshot(item.product)
    if product['payload_sha256'] != payload['product_sha256']: raise IdentityError('فرآورده تغییر کرده است.')
    return {'id': item.pk, 'payload_sha256': item.payload_sha256, **payload, 'product': product}


def safe_snapshot(item, function):
    try:
        return function(item)
    except (IdentityError, TypeError, ValueError, AttributeError, OverflowError, IngredientDraft.DoesNotExist,
            FormulationDraft.DoesNotExist, IdentityProductDraft.DoesNotExist):
        return None


def create_ingredient(*, actor, data):
    require_staff(actor, VIEW, ADD)
    validate_data(data, INGREDIENT_FIELDS)
    return IngredientDraft.objects.create(**data, recorded_by=actor, payload_sha256=digest({**data, 'recorded_by_id': actor.pk}))


def create_formulation(*, actor, data, components):
    require_staff(actor, VIEW, ADD)
    validate_data(data, FORMULATION_FIELDS)
    if not isinstance(components, list) or not 1 <= len(components) <= MAX_COMPONENTS:
        raise IdentityError('یک تا پنج ماده لازم است.')
    for row in components: validate_data(row, COMPONENT_FIELDS)
    ids = [row['ingredient_id'] for row in components]
    if len(set(ids)) != len(ids): raise IdentityError('هر ماده فقط یک بار مجاز است.')
    with transaction.atomic():
        ingredients = {item.pk: item for item in IngredientDraft.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
        if set(ids) != set(ingredients): raise IdentityConflict('ماده انتخاب‌شده در دسترس نیست.')
        try:
            snapshots = {key: ingredient_snapshot(item) for key, item in ingredients.items()}
        except IdentityError as exc:
            raise IdentityConflict('ماده انتخاب‌شده ناسازگار است.') from exc
        parts = [{**canonical(row), 'ingredient_sha256': snapshots[row['ingredient_id']]['payload_sha256']} for row in components]
        payload = {**data, 'recorded_by_id': actor.pk, 'components': parts}
        formulation = FormulationDraft.objects.create(**data, recorded_by=actor, payload_sha256=digest(payload))
        for ordinal, row in enumerate(components, 1):
            FormulationComponent.objects.create(formulation=formulation, ordinal=ordinal, **row,
                ingredient_sha256=snapshots[row['ingredient_id']]['payload_sha256'])
        return formulation


def create_product(*, actor, data, formulation_id):
    require_staff(actor, VIEW, ADD)
    validate_data(data, PRODUCT_FIELDS)
    if not _valid_id(formulation_id): raise IdentityError('شناسه فرمولاسیون معتبر نیست.')
    with transaction.atomic():
        form = FormulationDraft.objects.select_for_update().filter(pk=formulation_id).first()
        if not form or not safe_snapshot(form, formulation_snapshot): raise IdentityConflict('فرمولاسیون در دسترس یا سازگار نیست.')
        payload = {**data, 'recorded_by_id': actor.pk, 'formulation_id': form.pk, 'formulation_sha256': form.payload_sha256}
        return IdentityProductDraft.objects.create(**data, recorded_by=actor, formulation=form,
            formulation_sha256=form.payload_sha256, payload_sha256=digest(payload))


def create_package(*, actor, data, product_id):
    require_staff(actor, VIEW, ADD)
    validate_data(data, PACKAGE_FIELDS)
    if not _valid_id(product_id): raise IdentityError('شناسه فرآورده معتبر نیست.')
    with transaction.atomic():
        product = IdentityProductDraft.objects.select_for_update().filter(pk=product_id).first()
        if not product or not safe_snapshot(product, product_snapshot): raise IdentityConflict('فرآورده در دسترس یا سازگار نیست.')
        payload = {**canonical(data), 'recorded_by_id': actor.pk, 'product_id': product.pk, 'product_sha256': product.payload_sha256}
        return IdentityPackageDraft.objects.create(**data, recorded_by=actor, product=product,
            product_sha256=product.payload_sha256, payload_sha256=digest(payload))


def review_package(*, actor, package_id, decision, reason, expected_review, expected_graph_hash):
    require_staff(actor, VIEW, REVIEW)
    if (not _valid_id(package_id) or decision not in dict(IdentityPackageReview.DECISIONS)
            or not valid_review_reason(reason) or type(expected_review) is not int or not 0 <= expected_review <= MAX_ID
            or not _is_hash(expected_graph_hash)):
        raise IdentityConflict('اطلاعات بازبینی معتبر نیست.')
    with transaction.atomic():
        package = IdentityPackageDraft.objects.select_for_update(of=('self',)).select_related('product__formulation').filter(pk=package_id).first()
        if not package: raise IdentityConflict('بسته در دسترس نیست.')
        graph = safe_snapshot(package, package_snapshot)
        if not graph or digest(graph) != expected_graph_hash: raise IdentityConflict('اطلاعات زنجیره تغییر کرده یا ناسازگار است.')
        authors = {graph['recorded_by_id'], graph['product']['recorded_by_id'],
                   graph['product']['formulation']['recorded_by_id']}
        authors.update(item['recorded_by_id'] for item in graph['product']['formulation']['ingredients'])
        if actor.pk in authors: raise PermissionDenied
        latest = package.reviews.order_by('-pk').first()
        if (latest.pk if latest else 0) != expected_review: raise IdentityConflict('بازبینی جدیدی ثبت شده است.')
        return IdentityPackageReview.objects.create(package=package, reviewer=actor, decision=decision, reason=reason.strip(),
                                                    graph_sha256=expected_graph_hash, graph_snapshot=graph)


def valid_review_snapshot(graph, package_id):
    """Check a stored review graph offline; detects inconsistency, not forgery."""
    def base(node, fields, extras):
        if not isinstance(node, dict) or set(node) != set(fields) | {'id', 'payload_sha256', 'recorded_by_id'} | set(extras):
            raise IdentityError('ساختار تصویر بازبینی معتبر نیست.')
        if not _valid_id(node['id']) or not _valid_id(node['recorded_by_id']) or not _is_hash(node['payload_sha256']):
            raise IdentityError('شناسه یا هش تصویر معتبر نیست.')
        data = {key: node[key] for key in fields}
        for key in ('quantity', 'numerator', 'denominator'):
            if key in data:
                value = data[key]
                if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,7})\.[0-9]{4}', value):
                    raise IdentityError('مقدار تصویر معتبر نیست.')
                try:
                    data[key] = Decimal(value)
                    if not data[key].is_finite() or format(data[key], '.4f') != value:
                        raise IdentityError('مقدار تصویر معتبر نیست.')
                except (InvalidOperation, ValueError):
                    raise IdentityError('مقدار تصویر معتبر نیست.')
        validate_data(data, fields)
        return {**canonical(data), 'recorded_by_id': node['recorded_by_id']}

    try:
        package = base(graph, PACKAGE_FIELDS, ('product_id', 'product_sha256', 'product'))
        if graph['id'] != package_id: return False
        product_node = graph['product']
        product = base(product_node, PRODUCT_FIELDS, ('formulation_id', 'formulation_sha256', 'formulation'))
        form_node = product_node['formulation']
        form = base(form_node, FORMULATION_FIELDS, ('components', 'ingredients'))
        parts, ingredients = form_node['components'], form_node['ingredients']
        if (not isinstance(parts, list) or not isinstance(ingredients, list) or
                not 1 <= len(parts) <= MAX_COMPONENTS or len(parts) != len(ingredients)):
            return False
        seen = set()
        for part, ingredient in zip(parts, ingredients):
            ingredient_payload_data = base(ingredient, INGREDIENT_FIELDS, ())
            if digest(ingredient_payload_data) != ingredient['payload_sha256'] or ingredient['id'] in seen:
                return False
            seen.add(ingredient['id'])
            if not isinstance(part, dict) or set(part) != set(COMPONENT_FIELDS) | {'ingredient_sha256'}:
                return False
            component = {key: part[key] for key in COMPONENT_FIELDS}
            for key in ('numerator', 'denominator'):
                value = component[key]
                if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,7})\.[0-9]{4}', value): return False
                component[key] = Decimal(value)
                if not component[key].is_finite() or format(component[key], '.4f') != value: return False
            validate_data(component, COMPONENT_FIELDS)
            if part['ingredient_id'] != ingredient['id'] or part['ingredient_sha256'] != ingredient['payload_sha256']:
                return False
        form['components'] = parts
        if digest(form) != form_node['payload_sha256']: return False
        if not _valid_id(product_node['formulation_id']) or product_node['formulation_id'] != form_node['id'] or product_node['formulation_sha256'] != form_node['payload_sha256']:
            return False
        product.update(formulation_id=product_node['formulation_id'], formulation_sha256=product_node['formulation_sha256'])
        if digest(product) != product_node['payload_sha256']: return False
        if not _valid_id(graph['product_id']) or graph['product_id'] != product_node['id'] or graph['product_sha256'] != product_node['payload_sha256']:
            return False
        package.update(product_id=graph['product_id'], product_sha256=graph['product_sha256'])
        return digest(package) == graph['payload_sha256']
    except (IdentityError, TypeError, ValueError, KeyError, AttributeError, InvalidOperation, OverflowError, UnicodeError):
        return False
