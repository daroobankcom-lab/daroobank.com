from django.core.management.base import BaseCommand, CommandError
from ingestion.exceptions import StagingConflict
from pricing.importer import ImportValidationError, stage_csv


class Command(BaseCommand):
    help = 'Validate or stage an authorized local CSV for review; never publish prices.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='Path to an authorized UTF-8 CSV file')
        parser.add_argument('--source-name', required=True)
        parser.add_argument('--source-url', required=True)
        parser.add_argument('--commit', action='store_true', help='Store candidates (default is dry run)')
        parser.add_argument('--attest-authorized', action='store_true', help='Attest collection and internal storage are permitted')

    def handle(self, *args, **options):
        if options['commit'] and not options['attest_authorized']:
            raise CommandError('Staging requires --attest-authorized; do not import data without permission.')
        try:
            counts = stage_csv(options['path'], options['source_name'], options['source_url'], commit=options['commit'], rights_attested=options['attest_authorized'])
        except (ImportValidationError, StagingConflict) as exc:
            raise CommandError(str(exc)) from exc
        mode = 'STAGED' if options['commit'] else 'DRY RUN'
        self.stdout.write(f"{mode}: " + ', '.join(f'{key}={value}' for key, value in counts.items()))
        self.stdout.write('No prices were published. Product matches are suggestions requiring human review.')
        self.stdout.write('Repeated identities and IRC candidate sets may reuse earlier observations in this run; concurrent catalog changes may be missed.')
