from decimal import Decimal
from django import forms
from django.forms import BaseFormSet, formset_factory

from daroobank.forms import RawControlsMixin, RawMultilineControlsMixin
from .identity import MAX_COMPONENTS


class AssertionForm(RawControlsMixin, RawMultilineControlsMixin, forms.Form):
    raw_control_fields = ('source_name', 'source_url')
    source_name = forms.CharField(label='نام منبع ادعایی', max_length=200)
    source_url = forms.URLField(label='نشانی HTTPS منبع ادعایی', max_length=200)
    synthetic_ack = forms.BooleanField(label='فقط داده ساختگی و غیرمحرمانه وارد می‌کنم.')


class IngredientForm(AssertionForm):
    raw_control_fields = AssertionForm.raw_control_fields + ('name_fa', 'name_en')
    name_fa = forms.CharField(label='نام فارسی ماده ساختگی', max_length=200)
    name_en = forms.CharField(label='نام انگلیسی (اختیاری)', max_length=200, required=False)


class FormulationForm(AssertionForm):
    raw_control_fields = AssertionForm.raw_control_fields + ('name', 'dosage_form', 'route')
    name = forms.CharField(label='نام فرمولاسیون ساختگی', max_length=200)
    dosage_form = forms.CharField(label='شکل دارویی ادعایی', max_length=100)
    route = forms.CharField(label='مسیر مصرف ادعایی', max_length=100)


class ComponentForm(RawControlsMixin, forms.Form):
    raw_control_fields = ('ingredient_id', 'numerator', 'numerator_unit', 'denominator', 'denominator_unit')
    ingredient_id = forms.IntegerField(label='شناسه ماده', min_value=1, max_value=9223372036854775807)
    numerator = forms.DecimalField(label='مقدار صورت', max_digits=12, decimal_places=4, min_value=Decimal('0.0001'))
    numerator_unit = forms.CharField(label='واحد صورت', max_length=50)
    denominator = forms.DecimalField(label='مقدار مخرج', max_digits=12, decimal_places=4, min_value=Decimal('0.0001'))
    denominator_unit = forms.CharField(label='واحد مخرج', max_length=50)


class BaseComponentFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if not self.management_form.is_valid():
            return
        management = self.management_form.cleaned_data
        # This is a fixed create-only form, never an edit formset.
        if management['TOTAL_FORMS'] != MAX_COMPONENTS or management['INITIAL_FORMS'] != 0:
            raise forms.ValidationError('ساختار فرم اجزا معتبر نیست؛ صفحه ثبت را دوباره باز کنید.')
        if any(self.errors):
            return
        ingredient_ids = [form.cleaned_data['ingredient_id'] for form in self.forms if form.cleaned_data]
        if len(ingredient_ids) != len(set(ingredient_ids)):
            raise forms.ValidationError('هر ماده فقط یک بار مجاز است.')


ComponentFormSet = formset_factory(ComponentForm, formset=BaseComponentFormSet, extra=MAX_COMPONENTS,
                                    min_num=1, validate_min=True, max_num=MAX_COMPONENTS,
                                    validate_max=True, absolute_max=MAX_COMPONENTS)


class ProductForm(AssertionForm):
    raw_control_fields = AssertionForm.raw_control_fields + ('formulation_id', 'name', 'brand', 'manufacturer')
    formulation_id = forms.IntegerField(label='شناسه فرمولاسیون', min_value=1, max_value=9223372036854775807)
    name = forms.CharField(label='نام فرآورده ساختگی', max_length=200)
    brand = forms.CharField(label='نام تجاری ادعایی (اختیاری)', max_length=200, required=False)
    manufacturer = forms.CharField(label='سازنده ادعایی', max_length=200)


class PackageForm(AssertionForm):
    raw_control_fields = AssertionForm.raw_control_fields + ('product_id', 'description', 'quantity', 'quantity_unit', 'irc')
    product_id = forms.IntegerField(label='شناسه فرآورده', min_value=1, max_value=9223372036854775807)
    description = forms.CharField(label='شرح بسته ساختگی', max_length=200)
    quantity = forms.DecimalField(label='مقدار بسته', max_digits=12, decimal_places=4, min_value=Decimal('0.0001'))
    quantity_unit = forms.CharField(label='واحد مقدار بسته', max_length=50)
    irc = forms.CharField(label='IRC ادعایی (اختیاری)', max_length=80, required=False)


class IdentityReviewForm(RawControlsMixin, RawMultilineControlsMixin, forms.Form):
    raw_control_fields = ('expected_review', 'expected_graph_hash')
    raw_multiline_control_fields = ('reason',)
    decision = forms.ChoiceField(label='نتیجه بررسی اولیه', choices=[('', 'انتخاب کنید'),
        ('further_review', 'ارجاع برای بررسی بیشتر'), ('reject', 'رد'), ('defer', 'نیاز به بررسی بیشتر')])
    reason = forms.CharField(label='دلیل', min_length=12, max_length=1000, widget=forms.Textarea(attrs={'rows': 3}))
    expected_review = forms.IntegerField(min_value=0, max_value=9223372036854775807, widget=forms.HiddenInput)
    expected_graph_hash = forms.RegexField(regex=r'^[0-9a-f]{64}$', max_length=64, widget=forms.HiddenInput)


class PackageRevisionForm(PackageForm):
    raw_control_fields = tuple(field for field in PackageForm.raw_control_fields if field != 'product_id') + ('expected_graph_hash', 'expected_review')
    raw_multiline_control_fields = ('change_reason',)
    # Corrections remain tied to the same product; changing the product needs a separate assertion.
    product_id = None
    change_reason = forms.CharField(label='دلیل اصلاح ادعایی', min_length=12, max_length=1000,
                                    widget=forms.Textarea(attrs={'rows': 3}))
    expected_graph_hash = forms.RegexField(regex=r'^[0-9a-f]{64}$', max_length=64, widget=forms.HiddenInput)
    expected_review = forms.IntegerField(min_value=0, max_value=9223372036854775807, widget=forms.HiddenInput)


class IngredientRevisionForm(IngredientForm):
    raw_control_fields = IngredientForm.raw_control_fields + ('expected_graph_hash',)
    raw_multiline_control_fields = ('change_reason',)
    change_reason = forms.CharField(label='دلیل اصلاح ادعایی', min_length=12, max_length=1000,
                                    widget=forms.Textarea(attrs={'rows': 3}))
    expected_graph_hash = forms.RegexField(regex=r'^[0-9a-f]{64}$', max_length=64, widget=forms.HiddenInput)


class FormulationRevisionForm(FormulationForm):
    raw_control_fields = FormulationForm.raw_control_fields + ('expected_graph_hash',)
    raw_multiline_control_fields = ('change_reason',)
    change_reason = forms.CharField(label='دلیل اصلاح ادعایی', min_length=12, max_length=1000,
                                    widget=forms.Textarea(attrs={'rows': 3}))
    expected_graph_hash = forms.RegexField(regex=r'^[0-9a-f]{64}$', max_length=64, widget=forms.HiddenInput)


class ProductRevisionForm(ProductForm):
    raw_control_fields = tuple(field for field in ProductForm.raw_control_fields if field != 'formulation_id') + ('expected_graph_hash',)
    raw_multiline_control_fields = ('change_reason',)
    formulation_id = None
    change_reason = forms.CharField(label='دلیل اصلاح ادعایی', min_length=12, max_length=1000,
                                    widget=forms.Textarea(attrs={'rows': 3}))
    expected_graph_hash = forms.RegexField(regex=r'^[0-9a-f]{64}$', max_length=64, widget=forms.HiddenInput)


class BaseRevisionComponentFormSet(BaseFormSet):
    def __init__(self, *args, expected_initial, **kwargs):
        self.expected_initial = expected_initial
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.management_form.is_valid():
            return
        management = self.management_form.cleaned_data
        if management['TOTAL_FORMS'] != MAX_COMPONENTS or management['INITIAL_FORMS'] != self.expected_initial:
            raise forms.ValidationError('ساختار فرم اجزا معتبر نیست؛ صفحه اصلاح را دوباره باز کنید.')
        if any(self.errors):
            return
        ids = [form.cleaned_data['ingredient_id'] for form in self.forms if form.cleaned_data]
        if len(ids) != len(set(ids)):
            raise forms.ValidationError('هر ماده فقط یک بار مجاز است.')


RevisionComponentFormSet = formset_factory(ComponentForm, formset=BaseRevisionComponentFormSet,
    extra=MAX_COMPONENTS, min_num=1, validate_min=True, max_num=MAX_COMPONENTS,
    validate_max=True, absolute_max=MAX_COMPONENTS)
