"""Start only the local evaluation Compose project, optionally run DB tests.

Credentials stay in process environment and the sandbox container, not reports.
Never reads DATABASE_URL or starts/stops unrelated projects.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.evaluation.yml")]
LOCAL_PG = Path("/opt/homebrew/opt/postgresql@17/bin")
LOCAL_ROOT = ROOT / ".local" / "pg-evaluation"


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError("Sandbox command failed: " + args[0] + " (credentials/output suppressed)")
    return result.stdout


def environment():
    container = run([*COMPOSE, "ps", "-a", "-q", "postgres"], timeout=15).strip()
    if container:
        config = json.loads(run(["docker", "inspect", container], timeout=15))[0]
        values = dict(item.split("=", 1) for item in config["Config"]["Env"] if "=" in item)
        password = values["POSTGRES_PASSWORD"]
    else:
        volumes = run(["docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=agent-evaluation"], timeout=15).strip()
        if volumes:
            raise RuntimeError("Existing sandbox volume without its container: provide original credentials; no reset")
        password = secrets.token_urlsafe(32)
    env = dict(os.environ)
    env["EVALUATION_DB_PASSWORD"] = password
    env["EVALUATION_DATABASE_URL"] = "postgresql://postgres:" + password + "@127.0.0.1:55433/agent_eval_dev"
    return env


def local_environment():
    if not all((LOCAL_PG / name).is_file() for name in ("initdb", "pg_ctl", "psql", "createdb")):
        raise RuntimeError("Homebrew PostgreSQL 17 binaries are not installed")
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    LOCAL_ROOT.chmod(0o700)
    data = LOCAL_ROOT / "data"
    secret = LOCAL_ROOT / "password"
    if not data.exists():
        if secret.exists():
            raise RuntimeError("Password exists without sandbox cluster; investigate rather than overwrite")
        password=secrets.token_urlsafe(32)
        with tempfile.NamedTemporaryFile(mode="w",dir=LOCAL_ROOT,delete=False) as handle:
            handle.write(password)
            password_file=Path(handle.name)
        password_file.chmod(0o600)
        try:
            run([str(LOCAL_PG / "initdb"),"-D",str(data),"-U","eval_admin",
                 "--auth-local=scram-sha-256","--auth-host=scram-sha-256","--pwfile",str(password_file)],timeout=120)
            secret.write_text(password)
            secret.chmod(0o600)
        finally:
            password_file.unlink(missing_ok=True)
    if not secret.is_file():
        raise RuntimeError("Sandbox cluster exists without password; no credential reset")
    password=secret.read_text().strip()
    status=subprocess.run([str(LOCAL_PG / "pg_ctl"),"-D",str(data),"status"],capture_output=True).returncode
    if status:
        run([str(LOCAL_PG / "pg_ctl"),"-D",str(data),"-l",str(LOCAL_ROOT / "postgres.log"),
             "-o","-h 127.0.0.1 -p 55433","-w","start"],timeout=60)
    env=dict(os.environ,PGPASSWORD=password)
    check=run([str(LOCAL_PG / "psql"),"-h","127.0.0.1","-p","55433","-U","eval_admin",
               "-d","postgres","-tAc","SELECT 1 FROM pg_database WHERE datname = 'agent_eval_dev'"],env=env,timeout=10).strip()
    if check!="1":
        run([str(LOCAL_PG / "createdb"),"-h","127.0.0.1","-p","55433","-U","eval_admin","agent_eval_dev"],env=env,timeout=15)
    env["EVALUATION_DATABASE_URL"]="postgresql://eval_admin:"+quote(password,safe="")+"@127.0.0.1:55433/agent_eval_dev"
    env.pop("PGPASSWORD",None)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--test-adapter", action="store_true", help="Actual PostgreSQL/P2/P3/P4 with offline model graphs, no API calls")
    parser.add_argument("--serve", action="store_true", help="Run the local web app against the isolated sandbox DB; never uses DATABASE_URL from .env")
    parser.add_argument("--local", action="store_true", help="Use isolated Homebrew PostgreSQL instead of Docker")
    args = parser.parse_args()
    # Compose interpolation requires a value even for read-only ps.
    if args.local:
        env=local_environment()
    else:
        os.environ.setdefault("EVALUATION_DB_PASSWORD", "inspection-only-not-used-for-startup")
        env=environment()
        run([*COMPOSE, "up", "-d", "--wait", "--wait-timeout", "60"], env=env, timeout=180)
    print("Sandbox PostgreSQL healthy: 127.0.0.1:55433 / agent_eval_dev", flush=True)
    if args.test:
        code = subprocess.call([sys.executable, "-B", "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"], cwd=ROOT, env=env)
        if code:return code
    if args.test_adapter:
        workspace = ROOT.parent.parent
        env["EVALUATION_POSTGRES_ADAPTER_TEST"] = "1"
        return subprocess.call([str(workspace / "evaluation/asr/.venv/bin/python"), "-B", "-m", "unittest", "evaluation.tests.test_product_runtime", "-q"], cwd=workspace, env=env)
    if args.serve:
        env["DATABASE_URL"] = env["EVALUATION_DATABASE_URL"]
        env["EVALUATION_WEB_CALLS_ENABLED"] = "1"
        print("Starting local backend on 127.0.0.1:8000 with sandbox-only database; no DSN is printed.", flush=True)
        return subprocess.call([sys.executable,"-B","-m","uvicorn","src.api.app:app","--host","127.0.0.1","--port","8000"],cwd=ROOT,env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
