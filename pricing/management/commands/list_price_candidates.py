import json

from django.core.management.base import BaseCommand, CommandError
from daroobank.candidate_content_bounds import bounded_candidates, materialize_candidate
from pricing.importer import match_fields_valid, suggest_product
from pricing.models import PriceCandidate
from pricing.reviews import ReviewConflict, ensure_candidate_integrity


class Command(BaseCommand):
    help = 'List staged price candidates as JSON for a local operator; does not approve or publish.'

    def add_arguments(self, parser):
        parser.add_argument('--status', choices=['suggested', 'ambiguous', 'unmatched'])
        parser.add_argument('--limit', type=int, default=30)

    def handle(self, *args, **options):
        limit = options['limit']
        if not 1 <= limit <= 100:
            raise CommandError('Limit must be between 1 and 100.')
        records = PriceCandidate.objects.order_by('id')
        if options['status']:
            records = records.filter(match_status=options['status'])
        data = []
        for item in bounded_candidates(records)[:limit]:
            materialize_candidate(item)
            if item.content_oversized:
                # A partial/missing payload is uninspected, not necessarily invalid.
                data.append({'id': item.pk, 'review_required': True, 'payload_status': 'oversized',
                             'current_suggestion': {'match_status': 'unknown', 'suggested_product_id': None}})
                continue
            try:
                ensure_candidate_integrity(item)
            except ReviewConflict:
                # Do not echo or match an inconsistent staged payload. This local
                # diagnostic does not establish source rights or authenticity.
                data.append({'id': item.pk, 'review_required': True, 'payload_status': 'invalid',
                             'current_suggestion': {'match_status': 'invalid', 'suggested_product_id': None}})
                continue
            if match_fields_valid(item.source_fields):
                current_status, current_product = suggest_product(item.source_fields)
            else:
                current_status, current_product = 'invalid', None
            data.append({
                'id': item.pk,
                'review_required': True,
                'payload_status': 'consistent',
                'match_status': item.match_status,
                'suggested_product_id': item.suggested_product_id,
                'current_suggestion': {
                    'match_status': current_status,
                    'suggested_product_id': current_product.pk if current_product else None,
                },
                'source_name': item.source_name,
                'source_url': item.source_url,
                'source_record_id': item.source_record_id,
                'source_fields': item.source_fields,
                'original_amount': item.original_amount,
                'original_currency': item.original_currency,
                'amount_rial': item.amount_rial,
                'price_category': item.price_category,
                'unit': item.unit,
                'effective_date': item.effective_date.isoformat() if item.effective_date else None,
                'source_published_date': item.source_published_date.isoformat() if item.source_published_date else None,
                'collected_at': item.collected_at.isoformat(),
            })
        # ASCII JSON escapes control characters; never emit raw terminal escape sequences.
        self.stdout.write(json.dumps({'data': data, 'limit': limit}, ensure_ascii=True))
