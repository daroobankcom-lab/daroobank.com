import re

from django import forms
from daroobank.forms import SourceUploadRawControlsMixin
from .importer import MAX_FILE_BYTES
from .models import PriceCandidateReview
from .reviews import MAX_PK


class PriceUploadForm(SourceUploadRawControlsMixin, forms.Form):
    source_name = forms.CharField(label='نام منبع', max_length=200)
    source_url = forms.URLField(label='نشانی HTTPS منبع', max_length=200)
    csv_file = forms.FileField(label='فایل CSV مجاز')
    action = forms.ChoiceField(
        label='نوع عملیات', choices=[('preview', 'فقط بررسی آزمایشی'), ('stage', 'ثبت برای بررسی')],
        initial='preview',
    )
    rights_attested = forms.BooleanField(
        label='تأیید می‌کنم مجوز جمع‌آوری و ذخیره داخلی این داده را دارم.', required=False,
    )

    def clean_csv_file(self):
        upload = self.cleaned_data['csv_file']
        if upload.size > MAX_FILE_BYTES:
            raise forms.ValidationError('حجم فایل نباید بیشتر از ۲ مگابایت باشد.')
        return upload

    def clean(self):
        values = super().clean()
        if values.get('action') == 'stage' and not values.get('rights_attested'):
            self.add_error('rights_attested', 'برای ثبت داده باید مجوز را تأیید کنید.')
        return values


class PriceReviewForm(forms.Form):
    decision = forms.ChoiceField(label='نتیجه بررسی اولیه', choices=[
        ('', 'یک نتیجه انتخاب کنید'),
        (PriceCandidateReview.ACCEPT_SUGGESTION, 'پذیرش اولیه پیشنهاد تطبیق'),
        (PriceCandidateReview.REJECT, 'رد نامزد'),
        (PriceCandidateReview.DEFER, 'نیاز به بررسی بیشتر'),
    ])
    reason = forms.CharField(label='توضیح و دلیل', min_length=12, max_length=1000, widget=forms.Textarea(attrs={'rows': 4}))
    expected_review = forms.IntegerField(min_value=0, max_value=MAX_PK, widget=forms.HiddenInput)
    expected_product = forms.IntegerField(min_value=0, max_value=MAX_PK, widget=forms.HiddenInput)
    expected_product_hash = forms.CharField(required=False, max_length=64, widget=forms.HiddenInput)

    def clean_expected_product_hash(self):
        value = self.cleaned_data['expected_product_hash']
        if value and not re.fullmatch(r'[0-9a-f]{64}', value):
            raise forms.ValidationError('شناسه تطبیق معتبر نیست.')
        return value
