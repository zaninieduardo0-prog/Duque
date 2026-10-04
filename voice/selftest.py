"""Autoteste da voz do TELEX: mostra POR QUE ele às vezes não ouve.

Roda fora do TELEX, com o microfone livre. Grava alguns segundos, mede o
nível do som e diz, segundo a segundo, o que a ativação entendeu. Assim dá
para ver se o problema é microfone mudo, microfone errado, volume baixo,
limiar de ativação ou a conexão de voz.

    .\\.venv\\Scripts\\python.exe -m voice.selftest

Escreva o resultado e me mande (ou copie o que ele grava em duque.log).
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms, igual ao usado pela ativação


def _say(line: str, log: Callable[[str], Any]) -> None:
    print(line, flush=True)
    log(line)


def _rms(frame: Any) -> float:
    import numpy as np

    samples = np.asarray(frame, dtype="float32") / 32768.0
    return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0


def _bar(level: float, width: int = 30) -> str:
    fill = max(0, min(width, int(level * width / 0.2)))  # 0.2 RMS ~ fala alta
    return "[" + "#" * fill + "-" * (width - fill) + f"] {level:.3f}"


def run(seconds: float = 8.0, log: Callable[[str], Any] = lambda _m: None) -> dict[str, Any]:
    """Grava `seconds` s e devolve um resumo. Também imprime e registra no log."""
    report: dict[str, Any] = {"ok": False}
    _say("=" * 56, log)
    _say(f"AUTOTESTE DE VOZ DO TELEX ({time.strftime('%H:%M:%S')})", log)
    _say("=" * 56, log)

    # 1) Chaves
    tem_openai = bool(os.getenv("OPENAI_API_KEY"))
    _say(f"OPENAI_API_KEY: {'OK' if tem_openai else 'AUSENTE (sem voz nem conversa)'}", log)
    report["openai_key"] = tem_openai

    # 2) Dispositivos
    try:
        from pvrecorder import PvRecorder

        devices = PvRecorder.get_available_devices()
    except Exception as exc:
        _say(f"[FALHA] não consegui listar microfones: {type(exc).__name__}: {exc}", log)
        return report
    _say(f"Microfones ({len(devices)}):", log)
    for index, name in enumerate(devices):
        marca = "  <- DUQUE_WAKE_MIC" if str(os.getenv("DUQUE_WAKE_MIC", "")) == str(index) else ""
        _say(f"  {index}: {name}{marca}", log)
    report["devices"] = devices
    if not devices:
        _say("[FALHA] nenhum microfone. Conecte/!habilite um e tente de novo.", log)
        return report

    try:
        from voice.devices import pick_wake_device

        wake_index, motivo = pick_wake_device(devices)
    except Exception:
        wake_index, motivo = (int(os.getenv("DUQUE_WAKE_MIC", "-1")), "padrão")
    _say(f"Microfone escolhido: {wake_index} ({motivo})", log)

    # 3) Ativação local ("Bom dia, TELEX" / "Telex")
    try:
        from voice import local_wake

        listener = local_wake.load(log=lambda _m: None)
    except Exception as exc:
        listener = None
        _say(f"[AVISO] ativação local indisponível: {type(exc).__name__}: {exc}", log)
    _say(f'Ativação "Bom dia, TELEX": {"OK" if listener else "não carregada (só Hey Jarvis)"}', log)

    # 4) Grava e mede
    _say("", log)
    _say(f">> Fale normalmente nos próximos {seconds:.0f} s (ex.: 'Bom dia, TELEX').", log)
    _say("   A barra deve se mexer quando você fala. Se ficar parada, o microfone", log)
    _say("   está mudo ou é o microfone errado (ajuste com setx DUQUE_WAKE_MIC <n>).", log)
    try:
        recorder = PvRecorder(frame_length=FRAME, device_index=wake_index)
        recorder.start()
    except Exception as exc:
        _say(f"[FALHA] não consegui abrir o microfone {wake_index}: {exc}", log)
        return report
    niveis: list[float] = []
    ouviu: list[str] = []
    bloco = 0.0
    try:
        fim = time.monotonic() + seconds
        while time.monotonic() < fim:
            frame = recorder.read()
            nivel = _rms(frame)
            niveis.append(nivel)
            if listener is not None:
                try:
                    import numpy as np

                    heard = listener.feed(np.asarray(frame, dtype="int16").tobytes())
                    if heard is not None:
                        ouviu.append(heard.phrase)
                        _say(f'   >>> ENTENDEU: "{heard.phrase}" ({heard.kind})', log)
                except Exception:
                    pass
            bloco += FRAME / SAMPLE_RATE
            if bloco >= 0.5:
                bloco = 0.0
                print("   " + _bar(nivel), end="\r", flush=True)
    finally:
        recorder.stop()
        recorder.delete()

    pico = max(niveis) if niveis else 0.0
    media = sum(niveis) / len(niveis) if niveis else 0.0
    _say("", log)
    _say(f"Nível do microfone  — pico: {pico:.3f}  média: {media:.3f}", log)
    if pico < 0.01:
        _say("[PROBLEMA] o microfone quase não captou som. Veja se está mudo, se é o", log)
        _say("           microfone certo, e o volume de entrada no Windows.", log)
    elif pico < 0.04:
        _say("[ATENÇÃO] som bem baixo. Aumente o volume do microfone no Windows.", log)
    else:
        _say("[OK] o microfone está captando som.", log)
    if listener is not None and not ouviu:
        _say('[ATENÇÃO] captou som, mas não reconheceu "Bom dia, TELEX"/"Telex".', log)
        _say("          Fale mais claro/perto, ou me diga — ajusto o reconhecimento.", log)
    report.update({"ok": True, "pico": pico, "media": media, "ouviu": ouviu, "wake_mic": wake_index})
    _say("=" * 56, log)
    return report


def main() -> None:
    from pathlib import Path

    log_path = Path(__file__).resolve().parent.parent / "duque.log"
    try:
        handle = log_path.open("a", encoding="utf-8")
    except OSError:
        handle = None

    def log(line: str) -> None:
        if handle:
            handle.write(f"[AUTOTESTE] {line}\n")
            handle.flush()

    try:
        run(log=log)
    finally:
        if handle:
            handle.close()


if __name__ == "__main__":
    main()
