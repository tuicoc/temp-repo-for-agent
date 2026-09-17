#!/usr/bin/env python3
"""Preflight check. Run this before anything else.

    python setup.py

It answers one question — is this machine ready to run the project — and says
exactly what to do about whatever is not. It checks the interpreter, the
virtual environment, the installed packages, the .env file and the API keys in
it, and the model list, then prints a numbered list of the steps still left.

Nothing here imports the project, so it runs on an interpreter too old for the
dependencies and still reports that as the problem rather than crashing. For
the same reason it is written for Python 3.8 syntax and uses only the standard
library.

Despite the name this is not a setuptools script: the project is not packaged,
it is run from this directory. The name is kept because it is the first file
anyone looks for.
"""

import os
import shutil
import sys

MIN_PYTHON = (3, 10)
RECOMMENDED_PYTHON = "3.12"

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(ROOT, ".env")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")
MODELS_YAML = os.path.join(ROOT, "config", "models.yaml")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")

# Import name -> the line in requirements.txt that provides it.
PACKAGES = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("jwt", "PyJWT"),
    ("bcrypt", "bcrypt"),
    ("psycopg", "psycopg"),
    ("langchain", "langchain"),
    ("langchain_google_genai", "langchain-google-genai"),
    ("langchain_groq", "langchain-groq"),
    ("langchain_nvidia_ai_endpoints", "langchain-nvidia-ai-endpoints"),
    ("pydantic_settings", "pydantic-settings"),
    ("dotenv", "python-dotenv"),
    ("yaml", "PyYAML"),
    ("httpx", "httpx"),
]

# Environment variable -> where to get the key. These names are the ones each
# LangChain integration reads by default.
KEYS = [
    ("GOOGLE_API_KEY", "Google AI Studio", "https://aistudio.google.com/apikey"),
    ("GROQ_API_KEY", "Groq", "https://console.groq.com/keys"),
    ("NVIDIA_API_KEY", "NVIDIA NIM", "https://build.nvidia.com"),
]

# The web service needs these as well. Without them it starts and then fails on
# the first request, which is a worse place to find out.
WEB_KEYS = [
    ("JWT_SECRET", 'python -c "import secrets; print(secrets.token_urlsafe(48))"'),
    ("SEED_USER_EMAIL", "the one account that can sign in"),
    ("SEED_USER_PASSWORD", "its password"),
    ("DATABASE_URL", "postgresql://...?sslmode=require"),
    ("CORS_ORIGINS", "exact origins the browser app is served from"),
]

# Tracing is optional: without it everything still runs, you just cannot see
# inside a call afterwards.
OPTIONAL_KEYS = [
    ("LANGFUSE_PUBLIC_KEY", "Langfuse", "https://cloud.langfuse.com"),
    ("LANGFUSE_SECRET_KEY", "Langfuse", "https://cloud.langfuse.com"),
]

OK = "  ok   "
BAD = "  --   "

todo = []


def note(message):
    todo.append(message)


def check_python():
    version = sys.version_info
    shown = "%d.%d.%d" % version[:3]
    if version[:2] < MIN_PYTHON:
        print(BAD + "Python " + shown + ", but %d.%d or newer is required" % MIN_PYTHON)
        note(
            "Install Python "
            + RECOMMENDED_PYTHON
            + " and create the virtual environment with it."
        )
        return False
    print(OK + "Python " + shown)
    return True


def check_virtualenv():
    inside = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if inside:
        print(OK + "virtual environment active: " + sys.prefix)
        return True
    print(BAD + "no virtual environment active")
    note(
        "Create and activate one, so the dependencies do not go into the system "
        "Python:\n"
        "       python3 -m venv .venv\n"
        "       source .venv/bin/activate      (Windows: .venv\\Scripts\\activate)"
    )
    return False


def check_packages():
    try:
        from importlib.util import find_spec
    except ImportError:
        return False

    missing = []
    for module, requirement in PACKAGES:
        try:
            found = find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(requirement)

    if missing:
        print(BAD + "missing packages: " + ", ".join(missing))
        note("Install the dependencies:\n       pip install -r requirements.txt")
        return False
    print(OK + "all %d dependencies importable" % len(PACKAGES))
    return True


def check_env_file():
    if os.path.exists(ENV_FILE):
        print(OK + ".env present")
        return True
    if os.path.exists(ENV_EXAMPLE):
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        print(OK + ".env created from .env.example")
        note("Open .env and paste your API keys in.")
        return True
    print(BAD + "neither .env nor .env.example found")
    note("Restore .env.example from version control.")
    return False


def read_env_file():
    """Parse .env well enough to report which keys are filled in.

    python-dotenv is not imported here: this has to work before the
    dependencies are installed.
    """
    values = {}
    if not os.path.exists(ENV_FILE):
        return values
    with open(ENV_FILE, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip("'\"")
    return values


def check_keys():
    from_file = read_env_file()
    present = []
    absent = []
    for name, label, url in KEYS:
        if os.environ.get(name) or from_file.get(name):
            present.append(label)
        else:
            absent.append((name, label, url))

    if present:
        print(OK + "API keys set: " + ", ".join(present))
    for name, label, url in absent:
        print(BAD + name + " is empty (" + label + ")")

    if absent:
        lines = ["Fill in the missing keys in .env:"]
        for name, label, url in absent:
            lines.append("       " + name + "   " + url)
        note("\n".join(lines))

    missing_web = [
        name for name, _ in WEB_KEYS
        if not (os.environ.get(name) or from_file.get(name))
    ]
    if missing_web:
        print(BAD + "web service not configured: " + ", ".join(missing_web))
        lines = ["Set these in .env before running the API:"]
        for name, hint in WEB_KEYS:
            if name in missing_web:
                lines.append("       " + name + "   " + hint)
        note("\n".join(lines))
    else:
        print(OK + "web service configured")

    missing_optional = [
        name for name, _, _ in OPTIONAL_KEYS
        if not (os.environ.get(name) or from_file.get(name))
    ]
    if missing_optional:
        print(
            BAD
            + "tracing off: "
            + ", ".join(missing_optional)
            + " empty (optional)"
        )
    else:
        print(OK + "Langfuse tracing configured")

    return not absent and not missing_web


def check_models():
    if not os.path.exists(MODELS_YAML):
        print(BAD + "config/models.yaml is missing")
        note("Restore config/models.yaml from version control.")
        return False

    # Counting "models: []" avoids needing PyYAML before it is installed.
    with open(MODELS_YAML, "r", encoding="utf-8") as handle:
        text = handle.read()
    empty = text.count("models: []")
    if empty:
        print(BAD + "config/models.yaml has %d provider(s) with no models listed" % empty)
        note(
            "Discover the models your keys can reach, then paste the interesting "
            "ones into config/models.yaml:\n"
            "       python examples/probe_providers.py list"
        )
        return False
    print(OK + "config/models.yaml lists models")
    return True


def main():
    print("Preflight check for the project\n")

    if not check_python():
        report()
        return 1

    check_virtualenv()
    check_packages()
    check_env_file()
    check_keys()
    check_models()
    return report()


def report():
    if not todo:
        print("\nEverything is ready. Next:\n")
        print("    python examples/probe_providers.py run")
        return 0

    print("\nStill to do, in order:\n")
    for index, item in enumerate(todo, start=1):
        print("  %d. %s" % (index, item))
    print("")
    return 1


if __name__ == "__main__":
    sys.exit(main())
