from decimal import Decimal
from django import forms
from django.forms import formset_factory
from .identity import MAX_COMPONENTS
from .models import IdentityPackageReview


class AssertionForm(forms.Form):
    source_name = forms.CharField(label='نام منبع ادعایی', max_length=200)
    source_url = forms.URLField(label='نشانی HTTPS منبع ادعایی', max_length=200)
    synthetic_ack = forms.BooleanField(label='فقط داده ساختگی و غیرمحرمانه وارد می‌کنم.')


class IngredientForm(AssertionForm):
    name_fa = forms.CharField(label='نام فارسی ماده ساختگی', max_length=200)
    name_en = forms.CharField(label='نام انگلیسی (اختیاری)', max_length=200, required=False)


class FormulationForm(AssertionForm):
    name = forms.CharField(label='نام فرمولاسیون ساختگی', max_length=200)
    dosage_form = forms.CharField(label='شکل دارویی ادعایی', max_length=100)
    route = forms.CharField(label='مسیر مصرف ادعایی', max_length=100)


class ComponentForm(forms.Form):
    ingredient_id = forms.IntegerField(label='شناسه ماده', min_value=1, max_value=9223372036854775807)
    numerator = forms.DecimalField(label='مقدار صورت', max_digits=12, decimal_places=4, min_value=Decimal('0.0001'))
    numerator_unit = forms.CharField(label='واحد صورت', max_length=50)
    denominator = forms.DecimalField(label='مقدار مخرج', max_digits=12, decimal_places=4, min_value=Decimal('0.0001'))
    denominator_unit = forms.CharField(label='واحد مخرج', max_length=50)


ComponentFormSet = formset_factory(ComponentForm, extra=MAX_COMPONENTS, min_num=1, validate_min=True,
                                    max_num=MAX_COMPONENTS, validate_max=True, absolute_max=MAX_COMPONENTS)


class ProductForm(AssertionForm):
    formulation_id = forms.IntegerField(label='شناسه فرمولاسیون', min_value=1, max_value=9223372036854775807)
    name = forms.CharField(label='نام فرآورده ساختگی', max_length=200)
    brand = forms.CharField(label='نام تجاری ادعایی (اختیاری)', max_length=200, required=False)
    manufacturer = forms.CharField(label='سازنده ادعایی', max_length=200)


class PackageForm(AssertionForm):
    product_id = forms.IntegerField(label='شناسه فرآورده', min_value=1, max_value=9223372036854775807)
    description = forms.CharField(label='شرح بسته ساختگی', max_length=200)
    quantity = forms.DecimalField(label='مقدار بسته', max_digits=12, decimal_places=4, min_value=Decimal('0.0001'))
    quantity_unit = forms.CharField(label='واحد مقدار بسته', max_length=50)
    irc = forms.CharField(label='IRC ادعایی (اختیاری)', max_length=80, required=False)


class IdentityReviewForm(forms.Form):
    decision = forms.ChoiceField(label='نتیجه بررسی اولیه', choices=[('', 'انتخاب کنید'),
        ('further_review', 'ارجاع برای بررسی بیشتر'), ('reject', 'رد'), ('defer', 'نیاز به بررسی بیشتر')])
    reason = forms.CharField(label='دلیل', min_length=12, max_length=1000, widget=forms.Textarea(attrs={'rows': 3}))
    expected_review = forms.IntegerField(min_value=0, max_value=9223372036854775807, widget=forms.HiddenInput)
    expected_graph_hash = forms.RegexField(regex=r'^[0-9a-f]{64}$', max_length=64, widget=forms.HiddenInput)
