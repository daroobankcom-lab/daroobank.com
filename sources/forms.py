import re
from django import forms

from daroobank.forms import RawControlsMixin, RawMultilineControlsMixin

from .models import SourceClaimReview
from .services import FIELDS, MAX_PK, ClaimError, validate_data


class SourceClaimForm(RawControlsMixin, forms.Form):
    raw_control_fields = ('source_name', 'source_url', 'owner', 'evidence_url', 'evidence_note', 'starts_on', 'expires_on')
    source_name = forms.CharField(label='نام منبع', max_length=200)
    source_url = forms.URLField(label='نشانی HTTPS منبع', max_length=200)
    owner = forms.CharField(label='مالک یا دارنده حق اعلام‌شده', max_length=200)
    evidence_url = forms.URLField(label='نشانی HTTPS مدرک اعلام‌شده', max_length=200)
    evidence_note = forms.CharField(label='شرح کوتاه مدرک (بدون اطلاعات محرمانه)', max_length=1000, required=False)
    claims_collection = forms.BooleanField(label='جمع‌آوری', required=False)
    claims_storage = forms.BooleanField(label='ذخیره داخلی', required=False)
    claims_publication = forms.BooleanField(label='بازنشر', required=False)
    starts_on = forms.DateField(label='شروع اعلام‌شده (میلادی YYYY-MM-DD)', input_formats=['%Y-%m-%d'], required=False,
                                widget=forms.DateInput(attrs={'type': 'date'}))
    expires_on = forms.DateField(label='پایان اعلام‌شده (میلادی YYYY-MM-DD)', input_formats=['%Y-%m-%d'], required=False,
                                 widget=forms.DateInput(attrs={'type': 'date'}))
    attestation = forms.BooleanField(label='این موارد را به عنوان ادعای مستند، نه مجوز اثبات‌شده، ثبت می‌کنم.')

    def clean(self):
        data = super().clean()
        if all(key in data for key in FIELDS):
            try:
                validate_data({key: data[key] for key in FIELDS})
            except ClaimError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return data


class SourceReviewForm(RawControlsMixin, RawMultilineControlsMixin, forms.Form):
    raw_control_fields = ('expected_review', 'expected_hash')
    raw_multiline_control_fields = ('reason',)
    decision = forms.ChoiceField(label='نتیجه بررسی اولیه', choices=[
        ('', 'یک نتیجه انتخاب کنید'), (SourceClaimReview.FURTHER_REVIEW, 'ارجاع برای بررسی بیشتر'),
        (SourceClaimReview.REJECT, 'رد ادعا'), (SourceClaimReview.DEFER, 'نیاز به مدرک یا بررسی بیشتر'),
    ])
    reason = forms.CharField(label='دلیل', min_length=12, max_length=1000, widget=forms.Textarea(attrs={'rows': 4}))
    expected_review = forms.IntegerField(min_value=0, max_value=MAX_PK, widget=forms.HiddenInput)
    expected_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def clean_expected_hash(self):
        value = self.cleaned_data['expected_hash']
        if not re.fullmatch(r'[0-9a-f]{64}', value):
            raise forms.ValidationError('شناسه ادعا معتبر نیست.')
        return value
