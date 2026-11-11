"""
Model profiles and connections (Mickey, 2026-11-11): which models read a paper, where they run, and the settings of
those requests that data packs and modules don't decide.

- A **connection** is where requests go: the Anthropic API (built in; its key is the one in Settings), or a model
  server -- local (Ollama, LM Studio, llama.cpp, vLLM) or hosted (any OpenAI-compatible service: OpenAI, OpenRouter,
  a university server, ...). A server has an address, an optional key (system keychain), a time limit, how many
  requests it takes at once, and its models (context length, reads images, prices).
- A **profile** names one connection, a model for each role (plans the rows, paper details, extraction steps, figure
  suggestions, equations) and advanced settings: the output cap, temperature, prompt caching (Claude), steps at once,
  retries (Claude), prices for models the app's price table doesn't know.

The three built-in profiles (Standard, Balanced, Economy: settings.MODEL_PROFILES) are the tested defaults. They can
be changed (the window warns); only the changes are stored, and Reset removes them. An UNCHANGED built-in profile
runs exactly as before this module existed (`apply` leaves `profile_roles` empty, so RunConfig.model_for takes its
old path) -- Claude's requests for the defaults can't drift.

Stored in <app data>/model_profiles.json. The settings of the earlier single local server (local_models.json,
Settings > Model provider) become a connection named "Local server" with its profiles, the first time this is read.
A server profile runs through local_models.py (RunConfig.provider "local", RunConfig.local = the connection).
"""
from __future__ import annotations

import copy
import ipaddress
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from parameter_extractor import errors
from parameter_extractor.config import settings

ANTHROPIC = "anthropic"
# the roles a profile gives a model (local_models.PROFILE_ROLES kept these three; two added)
ROLES = [("structure_planner", "Plans the rows"), ("metadata", "Paper details"), ("*", "Extraction steps"),
         ("figure_planner", "Figure suggestions"), ("equations", "Equations as LaTeX")]
ROLE_HELP = {
    "structure_planner": "Reads the whole paper first and plans its rows (experiment sets and samples). The step the "
                         "others depend on: a strong model matters most here.",
    "metadata": "Reads page 1 for the title, authors, journal and year (a small model is enough).",
    "*": "Every extraction step of the data pack (conditions, chemistry, analysis, ...): most of the cost.",
    "figure_planner": "Suggestions when you choose to digitize a figure (reads the figure image).",
    "equations": "Converts numbered equations to LaTeX when that option is on (reads the equation images).",
}
KINDS = {ANTHROPIC: "Anthropic API (Claude)", "ollama": "Ollama", "openai": "OpenAI-compatible server"}
BUILTIN_LABELS = {"standard": "Standard", "balanced": "Balanced", "economy": "Economy"}
KEY_ACCOUNT_PREFIX = "model-connection:"
DEFAULTS = {"max_tokens": settings.MAX_TOKENS, "temperature": None, "prompt_caching": True,
            "parallel_steps": settings.MAX_PARALLEL_STAGES, "retries": 5}
SETTING_FIELDS = list(DEFAULTS)


def claude_models() -> List[str]:
    """Claude models the app has prices for, newest families first (others can be typed)."""
    from parameter_extractor.pricing import PRICES
    return list(PRICES)


@dataclass
class ServerModel:
    context: int = 32768
    vision: bool = False
    price_input: Optional[float] = None       # $ per million tokens (None: free on a local server, else unknown)
    price_output: Optional[float] = None


@dataclass
class Connection:
    id: str
    name: str
    kind: str = "ollama"                       # anthropic | ollama | openai
    url: str = ""
    timeout_sec: int = 900
    parallel: int = 1
    models: Dict[str, ServerModel] = field(default_factory=dict)
    key_account: str = ""                      # the keychain account holding its key ('' = KEY_ACCOUNT_PREFIX + id)

    @property
    def is_anthropic(self) -> bool:
        return self.kind == ANTHROPIC

    @property
    def account(self) -> str:
        return self.key_account or KEY_ACCOUNT_PREFIX + self.id

    @property
    def is_private(self) -> bool:
        """On this computer or the local network (no charges): localhost, a .local name, a private address."""
        host = (urlparse(self.url).hostname or "").lower()
        if host in ("localhost", "") or host.endswith(".local"):
            return True
        try:
            return ipaddress.ip_address(host).is_private
        except ValueError:
            return False

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("id")
        return d

    @classmethod
    def from_dict(cls, cid: str, d: dict) -> "Connection":
        d = dict(d or {})
        models = {n: ServerModel(**{k: v for k, v in (m or {}).items() if k in ServerModel.__dataclass_fields__})
                  for n, m in (d.pop("models", None) or {}).items()}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k not in ("id", "models")}
        return cls(id=cid, models=models, **known)


@dataclass
class Profile:
    id: str
    label: str
    connection: str = ANTHROPIC
    roles: Dict[str, str] = field(default_factory=dict)
    max_tokens: int = DEFAULTS["max_tokens"]
    temperature: Optional[float] = None        # None: the model's own default (Claude); 0 on servers
    prompt_caching: bool = True                # Claude only
    parallel_steps: int = DEFAULTS["parallel_steps"]
    retries: int = DEFAULTS["retries"]         # Claude only (the SDK's retries on rate limits / overload)
    prices: Dict[str, Dict[str, float]] = field(default_factory=dict)   # Claude models not in pricing.PRICES
    description: str = ""
    builtin: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("id")
        d.pop("builtin")
        return d


def builtin_roles(key: str) -> Dict[str, str]:
    """The model a built-in profile gives each role, as RunConfig.model_for picks it (for display and as the
    starting point of a changed copy)."""
    profile = settings.MODEL_PROFILES.get(key, {})
    out = {}
    for role, _label in ROLES:
        if role in profile:
            out[role] = profile[role]
        elif "*" in profile and role not in settings.PROFILE_EXEMPT:
            out[role] = profile["*"]
        else:
            out[role] = settings.MODELS.get("chemistry" if role == "*" else role, settings.MODELS["chemistry"])
    return out


def builtin_profile(key: str) -> Profile:
    return Profile(id=key, label=BUILTIN_LABELS.get(key, key.title()), roles=builtin_roles(key), builtin=True,
                   **{k: DEFAULTS[k] for k in SETTING_FIELDS})


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "profile"


def default_path() -> Path:
    from parameter_extractor.registry import default_registry_path
    return default_registry_path().with_name("model_profiles.json")


class ModelStore:
    """The connections and profiles, as stored in model_profiles.json (built-ins: only their changes)."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_path()
        self.connections: Dict[str, Connection] = {}
        self.user_profiles: Dict[str, Profile] = {}
        self.builtin_changes: Dict[str, dict] = {}
        self.migrated_from: Optional[Path] = None
        self._load()

    # ---- reading / writing -----------------------------------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text()) if self.path.is_file() else None
        except (OSError, ValueError):
            data = None
        if data is None:
            self._migrate_local_models()
            return
        for cid, c in (data.get("connections") or {}).items():
            if cid != ANTHROPIC:
                self.connections[cid] = Connection.from_dict(cid, c)
        for pid, p in (data.get("profiles") or {}).items():
            known = {k: v for k, v in (p or {}).items() if k in Profile.__dataclass_fields__ and k not in ("id",)}
            self.user_profiles[pid] = Profile(id=pid, **known)
        self.builtin_changes = {k: v for k, v in (data.get("builtin_changes") or {}).items()
                                if k in settings.MODEL_PROFILES and isinstance(v, dict)}

    def _migrate_local_models(self) -> None:
        """The earlier single local server (local_models.json) -> a connection 'local' + its profiles."""
        from parameter_extractor import local_models
        old = local_models.default_path()
        if not old.is_file():
            return
        local = local_models.load(old)
        if not local.models and not local.profiles:
            return
        conn = Connection(id="local", name="Local server", kind=local.kind, url=local.url,
                          timeout_sec=local.timeout_sec, parallel=local.parallel,
                          models={n: ServerModel(context=m.context, vision=m.vision) for n, m in local.models.items()},
                          key_account="local-model-server")       # gui.key_store.LOCAL_ACCOUNT: the key stays put
        self.connections["local"] = conn
        for name, roles in local.profiles.items():
            pid = self._free_id(name)
            self.user_profiles[pid] = Profile(id=pid, label=name, connection="local", roles=dict(roles),
                                              temperature=0.0)
        self.migrated_from = old

    def save(self) -> None:
        data = {"connections": {cid: c.to_dict() for cid, c in self.connections.items()},
                "profiles": {pid: p.to_dict() for pid, p in self.user_profiles.items()},
                "builtin_changes": {k: v for k, v in self.builtin_changes.items() if v}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # ---- connections ---------------------------------------------------------------------------------------------
    def anthropic(self) -> Connection:
        return Connection(id=ANTHROPIC, name="Anthropic API (Claude)", kind=ANTHROPIC,
                          models={m: ServerModel(context=200000, vision=True) for m in claude_models()})

    def all_connections(self) -> List[Connection]:
        return [self.anthropic()] + list(self.connections.values())

    def connection(self, cid: str) -> Optional[Connection]:
        return self.anthropic() if cid == ANTHROPIC else self.connections.get(cid)

    def add_connection(self, name: str, kind: str = "ollama", url: str = "") -> Connection:
        cid = _slug(name)
        n = 2
        while cid in self.connections or cid == ANTHROPIC:
            cid, n = f"{_slug(name)}-{n}", n + 1
        from parameter_extractor.local_models import DEFAULT_URLS
        conn = Connection(id=cid, name=name, kind=kind, url=url or DEFAULT_URLS.get(kind, ""))
        self.connections[cid] = conn
        return conn

    def remove_connection(self, cid: str) -> List[str]:
        """Removes a server and the profiles that use it; returns those profiles' labels."""
        gone = [p.label for p in self.user_profiles.values() if p.connection == cid]
        self.user_profiles = {k: p for k, p in self.user_profiles.items() if p.connection != cid}
        self.connections.pop(cid, None)
        return gone

    # ---- profiles --------------------------------------------------------------------------------------------------
    def _free_id(self, label: str) -> str:
        pid, n = _slug(label), 2
        while pid in self.user_profiles or pid in settings.MODEL_PROFILES:
            pid, n = f"{_slug(label)}-{n}", n + 1
        return pid

    def profiles(self) -> List[Profile]:
        """Built-ins (with their changes) first, then the user's own grouped by connection."""
        order = {c.id: i for i, c in enumerate(self.all_connections())}
        own = sorted(self.user_profiles.values(), key=lambda p: (order.get(p.connection, 99), p.label.lower()))
        return [self.profile(k) for k in settings.MODEL_PROFILES] + own

    def profile(self, pid: str) -> Optional[Profile]:
        if pid in settings.MODEL_PROFILES:
            p = builtin_profile(pid)
            for k, v in self.builtin_changes.get(pid, {}).items():
                if k == "roles":
                    p.roles = dict(p.roles, **v)
                elif k in SETTING_FIELDS or k == "prices":
                    setattr(p, k, v)
            return p
        return self.user_profiles.get(pid)

    def is_changed(self, pid: str) -> bool:
        return bool(self.builtin_changes.get(pid))

    def update(self, profile: Profile) -> None:
        """Stores a profile; for a built-in only what differs from its default."""
        if profile.builtin:
            default = builtin_profile(profile.id)
            changes = {k: getattr(profile, k) for k in SETTING_FIELDS + ["prices"]
                       if getattr(profile, k) != getattr(default, k)}
            roles = {r: m for r, m in profile.roles.items() if m and m != default.roles.get(r)}
            if roles:
                changes["roles"] = roles
            self.builtin_changes[profile.id] = changes
        else:
            self.user_profiles[profile.id] = profile

    def reset(self, pid: str) -> None:
        self.builtin_changes.pop(pid, None)

    def add_profile(self, label: str, connection: str = ANTHROPIC, copy_of: Optional[str] = None) -> Profile:
        base = self.profile(copy_of) if copy_of else None
        pid = self._free_id(label)
        if base is not None:
            p = replace(copy.deepcopy(base), id=pid, label=label, builtin=False)
        else:
            conn = self.connection(connection)
            first = next(iter(conn.models), "") if conn and not conn.is_anthropic else ""
            roles = builtin_roles("standard") if connection == ANTHROPIC else {r: first for r, _ in ROLES}
            p = Profile(id=pid, label=label, connection=connection, roles=roles,
                        temperature=None if connection == ANTHROPIC else 0.0)
        self.user_profiles[pid] = p
        return p

    def remove_profile(self, pid: str) -> None:
        self.user_profiles.pop(pid, None)

    def problems(self, profile: Profile) -> List[str]:
        """What would stop the profile from running."""
        out = []
        conn = self.connection(profile.connection)
        if conn is None:
            return [f"its connection '{profile.connection}' no longer exists"]
        for role, label in ROLES:
            if not (profile.roles.get(role) or "").strip() and role in ("structure_planner", "*"):
                out.append(f"no model for '{label}'")
        if not conn.is_anthropic:
            missing = sorted({m for m in profile.roles.values() if m and m not in conn.models})
            if missing:
                out.append(f"{', '.join(missing)} isn't among {conn.name}'s models (Test connection lists them)")
        return out


def summary(store: ModelStore, profile: Profile) -> str:
    """One profile in a few lines (the main window's hover text)."""
    conn = store.connection(profile.connection)
    lines = [f"<b>{profile.label}</b>" + (" (changed from the default)" if store.is_changed(profile.id) else ""),
             f"Runs on: {conn.name if conn else profile.connection}"]
    lines += [f"{label}: {profile.roles.get(role) or '-'}" for role, label in ROLES]
    if profile.description:
        lines.append(profile.description)
    return "<br>".join(lines)


def apply(config, profile_id: str, store: Optional[ModelStore] = None, key: str = ""):
    """`config` (a RunConfig) set up to run with the profile: where requests go, which model does what, and the
    profile's settings. `key`: the server connection's key (from the keychain). An unchanged built-in profile keeps
    RunConfig's own model choice (profile_roles empty), so its requests are exactly as before."""
    store = store or ModelStore()
    profile = store.profile(profile_id)
    if profile is None:
        raise errors.PipelineError(f"There's no model profile '{profile_id}'. Choose one in Models > Model "
                                   f"profiles….")
    conn = store.connection(profile.connection)
    problems = store.problems(profile)
    if problems:
        raise errors.PipelineError(f"The model profile '{profile.label}' can't run: {'; '.join(problems)}. Fix it in "
                                   f"Models > Model profiles….")
    changes = dict(model_profile=profile.id, max_tokens=profile.max_tokens, temperature=profile.temperature,
                   max_parallel_stages=profile.parallel_steps, max_retries=profile.retries,
                   prices=dict(profile.prices))
    if conn.is_anthropic:
        changes.update(provider=ANTHROPIC, profile_roles={} if (profile.builtin and not store.is_changed(profile.id))
                       else dict(profile.roles), prompt_caching=profile.prompt_caching and config.prompt_caching)
    else:
        changes.update(provider="local", profile_roles={}, local={
            "kind": conn.kind, "url": conn.url, "timeout_sec": conn.timeout_sec, "parallel": conn.parallel,
            "models": {n: asdict(m) for n, m in conn.models.items()}, "profiles": {profile.id: dict(profile.roles)},
            "api_key": key, "name": conn.name, "private": conn.is_private})
    return replace(config, **changes)          # replace: RunConfig.__post_init__ runs again (local: no caching)
