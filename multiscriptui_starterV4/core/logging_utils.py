from datetime import datetime


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def push_log(log_queue, level: str, message: str) -> None:
    log_queue.append({
        "timestamp": now_str(),
        "level": level.upper(),
        "message": str(message),
    })