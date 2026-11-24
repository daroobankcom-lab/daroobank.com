from django import forms

from daroobank.forms import ExplicitBooleanField, RawControlsMixin, RawMultilineControlsMixin

from .models import ClinicalDraft, ClinicalDraftReview
from .services import FIELDS, HASH, MAX_PK, DraftError, validate_data


class DraftForm(RawControlsMixin, RawMultilineControlsMixin, forms.Form):
    raw_multiline_control_fields = ('statement',)
    # Statement remains multiline; tabs and line breaks are allowed.
    raw_control_fields = ('subject', 'title', 'reference_title', 'reference_url', 'reference_location',
                          'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')
    subject = forms.CharField(label='موضوع ساختگی (بدون ارتباط خودکار با کاتالوگ)', max_length=200)
    audience = forms.ChoiceField(label='مخاطب', choices=[('', 'انتخاب کنید')] + ClinicalDraft.AUDIENCES)
    title = forms.CharField(label='عنوان پیش‌نویس', max_length=200)
    statement = forms.CharField(label='متن گزاره ساختگی', max_length=4000, widget=forms.Textarea(attrs={'rows': 6}))
    reference_title = forms.CharField(label='عنوان ارجاع اعلام‌شده', max_length=300)
    reference_url = forms.URLField(label='نشانی HTTPS ارجاع', max_length=200)
    reference_location = forms.CharField(label='محل دقیق گزاره در ارجاع', max_length=300)
    reference_author = forms.CharField(label='نویسنده یا سازمان اعلام‌شده (اختیاری)', max_length=200, required=False)
    reference_version = forms.CharField(label='نسخه منبع اعلام‌شده (اختیاری)', max_length=200, required=False)
    reference_published_on = forms.DateField(label='تاریخ انتشار اعلام‌شده (میلادی)', input_formats=['%Y-%m-%d'], required=False,
                                             widget=forms.DateInput(attrs={'type': 'date'}))
    reference_accessed_on = forms.DateField(label='تاریخ دسترسی اعلام‌شده (میلادی)', input_formats=['%Y-%m-%d'], required=False,
                                            widget=forms.DateInput(attrs={'type': 'date'}))
    synthetic_ack = ExplicitBooleanField(label='فقط اطلاعات ساختگی، غیرمحرمانه و بدون اطلاعات بیمار وارد می‌کنم.')

    def clean(self):
        data = super().clean()
        if all(key in data for key in FIELDS):
            try:
                validate_data({key: data[key] for key in FIELDS})
            except DraftError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return data


class RevisionForm(DraftForm):
    raw_control_fields = DraftForm.raw_control_fields + ('expected_parent_hash',)
    raw_multiline_control_fields = ('statement', 'change_reason')
    expected_parent_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)
    change_reason = forms.CharField(label='دلیل ایجاد نسخه جدید', min_length=12, max_length=1000,
                                    widget=forms.Textarea(attrs={'rows': 3}))

    def clean_expected_parent_hash(self):
        value = self.cleaned_data['expected_parent_hash']
        if not HASH.fullmatch(value):
            raise forms.ValidationError('شناسه نسخه قبلی معتبر نیست.')
        return value


class ReviewForm(RawControlsMixin, RawMultilineControlsMixin, forms.Form):
    raw_control_fields = ('expected_review', 'expected_hash', 'expected_evidence_hash')
    raw_multiline_control_fields = ('reason',)
    decision = forms.ChoiceField(label='نتیجه بررسی اولیه', choices=[('', 'انتخاب کنید'),
        (ClinicalDraftReview.FURTHER_REVIEW, 'ارجاع برای بررسی بیشتر'), (ClinicalDraftReview.REJECT, 'رد پیش‌نویس'),
        (ClinicalDraftReview.DEFER, 'نیاز به بررسی یا مدرک بیشتر')])
    reason = forms.CharField(label='دلیل', min_length=12, max_length=1000, widget=forms.Textarea(attrs={'rows': 4}))
    expected_review = forms.IntegerField(min_value=0, max_value=MAX_PK, widget=forms.HiddenInput)
    expected_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)
    expected_evidence_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def clean_expected_evidence_hash(self):
        value = self.cleaned_data['expected_evidence_hash']
        if not HASH.fullmatch(value):
            raise forms.ValidationError('شناسه ارجاع‌ها معتبر نیست.')
        return value

    def clean_expected_hash(self):
        value = self.cleaned_data['expected_hash']
        if not HASH.fullmatch(value):
            raise forms.ValidationError('شناسه پیش‌نویس معتبر نیست.')
        return value


class ReferenceForm(RawControlsMixin, forms.Form):
    raw_control_fields = ('reference_title', 'reference_url', 'reference_location', 'reference_author', 'reference_version',
                          'reference_published_on', 'reference_accessed_on', 'expected_draft_hash', 'expected_evidence_hash')
    reference_title = forms.CharField(label='عنوان ارجاع ساختگی', max_length=300)
    reference_url = forms.URLField(label='نشانی HTTPS ارجاع', max_length=200)
    reference_location = forms.CharField(label='محل دقیق در ارجاع', max_length=300)
    reference_author = forms.CharField(label='نویسنده یا سازمان اعلام‌شده (اختیاری)', max_length=200, required=False)
    reference_version = forms.CharField(label='نسخه اعلام‌شده (اختیاری)', max_length=200, required=False)
    reference_published_on = forms.DateField(label='تاریخ انتشار اعلام‌شده (میلادی)', input_formats=['%Y-%m-%d'], required=False,
                                             widget=forms.DateInput(attrs={'type': 'date'}))
    reference_accessed_on = forms.DateField(label='تاریخ دسترسی اعلام‌شده (میلادی)', input_formats=['%Y-%m-%d'], required=False,
                                            widget=forms.DateInput(attrs={'type': 'date'}))
    relation = forms.ChoiceField(label='رابطه ادعایی با گزاره', choices=[('', 'انتخاب کنید'),
        ('supports', 'پشتیبان ادعایی'), ('contradicts', 'متناقض ادعایی'),
        ('context', 'زمینه ادعایی'), ('unclear', 'رابطه نامشخص')])
    synthetic_ack = ExplicitBooleanField(label='فقط اطلاعات ساختگی، غیرمحرمانه و بدون اطلاعات بیمار وارد می‌کنم.')
    expected_draft_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)
    expected_evidence_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def clean(self):
        from .evidence import ASSERTION_FIELDS, validate_reference
        data = super().clean()
        if all(key in data for key in ASSERTION_FIELDS):
            try:
                validate_reference({key: data[key] for key in ASSERTION_FIELDS})
            except DraftError as exc:
                raise forms.ValidationError(str(exc)) from exc
        for key in ('expected_draft_hash', 'expected_evidence_hash'):
            if key in data and not HASH.fullmatch(data[key]):
                self.add_error(key, 'شناسه معتبر نیست.')
        return data
