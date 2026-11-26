"""Settings. Everything comes from environment variables or a .env file in the repo root."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env(path=None):
    """Read KEY=VALUE lines from .env (does not override variables already set)."""
    p = pathlib.Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


class Settings:
    @property
    def data_dir(self):
        return pathlib.Path(os.environ.get("VM_DATA_DIR", ROOT / "data"))

    @property
    def ventures_dir(self):
        return pathlib.Path(os.environ.get("VM_VENTURES_DIR", ROOT / "ventures"))

    @property
    def dfs_login(self):
        return os.environ.get("DATAFORSEO_LOGIN", "")

    @property
    def dfs_password(self):
        return os.environ.get("DATAFORSEO_PASSWORD", "")

    @property
    def max_usd_per_idea(self):
        """Hard cap on paid API money for one idea (phases 1-4). PDF: <= 5 EUR."""
        return _f("VM_MAX_USD_PER_IDEA", os.environ.get("DATAFORSEO_MAX_USD", 5))

    @property
    def phase1_max_usd(self):
        """Phase 1 (blocks 01-05) must stay cheap. PDF: <= 0.50 EUR."""
        return _f("VM_PHASE1_MAX_USD", 0.5)

    @property
    def ai_provider(self):
        return os.environ.get("VM_AI_PROVIDER", "auto").lower()

    @property
    def model_smart(self):
        return os.environ.get("VM_MODEL_SMART", "claude-sonnet-5-5")

    @property
    def model_fast(self):
        return os.environ.get("VM_MODEL_FAST", "claude-haiku-5-5")

    @property
    def count_cli_cost(self):
        """Claude Code CLI runs on a subscription, so its cost is not counted against the cap by default."""
        return os.environ.get("VM_COUNT_CLI_COST", "0") == "1"

    @property
    def cache_days(self):
        return _f("VM_CACHE_DAYS", 30)

    @property
    def max_serps(self):
        return int(_f("VM_MAX_SERPS", 60))

    @property
    def serp_depth(self):
        return int(_f("VM_SERP_DEPTH", 20))

    @property
    def min_market_usd(self):
        """Smallest search market (USD a year) worth building for. A size bar of the machine, not anybody's sales goal."""
        return _f("VM_MIN_MARKET_USD", 12000)

    @property
    def assumed_conversion(self):
        return _f("VM_ASSUMED_CONVERSION", 0.01)

    @property
    def market_countries(self):
        return [c.strip().lower() for c in os.environ.get("VM_MARKET_COUNTRIES", "us,gb,ca,au").split(",") if c.strip()]

    @property
    def house_rules(self):
        for name in ("house_rules.md", "house_rules.example.md"):
            p = ROOT / name
            if p.exists():
                return p.read_text(encoding="utf-8")
        return ""


S = Settings()

# Google location codes (DataForSEO / Google Ads). Pass a number to use any other location.
LOCATIONS = {
    "us": 2840, "gb": 2826, "uk": 2826, "ca": 2124, "au": 2036, "nz": 2554, "ie": 2372,
    "de": 2276, "fr": 2250, "es": 2724, "it": 2380, "nl": 2528, "be": 2056, "at": 2040,
    "ch": 2756, "se": 2752, "no": 2578, "dk": 2208, "fi": 2246, "pl": 2616, "pt": 2620,
    "lt": 2440, "lv": 2428, "ee": 2233, "cz": 2203, "in": 2356, "br": 2076, "mx": 2484,
    "za": 2710, "sg": 2702, "ae": 2784, "jp": 2392,
}
COUNTRY_LANG = {"us": "en", "gb": "en", "uk": "en", "ca": "en", "au": "en", "nz": "en", "ie": "en",
                "de": "de", "at": "de", "ch": "de", "fr": "fr", "be": "fr", "es": "es", "mx": "es",
                "it": "it", "nl": "nl", "se": "sv", "no": "no", "dk": "da", "fi": "fi", "pl": "pl",
                "pt": "pt", "br": "pt", "lt": "lt", "lv": "lv", "ee": "et", "cz": "cs", "in": "en",
                "za": "en", "sg": "en", "ae": "en", "jp": "ja"}


def location_code(country):
    c = str(country).lower()
    if c.isdigit():
        return int(c)
    if c not in LOCATIONS:
        raise ValueError(f"unknown country '{country}'. Use one of {sorted(LOCATIONS)} or a Google location code")
    return LOCATIONS[c]


# ---------------- research depth: quick / full / deep ----------------
# Each level is the same machine with different sizes. Upgrading later re-uses everything already fetched (cache).
DEPTHS = {
    "light": {"label": "Quick check", "about": "about 5 minutes, about $0.20 of data", "cap_env": "VM_LIGHT_MAX_USD", "cap": 0.5,
              "max_serps": 10, "serp_depth": 10, "suggest_seeds": 1, "suggest_limit": 20},
    "full": {"label": "Full check", "about": "about 30 minutes, about $2-3 of data", "cap_env": "VM_MAX_USD_PER_IDEA", "cap": 5.0,
             "max_serps": 60, "serp_depth": 20, "suggest_seeds": 3, "suggest_limit": 40, "ai_prompts": 4,
             "history_rivals": 3, "gap_rivals": 3, "ref_limit": 300, "extra_countries": []},
    "deep": {"label": "Deep check", "about": "about 45 minutes, about $4-7 of data", "cap_env": "VM_DEEP_MAX_USD", "cap": 10.0,
             "max_serps": 120, "serp_depth": 20, "suggest_seeds": 6, "suggest_limit": 60, "ai_prompts": 8,
             "history_rivals": 5, "gap_rivals": 5, "ref_limit": 800, "extra_countries": ["ie", "nz", "de", "fr", "nl"]},
}
LIGHT_BLOCKS = ["01", "02", "03", "04", "06", "07", "08", "09"]
ACTIVE = {"depth": "full"}  # set by the pipeline for the venture being run


def K(name):
    """A size setting for the active depth. Env vars (VM_MAX_SERPS, VM_SERP_DEPTH) still override full/deep."""
    d = ACTIVE.get("depth") or "full"
    if d != "light":
        if name == "max_serps" and os.environ.get("VM_MAX_SERPS") and d == "full":
            return S.max_serps
        if name == "serp_depth" and os.environ.get("VM_SERP_DEPTH"):
            return S.serp_depth
    return DEPTHS.get(d, DEPTHS["full"]).get(name, DEPTHS["full"].get(name))


def cap_usd(depth):
    p = DEPTHS.get(depth or "full", DEPTHS["full"])
    if depth in (None, "full"):
        return S.max_usd_per_idea
    try:
        return float(os.environ.get(p["cap_env"], p["cap"]))
    except ValueError:
        return p["cap"]
