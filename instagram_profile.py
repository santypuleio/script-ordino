"""
Instagram Ordino: unfollow + prospección comercial (Parte 1 y 2).

Usa la API interna del navegador (rápido, sin scroll en el modal).
La primera vez debes iniciar sesión en la ventana del script.

Uso:
  pip install -r requirements.txt
  python instagram_profile.py

Parte 1 — unfollow:
  python instagram_profile.py              → lista quién no te sigue
  python instagram_profile.py --unfollow

Parte 2 — individuales:
  python instagram_profile.py --discover
  python instagram_profile.py --follow
  python instagram_profile.py --message   (--mensajes)
  python instagram_profile.py --outreach-status

Parte 2 — fusiones (presets):
  python instagram_profile.py --engage       → follow + message
  python instagram_profile.py --outreach     → discover + follow + message
  python instagram_profile.py --prospect     → discover + follow
  python instagram_profile.py --daily        → unfollow + discover + follow + message

  También podés combinar: --discover --follow, etc.
  Agregar --dry-run para simular. --confirm para pedir SI antes de actuar.

Variables de entorno (Parte 1):
  INSTAGRAM_USERNAME, OUTPUT_FILE, UNFOLLOW_DELAY, UNFOLLOW_MAX

  Variables de entorno (Parte 2):
  OUTREACH_HASHTAGS, FOLLOW_MAX, FOLLOW_DELAY, MESSAGE_MAX, MESSAGE_DELAY
  OUTREACH_MIN_SCORE, OUTREACH_MAX_FOLLOWERS, MESSAGE_MIN_HOURS_AFTER_FOLLOW
  DM_MODE=api|manual|ui  (default api — sin abrir formulario de mensajes)

Sesión:
  python instagram_profile.py --logout / --logout-all
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

load_local_env_called = False


def load_local_env() -> None:
    """Carga variables desde .env en la carpeta del script (no commitear .env)."""
    global load_local_env_called
    if load_local_env_called:
        return
    load_local_env_called = True
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


load_local_env()

INSTAGRAM_URL = "https://www.instagram.com/"
IG_APP_ID = "936619743392459"
WAIT_SECONDS = 30
DEFAULT_LOGIN_WAIT = 600
API_PAGE_SIZE = 200
SCRIPT_TIMEOUT = 600
DEFAULT_UNFOLLOW_DELAY = 5.0
DEFAULT_UNFOLLOW_MAX = 0
DEFAULT_FOLLOW_MAX = 25
DEFAULT_FOLLOW_DELAY = 10.0
DEFAULT_MESSAGE_MAX = 10
DEFAULT_MESSAGE_DELAY = 20.0
DEFAULT_RETRY_DM_USERNAMES: tuple[str, ...] = (
    # bagsvictoria_ ya recibió el DM en la corrida anterior
    "sinfiltro.pe",
    "vaphouse.vp",
    "ttfragances",
    "mocadosperfumes",
    "parfumdivinerd_mayoristas",
    "one.outlet.gt",
    "manu.ferreiram",
    "el_ciruelo17",
    "ch_perfumesimportados",
)
DEFAULT_OUTREACH_MIN_SCORE = 2
DEFAULT_OUTREACH_MAX_FOLLOWERS = 50000
DEFAULT_MESSAGE_MIN_HOURS_AFTER_FOLLOW = 0
DEFAULT_MESSAGE_PAUSE_AFTER_FOLLOW = 120
DEFAULT_RATE_LIMIT_PAUSE = 90
DEFAULT_DISCOVER_MAX_HASHTAGS = 8
DEFAULT_DISCOVER_MAX_NEW = 50
DEFAULT_DISCOVER_BATCH_SIZE = 12
DEFAULT_DISCOVER_HASHTAG_PAUSE = 0.4
# Hashtags con foco Argentina (Instagram no filtra por país; evitamos tags globales).
DEFAULT_OUTREACH_HASHTAGS = (
    "emprendedoresargentina, emprendimientoargentina, tiendasargentina, "
    "tiendaonlineargentina, pymesargentina, negociosargentina, ventaargentina, "
    "impresion3dargentina, tienda3dargentina, makerargentina, "
    "buenosaires, tiendabsas, cordobaargentina, rosarioargentina, mendozaargentina, "
    "gamerargentina, videojuegosargentina, tiendagamerargentina, "
    "retrogamingargentina, tiendaretroargentina, gameboyargentina, "
    "compralocal, argentinaemprende"
)
_AR_HASHTAG_MARKERS: tuple[str, ...] = (
    "argentina",
    "argentino",
    "buenosaires",
    "bsas",
    "cordoba",
    "rosario",
    "mendoza",
    "cba",
    "platense",
    "pymes",
    "emprende",
    "compralocal",
)
_DM_SUCCESS_NEEDLES = (
    "ordino",
    "gestor de stock",
    "gestor",
    "ordinoar",
    "stock",
    "planilla",
    "landing/ecommerce",
    "whatsapp",
)
OUTREACH_DB_NAME = "ordino_outreach.db"
_LINK_AGGREGATORS = (
    "wa.me",
    "api.whatsapp",
    "whatsapp.com",
    "linktr.ee",
    "linktree",
    "beacons.ai",
    "bio.link",
    "campsite.bio",
    "taplink",
    "msha.ke",
    "instagram.com",
    "facebook.com",
    "fb.com",
    "bit.ly",
    "t.me",
)
_POSITIVE_BIO_KEYWORDS: dict[str, int] = {
    "tienda": 2,
    "venta": 2,
    "ventas": 2,
    "envio": 1,
    "envíos": 1,
    "envios": 1,
    "catalogo": 2,
    "catálogo": 2,
    "whatsapp": 1,
    "wpp": 1,
    "precio": 1,
    "precios": 1,
    "stock": 2,
    "emprend": 2,
    "perfume": 2,
    "arab": 1,
    "remera": 2,
    "ropa": 2,
    "indumentaria": 2,
    "tech": 1,
    "tecnolog": 1,
    "mayorista": 2,
    "minorista": 1,
    "producto": 1,
    "productos": 1,
    "negocio": 2,
    "comercio": 2,
    "online": 1,
    "shop": 1,
    "store": 1,
    "retro": 3,
    "gameboy": 3,
    "consola": 2,
    "consolas": 2,
    "nintendo": 2,
    "playstation": 1,
    "sega": 2,
    "videojuego": 2,
    "videojuegos": 2,
    "gamer": 1,
    "impresion3d": 3,
    "impresión3d": 3,
    "impresora3d": 3,
    "3d": 2,
    "filamento": 2,
    "maker": 2,
    "coleccion": 1,
    "colección": 1,
}
_NEGATIVE_BIO_KEYWORDS: dict[str, int] = {
    "influencer": -3,
    "meme": -3,
    "humor": -2,
    "blog personal": -3,
    "fanpage": -2,
    "futbol": -2,
    "fútbol": -2,
    "streamer": -2,
    "modelo": -2,
    "coach de vida": -2,
}
_OUTREACH_MESSAGE_TEMPLATE = """Hola! Vi {product_line} y están buenísimos.

Te hago una consulta:
¿Cómo manejan hoy el stock? ¿Con planillas o tienen algún sistema?"""
_PRODUCT_LINE_FROM_BIO: tuple[tuple[tuple[str, ...], str], ...] = (
    (("perfume", "perfumes", "aroma", "aromas", "fragancia", "esencia"), "los perfumes que venden"),
    (("remera", "remeras", "ropa", "indumentaria", "moda", "vestimenta"), "las prendas que venden"),
    (
        ("gameboy", "nintendo", "consola", "consolas", "retro", "videojuego", "gamer"),
        "los productos retro que venden",
    ),
    (
        ("impresion3d", "impresión3d", "impresora3d", "filamento", "maker", "3d"),
        "los productos de impresión 3D que venden",
    ),
    (("tecnologia", "tecnología", "tech", "celular", "accesorio"), "los productos de tecnología que venden"),
)
_AR_BIO_KEYWORDS: tuple[str, ...] = (
    "argentina",
    "argentino",
    "argentinos",
    "buenos aires",
    "caba",
    "córdoba",
    "cordoba",
    "rosario",
    "mendoza",
    "la plata",
    "mar del plata",
    "tucumán",
    "tucuman",
    "salta",
    "neuquén",
    "neuquen",
    "bariloche",
    "patagonia",
    "gba",
    "gran buenos aires",
    "capital federal",
    "provincia de buenos aires",
    "envios en argentina",
    "envíos en argentina",
    "envio a todo el pais",
    "envíos a todo el país",
    "pesos argentinos",
    "ars ",
    " pesos",
    "+54",
    "54 9",
    "549",
)
_FOREIGN_BIO_KEYWORDS: tuple[str, ...] = (
    "méxico",
    "mexico",
    "cdmx",
    "colombia",
    "bogotá",
    "bogota",
    "chile",
    "santiago de chile",
    "perú",
    "peru",
    "lima peru",
    "ecuador",
    "venezuela",
    "uruguay",
    "montevideo",
    "paraguay",
    "brasil",
    "brazil",
    "são paulo",
    "sao paulo",
    "españa",
    "spain",
    "madrid",
    "barcelona",
    "usa",
    "miami",
    "california",
    "united states",
    "estados unidos",
    "república dominicana",
    "republica dominicana",
    "guatemala",
    "costa rica",
)
_AR_CITY_NAMES: frozenset[str] = frozenset(
    {
        "buenos aires",
        "caba",
        "cordoba",
        "córdoba",
        "rosario",
        "mendoza",
        "la plata",
        "mar del plata",
        "tucuman",
        "tucumán",
        "salta",
        "neuquen",
        "neuquén",
        "bariloche",
        "san juan",
        "san luis",
        "santa fe",
        "parana",
        "paraná",
        "resistencia",
        "corrientes",
        "posadas",
        "formosa",
        "jujuy",
        "catamarca",
        "la rioja",
        "rio gallegos",
        "ushuaia",
        "rawson",
        "viedma",
    }
)
_AR_URL_TLDS: tuple[str, ...] = (".com.ar", ".ar/")
_FOREIGN_URL_TLDS: tuple[str, ...] = (
    ".com.mx",
    ".mx/",
    ".cl/",
    ".com.co",
    ".co/",
    ".com.pe",
    ".pe/",
    ".com.br",
    ".br/",
    ".es/",
)
_SKIP_USERNAMES = frozenset(
    {
        "explore",
        "direct",
        "reels",
        "accounts",
        "p",
        "stories",
        "about",
        "legal",
        "privacy",
        "terms",
        "api",
    }
)


def chrome_user_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("No se encontró LOCALAPPDATA (¿estás en Windows?).")
    return Path(local_app_data) / "Google" / "Chrome" / "User Data"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def automation_user_data_dir() -> Path:
    custom = os.environ.get("AUTOMATION_USER_DATA_DIR")
    if custom:
        return Path(custom)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    base = Path(local_app_data) / "Ordino"
    account = os.environ.get("INSTAGRAM_ACCOUNT", "").strip()
    if account:
        safe = re.sub(r"[^\w\-]", "_", account)
        return base / f"ChromeInstagram_{safe}"
    return base / "ChromeInstagram"


def is_chrome_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return "chrome.exe" in result.stdout.lower()


def _force_sync() -> bool:
    return os.environ.get("SYNC_CHROME_PROFILE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def login_wait_seconds() -> int:
    raw = os.environ.get("LOGIN_WAIT_SECONDS", str(DEFAULT_LOGIN_WAIT))
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_LOGIN_WAIT


_SESSION_FILE_STEMS = (
    "Cookies",
    "Login Data",
    "Preferences",
    "Secure Preferences",
    "Web Data",
    "Account Web Data",
    "TransportSecurity",
)
_SESSION_DIRS = ("Network", "Session Storage", "Local Storage")


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _copy_session_files(src_profile: Path, dest_profile: Path) -> int:
    copied = 0
    for stem in _SESSION_FILE_STEMS:
        for src_file in src_profile.glob(f"{stem}*"):
            if src_file.is_file():
                _copy_file(src_file, dest_profile / src_file.name)
                copied += 1
    return copied


def _copy_dir(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _copy_indexeddb_instagram(src_profile: Path, dest_profile: Path) -> None:
    src_idb = src_profile / "IndexedDB"
    if not src_idb.exists():
        return
    dest_idb = dest_profile / "IndexedDB"
    dest_idb.mkdir(parents=True, exist_ok=True)
    for item in src_idb.iterdir():
        if "instagram" not in item.name.lower():
            continue
        dest_item = dest_idb / item.name
        if item.is_dir():
            shutil.copytree(item, dest_item, dirs_exist_ok=True)
        else:
            _copy_file(item, dest_item)


def copy_session_artifacts(src_profile: Path, dest_profile: Path) -> None:
    dest_profile.mkdir(parents=True, exist_ok=True)
    print("  -> cookies y preferencias...", flush=True)
    n_files = _copy_session_files(src_profile, dest_profile)
    if n_files == 0:
        raise RuntimeError(f"No se encontraron cookies en {src_profile}.")
    for dir_name in _SESSION_DIRS:
        src_dir = src_profile / dir_name
        if src_dir.exists():
            print(f"  -> {dir_name}/...", flush=True)
            _copy_dir(src_dir, dest_profile / dir_name)
    print("  -> IndexedDB (Instagram)...", flush=True)
    _copy_indexeddb_instagram(src_profile, dest_profile)


def try_sync_from_chrome() -> None:
    """Opcional: copiar cookies desde Chrome (a menudo no mantiene el login)."""
    if is_chrome_running():
        raise RuntimeError("Cierra Chrome antes de usar SYNC_CHROME_PROFILE.")

    profile_name = os.environ.get("CHROME_PROFILE", "Default")
    src_root = chrome_user_data_dir()
    src_profile = src_root / profile_name
    dest_root = automation_user_data_dir()
    dest_profile = dest_root / profile_name

    if not src_profile.exists():
        raise RuntimeError(f"Perfil no encontrado: {src_profile}")

    print(
        "Intentando copiar sesión desde Chrome "
        "(en Chrome 136+ el login puede seguir sin funcionar)...\n",
        flush=True,
    )
    dest_root.mkdir(parents=True, exist_ok=True)
    copy_session_artifacts(src_profile, dest_profile)
    local_state = src_root / "Local State"
    if local_state.exists():
        _copy_file(local_state, dest_root / "Local State")


def prepare_automation_profile() -> Path:
    dest_root = automation_user_data_dir()
    profile_name = os.environ.get("CHROME_PROFILE", "Default")
    dest_root.mkdir(parents=True, exist_ok=True)
    (dest_root / profile_name).mkdir(parents=True, exist_ok=True)
    if _force_sync():
        try_sync_from_chrome()
    return dest_root


def instagram_login_username() -> str:
    """Usuario para login (INSTAGRAM_USERNAME o INSTAGRAM_ACCOUNT)."""
    for key in ("INSTAGRAM_USERNAME", "INSTAGRAM_ACCOUNT"):
        value = os.environ.get(key, "").strip().lstrip("@")
        if value:
            return value
    return ""


def instagram_login_password() -> str:
    return os.environ.get("INSTAGRAM_PASSWORD", "")


def build_driver() -> webdriver.Chrome:
    load_local_env()
    debug_port = os.environ.get("CHROME_DEBUG_PORT")
    options = Options()

    if debug_port:
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
    else:
        dest_root = prepare_automation_profile()
        profile_name = os.environ.get("CHROME_PROFILE", "Default")
        options.add_argument(f"--user-data-dir={dest_root.resolve()}")
        options.add_argument(f"--profile-directory={profile_name}")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.page_load_strategy = "normal"
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def safe_current_url(driver: webdriver.Chrome | None) -> str:
    if not driver:
        return "(sin navegador)"
    try:
        return driver.current_url
    except WebDriverException:
        return "(navegador cerrado o no responde)"


def safe_quit(driver: webdriver.Chrome | None) -> None:
    if not driver:
        return
    try:
        time.sleep(2)
        driver.quit()
    except WebDriverException:
        pass
    time.sleep(1)
    _kill_chromedriver()


def report_error(exc: BaseException, driver: webdriver.Chrome | None) -> None:
    print(f"\nError: {exc.__class__.__name__}: {exc or '(sin mensaje)'}", file=sys.stderr)
    print(f"URL: {safe_current_url(driver)}", file=sys.stderr)
    traceback.print_exc()


def _kill_chromedriver() -> None:
    subprocess.run(
        ["taskkill", "/IM", "chromedriver.exe", "/F"],
        capture_output=True,
        check=False,
    )


def _on_rm_error(_func, path: str, _exc_info) -> None:
    import stat

    try:
        os.chmod(path, stat.S_IWRITE)
        _func(path)
    except OSError:
        pass


def _force_remove_tree(path: Path, retries: int = 5) -> bool:
    for attempt in range(retries):
        if not path.exists():
            return True
        try:
            shutil.rmtree(path, onerror=_on_rm_error)
        except OSError:
            pass
        if not path.exists():
            return True
        time.sleep(1 + attempt)
    return not path.exists()


def ordino_profile_dirs() -> list[Path]:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    base = Path(local_app_data) / "Ordino"
    if not base.exists():
        return []
    return sorted(p for p in base.glob("ChromeInstagram*") if p.is_dir())


def clear_automation_session(*, all_profiles: bool = False) -> list[Path]:
    """Borra el perfil de Chrome (sin abrir navegador; evita cierres inesperados)."""
    _kill_chromedriver()
    time.sleep(0.5)

    targets = ordino_profile_dirs() if all_profiles else [automation_user_data_dir()]
    if not all_profiles and not targets:
        targets = [automation_user_data_dir()]

    removed: list[Path] = []

    for root in targets:
        if not root.exists():
            print(f"  (no existe) {root}", flush=True)
            continue

        print(f"Borrando perfil: {root}", flush=True)
        if _force_remove_tree(root):
            print("  -> Perfil eliminado", flush=True)
            removed.append(root)
        else:
            raise RuntimeError(
                f"No se pudo borrar:\n  {root}\n"
                "Cierra la ventana de Chrome que abrió el script y ejecuta:\n"
                "  python instagram_profile.py --logout"
            )

    if not removed and not all_profiles:
        print("No había datos de sesión que borrar.", flush=True)
    return removed


def has_instagram_session(driver: webdriver.Chrome) -> bool:
    """Detecta sesión por cookie sessionid o localStorage ds_user_id."""
    try:
        for cookie in driver.get_cookies():
            if cookie.get("name") == "sessionid" and cookie.get("value"):
                return True
        user_id = driver.execute_script(
            """
            try {
                if (localStorage.getItem('ds_user_id')) return true;
                if (document.cookie.includes('sessionid=')) return true;
                return false;
            } catch (e) { return false; }
            """
        )
        if user_id:
            return True
    except WebDriverException:
        pass
    return False


def session_is_active(driver: webdriver.Chrome) -> bool:
    return has_instagram_session(driver) or has_logged_in_ui(driver)


def _visible_login_form(driver: webdriver.Chrome) -> bool:
    selectors = (
        'input[name="username"]',
        'input[autocomplete="username"]',
        'input[type="password"]',
        'input[name="password"]',
    )
    for selector in selectors:
        try:
            if driver.find_element(By.CSS_SELECTOR, selector).is_displayed():
                return True
        except NoSuchElementException:
            continue
    return bool(
        driver.execute_script(
            """
            return !!document.querySelector(
                'input[type="password"], input[name="password"], input[autocomplete="current-password"]'
            );
            """
        )
    )


def is_login_page(driver: webdriver.Chrome) -> bool:
    if has_instagram_session(driver):
        return False
    if _is_saved_profile_login_screen(driver):
        return True
    url = driver.current_url.lower()
    if "/accounts/login" in url:
        return True
    if "instagram.com" in url and _visible_login_form(driver):
        return True
    return _visible_login_form(driver)


def has_logged_in_ui(driver: webdriver.Chrome) -> bool:
    if has_instagram_session(driver):
        return True
    for selector in (
        'a[aria-label="Profile"]',
        'a[aria-label="Perfil"]',
        'svg[aria-label="Home"]',
        'svg[aria-label="Inicio"]',
        'a[href="/direct/inbox/"]',
        'a[href="/direct/"]',
    ):
        try:
            if driver.find_element(By.CSS_SELECTOR, selector).is_displayed():
                return True
        except NoSuchElementException:
            continue
    return False


def wait_for_instagram_load(driver: webdriver.Chrome, timeout: int = 30) -> None:
    def _ready(d: webdriver.Chrome) -> bool:
        try:
            if d.execute_script("return document.readyState") != "complete":
                return False
            return has_instagram_session(d) or is_login_page(d) or has_logged_in_ui(d)
        except WebDriverException:
            return False

    try:
        WebDriverWait(driver, timeout).until(_ready)
    except TimeoutException as err:
        raise RuntimeError(
            f"Instagram no respondió a tiempo ({timeout}s). "
            f"URL: {safe_current_url(driver)}. "
            "¿Ves login, captcha o pantalla en blanco?"
        ) from err


def _find_login_username_field(driver: webdriver.Chrome):
    selectors = [
        (By.CSS_SELECTOR, 'input[name="username"]'),
        (By.CSS_SELECTOR, 'input[autocomplete="username"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="Phone number, username"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="Número de teléfono"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="usuario"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="correo"]'),
        (By.CSS_SELECTOR, 'input[aria-label*="celular"]'),
        (By.CSS_SELECTOR, 'form input[type="text"]'),
        (By.XPATH, "//input[@type='text' or @type='email']"),
    ]
    for by, value in selectors:
        try:
            for el in driver.find_elements(by, value):
                if el.is_displayed():
                    inp_type = (el.get_attribute("type") or "").lower()
                    if inp_type == "password":
                        continue
                    return el
        except NoSuchElementException:
            continue
    return None


def _find_login_password_field(driver: webdriver.Chrome):
    selectors = [
        (By.CSS_SELECTOR, 'input[name="password"]'),
        (By.CSS_SELECTOR, 'input[type="password"]'),
        (By.CSS_SELECTOR, 'input[autocomplete="current-password"]'),
    ]
    for by, value in selectors:
        try:
            el = driver.find_element(by, value)
            if el.is_displayed():
                return el
        except NoSuchElementException:
            continue
    return None


def _set_input_value(driver: webdriver.Chrome, element, value: str) -> None:
    driver.execute_script(
        """
        const el = arguments[0];
        const val = arguments[1];
        el.focus();
        const desc = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        );
        if (desc && desc.set) {
            desc.set.call(el, val);
        } else {
            el.value = val;
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        element,
        value,
    )


def _fill_login_field(driver: webdriver.Chrome, element, value: str) -> None:
    element.click()
    time.sleep(0.15)
    try:
        element.clear()
    except WebDriverException:
        pass
    try:
        ActionChains(driver).click(element).key_down(Keys.CONTROL).send_keys("a").key_up(
            Keys.CONTROL
        ).send_keys(Keys.BACKSPACE).send_keys(value).perform()
    except WebDriverException:
        element.send_keys(value)
    _set_input_value(driver, element, value)


def _wait_for_login_fields(
    driver: webdriver.Chrome, timeout: int = 25
) -> tuple[object, object]:
    def _ready(_driver: webdriver.Chrome) -> bool:
        user_field, pass_field = _find_login_fields(_driver)
        return bool(user_field and pass_field)

    WebDriverWait(driver, timeout).until(_ready)
    user_field, pass_field = _find_login_fields(driver)
    if not user_field or not pass_field:
        raise RuntimeError("No se encontraron campos de usuario/contraseña")
    return user_field, pass_field


def _is_onetap_screen(driver: webdriver.Chrome) -> bool:
    """Modal post-login: '¿Guardar tu información de inicio de sesión?' (/accounts/onetap/)."""
    try:
        url = driver.current_url.lower()
    except WebDriverException:
        return False
    if "/onetap" in url:
        return True
    return bool(
        driver.execute_script(
            """
            const t = (document.body.innerText || '').toLowerCase();
            return t.includes('guardar tu información de inicio de sesión')
                || t.includes('guardar tu informacion de inicio de sesion')
                || t.includes('save your login information');
            """
        )
    )


def dismiss_onetap_prompt(driver: webdriver.Chrome) -> bool:
    """Cierra el modal de guardar login (Ahora no o Guardar información)."""
    if not _is_onetap_screen(driver):
        return False
    print(
        "  Cerrando 'Guardar información de inicio de sesión' (Ahora no)...",
        flush=True,
    )
    if _click_labeled_button(driver, ("ahora no", "not now")):
        time.sleep(2)
        return True
    if _click_labeled_button(
        driver,
        (
            "guardar información",
            "guardar informacion",
            "save information",
            "save info",
        ),
    ):
        time.sleep(2)
        return True
    return bool(
        driver.execute_script(
            """
            const labels = ['ahora no', 'not now', 'guardar información', 'guardar informacion'];
            for (const el of document.querySelectorAll('button, div[role="button"]')) {
                const t = (el.textContent || '').trim().toLowerCase();
                if (labels.some((l) => t === l || t.includes(l))) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
    )


def _login_flow_complete(driver: webdriver.Chrome) -> bool:
    """Sesión lista o en pantalla onetap (un paso después de Continuar)."""
    return session_is_active(driver) or _is_onetap_screen(driver)


def _is_saved_profile_login_screen(driver: webdriver.Chrome) -> bool:
    """Pantalla con perfil guardado y botón Continuar (antes de entrar)."""
    if _is_onetap_screen(driver):
        return False
    if _login_flow_complete(driver):
        return False
    return bool(
        driver.execute_script(
            """
            const hasPassword = !!document.querySelector(
                'input[type="password"], input[name="password"]'
            );
            if (hasPassword) return false;
            const text = (document.body.innerText || '').toLowerCase();
            const hasContinue = text.includes('continuar') || text.includes('continue');
            const hasSwitch = text.includes('usar otro perfil')
                || text.includes('use another profile')
                || text.includes('switch accounts');
            return hasContinue && hasSwitch;
            """
        )
    )


def _click_labeled_button(driver: webdriver.Chrome, labels: tuple[str, ...]) -> bool:
    normalized = tuple(label.strip().lower() for label in labels)
    for tag in ("button", "div[role='button']", "a[role='button']"):
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, tag):
                try:
                    if not el.is_displayed():
                        continue
                except WebDriverException:
                    continue
                text = (el.text or el.get_attribute("aria-label") or "").strip().lower()
                if text not in normalized and not any(
                    text == label or text.startswith(label + " ") for label in normalized
                ):
                    continue
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", el
                )
                time.sleep(0.25)
                try:
                    el.click()
                except WebDriverException:
                    driver.execute_script("arguments[0].click();", el)
                return True
        except WebDriverException:
            continue
    return False


def _click_continue_button(driver: webdriver.Chrome) -> bool:
    """Clic en el botón azul Continuar (solo <button>, texto exacto)."""
    for label in ("Continuar", "Continue"):
        xpaths = (
            f"//button[normalize-space()='{label}']",
            f"//button[.//text()[normalize-space()='{label}']]",
            f"//button[contains(normalize-space(.), '{label}')]",
        )
        for xpath in xpaths:
            try:
                el = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", el
                )
                time.sleep(0.3)
                try:
                    ActionChains(driver).move_to_element(el).pause(0.2).click().perform()
                except WebDriverException:
                    el.click()
                return True
            except TimeoutException:
                continue

    for el in driver.find_elements(By.TAG_NAME, "button"):
        try:
            if not el.is_displayed():
                continue
            text = (el.text or "").strip().lower()
            if text in ("continuar", "continue"):
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", el
                )
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", el)
                return True
        except WebDriverException:
            continue
    return False


def _finalize_login_session(driver: webdriver.Chrome) -> None:
    """Tras login: cerrar onetap, ir al inicio y confirmar sessionid en el perfil."""
    dismiss_onetap_prompt(driver)
    dismiss_instagram_popups(driver)
    driver.get(INSTAGRAM_URL)
    time.sleep(3)
    dismiss_instagram_popups(driver)
    if has_instagram_session(driver):
        print(
            "  Cookie sessionid guardada en el perfil de automatización.",
            flush=True,
        )
    else:
        print(
            "  Aviso: no se detectó sessionid; la próxima corrida puede pedir login.",
            flush=True,
        )


def try_saved_profile_login(driver: webdriver.Chrome, expected_username: str) -> bool:
    """
    Login con un toque: pantalla con foto + 'Continuar' (perfil guardado en Chrome).
    Si el perfil mostrado no coincide con .env, usa 'Usar otro perfil'.
    """
    expected = expected_username.strip().lstrip("@").lower()
    if not expected:
        return False

    if _is_onetap_screen(driver):
        dismiss_onetap_prompt(driver)
        if session_is_active(driver):
            print("  Login OK (onetap).", flush=True)
            _finalize_login_session(driver)
            return True
        return False

    if session_is_active(driver):
        dismiss_onetap_prompt(driver)
        return True

    if not _is_saved_profile_login_screen(driver):
        return False

    page_text = (
        driver.execute_script(
            "return (document.body.innerText || '').toLowerCase();"
        )
        or ""
    )
    profile_visible = expected in page_text

    if not profile_visible:
        print(
            f"  Perfil guardado en pantalla no es @{expected}. "
            "Pulsando 'Usar otro perfil'...",
            flush=True,
        )
        _click_labeled_button(
            driver,
            (
                "usar otro perfil",
                "use another profile",
                "switch accounts",
                "cambiar de cuenta",
            ),
        )
        time.sleep(2.5)
        return False

    print(f"  Perfil guardado @{expected}: pulsando Continuar...", flush=True)
    clicked = False
    for click_try in range(1, 4):
        if _login_flow_complete(driver):
            clicked = True
            break
        if _click_continue_button(driver):
            clicked = True
            time.sleep(2)
            break
        if _login_flow_complete(driver):
            clicked = True
            break
        print(f"  Reintento clic Continuar ({click_try}/3)...", flush=True)
        time.sleep(1.5)

    if not _login_flow_complete(driver):
        print(
            "  Si hace falta, pulsá Continuar vos en Chrome "
            "(máx. 2 min; después aparece 'Guardar información').",
            flush=True,
        )
        try:
            WebDriverWait(driver, 120).until(lambda d: _login_flow_complete(d))
        except TimeoutException:
            return False

    dismiss_onetap_prompt(driver)
    try:
        WebDriverWait(driver, 30).until(lambda d: session_is_active(d))
    except TimeoutException:
        if not session_is_active(driver):
            return False

    print("  Login OK (Continuar).", flush=True)
    _finalize_login_session(driver)
    return True


def _open_login_page(driver: webdriver.Chrome) -> None:
    expected = instagram_login_username()
    for url in (
        INSTAGRAM_URL,
        f"{INSTAGRAM_URL}accounts/login/",
        f"{INSTAGRAM_URL}accounts/login/?next=/&source=auth_switcher",
    ):
        driver.get(url)
        WebDriverWait(driver, WAIT_SECONDS).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(2)
        dismiss_instagram_popups(driver)
        if session_is_active(driver):
            return
        if expected and try_saved_profile_login(driver, expected):
            return
        if _find_login_fields(driver)[0] and _find_login_fields(driver)[1]:
            return


def _click_login_submit(driver: webdriver.Chrome) -> bool:
    if driver.execute_script(
        """
        const labels = ['iniciar sesión', 'iniciar sesion', 'log in', 'login'];
        for (const el of document.querySelectorAll('button, div[role="button"]')) {
            const t = (el.textContent || el.getAttribute('aria-label') || '')
                .trim().toLowerCase();
            if (labels.some((l) => t === l || t.includes(l))) {
                el.scrollIntoView({ block: 'center' });
                el.click();
                return true;
            }
        }
        const submit = document.querySelector('button[type="submit"]');
        if (submit) { submit.click(); return true; }
        return false;
        """
    ):
        return True
    try:
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        return True
    except NoSuchElementException:
        return False


def dismiss_instagram_popups(driver: webdriver.Chrome) -> None:
    """Cierra modales típicos (notificaciones, guardar login, etc.)."""
    if dismiss_onetap_prompt(driver):
        time.sleep(1)
    for _ in range(3):
        clicked = driver.execute_script(
            """
            const labels = [
                'not now', 'ahora no', 'later', 'más tarde', 'cancel', 'cancelar',
                'aceptar', 'ok', 'entendido', 'got it', 'no thanks',
                'guardar información', 'guardar informacion', 'save information',
            ];
            for (const el of document.querySelectorAll(
                'button, div[role="button"], [role="dialog"] button'
            )) {
                const t = (el.textContent || el.getAttribute('aria-label') || '')
                    .trim().toLowerCase();
                if (!t) continue;
                if (labels.some((l) => t === l || t.includes(l))) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
        if not clicked:
            break
        time.sleep(1)


def _find_login_fields(driver: webdriver.Chrome) -> tuple[object | None, object | None]:
    """Usuario y contraseña en el formulario de login."""
    user_field = _find_login_username_field(driver)
    pass_field = _find_login_password_field(driver)
    if user_field and pass_field:
        return user_field, pass_field

    ordered: list[object] = []
    for inp in driver.find_elements(By.CSS_SELECTOR, "input"):
        try:
            if not inp.is_displayed():
                continue
        except WebDriverException:
            continue
        ordered.append(inp)

    user_field = None
    pass_field = None
    for inp in ordered:
        inp_type = (inp.get_attribute("type") or "text").lower()
        name = (inp.get_attribute("name") or "").lower()
        if inp_type == "password" or name == "password":
            pass_field = inp
        elif user_field is None and inp_type in ("text", "email", "tel", ""):
            user_field = inp
    return user_field, pass_field


def try_automatic_login(driver: webdriver.Chrome) -> bool:
    username = instagram_login_username()
    password = instagram_login_password()
    if not username or not password:
        print(
            "Sin credenciales: .env con INSTAGRAM_USERNAME (o INSTAGRAM_ACCOUNT) "
            "e INSTAGRAM_PASSWORD.",
            flush=True,
        )
        return False

    if session_is_active(driver):
        dismiss_onetap_prompt(driver)
        return True

    if _is_onetap_screen(driver):
        dismiss_onetap_prompt(driver)
        if session_is_active(driver):
            _finalize_login_session(driver)
            return True

    print(f"Iniciando sesión como @{username}...", flush=True)
    for attempt in range(1, 4):
        try:
            if session_is_active(driver):
                dismiss_onetap_prompt(driver)
                print("  Login OK (sesión detectada).", flush=True)
                return True

            if _is_onetap_screen(driver):
                dismiss_onetap_prompt(driver)
                if session_is_active(driver):
                    _finalize_login_session(driver)
                    return True

            if not is_login_page(driver) or not _find_login_fields(driver)[0]:
                _open_login_page(driver)
                if session_is_active(driver):
                    dismiss_onetap_prompt(driver)
                    print("  Login OK (ya había sesión).", flush=True)
                    return True
                if _is_onetap_screen(driver):
                    dismiss_onetap_prompt(driver)
                    if session_is_active(driver):
                        _finalize_login_session(driver)
                        return True

            if _is_saved_profile_login_screen(driver) and try_saved_profile_login(
                driver, username
            ):
                return True

            if _is_saved_profile_login_screen(driver):
                raise RuntimeError(
                    "Pantalla 'Continuar' visible pero no se pudo iniciar sesión"
                )

            user_field, pass_field = _wait_for_login_fields(driver, timeout=25)
            _fill_login_field(driver, user_field, username)
            time.sleep(0.4)
            _fill_login_field(driver, pass_field, password)
            time.sleep(0.5)

            if not _click_login_submit(driver):
                pass_field.send_keys(Keys.RETURN)

            print("  Enviando login, esperando respuesta...", flush=True)
            time.sleep(4)
            dismiss_instagram_popups(driver)

            WebDriverWait(driver, 90).until(lambda d: session_is_active(d))
            print("  Login OK.", flush=True)
            _finalize_login_session(driver)
            return True
        except TimeoutException:
            print(
                f"  Intento {attempt}/3: timeout (captcha, 2FA o credenciales incorrectas).",
                flush=True,
            )
            time.sleep(3)
        except (WebDriverException, RuntimeError) as exc:
            print(f"  Intento {attempt}/3 falló: {exc}", flush=True)
            time.sleep(2)

    return session_is_active(driver)


def ensure_logged_in(driver: webdriver.Chrome) -> None:
    load_local_env()
    has_creds = bool(instagram_login_username() and instagram_login_password())

    print("Verificando sesión en el perfil de automatización...", flush=True)
    driver.get(INSTAGRAM_URL)
    try:
        wait_for_instagram_load(driver, timeout=45)
    except RuntimeError:
        print("Instagram lento; reintentando...", flush=True)
        time.sleep(3)
    dismiss_instagram_popups(driver)

    if _is_onetap_screen(driver):
        dismiss_onetap_prompt(driver)

    if session_is_active(driver):
        print("Sesión activa (no hace falta login).", flush=True)
        return

    expected = instagram_login_username()
    if _is_onetap_screen(driver) and expected:
        dismiss_onetap_prompt(driver)
        if session_is_active(driver):
            _finalize_login_session(driver)
            print("Sesión activa (onetap cerrado).", flush=True)
            return

    if _is_saved_profile_login_screen(driver) and expected:
        if try_saved_profile_login(driver, expected):
            print("Sesión iniciada con perfil guardado (Continuar).", flush=True)
            return

    if has_creds and try_automatic_login(driver):
        dismiss_instagram_popups(driver)
        time.sleep(2)
        print("Sesión iniciada automáticamente.", flush=True)
        return

    if not session_is_active(driver):
        if has_creds:
            _open_login_page(driver)
            if try_automatic_login(driver):
                dismiss_instagram_popups(driver)
                print("Sesión iniciada automáticamente.", flush=True)
                return

    if session_is_active(driver):
        dismiss_instagram_popups(driver)
        print("Sesión activa.", flush=True)
        return

    if is_login_page(driver) or not session_is_active(driver):
        print(
            "\n"
            + "=" * 56
            + "\n"
            "  No se pudo iniciar sesión automáticamente.\n"
            "  Completá login/captcha/2FA en la ventana de Chrome.\n"
            "  (máx. 10 minutos; se guarda en el perfil Ordino)\n"
            + "=" * 56
            + "\n",
            flush=True,
        )
        timeout = login_wait_seconds()
        try:
            WebDriverWait(driver, timeout).until(lambda d: session_is_active(d))
        except TimeoutException:
            raise RuntimeError(
                f"No se detectó sesión tras {timeout}s. "
                "Revisá .env o iniciá sesión manualmente en Chrome."
            ) from None
        dismiss_instagram_popups(driver)
        _finalize_login_session(driver)
        print("Sesión guardada. Las próximas corridas no deberían pedir login.", flush=True)
        return

    dismiss_instagram_popups(driver)
    print("Continuando (Instagram cargó sin pantalla de login).", flush=True)


def warn_session_env_issues() -> None:
    if _env_truthy("RESET_SESSION") or _env_truthy("LOGOUT"):
        print(
            "AVISO: RESET_SESSION o LOGOUT en .env borra la sesión en cada corrida. "
            "Quitá esa variable del .env.",
            flush=True,
        )
    if _force_sync():
        print(
            "AVISO: SYNC_CHROME_PROFILE=1 puede pisar la sesión del perfil Ordino. "
            "Dejalo apagado salvo que sepas lo que hacés.",
            flush=True,
        )


def go_to_profile_by_username(driver: webdriver.Chrome, username: str) -> None:
    username = username.strip().lstrip("@").strip("/")
    driver.get(f"{INSTAGRAM_URL}{username}/")
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: username.lower() in d.current_url.lower()
    )


def detect_username(driver: webdriver.Chrome) -> str | None:
    """Obtiene el usuario logueado desde enlaces de la página."""
    return driver.execute_script(
        """
        const skip = new Set([
            'explore', 'direct', 'reels', 'accounts', 'p', 'stories',
            'about', 'legal', 'privacy', 'terms', 'api', ''
        ]);
        const fromHref = (href) => {
            const m = (href || '').match(/instagram\\.com\\/([^/?#]+)/i);
            return m && !skip.has(m[1].toLowerCase()) ? m[1] : null;
        };

        const profileLink = document.querySelector(
            'a[aria-label="Profile"], a[aria-label="Perfil"]'
        );
        if (profileLink) {
            const u = fromHref(profileLink.href);
            if (u) return u;
        }

        for (const a of document.querySelectorAll(
            'nav a[href], header a[href], [role="navigation"] a[href]'
        )) {
            const href = a.getAttribute('href') || '';
            const m = href.match(/^\\/([^\\/]+)\\/?$/);
            if (!m || skip.has(m[1].toLowerCase())) continue;
            if (a.querySelector('img')) return m[1];
        }
        return null;
        """
    )


def go_to_profile_via_ui(driver: webdriver.Chrome) -> None:
    short_wait = WebDriverWait(driver, 5)
    selectors = [
        (By.CSS_SELECTOR, 'a[aria-label="Profile"]'),
        (By.CSS_SELECTOR, 'a[aria-label="Perfil"]'),
        (
            By.XPATH,
            "//a[.//span[normalize-space()='Profile' or normalize-space()='Perfil']]",
        ),
    ]
    for by, value in selectors:
        try:
            link = short_wait.until(EC.element_to_be_clickable((by, value)))
            link.click()
            return
        except TimeoutException:
            continue

    raise RuntimeError(
        "No se encontró el botón de perfil. "
        "Define INSTAGRAM_USERNAME con tu usuario de Instagram."
    )


def username_from_url(url: str) -> str | None:
    match = re.search(r"instagram\.com/([^/?#]+)", url, re.IGNORECASE)
    if not match:
        return None
    name = match.group(1).lower()
    if name in _SKIP_USERNAMES:
        return None
    return match.group(1)


def go_to_my_profile(driver: webdriver.Chrome) -> str:
    env_user = instagram_login_username()
    if env_user:
        print(f"Abriendo perfil @{env_user}...", flush=True)
        go_to_profile_by_username(driver, env_user)
        return env_user

    print("Detectando tu usuario...", flush=True)
    username = detect_username(driver)
    if username:
        print(f"Abriendo perfil @{username}...", flush=True)
        go_to_profile_by_username(driver, username)
        return username

    print("Buscando enlace de perfil (máx. 15 s)...", flush=True)
    go_to_profile_via_ui(driver)
    from_url = username_from_url(driver.current_url)
    if from_url:
        return from_url

    raise RuntimeError(
        "No se pudo detectar tu usuario. Define INSTAGRAM_USERNAME (ej. santypuleio)."
    )


def list_type() -> str:
    """following = seguidos (cuentas que sigues); followers = seguidores."""
    raw = os.environ.get("INSTAGRAM_LIST", "following").strip().lower()
    if raw in ("followers", "seguidores", "seguidor"):
        return "followers"
    return "following"


def _wait_for_profile_page(driver: webdriver.Chrome, username: str) -> None:
    username_lower = username.lower()
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: username_lower in d.current_url.lower()
        and "/followers" not in d.current_url.lower()
        and "/following" not in d.current_url.lower()
    )
    time.sleep(1)


def _click_profile_list_button(
    driver: webdriver.Chrome, username: str, kind: str
) -> bool:
    """Clic en seguidos/seguidores del perfil (abre modal, sin cambiar URL)."""
    path = "followers" if kind == "followers" else "following"
    labels = (
        ["seguidores", "followers"]
        if kind == "followers"
        else ["seguidos", "following", "siguiendo"]
    )

    short_wait = WebDriverWait(driver, 8)
    css_candidates = [
        f'a[href="/{username}/{path}/"]',
        f'a[href*="/{username}/{path}"]',
        f'a[href*="/{path}/"]',
    ]
    for selector in css_candidates:
        try:
            link = short_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();",
                link,
            )
            return True
        except TimeoutException:
            continue

    for label in labels:
        xpath = (
            f"//a[contains(translate(., "
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{label}')]"
        )
        try:
            link = short_wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();",
                link,
            )
            return True
        except TimeoutException:
            continue

    return bool(
        driver.execute_script(
            """
            const path = arguments[0];
            const user = arguments[1].toLowerCase();
            const labels = arguments[2];

            const matchesPath = (href) => {
                const h = (href || '').toLowerCase();
                return h.includes('/' + path) && h.includes(user);
            };

            const clickEl = (el) => {
                if (!el) return false;
                el.scrollIntoView({ block: 'center' });
                el.click();
                return true;
            };

            // Enlaces del encabezado del perfil (href puede existir pero abre modal)
            for (const a of document.querySelectorAll('a[href]')) {
                if (matchesPath(a.getAttribute('href'))) return clickEl(a);
            }

            // Por texto visible (español / inglés)
            for (const a of document.querySelectorAll(
                'header a, section ul a, main section a'
            )) {
                const text = (a.textContent || '').toLowerCase();
                if (labels.some((l) => text.includes(l))) return clickEl(a);
            }

            // Tercer ítem del perfil: publicaciones | seguidores | seguidos
            for (const ul of document.querySelectorAll('header ul, section ul')) {
                const items = ul.querySelectorAll(':scope > li');
                if (items.length < 3) continue;
                const idx = path === 'followers' ? 1 : 2;
                const target = items[idx].querySelector('a') || items[idx];
                if (clickEl(target)) return true;
            }
            return false;
            """,
            path,
            username,
            labels,
        )
    )


def _wait_for_list_modal(driver: webdriver.Chrome) -> None:
    wait = WebDriverWait(driver, WAIT_SECONDS)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]')))
    wait.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, 'div[role="dialog"] a[href*="/"]')
        )
    )


def go_to_my_following_list(driver: webdriver.Chrome, username: str) -> None:
    kind = list_type()
    label = "seguidores" if kind == "followers" else "seguidos"
    username = username.strip().lstrip("@").strip("/")

    _wait_for_profile_page(driver, username)
    print(f"Clic en «{label}» en el perfil (@{username})...", flush=True)

    if not _click_profile_list_button(driver, username, kind):
        raise RuntimeError(
            f"No se encontró el botón de {label} en el perfil. "
            "Prueba con la ventana maximizada o define INSTAGRAM_USERNAME."
        )

    _wait_for_list_modal(driver)

    if username.lower() in driver.current_url.lower():
        print(f"Modal de {label} abierto (misma URL del perfil).", flush=True)
    else:
        print(f"Lista de {label} abierta.", flush=True)


_GET_USER_ID_JS = """
const username = arguments[0];
const appId = arguments[1];
const done = arguments[arguments.length - 1];
const uname = String(username).toLowerCase();

function apiHeaders() {
    const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
    return {
        'X-IG-App-ID': appId,
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrf,
        'X-Instagram-AJAX': '1',
        'Referer': 'https://www.instagram.com/' + encodeURIComponent(username) + '/',
        'Accept': '*/*',
    };
}

function idFromPage() {
    try {
        const ls = localStorage.getItem('ds_user_id');
        if (ls && /^\\d+$/.test(String(ls))) return String(ls);
    } catch (e) {}

    const meta = document.querySelector(
        'meta[property="instapp:owner_user_id"], meta[name="instagram:id"]'
    );
    if (meta) {
        const v = meta.getAttribute('content');
        if (v && /^\\d+$/.test(v)) return v;
    }

    const html = document.documentElement.innerHTML;
    const patterns = [
        new RegExp('"username":"' + uname + '"[^}]{0,800}?"id":"(\\\\d+)"', 'i'),
        new RegExp('"id":"(\\\\d+)"[^}]{0,800}?"username":"' + uname + '"', 'i'),
        /"profilePage_(\\d+)"/,
        /"profile_id":"(\\d+)"/,
        /"owner_id":"(\\d+)"/,
        /"target_user_id":"(\\d+)"/,
        /"user_id":"(\\d+)"/,
        /"pk":(\\d+),"username":"[^"]*"/i,
    ];
    for (const re of patterns) {
        const m = html.match(re);
        if (m && m[1]) return m[1];
    }

    for (const s of document.querySelectorAll(
        'script[type="application/json"], script:not([src])'
    )) {
        const t = s.textContent || '';
        if (!t.includes(uname) && !t.includes('profilePage')) continue;
        const tries = [
            t.match(/"id":"(\\d+)"/),
            t.match(/"pk":(\\d+)/),
            t.match(/profilePage_(\\d+)/),
        ];
        for (const m of tries) {
            if (m) return m[1];
        }
    }

    try {
        const path = '/' + username + '/';
        const shared = window.__additionalDataLoaded?.(path);
        const uid = shared?.graphql?.user?.id || shared?.data?.user?.id;
        if (uid) return String(uid);
    } catch (e) {}

    return null;
}

(async () => {
    const fromPageFirst = idFromPage();
    if (fromPageFirst) {
        done({ id: fromPageFirst, error: null, source: 'page' });
        return;
    }

    try {
        const url =
            'https://www.instagram.com/api/v1/users/web_profile_info/?username=' +
            encodeURIComponent(username);
        const resp = await fetch(url, {
            credentials: 'include',
            headers: apiHeaders(),
        });
        const raw = await resp.text();
        let data = null;
        try {
            data = JSON.parse(raw);
        } catch (e) {
            const fromPage = idFromPage();
            if (fromPage) {
                done({ id: fromPage, error: null, source: 'page' });
                return;
            }
            done({
                id: null,
                error: 'respuesta HTML (sesión o bloqueo temporal)',
            });
            return;
        }
        const id = data?.data?.user?.id || data?.data?.user?.pk;
        if (id) {
            done({ id: String(id), error: null, source: 'api' });
            return;
        }
        const apiErr = data?.message || data?.feedback_message || ('HTTP ' + resp.status);
        const fromPage = idFromPage();
        if (fromPage) {
            done({ id: fromPage, error: null, source: 'page', api_note: apiErr });
            return;
        }
        done({ id: null, error: apiErr });
    } catch (e) {
        const fromPage = idFromPage();
        if (fromPage) {
            done({ id: fromPage, error: null, source: 'page' });
            return;
        }
        done({ id: null, error: String(e) });
    }
})();
"""


_SCRAPE_FOLLOW_LIST_JS = """
const listType = arguments[0];
const maxScrolls = arguments[1];
const done = arguments[arguments.length - 1];

const SKIP = new Set([
    'explore', 'direct', 'reels', 'accounts', 'p', 'stories',
    'about', 'legal', 'privacy', 'terms', 'api', 'tags', 'locations',
]);

function scrapeDialog() {
    const dialog = document.querySelector('div[role="dialog"]');
    if (!dialog) return [];
    const users = [];
    const seen = new Set();
    for (const a of dialog.querySelectorAll('a[href]')) {
        const href = (a.getAttribute('href') || '').split('?')[0];
        const m = href.match(/^\\/([A-Za-z0-9._]+)\\/?$/);
        if (!m) continue;
        const key = m[1].toLowerCase();
        if (SKIP.has(key) || seen.has(key)) continue;
        seen.add(key);
        users.push({ id: '', username: m[1] });
    }
    return users;
}

function scrollDialog() {
    const dialog = document.querySelector('div[role="dialog"]');
    if (!dialog) return false;
    const scrollable =
        dialog.querySelector('[style*="overflow-y"]') ||
        dialog.querySelector('div._aano') ||
        dialog.querySelector('div[class*="scroll"]') ||
        dialog;
    const prev = scrollable.scrollTop;
    scrollable.scrollTop = scrollable.scrollHeight;
    return scrollable.scrollTop > prev;
}

(async () => {
    const seen = new Set();
    const all = [];
    let stagnant = 0;
    for (let i = 0; i < maxScrolls; i++) {
        for (const u of scrapeDialog()) {
            const key = u.username.toLowerCase();
            if (seen.has(key)) continue;
            seen.add(key);
            all.push(u);
        }
        if (!scrollDialog()) stagnant++;
        else stagnant = 0;
        if (stagnant >= 4) break;
        await new Promise((r) => setTimeout(r, 700));
    }
    done({ users: all, error: all.length ? null : 'modal vacío', listType });
})();
"""


_FETCH_LIST_JS = """
const userId = arguments[0];
const listType = arguments[1];
const pageSize = arguments[2];
const done = arguments[arguments.length - 1];
const appId = arguments[3];

function apiHeaders() {
    const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
    return {
        'X-IG-App-ID': appId,
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrf,
        'X-Instagram-AJAX': '1',
        'Referer': window.location.href,
        'Accept': '*/*',
    };
}

(async () => {
    const users = [];
    let maxId = null;
    try {
        while (true) {
            let url = `https://www.instagram.com/api/v1/friendships/${userId}/${listType}/?count=${pageSize}`;
            if (maxId) url += `&max_id=${encodeURIComponent(maxId)}`;
            const resp = await fetch(url, {
                credentials: 'include',
                headers: apiHeaders(),
            });
            if (!resp.ok) {
                done({ users: [], error: `HTTP ${resp.status}` });
                return;
            }
            const raw = await resp.text();
            let data;
            try {
                data = JSON.parse(raw);
            } catch (e) {
                done({ users: [], error: 'JSON inválido (HTML?): ' + raw.slice(0, 80) });
                return;
            }
            for (const u of (data.users || [])) {
                const id = String(u.pk || u.id || '');
                if (id && u.username) {
                    users.push({ id, username: u.username });
                }
            }
            if (data.message || data.feedback_message) {
                done({
                    users: [],
                    error: data.message || data.feedback_message,
                    blocked: true,
                });
                return;
            }
            if (!data.next_max_id) break;
            maxId = data.next_max_id;
        }
        done({ users, error: null });
    } catch (e) {
        done({ users: [], error: String(e), blocked: false });
    }
})();
"""


def _user_id_from_page_source(driver: webdriver.Chrome, username: str) -> str | None:
    """Respaldo en Python si el script async no encuentra el ID."""
    uname = username.lower()
    try:
        uid = driver.execute_script(
            """
            try {
                const ls = localStorage.getItem('ds_user_id');
                if (ls && /^\\d+$/.test(ls)) return ls;
            } catch (e) {}
            return null;
            """
        )
        if uid:
            return str(uid)
    except WebDriverException:
        pass

    try:
        html = driver.page_source
    except WebDriverException:
        return None

    patterns = [
        rf'"username":"{re.escape(uname)}".{{0,800}}?"id":"(\d+)"',
        rf'"id":"(\d+)".{{0,800}}?"username":"{re.escape(uname)}"',
        r'"profilePage_(\d+)"',
        r'"profile_id":"(\d+)"',
        r'"user_id":"(\d+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
    return None


def get_instagram_user_id(
    driver: webdriver.Chrome, username: str, *, quiet: bool = False
) -> str:
    username = username.strip().lstrip("@")
    go_to_profile_by_username(driver, username)
    time.sleep(3)

    driver.set_script_timeout(60)
    result = driver.execute_async_script(_GET_USER_ID_JS, username, IG_APP_ID)
    user_id = result.get("id")
    if not user_id:
        user_id = _user_id_from_page_source(driver, username)

    if not user_id:
        raise RuntimeError(
            f"No se pudo obtener el ID de @{username}: {result.get('error')}"
        )

    if not quiet:
        source = result.get("source") or ("page" if not result.get("api_note") else "page")
        note = result.get("api_note")
        if note:
            print(
                f"ID de @{username}: {user_id} ({source}; API: {note})",
                flush=True,
            )
        else:
            print(f"ID de @{username}: {user_id} ({source})", flush=True)
    return str(user_id)


def fetch_users_via_modal(
    driver: webdriver.Chrome, username: str, list_type: str
) -> list[dict[str, str]]:
    """Lista seguidos/seguidores desde el modal del perfil (sin API)."""
    label = "seguidores" if list_type == "followers" else "seguidos"
    print(f"  Abriendo modal de {label} en @{username}...", flush=True)
    _wait_for_profile_page(driver, username)
    if not _click_profile_list_button(driver, username, list_type):
        raise RuntimeError(f"No se pudo abrir la lista de {label} en el perfil.")
    _wait_for_list_modal(driver)
    time.sleep(1.5)

    driver.set_script_timeout(SCRIPT_TIMEOUT)
    result = driver.execute_async_script(_SCRAPE_FOLLOW_LIST_JS, list_type, 80)
    if result.get("error") and not result.get("users"):
        raise RuntimeError(f"Error modal ({list_type}): {result['error']}")

    users = result.get("users") or []
    try:
        driver.execute_script(
            """
            const dialog = document.querySelector('div[role="dialog"]');
            if (dialog) {
                const close = dialog.querySelector('svg[aria-label="Cerrar"], svg[aria-label="Close"]');
                (close?.closest('button') || close)?.click();
            }
            """
        )
    except WebDriverException:
        pass
    time.sleep(0.5)
    return users


def fetch_users_via_api(
    driver: webdriver.Chrome, user_id: str, list_type: str
) -> list[dict[str, str]]:
    """Descarga following o followers: [{id, username}, ...]."""
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    result = driver.execute_async_script(
        _FETCH_LIST_JS,
        user_id,
        list_type,
        API_PAGE_SIZE,
        IG_APP_ID,
    )
    if result.get("error"):
        err = str(result["error"])
        if result.get("blocked") or "feedback" in err.lower():
            raise RuntimeError(f"feedback_required:{list_type}")
        raise RuntimeError(f"Error API ({list_type}): {err}")
    return result.get("users") or []


def fetch_following_or_followers(
    driver: webdriver.Chrome, username: str, user_id: str, list_type: str
) -> list[dict[str, str]]:
    """API primero; si Instagram bloquea (feedback_required), usa el modal del perfil."""
    try:
        return fetch_users_via_api(driver, user_id, list_type)
    except RuntimeError as exc:
        if "feedback_required" not in str(exc).lower():
            raise
        print(
            f"  API bloqueada para {list_type} (feedback_required). "
            "Usando lista en pantalla...",
            flush=True,
        )
        return fetch_users_via_modal(driver, username, list_type)


_UNFOLLOW_JS = """
const targetId = arguments[0];
const appId = arguments[1];
const done = arguments[arguments.length - 1];
const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
if (!csrf) {
    done({ ok: false, error: 'sin csrftoken' });
    return;
}
fetch('https://www.instagram.com/api/v1/friendships/destroy/' + targetId + '/', {
    method: 'POST',
    credentials: 'include',
    headers: {
        'X-CSRFToken': csrf,
        'X-IG-App-ID': appId,
        'X-Requested-With': 'XMLHttpRequest',
    },
})
    .then(async (r) => {
        let body = null;
        try { body = await r.json(); } catch (e) {}
        done({
            ok: r.ok && body?.status === 'ok',
            status: r.status,
            error: body?.message || (r.ok ? null : 'HTTP ' + r.status),
        });
    })
    .catch((e) => done({ ok: false, error: String(e) }));
"""


def unfollow_delay_seconds() -> float:
    raw = os.environ.get("UNFOLLOW_DELAY", str(DEFAULT_UNFOLLOW_DELAY))
    try:
        return max(2.0, float(raw))
    except ValueError:
        return DEFAULT_UNFOLLOW_DELAY


def unfollow_max_count() -> int | None:
    raw = os.environ.get("UNFOLLOW_MAX", str(DEFAULT_UNFOLLOW_MAX)).strip()
    if raw in ("0", "none", "all", "inf"):
        return None
    try:
        n = int(raw)
        return None if n <= 0 else n
    except ValueError:
        return None


def requires_confirmation() -> bool:
    """Por defecto auto-ejecuta. Usa --confirm o REQUIRE_CONFIRM=1 para pedir SI."""
    if _env_truthy("REQUIRE_CONFIRM"):
        return True
    args = {a.lstrip("-").lower().replace("_", "-") for a in sys.argv[1:]}
    return "confirm" in args


def confirm_if_required(action_label: str, count: int) -> bool:
    if not requires_confirmation():
        print(f"\n{action_label} {count} cuentas (auto).\n", flush=True)
        return True
    print(
        f"\nVas a {action_label} {count} cuentas.\n"
        "Instagram puede limitar tu cuenta si haces muchas acciones seguidas.\n",
        flush=True,
    )
    answer = input("Escribe SI (mayúsculas) para confirmar: ").strip()
    return answer == "SI"


def unfollow_one(driver: webdriver.Chrome, target_id: str) -> dict:
    driver.set_script_timeout(30)
    return driver.execute_async_script(_UNFOLLOW_JS, target_id, IG_APP_ID)


def unfollow_users(
    driver: webdriver.Chrome,
    targets: list[dict[str, str]],
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    delay = unfollow_delay_seconds()
    max_n = unfollow_max_count()
    to_process = targets[:max_n] if max_n else targets

    if dry_run:
        print(f"\n[DRY-RUN] Se dejaría de seguir a {len(to_process)} cuentas:", flush=True)
        for u in to_process:
            print(f"  @{u['username']}", flush=True)
        return 0, len(to_process)

    if not confirm_if_required("DEJAR DE SEGUIR", len(to_process)):
        print("Cancelado. No se dejó de seguir a nadie.", flush=True)
        return 0, 0

    ok_count = 0
    fail_count = 0
    print(f"\nDejando de seguir (pausa ~{delay}s entre cada uno)...\n", flush=True)

    for i, user in enumerate(to_process, 1):
        username = user["username"]
        uid = user["id"]
        try:
            result = unfollow_one(driver, uid)
        except WebDriverException as exc:
            print(f"  [{i}/{len(to_process)}] @{username} — error navegador: {exc}", flush=True)
            fail_count += 1
            time.sleep(delay * 2)
            continue

        if result.get("ok"):
            ok_count += 1
            print(f"  [{i}/{len(to_process)}] @{username} — dejado de seguir", flush=True)
        else:
            fail_count += 1
            err = result.get("error") or result.get("status")
            print(f"  [{i}/{len(to_process)}] @{username} — falló ({err})", flush=True)
            if result.get("status") in (429, 403):
                print("  Pausa larga por límite de Instagram (60s)...", flush=True)
                time.sleep(60)

        if i < len(to_process):
            time.sleep(delay)

    print(
        f"\nResumen: {ok_count} dejados de seguir, {fail_count} fallos.",
        flush=True,
    )
    if max_n and len(targets) > max_n:
        print(
            f"Quedan {len(targets) - max_n} pendientes. "
            f"Vuelve a ejecutar --unfollow o sube UNFOLLOW_MAX.",
            flush=True,
        )
    return ok_count, fail_count


# ---------------------------------------------------------------------------
# Parte 2 — Outreach Ordino
# ---------------------------------------------------------------------------


def outreach_db_path() -> Path:
    custom = os.environ.get("OUTREACH_DB_PATH", "").strip()
    if custom:
        return Path(custom)
    return Path(__file__).resolve().parent / OUTREACH_DB_NAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_outreach_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prospects (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            user_id TEXT NOT NULL,
            bio TEXT DEFAULT '',
            followers_count INTEGER DEFAULT 0,
            external_url TEXT DEFAULT '',
            score INTEGER DEFAULT 0,
            source TEXT DEFAULT '',
            pitch_type TEXT DEFAULT 'no_website',
            status TEXT DEFAULT 'discovered',
            discovered_at TEXT NOT NULL,
            followed_at TEXT,
            contacted_at TEXT,
            skip_reason TEXT,
            error TEXT
        )
        """
    )
    conn.commit()


def outreach_connect() -> sqlite3.Connection:
    path = outreach_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_outreach_db(conn)
    return conn


def score_bio(bio: str) -> int:
    text = (bio or "").lower()
    total = 0
    for keyword, points in _POSITIVE_BIO_KEYWORDS.items():
        if keyword in text:
            total += points
    for keyword, penalty in _NEGATIVE_BIO_KEYWORDS.items():
        if keyword in text:
            total += penalty
    return total


def outreach_argentina_hashtags_only() -> bool:
    """Solo hashtags con marcadores argentinos (evita #retrogaming global, etc.)."""
    raw = os.environ.get("OUTREACH_ARGENTINA_HASHTAGS_ONLY", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def outreach_filter_hashtag_posts_argentina() -> bool:
    """Solo autores de posts con ubicación o caption argentina en el hashtag."""
    raw = os.environ.get("OUTREACH_FILTER_AR_POSTS", "0").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_argentina_focused_hashtag(tag: str) -> bool:
    t = tag.lower().lstrip("#")
    return any(marker in t for marker in _AR_HASHTAG_MARKERS)


def username_suggests_foreign(username: str) -> tuple[bool, str]:
    u = username.lower().strip().lstrip("@")
    if not u:
        return False, ""
    foreign_tlds = (".cl", ".mx", ".co", ".pe", ".br", ".ec", ".uy", ".ve")
    for tld in foreign_tlds:
        if tld in u:
            return True, f"usuario{tld}"
    foreign_bits = (
        "vzla",
        "venezuela",
        "_cl",
        "chile",
        "mexico",
        "méxico",
        "colombia",
        "peru",
        "perú",
        "brasil",
        "brazil",
    )
    for bit in foreign_bits:
        if bit in u:
            return True, f"usuario_{bit}"
    return False, ""


def outreach_require_argentina() -> bool:
    """Validar bio/URL al abrir cada perfil (desactivado por defecto; usamos hashtags AR)."""
    raw = os.environ.get("OUTREACH_REQUIRE_ARGENTINA", "0").strip().lower()
    return raw not in ("0", "false", "no", "off")


def outreach_argentina_strict() -> bool:
    """Si True, omite cuentas sin señales claras de Argentina (no adivina)."""
    raw = os.environ.get("OUTREACH_ARGENTINA_STRICT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def argentina_profile_verdict(
    profile: dict[str, object], *, username: str | None = None
) -> tuple[str, str]:
    """
    Clasifica perfil: 'ar' | 'foreign' | 'unknown'.
    Usa bio, URL, teléfono de negocio y ciudad de Instagram.
    """
    uname = str(username or profile.get("username") or "")
    foreign_user, foreign_reason = username_suggests_foreign(uname)
    if foreign_user:
        return "foreign", foreign_reason

    bio = str(profile.get("bio") or "").lower()
    url = str(profile.get("external_url") or "").lower()
    city = str(profile.get("city_name") or "").lower().strip()
    phone_cc = str(profile.get("public_phone_country_code") or "").strip()
    combined = f"{bio} {url} {city}"

    foreign_hits = [k for k in _FOREIGN_BIO_KEYWORDS if k in combined]
    for tld in _FOREIGN_URL_TLDS:
        if tld in url:
            foreign_hits.append(f"url{tld}")
            break

    ar_score = 0
    ar_hits: list[str] = []

    if phone_cc == "54":
        ar_score += 3
        ar_hits.append("tel+54")
    elif phone_cc and phone_cc not in ("54", ""):
        return "foreign", f"telefono_cc_{phone_cc}"

    if city and city in _AR_CITY_NAMES:
        ar_score += 3
        ar_hits.append(f"ciudad:{city}")

    for kw in _AR_BIO_KEYWORDS:
        if kw in bio:
            ar_score += 1
            ar_hits.append(kw)
            if ar_score >= 5:
                break

    for tld in _AR_URL_TLDS:
        if tld in url:
            ar_score += 2
            ar_hits.append("url.ar")
            break

    if "wa.me/549" in url or "api.whatsapp.com/send?phone=549" in url:
        ar_score += 3
        ar_hits.append("wa549")
    elif "wa.me/54" in url or "phone=54" in url:
        ar_score += 2
        ar_hits.append("wa54")

    if foreign_hits and ar_score < 2:
        return "foreign", foreign_hits[0]

    if ar_score >= 2:
        return "ar", ",".join(ar_hits[:4])

    if foreign_hits:
        return "foreign", foreign_hits[0]

    return "unknown", "sin_señales"


def include_argentina_profile(
    profile: dict[str, object], *, username: str | None = None
) -> tuple[bool, str]:
    if not outreach_require_argentina():
        return True, "filtro_desactivado"
    verdict, detail = argentina_profile_verdict(profile, username=username)
    if verdict == "ar":
        return True, detail
    if verdict == "foreign":
        return False, detail
    if outreach_argentina_strict():
        return False, f"sin_confirmar:{detail}"
    return True, f"incierto:{detail}"


def _host_from_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or parsed.path.split("/")[0]).lower()
    return host.removeprefix("www.")


def classify_pitch_type(external_url: str | None) -> str:
    url = (external_url or "").strip()
    if not url:
        return "no_website"
    host = _host_from_url(url if "://" in url else f"https://{url}")
    if not host:
        return "no_website"
    for aggregator in _LINK_AGGREGATORS:
        if aggregator in host:
            return "no_website"
    return "has_website"


def infer_product_line(bio: str) -> str:
    """Frase para 'Vi ___ y están buenísimos' según la bio del prospect."""
    text = (bio or "").lower()
    for keywords, phrase in _PRODUCT_LINE_FROM_BIO:
        if any(kw in text for kw in keywords):
            return phrase
    return "los productos que venden"


def infer_sale_niche(bio: str) -> str:
    """Alias usado en tests; devuelve categoría corta."""
    line = infer_product_line(bio)
    if "retro" in line:
        return "productos retro"
    if "perfumes" in line:
        return "perfumes"
    if "prendas" in line:
        return "ropa"
    if "impresión 3D" in line:
        return "impresión 3D"
    if "tecnología" in line:
        return "tecnología"
    return "productos"


def build_outreach_message(
    username: str, pitch_type: str, *, bio: str = ""
) -> str:
    """Un solo mensaje comercial; pitch_type se conserva en DB pero no cambia el texto."""
    _ = pitch_type
    _ = username
    product_line = infer_product_line(bio)
    return _OUTREACH_MESSAGE_TEMPLATE.format(product_line=product_line)


def outreach_hashtags() -> list[str]:
    raw = os.environ.get("OUTREACH_HASHTAGS", DEFAULT_OUTREACH_HASHTAGS)
    tags: list[str] = []
    for part in raw.split(","):
        tag = part.strip().lstrip("#").lower()
        if tag:
            tags.append(tag)
    if outreach_argentina_hashtags_only():
        ar_tags = [t for t in tags if is_argentina_focused_hashtag(t)]
        if ar_tags:
            return ar_tags
        return [
            t.strip().lstrip("#").lower()
            for t in DEFAULT_OUTREACH_HASHTAGS.split(",")
            if t.strip()
        ]
    return tags


def follow_max_count() -> int:
    raw = os.environ.get("FOLLOW_MAX", str(DEFAULT_FOLLOW_MAX))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_FOLLOW_MAX


def discover_max_hashtags() -> int:
    raw = os.environ.get("DISCOVER_MAX_HASHTAGS", str(DEFAULT_DISCOVER_MAX_HASHTAGS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_DISCOVER_MAX_HASHTAGS


def discover_max_new() -> int:
    raw = os.environ.get("DISCOVER_MAX_NEW", str(DEFAULT_DISCOVER_MAX_NEW))
    try:
        return max(5, int(raw))
    except ValueError:
        return DEFAULT_DISCOVER_MAX_NEW


def discover_batch_size() -> int:
    raw = os.environ.get("DISCOVER_BATCH_SIZE", str(DEFAULT_DISCOVER_BATCH_SIZE))
    try:
        return max(3, min(20, int(raw)))
    except ValueError:
        return DEFAULT_DISCOVER_BATCH_SIZE


def discover_hashtag_pause_seconds() -> float:
    raw = os.environ.get("DISCOVER_HASHTAG_PAUSE", str(DEFAULT_DISCOVER_HASHTAG_PAUSE))
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_DISCOVER_HASHTAG_PAUSE


def follow_delay_seconds() -> float:
    raw = os.environ.get("FOLLOW_DELAY", str(DEFAULT_FOLLOW_DELAY))
    try:
        return max(5.0, float(raw))
    except ValueError:
        return DEFAULT_FOLLOW_DELAY


def message_max_count() -> int:
    raw = os.environ.get("MESSAGE_MAX", str(DEFAULT_MESSAGE_MAX))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MESSAGE_MAX


def message_delay_seconds() -> float:
    raw = os.environ.get("MESSAGE_DELAY", str(DEFAULT_MESSAGE_DELAY))
    try:
        return max(10.0, float(raw))
    except ValueError:
        return DEFAULT_MESSAGE_DELAY


def dm_mode() -> str:
    """profile = Mensaje en perfil (default). api = solo fetch. ui = perfil+compose. manual = exportar txt."""
    raw = os.environ.get("DM_MODE", "profile").strip().lower()
    if raw in ("api", "ui", "profile", "manual"):
        return raw
    return "profile"


def dm_use_ui() -> bool:
    return dm_mode() in ("ui", "profile") or _env_truthy("DM_USE_UI")


def messages_export_path() -> Path:
    name = os.environ.get("MESSAGE_EXPORT_FILE", "mensajes_pendientes.txt")
    return Path(name)


def outreach_min_score() -> int:
    raw = os.environ.get("OUTREACH_MIN_SCORE", str(DEFAULT_OUTREACH_MIN_SCORE))
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_OUTREACH_MIN_SCORE


def outreach_max_followers() -> int:
    raw = os.environ.get("OUTREACH_MAX_FOLLOWERS", str(DEFAULT_OUTREACH_MAX_FOLLOWERS))
    try:
        return max(100, int(raw))
    except ValueError:
        return DEFAULT_OUTREACH_MAX_FOLLOWERS


def message_min_hours_after_follow() -> int:
    raw = os.environ.get(
        "MESSAGE_MIN_HOURS_AFTER_FOLLOW", str(DEFAULT_MESSAGE_MIN_HOURS_AFTER_FOLLOW)
    )
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MESSAGE_MIN_HOURS_AFTER_FOLLOW


def message_pause_after_follow_seconds() -> float:
    raw = os.environ.get(
        "MESSAGE_PAUSE_AFTER_FOLLOW", str(DEFAULT_MESSAGE_PAUSE_AFTER_FOLLOW)
    )
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_MESSAGE_PAUSE_AFTER_FOLLOW)


def rate_limit_pause_seconds() -> int:
    raw = os.environ.get("RATE_LIMIT_PAUSE", str(DEFAULT_RATE_LIMIT_PAUSE))
    try:
        return max(30, int(raw))
    except ValueError:
        return DEFAULT_RATE_LIMIT_PAUSE


def get_existing_prospect_usernames(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT username FROM prospects").fetchall()
    return {row["username"].lower() for row in rows}


def upsert_prospect(
    conn: sqlite3.Connection,
    *,
    username: str,
    user_id: str,
    bio: str,
    followers_count: int,
    external_url: str,
    score: int,
    source: str,
    pitch_type: str,
    status: str = "discovered",
) -> None:
    now = _utc_now_iso()
    conn.execute(
        """
        INSERT INTO prospects (
            username, user_id, bio, followers_count, external_url, score,
            source, pitch_type, status, discovered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            user_id=excluded.user_id,
            bio=excluded.bio,
            followers_count=excluded.followers_count,
            external_url=excluded.external_url,
            score=excluded.score,
            source=excluded.source,
            pitch_type=excluded.pitch_type
        WHERE prospects.status = 'discovered'
        """,
        (
            username,
            user_id,
            bio,
            followers_count,
            external_url,
            score,
            source,
            pitch_type,
            status,
            now,
        ),
    )
    conn.commit()


def mark_prospect_skipped(
    conn: sqlite3.Connection, username: str, reason: str
) -> None:
    conn.execute(
        """
        UPDATE prospects SET status='skipped', skip_reason=?
        WHERE username=? COLLATE NOCASE
        """,
        (reason, username),
    )
    conn.commit()


def mark_prospect_followed(conn: sqlite3.Connection, username: str) -> None:
    conn.execute(
        """
        UPDATE prospects SET status='followed', followed_at=?, error=NULL
        WHERE username=? COLLATE NOCASE
        """,
        (_utc_now_iso(), username),
    )
    conn.commit()


def mark_prospect_contacted(conn: sqlite3.Connection, username: str) -> None:
    conn.execute(
        """
        UPDATE prospects SET status='contacted', contacted_at=?, error=NULL
        WHERE username=? COLLATE NOCASE
        """,
        (_utc_now_iso(), username),
    )
    conn.commit()


def mark_prospect_failed(
    conn: sqlite3.Connection, username: str, error: str
) -> None:
    conn.execute(
        """
        UPDATE prospects SET status='failed', error=?
        WHERE username=? COLLATE NOCASE
        """,
        (error[:500], username),
    )
    conn.commit()


def get_prospects_to_follow(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT * FROM prospects
        WHERE status='discovered'
        ORDER BY score DESC, discovered_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return list(rows)


def get_prospects_to_message(
    conn: sqlite3.Connection,
    limit: int,
    min_hours: int,
    *,
    only_usernames: set[str] | None = None,
) -> list[sqlite3.Row]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=min_hours)
    cutoff_iso = cutoff.replace(microsecond=0).isoformat()
    order = "DESC" if min_hours == 0 else "ASC"
    params: list[object] = [cutoff_iso]
    username_filter = ""
    if only_usernames:
        placeholders = ",".join("?" for _ in only_usernames)
        username_filter = f" AND LOWER(username) IN ({placeholders})"
        params.extend(sorted(only_usernames, key=str.lower))
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT * FROM prospects
        WHERE status='followed'
          AND followed_at IS NOT NULL
          AND followed_at <= ?
          {username_filter}
        ORDER BY followed_at {order}
        LIMIT ?
        """,
        params,
    ).fetchall()
    return list(rows)


def print_outreach_status() -> None:
    path = outreach_db_path()
    if not path.exists():
        print(f"No hay base de outreach ({path}). Ejecuta --discover primero.", flush=True)
        return
    conn = outreach_connect()
    try:
        counts = conn.execute(
            """
            SELECT status, COUNT(*) AS n FROM prospects GROUP BY status ORDER BY status
            """
        ).fetchall()
        print(f"\nOutreach Ordino — {path.resolve()}\n", flush=True)
        total = 0
        for row in counts:
            print(f"  {row['status']}: {row['n']}", flush=True)
            total += row["n"]
        print(f"\n  Total: {total}", flush=True)
        recent = conn.execute(
            """
            SELECT username, status, score, pitch_type, source, discovered_at
            FROM prospects ORDER BY discovered_at DESC LIMIT 10
            """
        ).fetchall()
        if recent:
            print("\nÚltimos prospects:", flush=True)
            for row in recent:
                print(
                    f"  @{row['username']} [{row['status']}] "
                    f"score={row['score']} pitch={row['pitch_type']} "
                    f"via {row['source']}",
                    flush=True,
                )
    finally:
        conn.close()


_DISCOVER_HASHTAG_JS = """
const tagName = arguments[0];
const appId = arguments[1];
const filterArPosts = !!arguments[2];
const done = arguments[arguments.length - 1];

const SKIP = new Set([
    'explore', 'direct', 'reels', 'accounts', 'p', 'stories',
    'about', 'legal', 'privacy', 'terms', 'api', 'tags', 'locations',
]);

const tagReferer =
    'https://www.instagram.com/explore/tags/' +
    encodeURIComponent(tagName) +
    '/';

const AR_SIGNALS = [
    'argentina', 'argentino', 'buenos aires', 'caba', 'cordoba', 'córdoba',
    'rosario', 'mendoza', 'la plata', 'mar del plata', 'patagonia',
    'gba', '+54', '549', 'pesos argentinos',
];

const FOREIGN_SIGNALS = [
    'méxico', 'mexico', 'cdmx', 'colombia', 'bogotá', 'bogota', 'chile',
    'santiago', 'perú', 'peru', 'lima', 'ecuador', 'venezuela', 'vzla',
    'uruguay', 'montevideo', 'brasil', 'brazil', 'são paulo', 'sao paulo',
    'españa', 'spain', 'madrid', 'usa', 'miami',
];

function apiHeaders() {
    const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
    return {
        'X-IG-App-ID': appId,
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrf,
        'X-Instagram-AJAX': '1',
        'Referer': tagReferer,
        'Accept': '*/*',
    };
}

function usernameLooksForeign(name) {
    const u = (name || '').toLowerCase();
    if (/\\.(cl|mx|co|pe|br|ec|uy|ve)(\\b|$)/.test(u)) return true;
    return ['vzla', 'venezuela', '_cl', 'chile', 'mexico', 'colombia', 'peru', 'brasil']
        .some((bit) => u.includes(bit));
}

function postText(media) {
    const locName = media?.location?.name || '';
    const locAddr = media?.location?.address || '';
    const cap = media?.caption?.text || '';
    return (locName + ' ' + locAddr + ' ' + cap).toLowerCase();
}

function postMatchesArgentina(media) {
    const text = postText(media);
    if (!text.trim()) return false;
    for (const f of FOREIGN_SIGNALS) {
        if (text.includes(f)) return false;
    }
    for (const a of AR_SIGNALS) {
        if (text.includes(a)) return true;
    }
    return false;
}

let filteredPosts = 0;

function addUser(users, seen, u, media) {
    if (!u || !u.username) return;
    const key = u.username.toLowerCase();
    if (SKIP.has(key) || seen.has(key)) return;
    if (usernameLooksForeign(u.username)) return;
    if (filterArPosts && media && !postMatchesArgentina(media)) {
        filteredPosts += 1;
        return;
    }
    seen.add(key);
    users.push({
        id: String(u.pk || u.id || ''),
        username: u.username,
        is_private: !!u.is_private,
        followers_count: u.follower_count || u.edge_followed_by?.count || 0,
        bio: u.biography || u.bio || '',
        external_url: u.external_url || '',
        post_ar: !filterArPosts || (media && postMatchesArgentina(media)),
    });
}

function addUserFromMedia(users, seen, media) {
    const m = media?.media || media;
    if (!m?.user) return;
    addUser(users, seen, m.user, m);
}

function collectFromSections(sections, users, seen) {
    for (const section of (sections || [])) {
        const layout = section.layout_content || section || {};
        for (const item of (layout.medias || [])) {
            addUserFromMedia(users, seen, item);
        }
        for (const item of (layout.one_by_two_item?.clips?.items || [])) {
            addUserFromMedia(users, seen, item);
        }
        for (const row of (layout.fill_items || [])) {
            addUserFromMedia(users, seen, row);
        }
    }
}

function collectFromMediaItems(items, users, seen) {
    for (const item of (items || [])) {
        addUserFromMedia(users, seen, item);
    }
}

function collectFromTopSerp(data, users, seen) {
    collectFromSections(data.media_grid?.sections, users, seen);
    collectFromSections(data.sections, users, seen);
    collectFromMediaItems(data.media_grid?.items, users, seen);
    collectFromMediaItems(data.ranked_items, users, seen);
}

function collectFromDom(users, seen) {
    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        const m = href.match(/^\\/([^\\/?#]+)\\/?$/);
        if (!m || SKIP.has(m[1].toLowerCase())) continue;
        if (m[1].includes('.') || m[1].length < 2) continue;
        addUser(users, seen, { username: m[1], id: '' }, null);
    }
}

(async () => {
    const users = [];
    const seen = new Set();
    const errors = [];
    const headers = apiHeaders();

    async function tryFetch(label, url, init) {
        try {
            const resp = await fetch(url, {
                credentials: 'include',
                headers: { ...headers, ...(init?.headers || {}) },
                ...init,
            });
            if (!resp.ok) {
                errors.push(label + ': HTTP ' + resp.status);
                return null;
            }
            return await resp.json();
        } catch (e) {
            errors.push(label + ': ' + String(e));
            return null;
        }
    }

    const query = encodeURIComponent('#' + tagName);
    const topSerp = await tryFetch(
        'top_serp',
        'https://www.instagram.com/api/v1/fbsearch/web/top_serp/?query=' +
            query + '&search_surface=top_serp',
        { method: 'GET' }
    );
    if (topSerp) collectFromTopSerp(topSerp, users, seen);

    const tagInfo = await tryFetch(
        'web_info',
        'https://www.instagram.com/api/v1/tags/web_info/?tag_name=' +
            encodeURIComponent(tagName),
        { method: 'GET' }
    );
    const tagId = tagInfo?.data?.hashtag?.id || tagInfo?.data?.hashtag?.pk;
    if (tagId) {
        const sections = await tryFetch(
            'sections',
            'https://www.instagram.com/api/v1/tags/' + tagId + '/sections/',
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'tab=recent',
            }
        );
        if (sections) collectFromSections(sections.sections, users, seen);
    }

    if (users.length === 0) {
        const sectionsByName = await tryFetch(
            'sections_name',
            'https://www.instagram.com/api/v1/tags/' +
                encodeURIComponent(tagName) + '/sections/',
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'tab=recent',
            }
        );
        if (sectionsByName) collectFromSections(sectionsByName.sections, users, seen);
    }

    if (users.length === 0 && !filterArPosts) {
        collectFromDom(users, seen);
    }

    if (users.length === 0) {
        done({
            users: [],
            error: errors.length ? errors.join(' | ') : 'sin resultados',
        });
        return;
    }
    done({ users, error: null, warnings: errors, filtered_posts: filteredPosts });
})();
"""


_USER_PROFILE_JS = """
const username = arguments[0];
const appId = arguments[1];
const done = arguments[arguments.length - 1];
const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

fetch(
    'https://www.instagram.com/api/v1/users/web_profile_info/?username=' +
        encodeURIComponent(username),
    {
        credentials: 'include',
        headers: {
            'X-IG-App-ID': appId,
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrf,
            'X-Instagram-AJAX': '1',
            'Referer': 'https://www.instagram.com/' + encodeURIComponent(username) + '/',
            'Accept': '*/*',
        },
    }
)
    .then(async (r) => {
        const raw = await r.text();
        let d;
        try { d = JSON.parse(raw); } catch (e) {
            done({ user: null, error: 'JSON inválido' });
            return;
        }
        return d;
    })
    .then((d) => {
        if (!d) return;
        const u = d?.data?.user;
        if (!u) {
            done({ user: null, error: 'usuario no encontrado' });
            return;
        }
        let cityName = '';
        let streetAddress = '';
        try {
            const addr = u.business_address_json
                ? JSON.parse(u.business_address_json)
                : null;
            if (addr) {
                cityName = addr.city_name || '';
                streetAddress = addr.street_address || '';
            }
        } catch (e) {}
        done({
            user: {
                id: String(u.id || u.pk || ''),
                username: u.username,
                bio: u.biography || '',
                followers_count: u.edge_followed_by?.count || 0,
                external_url: u.external_url || u.external_url_linkshimmed || '',
                is_private: !!u.is_private,
                public_phone_country_code: String(u.public_phone_country_code || ''),
                city_name: cityName,
                business_street: streetAddress,
            },
            error: null,
        });
    })
    .catch((e) => done({ user: null, error: String(e) }));
"""


_BATCH_PROFILES_JS = """
const usernames = arguments[0];
const appId = arguments[1];
const done = arguments[arguments.length - 1];
const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

function headersFor(username) {
    const u = encodeURIComponent(username);
    return {
        'X-IG-App-ID': appId,
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrf,
        'X-Instagram-AJAX': '1',
        'Referer': 'https://www.instagram.com/' + u + '/',
        'Accept': '*/*',
    };
}

async function fetchOne(username) {
    try {
        const resp = await fetch(
            'https://www.instagram.com/api/v1/users/web_profile_info/?username=' +
                encodeURIComponent(username),
            { credentials: 'include', headers: headersFor(username) }
        );
        const raw = await resp.text();
        let d;
        try { d = JSON.parse(raw); } catch (e) {
            return { username, user: null, error: 'json' };
        }
        const u = d?.data?.user;
        if (!u) {
            return { username, user: null, error: 'not_found' };
        }
        let cityName = '';
        try {
            const addr = u.business_address_json
                ? JSON.parse(u.business_address_json)
                : null;
            if (addr) cityName = addr.city_name || '';
        } catch (e) {}
        return {
            username,
            user: {
                id: String(u.id || u.pk || ''),
                username: u.username,
                bio: u.biography || '',
                followers_count: u.edge_followed_by?.count || 0,
                external_url: u.external_url || u.external_url_linkshimmed || '',
                is_private: !!u.is_private,
                public_phone_country_code: String(u.public_phone_country_code || ''),
                city_name: cityName,
                business_street: '',
            },
            error: null,
        };
    } catch (e) {
        return { username, user: null, error: String(e) };
    }
}

(async () => {
    const profiles = await Promise.all(usernames.map((u) => fetchOne(u)));
    done({ profiles });
})();
"""


_FOLLOW_JS = """
const targetId = arguments[0];
const appId = arguments[1];
const done = arguments[arguments.length - 1];
const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
if (!csrf) {
    done({ ok: false, error: 'sin csrftoken' });
    return;
}
fetch('https://www.instagram.com/api/v1/friendships/create/' + targetId + '/', {
    method: 'POST',
    credentials: 'include',
    headers: {
        'X-CSRFToken': csrf,
        'X-IG-App-ID': appId,
        'X-Requested-With': 'XMLHttpRequest',
    },
})
    .then(async (r) => {
        let body = null;
        try { body = await r.json(); } catch (e) {}
        done({
            ok: r.ok && body?.status === 'ok',
            status: r.status,
            error: body?.message || (r.ok ? null : 'HTTP ' + r.status),
        });
    })
    .catch((e) => done({ ok: false, error: String(e) }));
"""


_CHECK_THREAD_JS = """
const userId = arguments[0];
const appId = arguments[1];
const done = arguments[arguments.length - 1];
const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

fetch(
    'https://www.instagram.com/api/v1/direct_v2/threads/get_by_participants/?recipient_users=' +
        encodeURIComponent(JSON.stringify([String(userId)])),
    {
        credentials: 'include',
        headers: {
            'X-IG-App-ID': appId,
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrf,
            'X-Instagram-AJAX': '1',
            'Referer': window.location.href,
        },
    }
)
    .then(async (r) => {
        if (!r.ok) {
            done({ exists: false, error: 'HTTP ' + r.status, checked: false });
            return;
        }
        const d = await r.json();
        const thread = d.thread || d;
        const exists = !!(thread && (thread.thread_id || thread.thread_v2_id));
        done({ exists, error: null, checked: true });
    })
    .catch((e) => done({ exists: false, error: String(e), checked: false }));
"""


_SEND_DM_JS = """
const userId = arguments[0];
const text = arguments[1];
const appId = arguments[2];
const done = arguments[arguments.length - 1];

function cookie(name) {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
}

const csrf = cookie('csrftoken');
if (!csrf) {
    done({ ok: false, error: 'sin csrftoken (abrí instagram.com con sesión)' });
    return;
}

const igDid = cookie('ig_did') || cookie('mid') || ('web-' + Date.now());
const deviceId = 'android-' + String(igDid).replace(/[^a-zA-Z0-9]/g, '').slice(0, 16);
const uuid = cookie('ig_did') || deviceId;
const referer = 'https://www.instagram.com/direct/inbox/';

function dmHeaders() {
    return {
        'X-CSRFToken': csrf,
        'X-IG-App-ID': appId,
        'X-Requested-With': 'XMLHttpRequest',
        'X-Instagram-AJAX': '1',
        'Referer': referer,
        'Accept': '*/*',
    };
}

function token() {
    return String(Date.now()) + '_' + Math.random().toString(36).slice(2, 10);
}

async function postForm(url, fields) {
    const body = new URLSearchParams();
    for (const [k, v] of Object.entries(fields)) body.set(k, String(v));
    const resp = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
            ...dmHeaders(),
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: body.toString(),
    });
    const raw = await resp.text();
    let respBody = null;
    try { respBody = JSON.parse(raw); } catch (e) {
        return {
            ok: false,
            status: resp.status,
            body: null,
            raw: raw.slice(0, 160),
            url,
        };
    }
    const success = resp.ok && (respBody?.status === 'ok' || respBody?.payload);
    return { ok: success, status: resp.status, body: respBody, raw: null, url };
}

function broadcastFields(recipientUsersJson) {
    const t = token();
    return {
        action: 'send_item',
        text,
        client_context: t,
        mutation_token: t,
        offline_threading_id: t,
        send_attribution: 'message_button',
        recipient_users: recipientUsersJson,
        mentioned_user_ids: '[]',
        csrftoken: csrf,
        _csrftoken: csrf,
        _uuid: uuid,
        device_id: deviceId,
    };
}

const broadcastUrls = [
    'https://www.instagram.com/api/v1/direct_v2/threads/broadcast/text/',
    'https://i.instagram.com/api/v1/direct_v2/threads/broadcast/text/',
];

const recipientVariants = [
    JSON.stringify([[String(userId)]]),
    JSON.stringify([String(userId)]),
];

(async () => {
    const errors = [];
    try {
        for (const url of broadcastUrls) {
            for (const recipient of recipientVariants) {
                const result = await postForm(url, broadcastFields(recipient));
                if (result.ok) {
                    done({
                        ok: true,
                        status: result.status,
                        method: 'api_broadcast',
                        url: result.url,
                    });
                    return;
                }
                errors.push(
                    (result.url || url) + ': ' +
                    (result.body?.message || result.raw || ('HTTP ' + result.status))
                );
            }
        }

        const threadResp = await fetch(
            'https://www.instagram.com/api/v1/direct_v2/threads/get_by_participants/?recipient_users=' +
                encodeURIComponent(JSON.stringify([String(userId)])),
            { credentials: 'include', headers: dmHeaders() }
        );
        if (threadResp.ok) {
            const threadData = await threadResp.json();
            const threadId = threadData?.thread?.thread_id || threadData?.thread?.thread_v2_id;
            if (threadId) {
                const t = token();
                const threadFields = {
                    action: 'send_item',
                    text,
                    client_context: t,
                    mutation_token: t,
                    csrftoken: csrf,
                    _csrftoken: csrf,
                    _uuid: uuid,
                    device_id: deviceId,
                };
                const result = await postForm(
                    'https://www.instagram.com/api/v1/direct_v2/threads/' +
                        threadId + '/items/',
                    threadFields
                );
                if (result.ok) {
                    done({ ok: true, status: result.status, method: 'api_thread' });
                    return;
                }
                errors.push('thread_items: ' + (result.body?.message || result.raw));
            }
        }

        done({
            ok: false,
            status: errors.length ? 0 : 0,
            error: errors.slice(0, 3).join(' | ') || 'broadcast falló',
            method: 'api',
        });
    } catch (e) {
        done({ ok: false, error: String(e), method: 'api' });
    }
})();
"""


def ensure_instagram_api_context(driver: webdriver.Chrome) -> None:
    """Sesión en instagram.com sin abrir cada hashtag en el navegador."""
    try:
        url = driver.current_url.lower()
    except WebDriverException:
        url = ""
    if "instagram.com" in url and "login" not in url:
        return
    driver.get(INSTAGRAM_URL)
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(1)


def go_to_hashtag_for_discovery(driver: webdriver.Chrome, hashtag: str) -> None:
    """Fallback: abre hashtag si la API sin navegar falla."""
    from urllib.parse import quote

    tag = hashtag.strip().lstrip("#")
    url = f"{INSTAGRAM_URL}explore/tags/{quote(tag)}/"
    driver.get(url)
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(1)


def _run_discover_hashtag_js(
    driver: webdriver.Chrome, hashtag: str
) -> dict[str, object]:
    driver.set_script_timeout(120)
    filter_posts = outreach_filter_hashtag_posts_argentina()
    return driver.execute_async_script(
        _DISCOVER_HASHTAG_JS, hashtag, IG_APP_ID, filter_posts
    )


def fetch_hashtag_users(
    driver: webdriver.Chrome, hashtag: str
) -> list[dict[str, object]]:
    ensure_instagram_api_context(driver)
    result = _run_discover_hashtag_js(driver, hashtag)
    if result.get("error"):
        go_to_hashtag_for_discovery(driver, hashtag)
        result = _run_discover_hashtag_js(driver, hashtag)
    for warning in result.get("warnings") or []:
        print(f"  Aviso API: {warning}", flush=True)
    filtered_posts = int(result.get("filtered_posts") or 0)
    if outreach_filter_hashtag_posts_argentina() and filtered_posts:
        print(
            f"  {filtered_posts} posts sin señal AR (omitidos)",
            flush=True,
        )
    if result.get("error"):
        raise RuntimeError(f"Hashtag #{hashtag}: {result['error']}")
    return result.get("users") or []


def fetch_user_profiles_batch(
    driver: webdriver.Chrome, usernames: list[str]
) -> dict[str, dict[str, object]]:
    """Varios perfiles en un solo round-trip (fetch paralelo en el navegador)."""
    names = [u.strip().lstrip("@") for u in usernames if u and u.strip()]
    if not names:
        return {}
    ensure_instagram_api_context(driver)
    driver.set_script_timeout(max(90, 15 * len(names)))
    result = driver.execute_async_script(_BATCH_PROFILES_JS, names, IG_APP_ID)
    out: dict[str, dict[str, object]] = {}
    for item in result.get("profiles") or []:
        user = item.get("user")
        if not user or not user.get("username"):
            continue
        out[str(user["username"]).lower()] = user
    return out


def needs_profile_api_fetch(raw: dict[str, object]) -> bool:
    uid = str(raw.get("id") or "")
    if not uid.isdigit() or int(uid) <= 0:
        return True
    bio = str(raw.get("bio") or "").strip()
    if outreach_min_score() > 0 and not bio:
        return True
    if not bio and not str(raw.get("external_url") or "").strip():
        return True
    return False


def merge_hashtag_user_profile(
    raw: dict[str, object], profile: dict[str, object] | None
) -> dict[str, object]:
    p = profile or {}
    return {
        "id": str(p.get("id") or raw.get("id") or ""),
        "username": str(p.get("username") or raw.get("username") or ""),
        "bio": str(p.get("bio") or raw.get("bio") or ""),
        "followers_count": int(
            p.get("followers_count") or raw.get("followers_count") or 0
        ),
        "external_url": str(p.get("external_url") or raw.get("external_url") or ""),
        "is_private": bool(
            p.get("is_private") if profile else raw.get("is_private")
        ),
    }


def fetch_user_profile(
    driver: webdriver.Chrome, username: str
) -> dict[str, object] | None:
    batch = fetch_user_profiles_batch(driver, [username])
    key = username.strip().lstrip("@").lower()
    if key in batch:
        return batch[key]
    try:
        uid = get_instagram_user_id(driver, username, quiet=True)
        return {
            "id": uid,
            "username": username.strip().lstrip("@"),
            "bio": "",
            "followers_count": 0,
            "external_url": "",
            "is_private": False,
            "public_phone_country_code": "",
            "city_name": "",
            "business_street": "",
        }
    except RuntimeError:
        return None


def follow_one(driver: webdriver.Chrome, target_id: str) -> dict:
    driver.set_script_timeout(30)
    return driver.execute_async_script(_FOLLOW_JS, target_id, IG_APP_ID)


def go_to_direct_inbox(driver: webdriver.Chrome) -> None:
    url = f"{INSTAGRAM_URL}direct/inbox/"
    driver.get(url)
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(2)


_GET_THREAD_ID_JS = """
const userId = arguments[0];
const appId = arguments[1];
const done = arguments[arguments.length - 1];
const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

fetch(
    'https://www.instagram.com/api/v1/direct_v2/threads/get_by_participants/?recipient_users=' +
        encodeURIComponent(JSON.stringify([String(userId)])),
    {
        credentials: 'include',
        headers: {
            'X-IG-App-ID': appId,
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrf,
            'X-Instagram-AJAX': '1',
            'Referer': 'https://www.instagram.com/direct/inbox/',
        },
    }
)
    .then(async (r) => {
        if (!r.ok) {
            done({ thread_id: null, error: 'HTTP ' + r.status });
            return;
        }
        const d = await r.json();
        const thread = d.thread || d;
        const threadId = thread?.thread_id || thread?.thread_v2_id;
        done({ thread_id: threadId ? String(threadId) : null, error: null });
    })
    .catch((e) => done({ thread_id: null, error: String(e) }));
"""


def direct_inbox_accessible(driver: webdriver.Chrome) -> bool:
    """True si /direct/inbox carga sin mandar a login.php."""
    try:
        driver.get(f"{INSTAGRAM_URL}direct/inbox/")
        WebDriverWait(driver, WAIT_SECONDS).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(2.5)
        url = driver.current_url.lower()
        if "login" in url:
            return False
        body = (driver.page_source or "").lower()
        if "no está disponible" in body or "not available" in body:
            return False
        return "/direct/" in url
    except WebDriverException:
        return False


def get_direct_thread_id(driver: webdriver.Chrome, user_id: str) -> str | None:
    if not direct_inbox_accessible(driver):
        return None
    driver.set_script_timeout(30)
    result = driver.execute_async_script(_GET_THREAD_ID_JS, user_id, IG_APP_ID)
    return result.get("thread_id") or None


def _direct_composer_present(driver: webdriver.Chrome) -> bool:
    return _find_direct_composer_element(driver) is not None


def _wait_for_direct_composer(driver: webdriver.Chrome, timeout: int = 25) -> bool:
    try:
        WebDriverWait(driver, timeout).until(lambda d: _direct_composer_present(d))
        return True
    except TimeoutException:
        return False


def _find_compose_search_input(driver: webdriver.Chrome):
    return driver.execute_script(
        """
        const path = (location.pathname || '').toLowerCase();
        const pick = (inp) => {
            if (!inp || !inp.offsetParent) return false;
            const r = inp.getBoundingClientRect();
            if (r.width < 40) return false;
            if (path.includes('/direct/new')) {
                if (inp.name === 'queryBox') return true;
                return r.left > 280;
            }
            const dialog = inp.closest('[role="dialog"]');
            return !!dialog;
        };
        for (const inp of document.querySelectorAll(
            'input[name="queryBox"], input[type="text"], input[type="search"]'
        )) {
            if (pick(inp)) return inp;
        }
        return null;
        """
    )


def open_direct_chat_with_user(
    driver: webdriver.Chrome, username: str, user_id: str | None = None
) -> bool:
    """Abre el panel de chat (conversación activa a la derecha)."""
    uname = username.strip().lstrip("@")

    if user_id:
        thread_id = get_direct_thread_id(driver, user_id)
        if thread_id:
            driver.get(f"{INSTAGRAM_URL}direct/t/{thread_id}/")
            WebDriverWait(driver, WAIT_SECONDS).until(
                lambda d: "/direct/t/" in d.current_url.lower()
            )
            time.sleep(2)
            dismiss_instagram_popups(driver)
            if _wait_for_direct_composer(driver, 20):
                return True

    driver.get(f"{INSTAGRAM_URL}direct/new/")
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(2.5)
    dismiss_instagram_popups(driver)

    if "/direct/new" not in driver.current_url.lower():
        if not _click_new_message_button(driver):
            driver.get(f"{INSTAGRAM_URL}direct/new/")
            time.sleep(2)

    search_input = _find_compose_search_input(driver)
    if not search_input:
        return False

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'}); arguments[0].focus(); arguments[0].click();",
        search_input,
    )
    time.sleep(0.3)
    try:
        search_input.clear()
    except WebDriverException:
        pass
    search_input.send_keys(uname)
    time.sleep(2.5)

    if not _select_user_in_compose(driver, uname):
        return False

    _click_compose_chat_button(driver)
    time.sleep(2)

    try:
        WebDriverWait(driver, WAIT_SECONDS).until(
            lambda d: "/direct/t/" in d.current_url.lower()
            or _direct_composer_present(d)
        )
    except TimeoutException:
        pass

    time.sleep(1.5)
    return _wait_for_direct_composer(driver, 20)


def thread_exists_with_user(driver: webdriver.Chrome, user_id: str) -> bool | None:
    """True=existe, False=no, None=no se pudo verificar."""
    driver.set_script_timeout(30)
    result = driver.execute_async_script(_CHECK_THREAD_JS, user_id, IG_APP_ID)
    if not result.get("checked"):
        return None
    if result.get("error"):
        return None
    return bool(result.get("exists"))


def _click_profile_message_button(driver: webdriver.Chrome) -> bool:
    xpaths = (
        "//a[contains(@href,'/direct/t/')]",
        "//div[@role='button'][normalize-space()='Mensaje']",
        "//div[@role='button'][normalize-space()='Message']",
        "//a[normalize-space()='Mensaje']",
        "//a[normalize-space()='Message']",
    )
    for xpath in xpaths:
        try:
            el = WebDriverWait(driver, 6).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el
            )
            time.sleep(0.2)
            try:
                el.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", el)
            return True
        except TimeoutException:
            continue

    return bool(
        driver.execute_script(
            """
            const labels = ['message', 'mensaje', 'enviar mensaje'];
            const matchText = (t) => {
                t = (t || '').trim().toLowerCase();
                return labels.some((l) => t === l || t.startsWith(l + ' '));
            };
            for (const a of document.querySelectorAll('a[href*="/direct/"]')) {
                const href = a.getAttribute('href') || '';
                if (!href.includes('/direct/t/') && !href.includes('/direct/new')) continue;
                const t = (a.textContent || a.getAttribute('aria-label') || '').toLowerCase();
                if (matchText(t) || href.includes('/direct/t/')) {
                    a.scrollIntoView({ block: 'center' });
                    a.click();
                    return true;
                }
            }
            for (const el of document.querySelectorAll(
                'header div[role="button"], header button, main div[role="button"]'
            )) {
                const t = (el.textContent || el.getAttribute('aria-label') || '');
                if (matchText(t)) {
                    el.scrollIntoView({ block: 'center' });
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
    )


def _click_new_message_button(driver: webdriver.Chrome) -> bool:
    selectors = [
        'svg[aria-label="New message"]',
        'svg[aria-label="Nuevo mensaje"]',
        'a[href="/direct/new/"]',
        'a[href*="/direct/new"]',
    ]
    for selector in selectors:
        try:
            el = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            if selector.startswith("svg"):
                driver.execute_script(
                    "arguments[0].closest('[role=button], a, button')?.click() || arguments[0].click();",
                    el,
                )
            else:
                el.click()
            return True
        except TimeoutException:
            continue
    return bool(
        driver.execute_script(
            """
            for (const el of document.querySelectorAll('[aria-label]')) {
                const l = (el.getAttribute('aria-label') || '').toLowerCase();
                if (l.includes('new message') || l.includes('nuevo mensaje')) {
                    (el.closest('[role=button]') || el).click();
                    return true;
                }
            }
            return false;
            """
        )
    )


def _select_user_in_compose(driver: webdriver.Chrome, username: str) -> bool:
    time.sleep(2.5)
    uname = username.lower()
    if driver.execute_script(
        """
        const user = arguments[0];
        const match = (el) => {
            const t = (el.textContent || el.getAttribute('aria-label') || '').toLowerCase();
            return t.includes(user);
        };
        for (const el of document.querySelectorAll(
            'div[role="dialog"] div[role="button"], div[role="dialog"] label, ' +
            'div[role="listbox"] div[role="button"], div[role="option"], ' +
            'div[role="button"], button'
        )) {
            if (!match(el)) continue;
            el.scrollIntoView({ block: 'center' });
            el.click();
            return true;
        }
        for (const img of document.querySelectorAll('img[alt]')) {
            const alt = (img.getAttribute('alt') || '').toLowerCase();
            if (!alt.includes(user)) continue;
            const row = img.closest('div[role="button"], label, li, div');
            if (row) {
                row.click();
                return true;
            }
        }
        return false;
        """,
        uname,
    ):
        return True
    try:
        WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//span[contains(text(), '{username}')]")
            )
        ).click()
        return True
    except TimeoutException:
        return False


def _click_compose_chat_button(driver: webdriver.Chrome) -> bool:
    time.sleep(1)
    return bool(
        driver.execute_script(
            """
            const labels = ['chat', 'next', 'siguiente', 'chatear', 'listo'];
            for (const el of document.querySelectorAll('div[role="button"], button')) {
                const t = (el.textContent || el.getAttribute('aria-label') || '')
                    .trim().toLowerCase();
                if (labels.some((l) => t === l || t.includes(l))) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
    )


def _is_login_wall(driver: webdriver.Chrome) -> bool:
    try:
        url = driver.current_url.lower()
    except WebDriverException:
        return True
    if "/accounts/login" in url or "login.php" in url:
        return True
    try:
        body = (driver.page_source or "").lower()
    except WebDriverException:
        return True
    if "profile no está disponible" in body or "profile isn't available" in body:
        return True
    if "iniciar sesión" in body and _visible_login_form(driver):
        return True
    return False


def _close_dm_overlay(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        """
        for (const label of ['Cerrar', 'Close']) {
            for (const svg of document.querySelectorAll('svg[aria-label]')) {
                if ((svg.getAttribute('aria-label') || '') !== label) continue;
                const btn = svg.closest('button, div[role="button"]');
                if (btn) { btn.click(); return true; }
            }
        }
        return false;
        """
    )
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).send_keys(Keys.ESCAPE).perform()
    except WebDriverException:
        pass
    time.sleep(0.8)


def stabilize_session_after_dm(driver: webdriver.Chrome) -> None:
    """Cierra chat flotante y vuelve al inicio para no romper el siguiente DM."""
    _close_dm_overlay(driver)
    dismiss_instagram_popups(driver)
    try:
        driver.get(INSTAGRAM_URL)
        WebDriverWait(driver, WAIT_SECONDS).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(2)
        dismiss_onetap_prompt(driver)
        dismiss_instagram_popups(driver)
    except WebDriverException:
        pass


def ensure_session_for_next_dm(driver: webdriver.Chrome) -> bool:
    """Antes de cada DM: recupera sesión si Instagram mostró login."""
    if not _is_login_wall(driver) and session_is_active(driver):
        return True
    print("  Sesión perdida; recuperando antes del siguiente DM...", flush=True)
    stabilize_session_after_dm(driver)
    if _is_saved_profile_login_screen(driver):
        expected = instagram_login_username()
        if expected and try_saved_profile_login(driver, expected):
            stabilize_session_after_dm(driver)
            return session_is_active(driver)
    if _is_login_wall(driver) or not session_is_active(driver):
        try:
            ensure_logged_in(driver)
        except RuntimeError:
            return False
    stabilize_session_after_dm(driver)
    return session_is_active(driver) and not _is_login_wall(driver)


def send_dm_ui_profile(driver: webdriver.Chrome, username: str, message: str) -> dict:
    try:
        if not ensure_session_for_next_dm(driver):
            return {"ok": False, "error": "sesion_perdida", "method": "ui_profile"}

        go_to_profile_by_username(driver, username)
        time.sleep(2.5)
        if _is_login_wall(driver):
            return {"ok": False, "error": "login_en_perfil", "method": "ui_profile"}
        dismiss_instagram_popups(driver)
        if not _click_profile_message_button(driver):
            return {"ok": False, "error": "boton_mensaje_no_encontrado", "method": "ui_profile"}

        try:
            WebDriverWait(driver, 20).until(lambda d: _direct_composer_present(d))
        except TimeoutException:
            pass
        time.sleep(2)

        if not _wait_for_direct_composer(driver, 15):
            return {"ok": False, "error": "campo_mensaje_no_encontrado", "method": "ui_profile"}
        if not _fill_direct_composer(driver, message):
            return {"ok": False, "error": "texto_no_escrito", "method": "ui_profile"}
        time.sleep(0.5)
        if not _submit_direct_composer(driver, message):
            time.sleep(2)
            if not _dm_send_succeeded(driver, message):
                return {"ok": False, "error": "no_enviado_verificado", "method": "ui_profile"}
        return {"ok": True, "method": "ui_profile"}
    except (TimeoutException, WebDriverException) as exc:
        return {"ok": False, "error": str(exc), "method": "ui_profile"}
    finally:
        stabilize_session_after_dm(driver)


def send_dm_ui_compose(
    driver: webdriver.Chrome,
    username: str,
    message: str,
    *,
    user_id: str | None = None,
) -> dict:
    try:
        if not open_direct_chat_with_user(driver, username, user_id):
            return {"ok": False, "error": "chat_no_abierto", "method": "ui_compose"}
        if not _fill_direct_composer(driver, message):
            return {"ok": False, "error": "texto_no_escrito", "method": "ui_compose"}
        time.sleep(0.5)
        if not _submit_direct_composer(driver, message):
            time.sleep(2)
            if not _dm_send_succeeded(driver, message):
                return {"ok": False, "error": "no_enviado_verificado", "method": "ui_compose"}
        return {"ok": True, "method": "ui_compose"}
    except (TimeoutException, WebDriverException) as exc:
        return {"ok": False, "error": str(exc), "method": "ui_compose"}


def send_dm_ui(
    driver: webdriver.Chrome,
    username: str,
    message: str,
    *,
    user_id: str | None = None,
    allow_inbox_compose: bool = False,
) -> dict:
    """Perfil (Mensaje). No abre inbox entre mensajes (rompe la sesión)."""
    result = send_dm_ui_profile(driver, username, message)
    if result.get("ok") or not allow_inbox_compose:
        return result
    if direct_inbox_accessible(driver):
        try:
            result = send_dm_ui_compose(driver, username, message, user_id=user_id)
        finally:
            stabilize_session_after_dm(driver)
        return result
    return result


def mark_prospect_message_error(
    conn: sqlite3.Connection, username: str, error: str
) -> None:
    """Mantiene status=followed para poder reintentar el DM."""
    conn.execute(
        """
        UPDATE prospects SET error=?
        WHERE username=? COLLATE NOCASE AND status IN ('followed', 'failed')
        """,
        (error[:500], username),
    )
    conn.execute(
        """
        UPDATE prospects SET status='followed'
        WHERE username=? COLLATE NOCASE AND status='failed' AND followed_at IS NOT NULL
        """,
        (username,),
    )
    conn.commit()


_FIND_MESSAGE_COMPOSER_JS = """
function findMessageComposer() {
    let best = null;
    let bestScore = -1;
    for (const el of document.querySelectorAll(
        'div[contenteditable="true"][role="textbox"], div[data-lexical-editor="true"]'
    )) {
        if (!el || !el.offsetParent) continue;
        const label = (el.getAttribute('aria-label') || '').toLowerCase();
        const lexical = el.getAttribute('data-lexical-editor') === 'true';
        const rect = el.getBoundingClientRect();
        if (rect.width < 20 || rect.height < 10) continue;
        let score = 0;
        if (lexical) score += 5;
        if (label.includes('enviar mensaje') || label.includes('send message')) score += 8;
        if (label.includes('mensaje') || label.includes('message')) score += 4;
        if (rect.bottom > window.innerHeight * 0.5) score += 3;
        if (el.closest('[role="dialog"]')) score += 2;
        const text = (el.innerText || '').trim();
        if (text.includes('enviar mensaje') && text.length < 30) score -= 5;
        if (score > bestScore) {
            bestScore = score;
            best = el;
        }
    }
    return best;
}
"""


def _find_direct_composer_element(driver: webdriver.Chrome):
    return driver.execute_script(_FIND_MESSAGE_COMPOSER_JS + "return findMessageComposer();")


def _composer_has_text(driver: webdriver.Chrome, message: str) -> bool:
    snippet = message.strip()[:50].lower()
    if len(snippet) < 5:
        return False
    return bool(
        driver.execute_script(
            """
            const expected = arguments[0];
            function findMessageComposer() {
                let best = null;
                let bestScore = -1;
                for (const el of document.querySelectorAll(
                    'div[contenteditable="true"][role="textbox"], div[data-lexical-editor="true"]'
                )) {
                    if (!el || !el.offsetParent) continue;
                    const label = (el.getAttribute('aria-label') || '').toLowerCase();
                    const lexical = el.getAttribute('data-lexical-editor') === 'true';
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 20 || rect.height < 10) continue;
                    let score = 0;
                    if (lexical) score += 5;
                    if (label.includes('enviar mensaje') || label.includes('send message')) score += 8;
                    if (label.includes('mensaje') || label.includes('message')) score += 4;
                    if (rect.bottom > window.innerHeight * 0.5) score += 3;
                    if (score > bestScore) { bestScore = score; best = el; }
                }
                return best;
            }
            const el = findMessageComposer();
            if (!el) return false;
            const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            if (!t || t.length < 4) return false;
            return t.includes(expected) || expected.includes(t.slice(0, 30));
            """,
            snippet,
        )
    )


def _fill_direct_composer(driver: webdriver.Chrome, message: str) -> bool:
    if not _wait_for_direct_composer(driver, 15):
        return False

    field = _find_direct_composer_element(driver)
    if not field:
        return False

    for _ in range(3):
        try:
            driver.execute_script(
                """
                const el = arguments[0];
                const text = arguments[1];
                el.scrollIntoView({ block: 'center' });
                el.focus();
                el.click();
                """,
                field,
                message,
            )
            time.sleep(0.3)
            try:
                ActionChains(driver).click(field).key_down(Keys.CONTROL).send_keys("a").key_up(
                    Keys.CONTROL
                ).send_keys(Keys.BACKSPACE).perform()
            except WebDriverException:
                pass
            time.sleep(0.2)

            filled = driver.execute_script(
                """
                const el = arguments[0];
                const text = arguments[1];
                el.focus();
                if (document.execCommand) {
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, text);
                }
                el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));
                return true;
                """,
                field,
                message,
            )
            if not filled:
                ActionChains(driver).click(field).send_keys(message).perform()

            time.sleep(0.5)
            if _composer_has_text(driver, message):
                return True
        except WebDriverException:
            time.sleep(0.4)
    return False


def _click_send_message_button(driver: webdriver.Chrome) -> bool:
    return bool(
        driver.execute_script(
            """
            const matchSend = (label) => {
                label = (label || '').trim().toLowerCase();
                return label === 'send' || label === 'enviar';
            };
            for (const svg of document.querySelectorAll('svg[aria-label]')) {
                const label = svg.getAttribute('aria-label') || '';
                if (!matchSend(label)) continue;
                const btn = svg.closest('div[role="button"]') || svg.parentElement;
                if (btn && btn.getAttribute('aria-disabled') !== 'true') {
                    btn.click();
                    return true;
                }
            }
            for (const el of document.querySelectorAll('div[role="button"], button')) {
                const label = (el.getAttribute('aria-label') || el.textContent || '')
                    .trim().toLowerCase();
                if (matchSend(label)) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
    )


def _page_contains_text(driver: webdriver.Chrome, needle: str) -> bool:
    n = needle.strip().lower()
    if len(n) < 3:
        return False
    return bool(
        driver.execute_script(
            """
            const needle = arguments[0];
            const roots = document.querySelectorAll(
                '[role="dialog"], [role="main"], main, body'
            );
            for (const root of roots) {
                const t = (root.innerText || '').toLowerCase();
                if (t.includes(needle)) return true;
            }
            return false;
            """,
            n,
        )
    )


def _verify_message_in_chat(driver: webdriver.Chrome, message: str) -> bool:
    snippet = message.strip()[:60].lower()
    words = [w for w in snippet.split() if len(w) > 4][:3]
    check = " ".join(words) if words else snippet[:25]
    if len(check) < 5:
        check = snippet[:25]
    if _page_contains_text(driver, check):
        return True
    for word in words:
        if len(word) > 4 and _page_contains_text(driver, word):
            return True
    return False


def _dm_send_succeeded(driver: webdriver.Chrome, message: str) -> bool:
    """True si el DM parece enviado (composer vacío, texto en chat o marca Ordino)."""
    if not _composer_has_text(driver, message):
        return True
    if _verify_message_in_chat(driver, message):
        return True
    for needle in _DM_SUCCESS_NEEDLES:
        if _page_contains_text(driver, needle):
            return True
    return False


def _submit_direct_composer(driver: webdriver.Chrome, message: str) -> bool:
    if not _composer_has_text(driver, message):
        return False

    if _click_send_message_button(driver):
        time.sleep(3)
        if _dm_send_succeeded(driver, message):
            return True

    field = _find_direct_composer_element(driver)
    if field:
        try:
            ActionChains(driver).move_to_element(field).click().send_keys(Keys.ENTER).perform()
            time.sleep(3)
            if _dm_send_succeeded(driver, message):
                return True
        except WebDriverException:
            pass
    return False


def prepare_dm_session(driver: webdriver.Chrome) -> None:
    """Inicio estable para DMs por perfil (sin abrir inbox en cada corrida)."""
    driver.get(INSTAGRAM_URL)
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    time.sleep(2)
    dismiss_onetap_prompt(driver)
    dismiss_instagram_popups(driver)
    print("  Listo para DMs (perfil -> Mensaje, sin inbox).", flush=True)


def send_dm_api(driver: webdriver.Chrome, user_id: str, text: str) -> dict:
    url = driver.current_url.lower()
    if "login" in url:
        driver.get(INSTAGRAM_URL)
        time.sleep(2)
    driver.set_script_timeout(60)
    return driver.execute_async_script(_SEND_DM_JS, user_id, text, IG_APP_ID)


def send_dm(
    driver: webdriver.Chrome,
    user_id: str,
    text: str,
    *,
    username: str | None = None,
) -> dict:
    """Default: boton Mensaje en perfil. API solo como respaldo."""
    if dm_mode() == "manual":
        return {"ok": False, "error": "DM_MODE=manual (usá --export-messages)"}

    mode = dm_mode()
    ui_result: dict = {"ok": False, "error": "sin_ui"}
    api_result: dict = {"ok": False, "error": "sin_api"}

    if username and mode in ("profile", "ui"):
        ui_result = send_dm_ui(
            driver, username, text, user_id=user_id, allow_inbox_compose=False
        )
        if ui_result.get("ok"):
            return ui_result

    uid_ok = str(user_id or "").isdigit() and int(user_id) > 0
    if uid_ok and mode == "api":
        api_result = send_dm_api(driver, user_id, text)
        if api_result.get("ok"):
            return api_result

    if username and mode == "api":
        ui_result = send_dm_ui(driver, username, text, user_id=user_id)
        if ui_result.get("ok"):
            return ui_result

    api_err = api_result.get("error") or api_result.get("status")
    ui_err = ui_result.get("error")
    if username:
        return {
            "ok": False,
            "error": f"perfil/compose: {ui_err}; api: {api_err}",
            "status": api_result.get("status"),
        }
    return api_result


def export_outreach_messages(
    *,
    min_hours_after_follow: int = 0,
    only_usernames: set[str] | None = None,
) -> Path:
    """Genera un .txt con mensajes listos para copiar/pegar (sin Selenium)."""
    conn = outreach_connect()
    targets = get_prospects_to_message(
        conn, message_max_count(), min_hours_after_follow, only_usernames=only_usernames
    )
    out = messages_export_path()
    blocks: list[str] = []
    count = 0
    for row in targets:
        if row["status"] == "contacted":
            continue
        username = row["username"]
        message = build_outreach_message(
            username, row["pitch_type"], bio=row["bio"] or ""
        )
        blocks.append(
            f"@{username}\n"
            f"Perfil: {INSTAGRAM_URL}{username}/\n"
            f"Nuevo DM: {INSTAGRAM_URL}direct/new/\n\n"
            f"{message}\n"
            f"{'-' * 50}\n"
        )
        count += 1
    conn.close()
    out.write_text(
        (f"# {count} mensajes Ordino — copiá cada bloque en Instagram\n\n" + "\n".join(blocks))
        if blocks
        else "# No hay prospects pendientes para mensaje\n",
        encoding="utf-8",
    )
    return out.resolve()


def reset_failed_for_messaging(
    conn: sqlite3.Connection, *, only_usernames: set[str] | None = None
) -> int:
    """Reintenta prospects que fallaron al enviar DM pero ya fueron seguidos."""
    username_filter = ""
    params: list[object] = []
    if only_usernames:
        placeholders = ",".join("?" for _ in only_usernames)
        username_filter = f" AND LOWER(username) IN ({placeholders})"
        params.extend(sorted(only_usernames, key=str.lower))
    cur = conn.execute(
        f"""
        UPDATE prospects
        SET status='followed', error=NULL
        WHERE status='failed' AND followed_at IS NOT NULL
        {username_filter}
        """,
        params,
    )
    conn.commit()
    return cur.rowcount


def confirm_action(label: str, count: int) -> bool:
    return confirm_if_required(label, count)


def wait_after_follow_before_messages() -> None:
    pause = message_pause_after_follow_seconds()
    if pause <= 0:
        return
    print(
        f"\nEsperando {pause:.0f}s antes de enviar DMs (post-follow)...",
        flush=True,
    )
    time.sleep(pause)


def discover_prospects(
    driver: webdriver.Chrome,
    my_username: str,
    following_usernames: set[str],
    *,
    dry_run: bool = False,
) -> int:
    conn = outreach_connect()
    existing = get_existing_prospect_usernames(conn)
    min_score = outreach_min_score()
    max_followers = outreach_max_followers()
    my_lower = my_username.lower()
    added = 0
    skipped = 0

    tags = outreach_hashtags()
    if outreach_argentina_hashtags_only():
        print(
            f"\nHashtags solo Argentina ({len(tags)} tags, sin etiquetas globales).",
            flush=True,
        )
    if outreach_filter_hashtag_posts_argentina():
        print(
            "Posts: solo autores con publicación ubicada/caption argentina en el hashtag.",
            flush=True,
        )
    if outreach_require_argentina():
        mode = "estricto" if outreach_argentina_strict() else "permisivo"
        print(f"Validación de perfil Argentina activa ({mode}).", flush=True)

    max_new = discover_max_new()
    max_tags = discover_max_hashtags()
    batch_n = discover_batch_size()
    tags_run = tags[:max_tags]
    print(
        f"\nDescubrimiento rápido: hasta {max_new} prospects, "
        f"{len(tags_run)} hashtags, lotes de {batch_n} perfiles (API, sin abrir cada perfil).",
        flush=True,
    )
    ensure_instagram_api_context(driver)

    for hashtag in tags_run:
        if added >= max_new:
            break
        print(f"\n-> #{hashtag}", flush=True)
        try:
            users = fetch_hashtag_users(driver, hashtag)
        except RuntimeError as exc:
            print(f"  Error: {exc}", flush=True)
            time.sleep(rate_limit_pause_seconds())
            continue

        candidates: list[dict[str, object]] = []
        for raw in users:
            username = str(raw.get("username", "")).strip()
            if not username:
                continue
            uname_lower = username.lower()
            if uname_lower == my_lower or uname_lower in _SKIP_USERNAMES:
                skipped += 1
                continue
            if uname_lower in following_usernames or uname_lower in existing:
                skipped += 1
                continue
            candidates.append(raw)

        print(f"  {len(users)} en hashtag, {len(candidates)} candidatos nuevos", flush=True)

        for i in range(0, len(candidates), batch_n):
            if added >= max_new:
                break
            chunk = candidates[i : i + batch_n]
            to_fetch = [
                str(r["username"])
                for r in chunk
                if needs_profile_api_fetch(r)
            ]
            profiles_map = (
                fetch_user_profiles_batch(driver, to_fetch) if to_fetch else {}
            )
            batch_added = 0
            for raw in chunk:
                username = str(raw.get("username", "")).strip()
                uname_lower = username.lower()
                merged = merge_hashtag_user_profile(
                    raw, profiles_map.get(uname_lower)
                )
                uid = str(merged.get("id") or "")
                if not uid.isdigit() or int(uid) <= 0:
                    skipped += 1
                    continue
                if merged.get("is_private"):
                    skipped += 1
                    continue
                followers = int(merged.get("followers_count") or 0)
                if followers > max_followers:
                    skipped += 1
                    continue
                bio = str(merged.get("bio") or "")
                external_url = str(merged.get("external_url") or "")
                score = score_bio(bio)
                if score < min_score:
                    skipped += 1
                    continue
                pitch_type = classify_pitch_type(external_url)
                prospect = {
                    "username": username,
                    "user_id": uid,
                    "bio": bio,
                    "followers_count": followers,
                    "external_url": external_url,
                    "score": score,
                    "source": f"#{hashtag}",
                    "pitch_type": pitch_type,
                }
                if dry_run:
                    added += 1
                    batch_added += 1
                    continue
                upsert_prospect(conn, **prospect)
                existing.add(uname_lower)
                added += 1
                batch_added += 1
            if batch_added and not dry_run:
                print(f"  +{batch_added} prospects (#{hashtag})", flush=True)

        time.sleep(discover_hashtag_pause_seconds())

    conn.close()
    print(f"\nDescubrimiento: {added} nuevos, {skipped} omitidos.", flush=True)
    return added


def follow_prospects(
    driver: webdriver.Chrome,
    *,
    dry_run: bool = False,
) -> tuple[int, int, list[str]]:
    conn = outreach_connect()
    limit = follow_max_count()
    delay = follow_delay_seconds()
    pause = rate_limit_pause_seconds()
    targets = get_prospects_to_follow(conn, limit)
    followed_usernames: list[str] = []

    if not targets:
        print("\nNo hay prospects pendientes de follow.", flush=True)
        conn.close()
        return 0, 0, followed_usernames

    if dry_run:
        print(f"\n[DRY-RUN] Se seguirían {len(targets)} cuentas:", flush=True)
        for row in targets:
            print(
                f"  @{row['username']} score={row['score']} pitch={row['pitch_type']}",
                flush=True,
            )
        conn.close()
        return 0, len(targets), [row["username"] for row in targets]

    if not confirm_action("SEGUIR", len(targets)):
        print("Cancelado. No se siguió a nadie.", flush=True)
        conn.close()
        return 0, 0, followed_usernames

    ok_count = 0
    fail_count = 0
    print(f"\nSiguiendo cuentas (pausa ~{delay}s entre cada una)...\n", flush=True)

    for i, row in enumerate(targets, 1):
        username = row["username"]
        uid = row["user_id"]
        try:
            result = follow_one(driver, uid)
        except WebDriverException as exc:
            print(f"  [{i}/{len(targets)}] @{username} — error navegador: {exc}", flush=True)
            mark_prospect_failed(conn, username, str(exc))
            fail_count += 1
            time.sleep(delay * 2)
            continue

        if result.get("ok"):
            ok_count += 1
            mark_prospect_followed(conn, username)
            followed_usernames.append(username)
            print(f"  [{i}/{len(targets)}] @{username} — seguido", flush=True)
        else:
            fail_count += 1
            err = str(result.get("error") or result.get("status") or "error")
            mark_prospect_failed(conn, username, err)
            print(f"  [{i}/{len(targets)}] @{username} — falló ({err})", flush=True)
            if result.get("status") in (429, 403):
                print(f"  Pausa larga por límite de Instagram ({pause}s)...", flush=True)
                time.sleep(pause)

        if i < len(targets):
            time.sleep(delay)

    conn.close()
    print(f"\nResumen follow: {ok_count} ok, {fail_count} fallos.", flush=True)
    return ok_count, fail_count, followed_usernames


def send_outreach_messages(
    driver: webdriver.Chrome,
    *,
    dry_run: bool = False,
    min_hours_after_follow: int | None = None,
    only_usernames: set[str] | None = None,
    skip_thread_check: bool = True,
    skip_confirm: bool = False,
) -> tuple[int, int]:
    conn = outreach_connect()
    reset_n = reset_failed_for_messaging(conn, only_usernames=only_usernames)
    if reset_n:
        print(f"Reintentando {reset_n} prospects que fallaron al enviar.", flush=True)
    limit = message_max_count()
    delay = message_delay_seconds()
    pause = rate_limit_pause_seconds()
    min_hours = 0 if min_hours_after_follow is None else min_hours_after_follow
    print(f"\nBuscando prospects para DM (followed, espera >= {min_hours}h)...", flush=True)
    targets = get_prospects_to_message(
        conn, limit, min_hours, only_usernames=only_usernames
    )

    if not targets:
        if min_hours == 0:
            print("\nNo hay prospects recién seguidos para DM.", flush=True)
        else:
            print(
                f"\nNo hay prospects listos para DM "
                f"(status=followed y >= {min_hours}h desde el follow).",
                flush=True,
            )
        conn.close()
        return 0, 0

    pending: list[tuple[sqlite3.Row, str]] = []
    for row in targets:
        username = row["username"]
        user_id = row["user_id"]
        if row["status"] == "contacted":
            continue
        if not skip_thread_check:
            exists = thread_exists_with_user(driver, user_id)
            if exists is True:
                mark_prospect_skipped(conn, username, "conversacion_previa")
                print(f"  @{username} — omitido (ya hay conversación)", flush=True)
                continue
            if exists is None:
                print(f"  @{username} — inbox no verificado, se intentará enviar", flush=True)

        message = build_outreach_message(
            username, row["pitch_type"], bio=row["bio"] or ""
        )
        pending.append((row, message))
        time.sleep(0.5)

    if not pending:
        print("\nNingún prospect pasó la validación anti-spam.", flush=True)
        conn.close()
        return 0, 0

    if dry_run:
        print(f"\n[DRY-RUN] Se enviarían {len(pending)} mensajes:\n", flush=True)
        for row, message in pending:
            print(f"--- @{row['username']} ({row['pitch_type']}) ---", flush=True)
            print(message, flush=True)
            print(flush=True)
        conn.close()
        return 0, len(pending)

    if not skip_confirm and not confirm_action("ENVIAR MENSAJES a", len(pending)):
        print("Cancelado. No se envió ningún mensaje.", flush=True)
        conn.close()
        return 0, 0

    mode = dm_mode()
    if mode == "manual":
        out = messages_export_path()
        blocks: list[str] = []
        for row, message in pending:
            username = row["username"]
            blocks.append(
                f"@{username}\n"
                f"Perfil: {INSTAGRAM_URL}{username}/\n"
                f"Nuevo DM: {INSTAGRAM_URL}direct/new/\n\n"
                f"{message}\n"
                f"{'-' * 50}\n"
            )
        out.write_text(
            f"# {len(pending)} mensajes — copiá en Instagram\n\n" + "\n".join(blocks),
            encoding="utf-8",
        )
        print(f"\nModo manual: mensajes exportados a {out.resolve()}", flush=True)
        conn.close()
        return 0, len(pending)

    prepare_dm_session(driver)
    ok_count = 0
    fail_count = 0
    print(
        f"\nEnviando mensajes — perfil -> Mensaje (pausa ~{delay}s entre cuentas)...\n",
        flush=True,
    )

    for i, (row, message) in enumerate(pending, 1):
        username = row["username"]
        uid = row["user_id"]

        try:
            if not ensure_session_for_next_dm(driver):
                err = "sesion_no_recuperada"
                print(f"  [{i}/{len(pending)}] @{username} — falló ({err})", flush=True)
                mark_prospect_message_error(conn, username, err)
                fail_count += 1
                continue

            if not skip_thread_check:
                exists = thread_exists_with_user(driver, uid)
                if exists is True:
                    mark_prospect_skipped(conn, username, "conversacion_previa")
                    print(
                        f"  [{i}/{len(pending)}] @{username} — omitido (conversación detectada)",
                        flush=True,
                    )
                    continue

            result = send_dm(driver, uid, message, username=username)
        except WebDriverException as exc:
            err = str(exc)
            print(f"  [{i}/{len(pending)}] @{username} — error navegador: {err}", flush=True)
            mark_prospect_message_error(conn, username, err)
            fail_count += 1
            if "invalid session" in err.lower():
                print("Navegador cerrado. Deteniendo envío de mensajes.", flush=True)
                break
            time.sleep(delay * 2)
            continue

        if result.get("ok"):
            ok_count += 1
            mark_prospect_contacted(conn, username)
            via = result.get("method") or "api"
            print(f"  [{i}/{len(pending)}] @{username} — mensaje enviado ({via})", flush=True)
        else:
            fail_count += 1
            err = str(result.get("error") or result.get("status") or "error")
            mark_prospect_message_error(conn, username, err)
            print(f"  [{i}/{len(pending)}] @{username} — falló ({err})", flush=True)
            if result.get("status") in (429, 403):
                print(f"  Pausa larga por límite de Instagram ({pause}s)...", flush=True)
                time.sleep(pause)

        stabilize_session_after_dm(driver)
        if i < len(pending):
            time.sleep(delay)

    conn.close()
    print(f"\nResumen DM: {ok_count} enviados, {fail_count} fallos.", flush=True)
    return ok_count, fail_count


def _retry_dm_usernames_from_argv() -> set[str]:
    args = sys.argv[1:]
    names: list[str] = []
    capture = False
    for arg in args:
        key = arg.lstrip("-").lower().replace("_", "-")
        if key in ("retry-messages", "retry-messages-only", "reintentar-mensajes"):
            capture = True
            continue
        if capture and not arg.startswith("-"):
            names.append(arg.strip().lstrip("@"))
    if names:
        return {n.lower() for n in names if n}
    env_list = os.environ.get("MESSAGE_RETRY_USERNAMES", "").strip()
    if env_list:
        return {n.strip().lstrip("@").lower() for n in env_list.split(",") if n.strip()}
    return {n.lower() for n in DEFAULT_RETRY_DM_USERNAMES}


def _mark_sent_usernames_from_argv() -> set[str]:
    args = sys.argv[1:]
    names: list[str] = []
    capture = False
    for arg in args:
        key = arg.lstrip("-").lower().replace("_", "-")
        if key in ("mark-sent", "marcar-enviados"):
            capture = True
            continue
        if capture and not arg.startswith("-"):
            names.append(arg.strip().lstrip("@"))
    if names:
        return {n.lower() for n in names if n}
    all_retry = {n.lower() for n in DEFAULT_RETRY_DM_USERNAMES}
    all_retry.add("bagsvictoria_")
    return all_retry


def mark_prospects_sent(usernames: set[str]) -> int:
    """Marca como contacted quien ya recibió DM (corrige falsos fallos de verificación)."""
    conn = outreach_connect()
    n = 0
    for username in sorted(usernames):
        row = conn.execute(
            "SELECT username, status FROM prospects WHERE username=? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if not row:
            print(f"  @{username} — no está en la base", flush=True)
            continue
        mark_prospect_contacted(conn, username)
        n += 1
        print(f"  @{username} — marcado contacted (era {row['status']})", flush=True)
    conn.close()
    return n


def _run_mark_sent_only() -> int:
    targets = _mark_sent_usernames_from_argv()
    print(f"\nMarcando {len(targets)} cuentas como DM enviado en la base...\n", flush=True)
    n = mark_prospects_sent(targets)
    print(f"\nListo: {n} actualizadas.", flush=True)
    return 0


def _run_retry_messages_only() -> int:
    """Solo reenvía DMs a las 9 cuentas pendientes (o las que pases tras el flag)."""
    targets = _retry_dm_usernames_from_argv()
    print(f"\nReintento DM a {len(targets)} cuentas:\n", flush=True)
    for u in sorted(targets):
        print(f"  @{u}", flush=True)

    driver: webdriver.Chrome | None = None
    try:
        driver = build_driver()
        ensure_logged_in(driver)
        go_to_my_profile(driver)
        stabilize_session_after_dm(driver)
        os.environ["MESSAGE_MAX"] = str(max(message_max_count(), len(targets)))
        ok_count, fail_count = send_outreach_messages(
            driver,
            min_hours_after_follow=0,
            only_usernames=targets,
            skip_thread_check=True,
            skip_confirm=True,
        )
        print(f"\nReintento terminado: {ok_count} enviados, {fail_count} fallos.", flush=True)
        return 0 if fail_count == 0 else 1
    except Exception as exc:
        report_error(exc, driver)
        return 1
    finally:
        safe_quit(driver)


def output_file_path() -> Path:
    name = os.environ.get("OUTPUT_FILE", "no_te_siguen.txt")
    return Path(name)


def get_not_following_back(
    driver: webdriver.Chrome, username: str
) -> tuple[list[dict[str, str]], int, int]:
    """Cuentas que sigues y no te siguen = following − followers."""
    print("\nDescargando listas vía API...", flush=True)
    user_id = get_instagram_user_id(driver, username)

    print("-> Seguidos (a quien sigues)...", flush=True)
    following = fetch_following_or_followers(driver, username, user_id, "following")
    print(f"   {len(following)} cuentas", flush=True)

    print("-> Seguidores (quien te sigue)...", flush=True)
    followers = fetch_following_or_followers(driver, username, user_id, "followers")
    print(f"   {len(followers)} cuentas", flush=True)

    follower_names = {u["username"].lower() for u in followers}
    not_back = sorted(
        (u for u in following if u["username"].lower() not in follower_names),
        key=lambda u: u["username"].lower(),
    )
    return not_back, len(following), len(followers)


def list_not_following_back(driver: webdriver.Chrome, username: str) -> list[dict[str, str]]:
    not_back, n_following, n_followers = get_not_following_back(driver, username)

    out = output_file_path()
    out.write_text(
        "\n".join(u["username"] for u in not_back) + ("\n" if not_back else ""),
        encoding="utf-8",
    )

    print(f"\n{'=' * 50}", flush=True)
    print(
        f"  {len(not_back)} no te siguen de vuelta "
        f"(sigues {n_following}, te siguen {n_followers})",
        flush=True,
    )
    print(f"{'=' * 50}\n", flush=True)

    for user in not_back:
        print(f"  @{user['username']}", flush=True)

    print(f"\nListado guardado en: {out.resolve()}", flush=True)
    return not_back


def _cli_flags() -> dict[str, bool]:
    args = {a.lstrip("-").lower().replace("_", "-") for a in sys.argv[1:]}
    dry_run = "dry-run" in args or "dryrun" in args or _env_truthy("UNFOLLOW_DRY_RUN")
    return {
        "unfollow": "unfollow" in args or _env_truthy("UNFOLLOW"),
        "discover": "discover" in args,
        "follow": "follow" in args,
        "message": "message" in args or "mensajes" in args,
        "daily": "daily" in args,
        "outreach": "outreach" in args,
        "engage": "engage" in args,
        "prospect": "prospect" in args,
        "outreach_status": "outreach-status" in args,
        "help": "help" in args or "h" in args,
        "dry_run": dry_run,
        "confirm": "confirm" in args,
    }


_PIPELINE_PRESETS: dict[str, list[str]] = {
    "daily": ["unfollow", "discover", "follow", "message"],
    "outreach": ["discover", "follow", "message"],
    "engage": ["follow", "message"],
    "prospect": ["discover", "follow"],
}


def resolve_pipeline(flags: dict[str, bool]) -> list[str] | None:
    for preset in ("daily", "outreach", "engage", "prospect"):
        if flags.get(preset):
            return _PIPELINE_PRESETS[preset][:]
    steps: list[str] = []
    for step in ("discover", "follow", "message"):
        if flags.get(step):
            steps.append(step)
    return steps or None


def print_cli_help() -> None:
    print(
        """
Comandos — script Ordino Instagram

  Parte 1:
    (sin args)          Lista quién no te sigue de vuelta
    --unfollow          Deja de seguir a esas cuentas

  Parte 2 — individuales:
    --discover          Busca prospects por hashtag
    --follow            Sigue prospects pendientes
    --message, --mensajes Envia DMs comerciales (perfil -> Mensaje)
    --retry-messages    Reenvía solo a las 9 cuentas pendientes del último fallo
    --mark-sent         Marca contacted en DB (corrige falsos fallos; sin Chrome)
    --export-messages   Genera mensajes_pendientes.txt (sin Chrome)
    --outreach-status   Estado del ledger (sin abrir Chrome)

  Parte 2 — fusiones:
    --engage            follow + message
    --outreach          discover + follow + message
    --prospect          discover + follow
    --daily             unfollow + discover + follow + message

  También podés combinar pasos: --discover --follow, etc.

  Opciones:
    --dry-run           Simula sin ejecutar acciones reales
    --confirm           Pide escribir SI antes de actuar
    --logout            Borra sesión guardada
    --test-dm USER      Prueba envío DM a un usuario (default: santypuleio)
    --check-argentina USER  Verifica señales de cuenta argentina en un perfil

  Ejemplos:
    python instagram_profile.py --daily
    python instagram_profile.py --engage
    python instagram_profile.py --outreach --dry-run
        """.strip(),
        flush=True,
    )


def _run_outreach_discover(
    driver: webdriver.Chrome, username: str, *, dry_run: bool
) -> None:
    user_id = get_instagram_user_id(driver, username)
    following = fetch_following_or_followers(driver, username, user_id, "following")
    following_names = {u["username"].lower() for u in following}
    discover_prospects(
        driver,
        username,
        following_names,
        dry_run=dry_run,
    )


def _pipeline_label(steps: list[str]) -> str:
    return " + ".join(steps)


def _run_pipeline(
    driver: webdriver.Chrome, username: str, steps: list[str], *, dry_run: bool
) -> None:
    print(f"\nPipeline: {_pipeline_label(steps)}\n", flush=True)
    followed_now: list[str] = []

    if "unfollow" in steps:
        not_back = list_not_following_back(driver, username)
        if not_back:
            unfollow_users(driver, not_back, dry_run=dry_run)
        else:
            print("\nNo hay cuentas para dejar de seguir.", flush=True)

    if "discover" in steps:
        _run_outreach_discover(driver, username, dry_run=dry_run)

    if "follow" in steps:
        _, _, followed_now = follow_prospects(driver, dry_run=dry_run)

    if "message" in steps:
        same_session = "follow" in steps
        if same_session and followed_now and not dry_run:
            wait_after_follow_before_messages()
        send_outreach_messages(
            driver,
            dry_run=dry_run,
            min_hours_after_follow=0,
            only_usernames=set(followed_now) if same_session and followed_now else None,
        )

    print(f"\nCompletado: {_pipeline_label(steps)}.", flush=True)


def _check_argentina_target_from_argv() -> str | None:
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        key = arg.lstrip("-").lower().replace("_", "-")
        if key in ("check-argentina", "verificar-argentina", "es-argentina"):
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                return args[i + 1].strip().lstrip("@")
            return None
    return None


def _run_check_argentina(target_username: str) -> int:
    load_local_env()
    target = target_username.strip().lstrip("@")
    print(f"\nVerificando si @{target} parece cuenta argentina...\n", flush=True)
    driver: webdriver.Chrome | None = None
    try:
        driver = build_driver()
        ensure_logged_in(driver)
        profile = fetch_user_profile(driver, target)
        if not profile:
            print("No se pudo leer el perfil.", flush=True)
            return 1
        verdict, detail = argentina_profile_verdict(profile)
        include, reason = include_argentina_profile(profile)
        print(f"Bio: {(profile.get('bio') or '')[:120]}", flush=True)
        print(f"URL: {profile.get('external_url') or '-'}", flush=True)
        print(f"Tel. país: {profile.get('public_phone_country_code') or '-'}", flush=True)
        print(f"Ciudad IG: {profile.get('city_name') or '-'}", flush=True)
        print(f"Veredicto: {verdict} ({detail})", flush=True)
        print(
            f"Incluiría en outreach: {'sí' if include else 'no'} ({reason})",
            flush=True,
        )
        return 0 if include else 1
    except Exception as exc:
        report_error(exc, driver)
        return 1
    finally:
        safe_quit(driver)


def _test_dm_target_from_argv() -> str | None:
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        key = arg.lstrip("-").lower().replace("_", "-")
        if key in ("test-dm", "testdm"):
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                return args[i + 1].strip().lstrip("@")
            return "santypuleio"
    return None


def _run_test_dm(target_username: str) -> int:
    """Envía un DM de prueba por API (igual que --message)."""
    load_local_env()
    target = target_username.strip().lstrip("@")
    stamp = datetime.now().strftime("%H:%M:%S")
    message = (
        f"Prueba Ordino ({stamp}): mensaje automatico del script. "
        "Si lo recibis, el envio masivo ya puede funcionar."
    )
    print(f"\nTest DM -> @{target}\n", flush=True)

    driver: webdriver.Chrome | None = None
    try:
        driver = build_driver()
        ensure_logged_in(driver)
        go_to_my_profile(driver)

        profile = fetch_user_profile(driver, target)
        uid = str(profile["id"]) if profile and profile.get("id") else ""
        if uid:
            print(f"ID destino: {uid}", flush=True)
        else:
            print(f"Sin ID API para @{target}; se intenta solo por perfil (Mensaje).", flush=True)
        prepare_dm_session(driver)

        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            print(f"\nIntento {attempt}/{max_attempts}...", flush=True)
            result = send_dm(driver, uid, message, username=target)
            if result.get("ok"):
                via = result.get("method") or "ok"
                print(f"\nOK: mensaje enviado a @{target} ({via})", flush=True)
                return 0
            print(f"Falló: {result.get('error')}", flush=True)
            time.sleep(5)

        print(f"\nNo se pudo enviar a @{target} tras {max_attempts} intentos.", flush=True)
        return 1
    except Exception as exc:
        report_error(exc, driver)
        return 1
    finally:
        safe_quit(driver)


def _run_with_driver(steps: list[str]) -> int:
    load_local_env()
    warn_session_env_issues()

    if not os.environ.get("CHROME_DEBUG_PORT") and _force_sync() and is_chrome_running():
        print("Cierra Chrome antes de sincronizar.\n", file=sys.stderr)
        return 1

    if _env_truthy("RESET_SESSION") or _env_truthy("LOGOUT"):
        print(
            "Aviso: tienes RESET_SESSION/LOGOUT activo; se borrará la sesión.\n"
            "Para cambiar de cuenta usa: python instagram_profile.py --logout\n",
            flush=True,
        )
        clear_automation_session()

    profile_dir = automation_user_data_dir().resolve()
    account = instagram_login_username() or "(sin INSTAGRAM_ACCOUNT en .env)"
    print(f"Perfil de automatización:\n  {profile_dir}\n  Cuenta: @{account}\n", flush=True)

    driver: webdriver.Chrome | None = None
    flags = _cli_flags()
    try:
        driver = build_driver()
        ensure_logged_in(driver)
        username = go_to_my_profile(driver)
        _run_pipeline(driver, username, steps, dry_run=flags["dry_run"])
        return 0
    except Exception as exc:
        report_error(exc, driver)
        return 1
    finally:
        safe_quit(driver)


def main() -> int:
    load_local_env()
    warn_session_env_issues()

    if not os.environ.get("CHROME_DEBUG_PORT") and _force_sync() and is_chrome_running():
        print("Cierra Chrome antes de sincronizar.\n", file=sys.stderr)
        return 1

    if _env_truthy("RESET_SESSION") or _env_truthy("LOGOUT"):
        print(
            "Aviso: tienes RESET_SESSION/LOGOUT activo; se borrará la sesión.\n"
            "Para cambiar de cuenta usa: python instagram_profile.py --logout\n",
            flush=True,
        )
        clear_automation_session()

    profile_dir = automation_user_data_dir().resolve()
    account = instagram_login_username() or "(sin INSTAGRAM_ACCOUNT en .env)"
    print(f"Perfil de automatización:\n  {profile_dir}\n  Cuenta: @{account}\n", flush=True)

    driver: webdriver.Chrome | None = None
    try:
        driver = build_driver()
        ensure_logged_in(driver)

        username = go_to_my_profile(driver)
        not_back = list_not_following_back(driver, username)

        flags = _cli_flags()
        if flags["unfollow"]:
            if not not_back:
                print("\nNo hay cuentas para dejar de seguir.", flush=True)
            else:
                unfollow_users(driver, not_back, dry_run=flags["dry_run"])
        elif not_back:
            print(
                "\nPara dejar de seguir a estas cuentas:\n"
                "  python instagram_profile.py --unfollow\n"
                "  (prueba antes: python instagram_profile.py --unfollow --dry-run)",
                flush=True,
            )

        return 0
    except Exception as exc:
        report_error(exc, driver)
        return 1
    finally:
        safe_quit(driver)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        args = {a.lstrip("-").lower().replace("_", "-") for a in sys.argv[1:]}
        if args & {"logout", "reset"}:
            try:
                clear_automation_session()
                print(
                    "\nListo. Ahora ejecuta:\n  python instagram_profile.py\n"
                    "e inicia sesión con la otra cuenta.",
                    flush=True,
                )
                raise SystemExit(0)
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
        if "logout-all" in args:
            try:
                clear_automation_session(all_profiles=True)
                print(
                    "\nTodas las sesiones guardadas fueron borradas.\n"
                    "Ejecuta: python instagram_profile.py",
                    flush=True,
                )
                raise SystemExit(0)
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
        if "outreach-status" in args:
            print_outreach_status()
            raise SystemExit(0)
        if args & {"mark-sent", "marcar-enviados"}:
            load_local_env()
            raise SystemExit(_run_mark_sent_only())
        if args & {"retry-messages", "retry-messages-only", "reintentar-mensajes"}:
            load_local_env()
            raise SystemExit(_run_retry_messages_only())
        if "export-messages" in args:
            load_local_env()
            out = export_outreach_messages()
            print(f"\nListo: {out}", flush=True)
            print("Abrí el archivo, andá a direct/new en Instagram y copiá cada mensaje.", flush=True)
            raise SystemExit(0)
        if "help" in args or "h" in args:
            print_cli_help()
            raise SystemExit(0)

        ar_target = _check_argentina_target_from_argv()
        if ar_target is not None:
            raise SystemExit(_run_check_argentina(ar_target))
        test_target = _test_dm_target_from_argv()
        if test_target is not None:
            raise SystemExit(_run_test_dm(test_target))

        flags = _cli_flags()
        pipeline = resolve_pipeline(flags)
        if pipeline:
            raise SystemExit(_run_with_driver(pipeline))
        if "unfollow" in args:
            raise SystemExit(main())
        print(f"Argumento desconocido: {sys.argv[1]}", file=sys.stderr)
        print("Usa --help para ver los comandos.", file=sys.stderr)
        raise SystemExit(1)

    raise SystemExit(main())
