"""Read-only, bounded traversal of private synthetic revision links.

This reports internal consistency of inspected links, not authenticity, approval,
clinical identity or a consistent database snapshot.
"""
import re

from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac

from daroobank.signed_cursors import loads_nonfuture

from .identity import (MAX_ID, VIEW, digest, require_staff, safe_snapshot, ingredient_snapshot,
                       formulation_snapshot, product_snapshot, package_snapshot,
                       valid_identity_revision, valid_package_revision)
from .models import (IngredientDraft, FormulationDraft, IdentityProductDraft, IdentityPackageDraft,
                     IngredientRevision, FormulationRevision, ProductRevision, IdentityPackageRevision)

PAGE_SIZE = 20
CURSOR_SALT = 'catalog.identity.lineage.v1'
CURSOR_MAX_AGE = 3600
MAX_CURSOR_LENGTH = 1024
_HASH = re.compile(r'^[0-9a-f]{64}$')

KINDS = {
    'ingredient': (IngredientDraft, IngredientRevision, ingredient_snapshot),
    'formulation': (FormulationDraft, FormulationRevision, formulation_snapshot),
    'product': (IdentityProductDraft, ProductRevision, product_snapshot),
    'package': (IdentityPackageDraft, IdentityPackageRevision, package_snapshot),
}


class InvalidLineageCursor(ValueError):
    pass


class LineageNotFound(ValueError):
    pass


def _id(value):
    return type(value) is int and 1 <= value <= MAX_ID


def _fingerprint(value):
    # The token is signed, not encrypted; keyed digests avoid placing raw graph hashes in it.
    return salted_hmac(CURSOR_SALT + '.graph', value, algorithm='sha256').hexdigest()


def _encode(kind, anchor_id, anchor_hash, current_id, current_hash, depth):
    return signing.dumps({'kind': kind, 'anchor': anchor_id, 'anchor_graph': _fingerprint(anchor_hash),
                          'current': current_id, 'current_graph': _fingerprint(current_hash), 'depth': depth},
                         salt=CURSOR_SALT)


def _decode(token, kind, anchor_id, anchor_hash):
    if not isinstance(token, str) or not token or len(token) > MAX_CURSOR_LENGTH or token.startswith('.'):
        raise InvalidLineageCursor
    try:
        data = loads_nonfuture(token, salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE)
        if (not isinstance(data, dict) or set(data) != {'kind', 'anchor', 'anchor_graph', 'current', 'current_graph', 'depth'}
                or data['kind'] != kind or type(data['anchor']) is not int or data['anchor'] != anchor_id
                or not _id(data['current']) or data['current'] >= anchor_id
                or type(data['depth']) is not int or not PAGE_SIZE <= data['depth'] <= MAX_ID
                # Every valid parent ID is strictly less than its child ID.
                # This necessary bound does not prove the skipped path exists.
                or data['depth'] > anchor_id - data['current'] or data['depth'] % PAGE_SIZE != 0
                or not isinstance(data['anchor_graph'], str) or not _HASH.fullmatch(data['anchor_graph'])
                or not isinstance(data['current_graph'], str) or not _HASH.fullmatch(data['current_graph'])
                or not constant_time_compare(data['anchor_graph'], _fingerprint(anchor_hash))):
            raise InvalidLineageCursor
        return data['current'], data['current_graph'], data['depth']
    except (signing.BadSignature, TypeError, ValueError, KeyError, OverflowError) as exc:
        raise InvalidLineageCursor from exc


def inspect_lineage(*, actor, kind, anchor_id, cursor=''):
    """Inspect at most PAGE_SIZE immediate-parent links; no changes or snapshot guarantee."""
    require_staff(actor, VIEW)
    if not isinstance(kind, str) or kind not in KINDS or not _id(anchor_id):
        raise LineageNotFound
    if not isinstance(cursor, str):
        raise InvalidLineageCursor
    model, link_model, snapshot_fn = KINDS[kind]
    # Avoid inner joins so missing related rows are reported as inconsistent.
    objects = model.objects.all()
    anchor = objects.filter(pk=anchor_id).first()
    if anchor is None:
        raise LineageNotFound
    graph = safe_snapshot(anchor, snapshot_fn)
    if not graph:
        if cursor: raise InvalidLineageCursor
        return {'kind': kind, 'anchor_id': anchor_id, 'status': 'inconsistent', 'rows': [], 'next_cursor': None}
    anchor_hash = digest(graph)
    depth = 0
    current_id, current_hash = anchor_id, anchor_hash
    if cursor:
        current_id, expected, depth = _decode(cursor, kind, anchor_id, anchor_hash)
        current = objects.filter(pk=current_id).first()
        graph = safe_snapshot(current, snapshot_fn) if current else None
        if not graph:
            raise InvalidLineageCursor
        current_hash = digest(graph)
        if not constant_time_compare(expected, _fingerprint(current_hash)):
            raise InvalidLineageCursor
    rows = []
    # Do not inner-join links to related records: a dangling parent created by
    # privileged out-of-band writes must be flagged, not treated as no link.
    links = link_model.objects.all()
    for _ in range(PAGE_SIZE):
        link = links.filter(child_id=current_id).first()
        if link is None:
            return {'kind': kind, 'anchor_id': anchor_id, 'status': 'no_parent', 'rows': rows, 'next_cursor': None}
        valid = valid_package_revision(link, current_id) if kind == 'package' else valid_identity_revision(kind, link, current_id)
        if not valid or not constant_time_compare(link.child_graph_sha256, current_hash):
            return {'kind': kind, 'anchor_id': anchor_id, 'status': 'inconsistent', 'rows': rows, 'next_cursor': None}
        depth += 1
        rows.append({'child_id': current_id, 'parent_id': link.parent_id, 'depth': depth})
        current_id, current_hash = link.parent_id, link.parent_graph_sha256
    more = links.filter(child_id=current_id).exists()
    token = _encode(kind, anchor_id, anchor_hash, current_id, current_hash, depth) if more else None
    return {'kind': kind, 'anchor_id': anchor_id, 'status': 'more' if more else 'no_parent',
            'rows': rows, 'next_cursor': token}
