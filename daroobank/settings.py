"""Development foundation; deployment requires separate hardening and review."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get('DAROOBANK_DEBUG') == '1'
# The staff portal is restricted to development until MFA, throttling and audit exist.
STAFF_PORTAL_ENABLED = DEBUG
SECRET_KEY = os.environ.get('DAROOBANK_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'development-only-not-for-production'
    else:
        raise ImproperlyConfigured('DAROOBANK_SECRET_KEY is required outside development')
ALLOWED_HOSTS = [x.strip() for x in os.environ.get('DAROOBANK_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if x.strip()]
if DEBUG:
    ALLOWED_HOSTS += ['.e2b.app', 'testserver']
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.staticfiles', 'catalog', 'pricing', 'sources', 'ingestion', 'clinical']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'daroobank.middleware.PublicReadPrivacyHeadersMiddleware',
    'daroobank.middleware.StaffPrivacyHeadersMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
]
if not DEBUG:
    MIDDLEWARE.append('django.middleware.clickjacking.XFrameOptionsMiddleware')
    SECURE_SSL_REDIRECT = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
ROOT_URLCONF = 'daroobank.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'daroobank.context.staff_portal_context']},
}]
WSGI_APPLICATION = 'daroobank.wsgi.application'
# PostgreSQL is the only supported backend, including development and tests.
# Empty password is allowed for peer/certificate authentication; deployments using
# password authentication must provide it through their environment/secret manager.
def required_database_setting(name):
    value = os.environ.get(name, '')
    if not value:
        raise ImproperlyConfigured(f'{name} is required for PostgreSQL')
    return value


try:
    db_conn_max_age = int(os.environ.get('POSTGRES_CONN_MAX_AGE', '0'))
    db_port = int(os.environ.get('POSTGRES_PORT', '5432'))
    if db_conn_max_age < 0 or not 1 <= db_port <= 65535:
        raise ValueError
except ValueError as exc:
    raise ImproperlyConfigured('Invalid PostgreSQL port or connection lifetime') from exc

db_options = {'connect_timeout': 5}
if os.environ.get('POSTGRES_SSLMODE'):
    db_options['sslmode'] = os.environ['POSTGRES_SSLMODE']
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': required_database_setting('POSTGRES_DB'),
    'USER': required_database_setting('POSTGRES_USER'),
    'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
    'HOST': required_database_setting('POSTGRES_HOST'),
    'PORT': db_port,
    'CONN_MAX_AGE': db_conn_max_age,
    'CONN_HEALTH_CHECKS': True,
    'OPTIONS': db_options,
}}
LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'

# These safeguards do not replace MFA, throttling, monitoring or a deployment review.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = 'staff_login'
LOGIN_REDIRECT_URL = 'staff_prices'
