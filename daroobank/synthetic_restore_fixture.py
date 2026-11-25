"""Cross-domain fixture only for the opt-in, disposable PostgreSQL restore drill."""
import io
import re
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection

from catalog.comparisons import valid_candidate as valid_product
from catalog.intake import review_product
from catalog.models import ProductCandidate, ProductCandidateReview
from catalog.test_intake import make_csv
from clinical.evidence import add_reference, evidence_state, reviewed_evidence
from clinical.models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from clinical.services import create_draft, review_draft, valid_draft
from ingestion.models import ImportReceipt, ImportReceiptItem
from ingestion.receipts import manifest_item_safe, manifest_structure, stage_price_with_receipt, stage_product_with_receipt
from pricing.comparisons import valid_candidate as valid_price
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import record_preliminary_review
from pricing.test_workflow import csv_bytes
from sources.models import SourceClaim, SourceClaimReview
from sources.review_inspection import classify_review
from sources.services import record_claim, review_claim, valid_claim


def _require(condition):
    """Keep synthetic-fixture checks active even when Python runs with -O."""
    if not condition:
        raise AssertionError('Synthetic restore fixture verification failed.')


def _require_disposable_name():
    # This does not prove the server is disposable. It is an additional guard,
    # never a substitute for independently checking the server and data.
    if (not settings.DEBUG or connection.vendor != 'postgresql'
            or not re.fullmatch(r'test_daroobank_restore_(?:target_)?[0-9a-f]{32}', connection.settings_dict['NAME'])):
        raise RuntimeError('Synthetic restore fixture requires an isolated restore database.')


def verify_identity_fixture(package_id, review_id, graph_hash):
    """Check the selected synthetic identity graph in the isolated database."""
    _require_disposable_name()
    from catalog.identity import digest, package_snapshot, review_is_consistent
    from catalog.models import IdentityPackageDraft, IdentityPackageReview

    package = IdentityPackageDraft.objects.get(pk=package_id)
    review = IdentityPackageReview.objects.get(pk=review_id)
    _require(IdentityPackageDraft.objects.count() == 1 and IdentityPackageReview.objects.count() == 1)
    _require(digest(package_snapshot(package)) == graph_hash)
    _require(review.package_id == package.pk and review.graph_sha256 == graph_hash)
    _require(review_is_consistent(review, package.pk) and review.reviewer.username == 'synthetic-restore-reviewer')
    _require(package.recorded_by.username == 'synthetic-restore-author')


def build_cross_domain_fixture(author, reviewer):
    _require_disposable_name()
    if not getattr(settings, 'DAROOBANK_RESTORE_ISOLATED', False):
        raise RuntimeError('Synthetic fixture creation requires dedicated restore settings.')
    author.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
        codename__in=['view_sourceclaim', 'add_sourceclaim']))
    reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
        codename__in=['view_sourceclaim', 'review_sourceclaim']))
    author.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
        codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
    reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
        codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
    author.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
        codename__in=['view_productcandidate', 'add_productcandidate']))
    reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
        codename__in=['view_productcandidate', 'review_productcandidate']))
    author.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
        codename__in=['view_pricecandidate', 'add_pricecandidate']))
    reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
        codename__in=['view_pricecandidate', 'review_pricecandidate']))
    # Refresh instances to avoid stale per-instance permission caches.
    author = get_user_model().objects.get(pk=author.pk)
    reviewer = get_user_model().objects.get(pk=reviewer.pk)
    source_name, url = 'منبع ساختگی تمرین بازیابی', 'https://example.org/synthetic-restore'
    reason = 'دلیل ساختگی برای آزمایش بازیابی'
    claim, created = record_claim(actor=author, data={
        'source_name': source_name, 'source_url': url, 'owner': 'مالک فرضی',
        'evidence_url': 'https://example.org/synthetic-evidence', 'evidence_note': '',
        'claims_collection': True, 'claims_storage': True, 'claims_publication': False,
        'starts_on': date(2025, 1, 2), 'expires_on': None})
    _require(created)
    review_claim(actor=reviewer, claim_id=claim.pk, decision='defer', reason=reason,
                 expected_review=0, expected_hash=claim.payload_sha256)

    product_row = {'source_record_id': 'restore-product', 'name_fa': 'فرآورده ساختگی بازیابی', 'name_en': '',
        'manufacturer': 'سازنده فرضی', 'strength': '5 mg', 'dosage_form': 'قرص',
        'package_description': '10 عدد', 'irc': '001'}
    stage_product_with_receipt(io.BytesIO(make_csv([product_row, product_row])), source_name, url,
                               actor=author, rights_attested=True)
    product = ProductCandidate.objects.get(source_record_id='restore-product')
    review_product(actor=reviewer, candidate_id=product.pk, decision='defer', reason=reason,
                   expected_review=0, expected_hash=product.payload_sha256)
    price_row = {'source_record_id': 'restore-price', 'irc': '001', 'manufacturer': 'سازنده فرضی',
        'strength': '5 mg', 'dosage_form': 'قرص', 'package_description': '10 عدد', 'amount': '100',
        'currency': 'RIAL', 'category': 'retail', 'unit': 'package', 'effective_date': '', 'source_published_date': ''}
    stage_price_with_receipt(io.BytesIO(csv_bytes([price_row, price_row])), source_name, url,
                             actor=author, rights_attested=True)
    price = PriceCandidate.objects.get(source_record_id='restore-price')
    record_preliminary_review(actor=reviewer, candidate_id=price.pk, decision='defer', reason=reason,
                              expected_review=0, expected_product=0, expected_product_hash='')

    draft_data = {'subject': 'موضوع ساختگی بازیابی', 'audience': 'patient', 'title': 'عنوان ساختگی بازیابی',
        'statement': 'متن ساختگی برای تمرین بازیابی پایگاه داده', 'reference_title': 'مرجع ساختگی',
        'reference_url': 'https://example.org/synthetic-reference', 'reference_location': 'بخش ساختگی',
        'reference_author': '', 'reference_version': '', 'reference_published_on': None, 'reference_accessed_on': None}
    draft = create_draft(actor=author, data=draft_data)
    reference = {key: draft_data[key] for key in ('reference_title', 'reference_url', 'reference_location',
        'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')}
    reference['relation'] = 'context'
    add_reference(actor=author, draft_id=draft.pk, data=reference, expected_draft_hash=draft.payload_sha256,
                  expected_evidence_hash=evidence_state(draft)['fingerprint'])
    review_draft(actor=reviewer, draft_id=draft.pk, decision='defer', reason=reason, expected_review=0,
                 expected_hash=draft.payload_sha256, expected_evidence_hash=evidence_state(draft)['fingerprint'])


def verify_cross_domain_fixture():
    _require_disposable_name()
    author = get_user_model().objects.get(username='synthetic-restore-author')
    reviewer = get_user_model().objects.get(username='synthetic-restore-reviewer')
    for app, entity in (('sources', 'sourceclaim'), ('catalog', 'productcandidate'),
                        ('pricing', 'pricecandidate'), ('clinical', 'clinicaldraft')):
        _require(author.has_perm(f'{app}.view_{entity}') and author.has_perm(f'{app}.add_{entity}'))
        _require(reviewer.has_perm(f'{app}.view_{entity}') and reviewer.has_perm(f'{app}.review_{entity}'))
    claim, claim_review = SourceClaim.objects.get(), SourceClaimReview.objects.get()
    _require(valid_claim(claim) and claim.recorded_by_id == author.pk and claim_review.reviewer_id == reviewer.pk)
    _require(classify_review(claim_review, claim, True) == ('consistent', 'same'))
    product, product_review = ProductCandidate.objects.get(), ProductCandidateReview.objects.get()
    price, price_review = PriceCandidate.objects.get(), PriceCandidateReview.objects.get()
    _require(valid_product(product) and valid_price(price) and price.amount_rial == 100)
    _require(product.staged_by_id == author.pk and product_review.candidate_id == product.pk)
    _require(price.staged_by_id == author.pk and price_review.candidate_id == price.pk)
    _require(product_review.candidate_payload_sha256 == product.payload_sha256)
    _require(price_review.candidate_payload_sha256 == price.payload_sha256)
    _require(product_review.reviewer_id == price_review.reviewer_id == reviewer.pk)
    _require(ImportReceipt.objects.count() == 2 and ImportReceiptItem.objects.count() == 4)
    for receipt in ImportReceipt.objects.all():
        _require(receipt.actor_id == author.pk and (receipt.rows, receipt.created, receipt.duplicates) == (2, 1, 1))
        _require(manifest_structure(receipt) == 'available')
        _require(all(manifest_item_safe(receipt, item) for item in receipt.items.all()))
    draft, draft_review = ClinicalDraft.objects.get(), ClinicalDraftReview.objects.get()
    reference = ClinicalReferenceAssertion.objects.get()
    _require(valid_draft(draft) and draft.author_id == author.pk and draft_review.reviewer_id == reviewer.pk)
    _require(draft_review.draft_id == draft.pk and draft_review.draft_payload_sha256 == draft.payload_sha256)
    _require(reference.draft_id == draft.pk and reference.recorded_by_id == author.pk)
    current, historical = evidence_state(draft), reviewed_evidence(draft_review)
    _require(current['status'] == historical['status'] == 'available' and current['fingerprint'] == historical['fingerprint'])
    _require(draft_review.review_snapshot['evidence_snapshot'][0]['id'] == reference.pk)


def verify_post_restore_writes():
    """Exercise generated IDs and relationships on the fresh restored target only."""
    _require_disposable_name()
    if not re.fullmatch(r'test_daroobank_restore_target_[0-9a-f]{32}', connection.settings_dict['NAME']):
        raise RuntimeError('Post-restore writes require the new synthetic target database.')
    from django.db.models import Max
    from catalog.identity import digest, package_snapshot, review_package
    from catalog.models import IdentityPackageDraft, IdentityPackageReview
    from catalog.test_identity import build

    models = (SourceClaim, SourceClaimReview, ProductCandidate, ProductCandidateReview,
              PriceCandidate, PriceCandidateReview, ImportReceipt, ImportReceiptItem,
              ClinicalDraft, ClinicalReferenceAssertion, ClinicalDraftReview,
              IdentityPackageDraft, IdentityPackageReview)
    before = {model: model.objects.aggregate(value=Max('pk'))['value'] or 0 for model in models}
    author = get_user_model().objects.get(username='synthetic-restore-author')
    reviewer = get_user_model().objects.get(username='synthetic-restore-reviewer')
    reason = 'آزمایش ساختگی ثبت پس از بازیابی'
    name = 'منبع دوم ساختگی بازیابی'
    url = 'https://example.org/synthetic-after-restore'
    claim, created = record_claim(actor=author, data={
        'source_name': name, 'source_url': url, 'owner': 'مالک فرضی',
        'evidence_url': 'https://example.org/synthetic-after-evidence', 'evidence_note': '',
        'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
        'starts_on': None, 'expires_on': None})
    _require(created)
    review_claim(actor=reviewer, claim_id=claim.pk, decision='defer', reason=reason,
                 expected_review=0, expected_hash=claim.payload_sha256)
    product_row = {'source_record_id': 'restore-product-new', 'name_fa': 'فرآورده ساختگی دوم', 'name_en': '',
        'manufacturer': 'سازنده فرضی', 'strength': '5 mg', 'dosage_form': 'قرص',
        'package_description': '10 عدد', 'irc': '002'}
    stage_product_with_receipt(io.BytesIO(make_csv([product_row])), name, url, actor=author, rights_attested=True)
    product = ProductCandidate.objects.get(source_record_id='restore-product-new')
    review_product(actor=reviewer, candidate_id=product.pk, decision='defer', reason=reason,
                   expected_review=0, expected_hash=product.payload_sha256)
    price_row = {'source_record_id': 'restore-price-new', 'irc': '002', 'manufacturer': 'سازنده فرضی',
        'strength': '5 mg', 'dosage_form': 'قرص', 'package_description': '10 عدد', 'amount': '101',
        'currency': 'RIAL', 'category': 'retail', 'unit': 'package', 'effective_date': '', 'source_published_date': ''}
    stage_price_with_receipt(io.BytesIO(csv_bytes([price_row])), name, url, actor=author, rights_attested=True)
    price = PriceCandidate.objects.get(source_record_id='restore-price-new')
    record_preliminary_review(actor=reviewer, candidate_id=price.pk, decision='defer', reason=reason,
                              expected_review=0, expected_product=0, expected_product_hash='')
    draft_data = {'subject': 'موضوع دوم ساختگی', 'audience': 'patient', 'title': 'عنوان دوم ساختگی',
        'statement': 'متن دوم ساختگی برای آزمایش بازیابی پایگاه داده', 'reference_title': 'مرجع دوم ساختگی',
        'reference_url': 'https://example.org/synthetic-after-reference', 'reference_location': 'بخش فرضی',
        'reference_author': '', 'reference_version': '', 'reference_published_on': None, 'reference_accessed_on': None}
    draft = create_draft(actor=author, data=draft_data)
    reference = {key: draft_data[key] for key in ('reference_title', 'reference_url', 'reference_location',
        'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')}
    reference['relation'] = 'context'
    add_reference(actor=author, draft_id=draft.pk, data=reference, expected_draft_hash=draft.payload_sha256,
                  expected_evidence_hash=evidence_state(draft)['fingerprint'])
    review_draft(actor=reviewer, draft_id=draft.pk, decision='defer', reason=reason, expected_review=0,
                 expected_hash=draft.payload_sha256, expected_evidence_hash=evidence_state(draft)['fingerprint'])
    package = build(author)[-1]
    review_package(actor=reviewer, package_id=package.pk, decision='defer', reason=reason,
                   expected_review=0, expected_graph_hash=digest(package_snapshot(package)))
    for model in models:
        _require(model.objects.aggregate(value=Max('pk'))['value'] > before[model])


def verify_source_sequence_probe():
    """Insert one more synthetic claim, only on the already-restored target."""
    _require_disposable_name()
    if not re.fullmatch(r'test_daroobank_restore_target_[0-9a-f]{32}', connection.settings_dict['NAME']):
        raise RuntimeError('Sequence probe requires the new synthetic target database.')
    author = get_user_model().objects.get(username='synthetic-restore-author')
    claim, created = record_claim(actor=author, data={
        'source_name': 'منبع ساختگی آزمون دنباله',
        'source_url': 'https://example.org/synthetic-sequence-probe', 'owner': 'مالک فرضی',
        'evidence_url': 'https://example.org/synthetic-sequence-evidence', 'evidence_note': '',
        'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
        'starts_on': None, 'expires_on': None})
    _require(created and valid_claim(claim))
