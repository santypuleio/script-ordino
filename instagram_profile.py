"""
Instagram: lista quién sigues y no te sigue de vuelta.

Usa la API interna del navegador (rápido, sin scroll en el modal).
La primera vez debes iniciar sesión en la ventana del script.

Uso:
  pip install -r requirements.txt
  python instagram_profile.py

Opcional:
  INSTAGRAM_USERNAME=tu_usuario
  OUTPUT_FILE=no_te_siguen.txt
  UNFOLLOW_DELAY=5          → segundos entre cada unfollow (default 5)
  UNFOLLOW_MAX=100          → máximo por ejecución (default 0 = sin límite)

Comandos:
  python instagram_profile.py              → solo lista quién no te sigue
  python instagram_profile.py --unfollow   → deja de seguir a esas cuentas
  python instagram_profile.py --unfollow --dry-run   → simula sin dejar de seguir
  python instagram_profile.py --logout / --logout-all
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

INSTAGRAM_URL = "https://www.instagram.com/"
IG_APP_ID = "936619743392459"
WAIT_SECONDS = 30
DEFAULT_LOGIN_WAIT = 600
API_PAGE_SIZE = 200
SCRIPT_TIMEOUT = 600
DEFAULT_UNFOLLOW_DELAY = 5.0
DEFAULT_UNFOLLOW_MAX = 0
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
    print("  → cookies y preferencias...", flush=True)
    n_files = _copy_session_files(src_profile, dest_profile)
    if n_files == 0:
        raise RuntimeError(f"No se encontraron cookies en {src_profile}.")
    for dir_name in _SESSION_DIRS:
        src_dir = src_profile / dir_name
        if src_dir.exists():
            print(f"  → {dir_name}/...", flush=True)
            _copy_dir(src_dir, dest_profile / dir_name)
    print("  → IndexedDB (Instagram)...", flush=True)
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


def build_driver() -> webdriver.Chrome:
    debug_port = os.environ.get("CHROME_DEBUG_PORT")
    options = Options()

    if debug_port:
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
    else:
        dest_root = prepare_automation_profile()
        profile_name = os.environ.get("CHROME_PROFILE", "Default")
        options.add_argument(f"--user-data-dir={dest_root}")
        options.add_argument(f"--profile-directory={profile_name}")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.page_load_strategy = "eager"
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
        driver.quit()
    except WebDriverException:
        pass
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
            print("  → Perfil eliminado", flush=True)
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
    for cookie in driver.get_cookies():
        if cookie.get("name") == "sessionid" and cookie.get("value"):
            return True
    try:
        user_id = driver.execute_script(
            "try { return localStorage.getItem('ds_user_id'); } catch (e) { return null; }"
        )
        if user_id:
            return True
    except Exception:
        pass
    return False


def _visible_login_form(driver: webdriver.Chrome) -> bool:
    try:
        field = driver.find_element(By.CSS_SELECTOR, 'input[name="username"]')
        return field.is_displayed()
    except NoSuchElementException:
        return False


def is_login_page(driver: webdriver.Chrome) -> bool:
    if has_instagram_session(driver):
        return False
    if "/accounts/login" in driver.current_url:
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


def ensure_logged_in(driver: webdriver.Chrome) -> None:
    driver.get(INSTAGRAM_URL)
    wait_for_instagram_load(driver)

    if has_instagram_session(driver) or has_logged_in_ui(driver):
        print("Sesión activa en el perfil de automatización.")
        return

    if is_login_page(driver):
        print(
            "\n"
            "═" * 56 + "\n"
            "  Inicia sesión en Instagram en esta ventana.\n"
            "  (usuario, contraseña o el método que uses)\n"
            "  La sesión se guardará para la próxima vez.\n"
            "═" * 56 + "\n",
            flush=True,
        )
        timeout = login_wait_seconds()
        wait = WebDriverWait(driver, timeout)
        try:
            wait.until(
                lambda d: has_instagram_session(d) or has_logged_in_ui(d)
            )
        except TimeoutException:
            raise RuntimeError(
                f"No se detectó sesión tras {timeout}s. "
                "Vuelve a ejecutar el script e inicia sesión."
            ) from None
        time.sleep(2)
        print("Sesión guardada.", flush=True)
        return

    # Cargó algo que no es login claro (p. ej. modal de notificaciones)
    print("Continuando (Instagram cargó sin pantalla de login).", flush=True)


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
    env_user = os.environ.get("INSTAGRAM_USERNAME", "").strip().lstrip("@")
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


_FETCH_LIST_JS = """
const userId = arguments[0];
const listType = arguments[1];
const pageSize = arguments[2];
const done = arguments[arguments.length - 1];
const appId = arguments[3];

(async () => {
    const users = [];
    let maxId = null;
    try {
        while (true) {
            let url = `https://www.instagram.com/api/v1/friendships/${userId}/${listType}/?count=${pageSize}`;
            if (maxId) url += `&max_id=${encodeURIComponent(maxId)}`;
            const resp = await fetch(url, {
                credentials: 'include',
                headers: {
                    'X-IG-App-ID': appId,
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            if (!resp.ok) {
                done({ users: [], error: `HTTP ${resp.status}` });
                return;
            }
            const data = await resp.json();
            for (const u of (data.users || [])) {
                const id = String(u.pk || u.id || '');
                if (id && u.username) {
                    users.push({ id, username: u.username });
                }
            }
            if (!data.next_max_id) break;
            maxId = data.next_max_id;
        }
        done({ users, error: null });
    } catch (e) {
        done({ users: [], error: String(e) });
    }
})();
"""


def get_instagram_user_id(driver: webdriver.Chrome, username: str) -> str:
    driver.set_script_timeout(60)
    result = driver.execute_async_script(
        """
        const username = arguments[0];
        const appId = arguments[1];
        const done = arguments[arguments.length - 1];
        fetch(
            'https://www.instagram.com/api/v1/users/web_profile_info/?username=' +
                encodeURIComponent(username),
            {
                credentials: 'include',
                headers: { 'X-IG-App-ID': appId },
            }
        )
            .then((r) => r.json())
            .then((d) => done({ id: d?.data?.user?.id ?? null, error: null }))
            .catch((e) => done({ id: null, error: String(e) }));
        """,
        username,
        IG_APP_ID,
    )
    if result.get("error") or not result.get("id"):
        raise RuntimeError(
            f"No se pudo obtener el ID de @{username}: {result.get('error')}"
        )
    return str(result["id"])


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
        raise RuntimeError(f"Error API ({list_type}): {result['error']}")
    return result.get("users") or []


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


def unfollow_one(driver: webdriver.Chrome, target_id: str) -> dict:
    driver.set_script_timeout(30)
    return driver.execute_async_script(_UNFOLLOW_JS, target_id, IG_APP_ID)


def confirm_unfollow(count: int) -> bool:
    print(
        f"\n⚠️  Vas a DEJAR DE SEGUIR a {count} cuentas.\n"
        "   Instagram puede limitar tu cuenta si haces muchos de golpe.\n",
        flush=True,
    )
    answer = input('Escribe SI (mayúsculas) para confirmar: ').strip()
    return answer == "SI"


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

    if not confirm_unfollow(len(to_process)):
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


def output_file_path() -> Path:
    name = os.environ.get("OUTPUT_FILE", "no_te_siguen.txt")
    return Path(name)


def get_not_following_back(
    driver: webdriver.Chrome, username: str
) -> tuple[list[dict[str, str]], int, int]:
    """Cuentas que sigues y no te siguen = following − followers."""
    print("\nDescargando listas vía API...", flush=True)
    user_id = get_instagram_user_id(driver, username)
    print(f"ID de usuario: {user_id}", flush=True)

    print("→ Seguidos (a quién sigues)...", flush=True)
    following = fetch_users_via_api(driver, user_id, "following")
    print(f"   {len(following)} cuentas", flush=True)

    print("→ Seguidores (quién te sigue)...", flush=True)
    followers = fetch_users_via_api(driver, user_id, "followers")
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

    print(f"\n{'═' * 50}", flush=True)
    print(
        f"  {len(not_back)} no te siguen de vuelta "
        f"(sigues {n_following}, te siguen {n_followers})",
        flush=True,
    )
    print(f"{'═' * 50}\n", flush=True)

    for user in not_back:
        print(f"  @{user['username']}", flush=True)

    print(f"\nListado guardado en: {out.resolve()}", flush=True)
    return not_back


def _cli_flags() -> tuple[bool, bool]:
    args = {a.lstrip("-").lower() for a in sys.argv[1:]}
    unfollow = "unfollow" in args or _env_truthy("UNFOLLOW")
    dry_run = "dry-run" in args or "dryrun" in args or _env_truthy("UNFOLLOW_DRY_RUN")
    return unfollow, dry_run


def main() -> int:
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

    profile_dir = automation_user_data_dir()
    print("Perfil de automatización:", profile_dir, "\n", sep="\n")

    driver: webdriver.Chrome | None = None
    try:
        driver = build_driver()
        ensure_logged_in(driver)

        username = go_to_my_profile(driver)
        not_back = list_not_following_back(driver, username)

        do_unfollow, dry_run = _cli_flags()
        if do_unfollow:
            if not not_back:
                print("\nNo hay cuentas para dejar de seguir.", flush=True)
            else:
                unfollow_users(driver, not_back, dry_run=dry_run)
        elif not_back:
            print(
                "\nPara dejar de seguir a estas cuentas:\n"
                "  python instagram_profile.py --unfollow\n"
                "  (prueba antes: python instagram_profile.py --unfollow --dry-run)",
                flush=True,
            )

        input("\nListo. Pulsa Enter para cerrar el navegador...")
        return 0
    except Exception as exc:
        report_error(exc, driver)
        if driver:
            try:
                input("\nHubo un error. Pulsa Enter para cerrar el navegador...")
            except KeyboardInterrupt:
                print("\nCancelado.", flush=True)
        return 1
    finally:
        safe_quit(driver)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        args = {a.lstrip("-").lower() for a in sys.argv[1:]}
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
        if "unfollow" in args:
            raise SystemExit(main())
        print(f"Argumento desconocido: {sys.argv[1]}", file=sys.stderr)
        raise SystemExit(1)

    raise SystemExit(main())
