from django import forms
# oben in ticket/forms.py
from django.core.files.uploadedfile import UploadedFile, InMemoryUploadedFile, TemporaryUploadedFile


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    def to_python(self, data):
        # Nichts hochgeladen
        if not data:
            return []
        # Einzeldatei -> in Liste packen
        if isinstance(data, UploadedFile):
            return [data]
        # Mehrere Dateien -> Liste durchreichen
        if isinstance(data, (list, tuple)):
            # optional: nur UploadedFile-Instanzen durchlassen
            return [f for f in data if isinstance(f, UploadedFile)]
        # Fallback: als leer behandeln statt Fehler zu werfen
        return []

class CreateTicketForm(forms.Form):
    title = forms.CharField(
        label='Titel',
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'name': 'title',
                'placeholder': 'Titel (nicht erforderlich)'
            }
        )
    )

    note = forms.CharField(
        label='Problembeschreibung',
        required=True,
        widget=forms.Textarea(
            attrs={'class': 'summernote',
                   'name': 'note',
                   'id': 'compose-textarea'
                   }
        )
    )

    files = MultiFileField(             # <- HIER statt forms.FileField
        label='Datei hochladen',
        required=False,
        widget=MultiFileInput(attrs={
            'class': 'custom-file-input',
            'multiple': True,
            'id': 'attachments',
        })
    )


class PauseTicketForm(forms.Form):
    paused_until = forms.DateTimeField(
        label='Bis wann pausieren?'
    )


class SearchUsersForm(forms.Form):
    name = forms.CharField(
        label='',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control form-control-sm',
                'id': 'name',
                'name': 'name',
                'placeholder': '',
                'type': 'input'
            }
        )
    )
