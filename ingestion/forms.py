from django import forms
from .schedule import DEFAULT_END, DEFAULT_START, DEFAULT_ZONE, ScheduleError, parse_time, parse_zone


class WindowForm(forms.Form):
    start = forms.CharField(label='شروع محلی (HH:MM)', max_length=5, initial=DEFAULT_START)
    end = forms.CharField(label='پایان محلی (HH:MM)', max_length=5, initial=DEFAULT_END)
    zone = forms.CharField(label='منطقه زمانی IANA', max_length=80, initial=DEFAULT_ZONE)

    def clean(self):
        values = super().clean()
        try:
            if 'start' in values and 'end' in values:
                if parse_time(values['start']) == parse_time(values['end']):
                    raise ScheduleError('ساعت شروع و پایان نباید برابر باشند.')
            if 'zone' in values:
                parse_zone(values['zone'])
        except ScheduleError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return values
