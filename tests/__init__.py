import os


# ONLY boot Django if this specific VS Code secret variable is present
if os.environ.get("VSCODE_TEST_DISCOVERY") == "1":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    django.setup()
