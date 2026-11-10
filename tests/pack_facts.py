"""
Facts about a data pack taken from the pack itself (2026-11-09), so tests that check rules about the app's own packs
(order of steps and categories, which categories the model may choose, how many requests a paper costs) don't break
when a module is linked or unlinked, a module gains a step or category, or a new module is added. Check the RULE
(this before that, these present, the shared ones last), and take what the linked modules bring from here.
"""
from typing import Iterable, List


def pack(pack_id: str):
    from parameter_extractor import packs
    return packs.available(include_template=True)[pack_id]


def module_category_ids(pack_id: str) -> List[str]:
    """Categories a pack has only because a linked module brings them (packs.Pack tags them with the module)."""
    return [c["id"] for c in pack(pack_id).manifest.variable_categories if c.get("module")]


def without_module_categories(ids: Iterable[str], pack_id: str) -> List[str]:
    extra = set(module_category_ids(pack_id))
    return [i for i in ids if i not in extra]


def step_names(pack_id: str) -> List[str]:
    """The pack's spec steps (its own and its modules'), in run order."""
    from parameter_extractor.stages.optional import load_specs
    return list(load_specs(pack(pack_id)))


def module_step_names(pack_id: str) -> List[str]:
    """Spec steps a pack has only through its linked modules (and the modules those need)."""
    p = pack(pack_id)
    names = {f.stem for mod in p.modules for f in mod.stage_files()}
    own = {f.stem for f in p.stages_dir.glob("*.json")} if p.stages_dir.is_dir() else set()
    return [n for n in step_names(pack_id) if n in names and n not in own]


def without_module_steps(names: Iterable[str], pack_id: str) -> List[str]:
    extra = set(module_step_names(pack_id))
    return [n for n in names if n not in extra]


def request_steps(pack_id: str) -> List[str]:
    """Every paper-reading step a pack may make after row planning: its built-in steps it uses, then its spec steps."""
    p = pack(pack_id)
    built_in = [n for n in ("chemistry", "analysis", "fit_models") if p.uses(n)]
    return built_in + step_names(pack_id)


def module_ids(pack_id: str) -> List[str]:
    """The modules a pack uses after resolving (linked ones + what they need)."""
    return [m.id for m in pack(pack_id).modules]


def in_order(seq: List[str], items: List[str]) -> bool:
    """Every item is in seq, in this relative order (other entries may sit between them)."""
    seq = list(seq)
    try:
        at = [seq.index(i) for i in items]
    except ValueError:
        return False
    return at == sorted(at)


def present_in_order(seq: List[str], items: List[str]) -> bool:
    """The items that ARE in seq keep this relative order (for things a module may or may not bring)."""
    return in_order(seq, [i for i in items if i in seq])


def linked(pack_id: str, *needed: str):
    """The pack with these modules linked, for tests of what a module DOES (its vocabulary, its step): the app's pack
    itself when it links them all (the usual case), else a copy that links them too, made once in this test
    process's data folder (tests/_isolation.py) -- so unlinking a module from an app pack doesn't fail the tests of
    that module. Use `.id` with packs.activate / RunConfig(pack=...)."""
    from parameter_extractor import modules, pack_modules, packs
    base = pack(pack_id)
    have = set(module_ids(pack_id))
    missing = [m for m in needed if modules.canonical_id(m) not in have]
    if not missing:
        return base
    import hashlib
    copy_id = f"{pack_id[:24]}_t{hashlib.md5(' '.join(sorted(missing)).encode()).hexdigest()[:8]}"   # one per set
    if copy_id not in packs.available():
        made = packs.create_pack(copy_id, base.manifest.label + " (test copy)", source=base)
        pack_modules.add_modules(made.folder, missing)
    return packs.available()[copy_id]


# The modules each app pack linked when its reference runs (runs/reference, runs/*_auto) were recorded. A replay
# reproduces those outputs only while the pack still links them: LINKING more never changes a replay (a step a
# recording lacks is replayed as finding nothing), UNLINKING one of these does, on purpose -- the pack then really
# extracts something else. The replays name the module in their failure message (`why_replay_differs`).
RECORDED_WITH = {
    "prebiotic_chemistry": ["analysis", "solution_chemistry", "kinetics", "wet_dry", "peptides_oligomers"],
    "exoplanets": [],
}


def unlinked_since_recording(pack_id: str = "prebiotic_chemistry") -> List[str]:
    from parameter_extractor import modules
    have = set(module_ids(pack_id))
    return [m for m in RECORDED_WITH.get(pack_id, []) if modules.canonical_id(m) not in have]


def why_replay_differs(pack_id: str = "prebiotic_chemistry") -> str:
    """For a replay's assertion message: the likely reason its output changed, if it's a module unlinked."""
    gone = unlinked_since_recording(pack_id)
    if not gone:
        return "replayed output differs from the reference (a code change, or a module changed its columns)"
    return (f"the {pack_id} pack no longer links {', '.join(gone)}, which the reference runs were recorded with: "
            f"its outputs really changed -- re-record the references (scripts/record_reference.py) and update "
            f"tests/pack_facts.RECORDED_WITH, or link the module again")


def module_of_step(step: str) -> str:
    """The app module whose step this is ('wet_dry' -> 'wet_dry', 'oligomer_linkage' -> 'peptides_oligomers')."""
    from parameter_extractor import modules
    for mid, mod in modules.available().items():
        if any(f.stem == step for f in mod.stage_files()):
            return mid
    raise KeyError(f"no module has a step '{step}'")


def module_step(step: str, pack_id: str = "prebiotic_chemistry"):
    """A module's step (StageSpec) as a pack linking that module sees it -- for tests of the step itself."""
    from parameter_extractor.stages.optional import load_specs
    return load_specs(linked(pack_id, module_of_step(step)))[step]
