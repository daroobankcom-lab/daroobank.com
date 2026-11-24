import re
from django import forms

from daroobank.forms import SourceUploadRawControlsMixin
from .intake import MAX_FILE_BYTES, MAX_PK
from .models import ProductCandidateReview


class ProductUploadForm(SourceUploadRawControlsMixin, forms.Form):
    source_name = forms.CharField(label='نام منبع', max_length=200)
    source_url = forms.URLField(label='نشانی HTTPS منبع', max_length=200)
    csv_file = forms.FileField(label='فایل CSV مجاز')
    action = forms.ChoiceField(label='نوع عملیات', choices=[('preview', 'فقط بررسی آزمایشی'), ('stage', 'ثبت برای بررسی')], initial='preview')
    rights_attested = forms.BooleanField(label='مجوز جمع‌آوری و ذخیره داخلی این داده را دارم.', required=False)

    def clean_csv_file(self):
        file = self.cleaned_data['csv_file']
        if file.size > MAX_FILE_BYTES:
            raise forms.ValidationError('حجم فایل نباید بیشتر از یک مگابایت باشد.')
        return file

    def clean(self):
        data = super().clean()
        if data.get('action') == 'stage' and not data.get('rights_attested'):
            self.add_error('rights_attested', 'برای ثبت داده باید مجوز را تأیید کنید.')
        return data


class ProductReviewForm(forms.Form):
    decision = forms.ChoiceField(label='نتیجه بررسی اولیه', choices=[
        ('', 'یک نتیجه انتخاب کنید'),
        (ProductCandidateReview.FURTHER_REVIEW, 'قابل ارجاع برای بررسی بیشتر'),
        (ProductCandidateReview.REJECT, 'رد نامزد'),
        (ProductCandidateReview.DEFER, 'نیاز به بررسی بیشتر'),
    ])
    reason = forms.CharField(label='توضیح و دلیل', min_length=12, max_length=1000, widget=forms.Textarea(attrs={'rows': 4}))
    expected_review = forms.IntegerField(min_value=0, max_value=MAX_PK, widget=forms.HiddenInput)
    expected_hash = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def clean_expected_hash(self):
        value = self.cleaned_data['expected_hash']
        if not re.fullmatch(r'[0-9a-f]{64}', value):
            raise forms.ValidationError('شناسه داده معتبر نیست.')
        return value
