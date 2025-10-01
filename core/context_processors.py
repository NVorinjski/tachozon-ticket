from django.conf import settings

def branding(request):
    return {
        "SITE_BRAND":   getattr(settings, "SITE_BRAND", "Tachozon"),
        "PRODUCT_NAME": getattr(settings, "PRODUCT_NAME", "Ticket"),
        "SITE_TITLE":   getattr(settings, "SITE_TITLE", "Tachozon Ticket"),
        "LOGO_URL":     getattr(settings, "LOGO_URL", "/static/assets/img/logo.png"),
    }