import os
from pathlib import Path
from datetime import timedelta

# Python 3.14 Django Compatibility Patch
import gantt_app.py314_compat  # noqa

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-gantt-excel-pro-key-dev-1234567890abcdef')

DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Security & Third party
    'axes',
    'rest_framework',
    
    # Local apps
    'projects.apps.ProjectsConfig',
    'teams.apps.TeamsConfig',
]

AUTHENTICATION_BACKENDS = [
    'projects.validators.RobustAxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',
]

ROOT_URLCONF = 'gantt_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'gantt_app.wsgi.application'

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Optional PostgreSQL support via environment variables
if os.environ.get('DATABASE_URL'):
    import environ
    env = environ.Env()
    DATABASES['default'] = env.db('DATABASE_URL')

# Password Hashers (Argon2id as default, followed by PBKDF2, BCrypt, Scrypt fallbacks)
# https://docs.djangoproject.com/en/5.1/topics/auth/passwords/#using-argon2-with-django
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
]

# Password validation (NIST SP 800-63B standard, Master Admin 'aman' exempted)
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'projects.validators.EnterpriseUserAttributeSimilarityValidator',
    },
    {
        'NAME': 'projects.validators.ContextSpecificWordValidator',
    },
    {
        'NAME': 'projects.validators.EnterpriseMinimumLengthValidator',
        'OPTIONS': {'min_length': 12, 'max_length': 128},
    },
    {
        'NAME': 'projects.validators.EnterpriseCommonPasswordValidator',
    },
    {
        'NAME': 'projects.validators.EnterpriseNumericPasswordValidator',
    },
    {
        'NAME': 'projects.validators.PwnedPasswordValidator',
        'OPTIONS': {'threshold': 1, 'timeout': 2.0, 'fail_open': True},
    },
]

# Brute-Force & Credential Stuffing Defense (django-axes)
# https://django-axes.readthedocs.io/
AXES_FAILURE_LIMIT = 5                      # Lockout threshold: 5 failed attempts
AXES_COOLOFF_TIME = timedelta(hours=1)       # 1-hour cool-off lockout period
AXES_RESET_ON_SUCCESS = True                # Reset failure counter upon successful login
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_WHITELIST_USERS = ['aman']             # Master admin emergency exemption
AXES_VERBOSE = False

# Transport & Cookie Security (NIST & OWASP ASVS Compliant)
# https://docs.djangoproject.com/en/5.1/ref/settings/#security
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False               # False permits CSRF token retrieval for JavaScript
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Enforced in production (DEBUG=False)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Internationalization (Indian Standard)
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-in'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True

# Indian Standard Date & Time Formatting
DATE_FORMAT = 'd/m/Y'
SHORT_DATE_FORMAT = 'd/m/Y'
DATETIME_FORMAT = 'd/m/Y H:i'
SHORT_DATETIME_FORMAT = 'd/m/Y H:i'
USE_L10N = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
}

# Auth redirects
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
