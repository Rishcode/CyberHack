def create_chrome_driver(headless: bool | None = None, attach_existing: bool | None = None):
    """
    Create / attach to a Chrome instance using your default profile.
    """

    if headless is None:
        headless_env = os.environ.get("HEADLESS", "").lower()
        if headless_env in {"1", "true", "yes"}:
            headless = True
    if attach_existing is None:
        attach_env = os.environ.get("ATTACH_EXISTING", "").lower()
        if attach_env in {"1", "true", "yes"}:
            attach_existing = True

    options = Options()

    if attach_existing:
        # Attach to an already open Chrome instance
        debug_address = os.environ.get("DEBUG_ADDRESS", "127.0.0.1:9222")
        options.debugger_address = debug_address
    else:
        # === Use your default Chrome profile ===
        user_data_dir = r"C:\Users\Asus\AppData\Local\Google\Chrome\User Data"
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument("--profile-directory=1")  # Or 'Profile 1', 'Profile 2', etc.

        if headless:
            options.add_argument("--headless=new")

        # Stability tweaks
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])

    try:
        return webdriver.Chrome(options=options)
    except WebDriverException as e:
        if attach_existing:
            raise RuntimeError(f"Failed attaching to existing Chrome at {options.debugger_address}: {e}") from e
        raise
