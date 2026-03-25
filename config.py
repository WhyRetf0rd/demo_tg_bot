import os
import re
from dataclasses import dataclass
from pathlib import Path

# Ищем переменные рядом с этим файлом (и при необходимости в текущей папке запуска).
_BASE_DIR = Path(__file__).resolve().parent

# Дополнительно подхватываем через python-dotenv (на случай нестандартного синтаксиса).
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[misc, assignment]


def _candidate_env_paths() -> list[Path]:
    """Все возможные имена файла с секретами (Windows любит .env.txt)."""
    names = (".env", "env", ".env.txt", "secrets.env", "local.env")
    paths = [_BASE_DIR / name for name in names]
    paths.append(Path.cwd() / ".env")
    # Уникальные, только существующие
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        if rp.is_file():
            result.append(rp)
    return result


def _parse_env_raw(content: str) -> dict[str, str]:
    """Простой разбор KEY=VALUE (без многострочных значений)."""
    out: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lstrip("\ufeff")
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            out[key] = value
    return out


def _read_env_file(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}

    return _parse_env_raw(text)


def _apply_env_example_fallback() -> None:
    """
    Если файла .env нет, многие кладут переменные только в .env.example.
    Подставляем оттуда только те ключи, которые ещё пустые в окружении.
    """
    example = _BASE_DIR / ".env.example"
    if not example.is_file():
        return
    parsed = _read_env_file(example)
    for key, value in parsed.items():
        if value and not (os.getenv(key) or "").strip():
            os.environ[key] = value


def _load_all_env_files() -> Path | None:
    """
    Читает все найденные .env-файлы; значения из файлов перезаписывают os.environ
    (удобно для локальной разработки).
    """
    paths = _candidate_env_paths()
    last: Path | None = None
    for path in paths:
        parsed = _read_env_file(path)
        for key, value in parsed.items():
            os.environ[key] = value
        if parsed:
            last = path
        elif path.exists():
            last = last or path  # файл есть, но пустой/не распарсился — для подсказки в ошибке
    if load_dotenv is not None:
        for path in paths:
            load_dotenv(path, encoding="utf-8", override=True)
        if not paths:
            load_dotenv(encoding="utf-8", override=False)
    # Важно: отдельно от основных имён — не перетираем уже заданный .env
    _apply_env_example_fallback()
    if load_dotenv is not None:
        ex = _BASE_DIR / ".env.example"
        if ex.is_file():
           load_dotenv(ex, encoding="utf-8", override=False,)   # или "replace"
    return last


_ENV_LOADED_FROM = _load_all_env_files()


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_id: int
    channel_id: int
    database_path: str = "appointments.db"


def _list_env_filenames() -> str:
    """Для подсказки в ошибке: какие env-подобные файлы реально лежат в папке."""
    allowed = {".env", ".env.txt", "env", "secrets.env", "local.env"}

    def _is_env_like(p: Path) -> bool:
        n = p.name
        return n in allowed or n.startswith(".env") or n.endswith(".env")

    try:
        names = sorted(p.name for p in _BASE_DIR.iterdir() if p.is_file() and _is_env_like(p))
    except OSError:
        names = []
    return ", ".join(names) or "(ни одного .env / .env.example не найдено)"


def _get_required(name: str) -> str:
    raw = os.getenv(name)
    value = raw.strip() if raw else ""
    if not value:
        searched = ", ".join(str(p) for p in _candidate_env_paths()) or "(нет .env / env / .env.txt)"
        hint = (
            f"\n  Файлы с переменными (проверены пути): {searched}\n"
            f"  В папке проекта сейчас: {_list_env_filenames()}\n"
            f"  Папка проекта: {_BASE_DIR}\n"
            f"  Создайте файл .env рядом с bot.py или допишите {name}=... в .env.example\n"
            f"  (значения из .env.example подхватываются, только если переменная ещё не задана)."
        )
        if _ENV_LOADED_FROM:
            hint += f"\n  Последний основной env-файл: {_ENV_LOADED_FROM}"
        raise RuntimeError(f"Environment variable {name} is required.{hint}")
    return value


def _parse_telegram_int(name: str) -> int:
    """ID из .env: убираем пробелы, поддерживаем -100… для каналов."""
    raw = _get_required(name).replace(" ", "").replace("\u00a0", "")
    try:
        return int(raw)
    except ValueError as e:
        raise RuntimeError(f"{name} должен быть числом (Telegram id), сейчас: {raw!r}") from e


settings = Settings(
    bot_token=_get_required("BOT_TOKEN"),
    admin_id=_parse_telegram_int("ADMIN_ID"),
    channel_id=_parse_telegram_int("CHANNEL_ID"),
    database_path=(os.getenv("DATABASE_PATH") or "appointments.db").strip(),
)
