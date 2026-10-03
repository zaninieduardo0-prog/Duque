"""Diagnóstico do Duque: confere tudo que precisa estar pronto antes de rodar.

Uso:  python diagnostico.py            (rápido)
      python diagnostico.py --testes   (também roda a suíte de testes)
"""

from __future__ import annotations

import importlib
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK, WARN, FAIL = "ok", "aviso", "falha"
ICONS = {OK: "[OK]   ", WARN: "[AVISO]", FAIL: "[FALHA]"}

REQUIRED_PACKAGES = {
    "flask": "servidor e HUD",
    "openai": "conversa e voz",
    "agents": "voz Realtime (openai-agents)",
    "numpy": "áudio",
    "openwakeword": "wake word \"Hey Jarvis\"",
    "sounddevice": "microfone e alto-falante",
    "pvrecorder": "microfone da wake word",
    "pedalboard": "processamento de voz",
}
OPTIONAL_PACKAGES = {"anthropic": "Forja com Claude", "pytest": "testes"}


@dataclass(slots=True)
class Check:
    status: str
    name: str
    detail: str = ""


def mask(value: str) -> str:
    return value[:4] + "…" + value[-4:] if len(value) > 10 else "definida"


def check_python() -> Check:
    version = sys.version_info
    if version < (3, 11):
        return Check(FAIL, "Python", f"{version.major}.{version.minor} — precisa 3.11 ou mais novo")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    detail = f"{version.major}.{version.minor} ({sys.executable})"
    return Check(OK if in_venv else WARN, "Python", detail + ("" if in_venv else " — fora da .venv: rode pelo preparar_duque.bat"))


def check_packages() -> list[Check]:
    checks = []
    for name, purpose in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(name)
            checks.append(Check(OK, f"pacote {name}", purpose))
        except Exception as exc:
            checks.append(Check(FAIL, f"pacote {name}", f"{purpose} — {type(exc).__name__}: rode 'pip install -e .'"))
    for name, purpose in OPTIONAL_PACKAGES.items():
        try:
            importlib.import_module(name)
            checks.append(Check(OK, f"pacote {name}", purpose))
        except Exception:
            checks.append(Check(WARN, f"pacote {name}", f"{purpose} — opcional"))
    return checks


def check_keys(env: dict[str, str] | None = None) -> list[Check]:
    env = dict(os.environ if env is None else env)
    checks = []
    openai_key = env.get("OPENAI_API_KEY", "")
    checks.append(Check(OK if openai_key else FAIL, "OPENAI_API_KEY", mask(openai_key) if openai_key else "ausente: sem voz e sem conversa com IA"))
    anthropic_key = env.get("ANTHROPIC_API_KEY", "")
    checks.append(Check(OK if anthropic_key else WARN, "ANTHROPIC_API_KEY", mask(anthropic_key) if anthropic_key else "ausente: a Forja usará a OpenAI (ou fica desligada)"))
    token = env.get("DUQUE_GITHUB_TOKEN") or env.get("GITHUB_TOKEN") or ""
    checks.append(Check(OK if token else WARN, "DUQUE_GITHUB_TOKEN", "definido" if token else "ausente: a Forja envia o branch mas não abre PR"))
    return checks


def check_wakeword() -> Check:
    try:
        import openwakeword

        path = Path(str(openwakeword.__file__)).resolve().parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"
        if path.exists():
            return Check(OK, "modelo Hey Jarvis", path.name)
        return Check(FAIL, "modelo Hey Jarvis", "não baixado: rode  python -c \"import openwakeword.utils as u; u.download_models()\"")
    except Exception as exc:
        return Check(FAIL, "modelo Hey Jarvis", f"{type(exc).__name__}: {exc}")


def check_microphones() -> list[Check]:
    checks = []
    try:
        from pvrecorder import PvRecorder

        from voice.devices import HANDS_FREE, pick_wake_device

        devices = PvRecorder.get_available_devices()
        if not devices:
            checks.append(Check(FAIL, "microfones", "nenhum encontrado"))
        else:
            wake_index, reason = pick_wake_device(devices)
            listing = "; ".join(f"{index}: {name}" for index, name in enumerate(devices))
            valid = -1 <= wake_index < len(devices)
            chosen = devices[wake_index] if 0 <= wake_index < len(devices) else "padrão"
            status = OK if valid else FAIL
            if valid and HANDS_FREE.search(chosen):
                status = WARN
                reason += " — microfone Bluetooth: o som do fone pode sumir enquanto o Duque escuta"
            checks.append(Check(status, "microfone da wake word", f"{wake_index} ({chosen}) — {reason} | disponíveis → {listing}"))
    except Exception as exc:
        checks.append(Check(FAIL, "microfones", f"{type(exc).__name__}: {exc}"))
    return checks


def check_chrome() -> Check:
    if sys.platform != "win32":
        return Check(OK, "Chrome", "não é Windows: links abrem no navegador padrão")
    from computer.chrome import chrome_executable, resolve_profile, wanted_profile

    executable = chrome_executable()
    if not executable:
        return Check(WARN, "Chrome", "não encontrado: links abrem no navegador padrão")
    profile = resolve_profile()
    if not profile:
        return Check(WARN, "Chrome", f"perfil '{wanted_profile()}' não encontrado: o Chrome pode pedir para escolher a conta")
    return Check(OK, "Chrome", f"perfil '{profile}' (procurado: {wanted_profile()})")


def check_git(root: Path = ROOT) -> list[Check]:
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=20)

    checks = []
    try:
        if git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return [Check(WARN, "git", "pasta não é um repositório: Forja e atualização automática desligadas")]
        branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        checks.append(Check(OK if branch == "main" else WARN, "git branch", branch + ("" if branch == "main" else " — a atualização automática só roda no main")))
        dirty = [line for line in git("status", "--porcelain", "--untracked-files=no").stdout.splitlines() if line.strip()]
        checks.append(Check(OK if not dirty else WARN, "git alterações locais", "nenhuma" if not dirty else f"{len(dirty)} arquivo(s): a atualização automática não roda até resolver"))
        remote = git("ls-remote", "--heads", "origin", "main")
        checks.append(Check(OK if remote.returncode == 0 else WARN, "git remoto", "GitHub acessível" if remote.returncode == 0 else "não acessível (internet ou credenciais)"))
    except FileNotFoundError:
        checks.append(Check(WARN, "git", "git não instalado: Forja e atualização automática desligadas"))
    except subprocess.TimeoutExpired:
        checks.append(Check(WARN, "git remoto", "tempo esgotado"))
    return checks


def check_port(port: int = 5000) -> Check:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        busy = sock.connect_ex(("127.0.0.1", port)) == 0
    return Check(OK, "porta 5000", "em uso (o Duque já está rodando?)" if busy else "livre")


def run_tests() -> Check:
    command = [sys.executable, "-m", "pytest", "-q", "tests"]
    try:
        importlib.import_module("pytest")
    except Exception:
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]
    completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, timeout=900)
    tail = (completed.stdout + completed.stderr).strip().splitlines()[-1:] or [""]
    return Check(OK if completed.returncode == 0 else FAIL, "testes automáticos", tail[0])


def check_local_wake() -> Check:
    """Ativação "Bom dia, TELEX" (Vosk, local). Sem ela o TELEX acorda com "Hey Jarvis"."""
    from voice import local_wake

    model_dir = local_wake.find_model()
    if model_dir is None:
        return Check(WARN, "ativação Bom dia, TELEX", "modelo não baixado: rode  python -m voice.local_wake --baixar  (por ora só \"Hey Jarvis\")")
    try:
        import vosk  # type: ignore[import-not-found]

        vosk.SetLogLevel(-1)
        listener = local_wake.LocalWake(vosk.Model(str(model_dir)), vosk.KaldiRecognizer)
    except Exception as exc:
        return Check(WARN, "ativação Bom dia, TELEX", f"{type(exc).__name__}: {exc} (por ora só \"Hey Jarvis\")")
    return Check(OK, "ativação Bom dia, TELEX", f"{model_dir.name}; nome como {', '.join(listener.names)}")


def collect(with_tests: bool = False) -> list[Check]:
    checks = [check_python(), *check_packages(), *check_keys(), check_wakeword(), check_local_wake(), *check_microphones(), check_chrome(), *check_git(), check_port()]
    if with_tests:
        checks.append(run_tests())
    return checks


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    print("=" * 64)
    print("DUQUE — DIAGNÓSTICO")
    print("=" * 64)
    checks = collect(with_tests="--testes" in args)
    for check in checks:
        print(f"{ICONS[check.status]} {check.name}: {check.detail}")
    failures = sum(check.status == FAIL for check in checks)
    warnings = sum(check.status == WARN for check in checks)
    print("-" * 64)
    if failures:
        print(f"{failures} falha(s) e {warnings} aviso(s). Corrija as falhas antes de iniciar o Duque.")
    else:
        print(f"Pronto para rodar. {warnings} aviso(s) (não impedem o uso).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
