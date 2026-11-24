from django import forms

from daroobank.forms import RawControlsMixin
from .schedule import DEFAULT_END, DEFAULT_START, DEFAULT_ZONE, ScheduleError, parse_time, parse_zone


class WindowForm(RawControlsMixin, forms.Form):
    # Check the submitted strings before CharField strips boundary controls.
    raw_control_fields = ('start', 'end', 'zone')
    start = forms.CharField(label='شروع محلی (HH:MM)', max_length=5, initial=DEFAULT_START)
    end = forms.CharField(label='پایان محلی (HH:MM)', max_length=5, initial=DEFAULT_END)
    zone = forms.CharField(label='منطقه زمانی IANA', max_length=80, initial=DEFAULT_ZONE)

    def clean_start(self):
        value = self.cleaned_data['start']
        try:
            parse_time(value)
        except ScheduleError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return value

    def clean_end(self):
        value = self.cleaned_data['end']
        try:
            parse_time(value)
        except ScheduleError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return value

    def clean_zone(self):
        value = self.cleaned_data['zone']
        try:
            parse_zone(value)
        except ScheduleError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return value

    def clean(self):
        values = super().clean()
        if 'start' in values and 'end' in values and values['start'] == values['end']:
            raise forms.ValidationError('ساعت شروع و پایان نباید برابر باشند.')
        return values
