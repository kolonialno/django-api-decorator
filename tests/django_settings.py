SECRET_KEY = "asdf"
USE_TZ = True

# ATOMIC_REQUESTS is on to match the setup where views must opt out of the
# request transaction, which is what @api and method_router do.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "ATOMIC_REQUESTS": True,
    }
}

API_DECORATOR_DEFAULT_ATOMIC = False
API_DECORATOR_DEFAULT_LOGIN_REQUIRED = False
API_DECORATOR_GENERATE_SCHEMA_BY_ALIAS = True

ROOT_URLCONF = "tests.urls"
