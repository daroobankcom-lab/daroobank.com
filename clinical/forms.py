from django import forms

from .models import ClinicalDraft, ClinicalDraftReview
from .services import FIELDS, HASH, DraftError, validate_data


class DraftForm(forms.Form):
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
    synthetic_ack = forms.BooleanField(label='فقط اطلاعات ساختگی، غیرمحرمانه و بدون اطلاعات بیمار وارد می‌کنم.')

    def clean(self):
        data = super().clean()
        if all(key in data for key in FIELDS):
            try:
                validate_data({key: data[key] for key in FIELDS})
            except DraftError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return data


class RevisionForm(DraftForm):
    expected_parent_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)
    change_reason = forms.CharField(label='دلیل ایجاد نسخه جدید', min_length=12, max_length=1000,
                                    widget=forms.Textarea(attrs={'rows': 3}))

    def clean_expected_parent_hash(self):
        value = self.cleaned_data['expected_parent_hash']
        if not HASH.fullmatch(value):
            raise forms.ValidationError('شناسه نسخه قبلی معتبر نیست.')
        return value


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label='نتیجه بررسی اولیه', choices=[('', 'انتخاب کنید'),
        (ClinicalDraftReview.FURTHER_REVIEW, 'ارجاع برای بررسی بیشتر'), (ClinicalDraftReview.REJECT, 'رد پیش‌نویس'),
        (ClinicalDraftReview.DEFER, 'نیاز به بررسی یا مدرک بیشتر')])
    reason = forms.CharField(label='دلیل', min_length=12, max_length=1000, widget=forms.Textarea(attrs={'rows': 4}))
    expected_review = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    expected_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def clean_expected_hash(self):
        value = self.cleaned_data['expected_hash']
        if not HASH.fullmatch(value):
            raise forms.ValidationError('شناسه پیش‌نویس معتبر نیست.')
        return value
