"""Pure, conservative two-profile merge planning. No filesystem side effects.

Each profile is compared with its own last observation. Disjoint edits merge;
competing edits to a record or an ordering stop the entire plan. Missing values
are retained unless removals were explicitly enabled. Project deletion safely
unassigns local threads and removes dangling project presentation metadata.
"""
from __future__ import annotations

from copy import deepcopy
import json

from .errors import CompatibilityError, ValidationError
from .state import (ATOM_KEY, IDS_KEY, LIST_FIELDS, MAP_FIELDS, PROFILE_KEY,
                    apply_views, snapshot_profiles, validate_view)

_LISTS = {"project_order", "pins", "projectless"}
_MISSING = object()


def validate_config(config: dict) -> None:
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise CompatibilityError("Unsupported configuration schema.")
    profiles = config.get("profile_ids")
    if (not isinstance(profiles, list) or len(profiles) != 2
            or not all(isinstance(p, str) and p for p in profiles)
            or len(set(profiles)) != 2):
        raise ValidationError("Select exactly two distinct profile IDs.")
    if config.get("seed_profile") not in (None, *profiles):
        raise ValidationError("The seed must be one of the selected profiles.")
    if not isinstance(config.get("allow_removals", False), bool):
        raise ValidationError("allow_removals must be a boolean.")


def _nonempty(view: dict) -> bool:
    return any(bool(value) for key, value in view.items()
               if key != "atom_orders") or any(view.get("atom_orders", {}).values())


def _same(a, b) -> bool:
    return a is b or (a is not _MISSING and b is not _MISSING and a == b)


def _unique(values: list) -> list:
    return list(dict.fromkeys(values))


def _retain_omitted(state: dict, profile: str, current: dict, before: dict) -> None:
    """An absent whole field is an incomplete observation, never a removal."""
    envelope = state[PROFILE_KEY]
    if envelope["owner"] == profile:
        globals_, atoms = state, state.get(ATOM_KEY, {})
    else:
        record = envelope["inactive"][profile]
        globals_, atoms = record["globals"], record["atoms"]
    for category, key in {**MAP_FIELDS, **LIST_FIELDS, "ids": IDS_KEY}.items():
        if key not in globals_:
            current[category] = deepcopy(before[category])
    for key, value in before["atom_orders"].items():
        if key not in atoms:
            current["atom_orders"][key] = deepcopy(value)
    for key, value in before["preferences"].items():
        if key not in atoms:
            current["preferences"][key] = deepcopy(value)


def _validate_observation(view: dict) -> None:
    try:
        normalized = deepcopy(view)
        _safe_references(normalized, [])
        validate_view(normalized)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValidationError("Invalid source observation in sync journal.") from exc


def _safe_references(view: dict, warnings: list[str]) -> None:
    """Project removals unassign rather than delete local chat organization."""
    projects = set(view["projects"])
    for thread, assignment in list(view["assignments"].items()):
        if assignment.get("projectId") not in projects:
            del view["assignments"][thread]
            if thread not in view["projectless"]:
                view["projectless"].append(thread)
            warnings.append("A removed project's local thread was safely unassigned.")
    for category in ("thread_orders", "appearances"):
        view[category] = {k: v for k, v in view[category].items() if k in projects}
    view["project_order"] = [p for p in view["project_order"] if p in projects]
    for encoded in list(view["ids"]):
        try:
            _, project = json.loads(encoded)
        except (ValueError, TypeError):
            raise ValidationError("Malformed local project identifier mapping.") from None
        if project not in projects:
            del view["ids"][encoded]
    prefix = "sidebar-project-expanded-v1-codex:"
    for key in list(view["preferences"]):
        if key.startswith(prefix) and key[len(prefix):] not in projects:
            del view["preferences"][key]
    for key, order in view["atom_orders"].items():
        view["atom_orders"][key] = [v for v in order if not v.startswith("codex:project:")
                                    or v[len("codex:project:"):] in projects]
    # A local chat cannot simultaneously be assigned and projectless.
    view["projectless"] = [t for t in view["projectless"] if t not in view["assignments"]]
    for project, order in view["thread_orders"].items():
        order["threadIds"] = [t for t in order["threadIds"]
            if t in view["assignments"] and view["assignments"][t].get("projectId") == project]


def _merge_order(base: list, edits: list[tuple[str, list, list]], removals: bool,
                 path: str, tombstones: dict, conflicts: list) -> list:
    removed = set()
    additions = []
    orders = []
    for profile, before, current in edits:
        deleted = set(before) - set(current) if removals else set()
        added = [v for v in current if v not in before]
        removed.update(deleted)
        additions.extend(added)
        if before != current:
            orders.append((profile, current))
        for value in deleted:
            tombstones[json.dumps([path, value])] = True
        for value in added:
            tombstones.pop(json.dumps([path, value]), None)
    if set(additions) & removed:
        conflicts.append({"category": path, "reason": "Concurrent addition and removal."})
    for i, (_, left) in enumerate(orders):
        for _, right in orders[i + 1:]:
            common = set(left) & set(right)
            if [v for v in left if v in common] != [v for v in right if v in common]:
                conflicts.append({"category": path, "reason": "Competing order edits."})
    result = [v for v in base if v not in removed]
    if orders:
        result = _unique(orders[0][1] + result)
    result = _unique(result + additions)
    return [v for v in result if v not in removed
            and json.dumps([path, v]) not in tombstones]


def plan_sync(state: dict, journal: dict | None, config: dict) -> dict:
    """Return a complete proposal; a conflicted plan preserves state and journal.

    ``seen`` records source observations, not hypothetical applied views. The
    storage transaction advances it to actual applied views after a sync. This
    distinction lets watcher captures collect chronological edits without
    replaying an unchanged stale inactive-account snapshot.
    """
    validate_config(config)
    profiles = config["profile_ids"]
    current = snapshot_profiles(state, profiles)
    if set(current) != set(profiles):
        raise ValidationError("Both complete selected account snapshots are required.")
    warnings: list[str] = []
    conflicts: list[dict] = []
    changes: list[dict] = []
    removals = config.get("allow_removals", False)
    previous_assignments = {}
    if isinstance(journal, dict) and isinstance(journal.get("canonical"), dict):
        previous_assignments = deepcopy(journal["canonical"].get("assignments", {}))
    if journal is None:
        seed = config.get("seed_profile")
        if seed not in profiles:
            raise ValidationError("Initial synchronization requires an explicit seed profile.")
        if not _nonempty(current[seed]) and any(_nonempty(v) for v in current.values()):
            raise ValidationError("The selected seed snapshot is empty; review before synchronization.")
        canonical = deepcopy(current[seed])
        other = next(p for p in profiles if p != seed)
        for category, values in current[other].items():
            if category in _LISTS:
                canonical[category] = _unique(canonical[category] + values)
            elif category == "atom_orders":
                for key, value in values.items():
                    canonical[category][key] = _unique(canonical[category].get(key, []) + value)
            else:
                canonical[category] = {**deepcopy(values), **canonical[category]}
        result_journal = {"schema_version": 1, "profile_ids": list(profiles),
                          "canonical": canonical, "seen": deepcopy(current), "tombstones": {}}
    else:
        if not isinstance(journal, dict) or journal.get("schema_version") != 1:
            raise CompatibilityError("Unsupported sync journal schema.")
        if journal.get("profile_ids", profiles) != profiles:
            raise ValidationError("The journal belongs to a different selected profile pair.")
        if not isinstance(journal.get("seen"), dict) or set(journal["seen"]) != set(profiles):
            raise ValidationError("The journal has incomplete profile observations.")
        canonical = deepcopy(journal.get("canonical"))
        validate_view(canonical)
        for p in profiles:
            if not isinstance(journal["seen"][p], dict) or set(journal["seen"][p]) != set(canonical):
                raise ValidationError("Invalid profile observation in sync journal.")
            _validate_observation(journal["seen"][p])
            if _nonempty(journal["seen"][p]) and not _nonempty(current[p]):
                raise ValidationError("A previously populated account snapshot is empty; synchronization paused.")
            if journal["seen"][p]["projects"] and not current[p]["projects"]:
                raise ValidationError("All local projects disappeared from a snapshot; review required.")
            _retain_omitted(state, p, current[p], journal["seen"][p])
        result_journal = deepcopy(journal)
        tombstones = result_journal.setdefault("tombstones", {})
        if not isinstance(tombstones, dict):
            raise ValidationError("Invalid removal tombstones.")
        for category, values in canonical.items():
            if category in _LISTS:
                edits = [(p, journal["seen"][p][category], current[p][category]) for p in profiles]
                canonical[category] = _merge_order(values, edits, removals, category, tombstones, conflicts)
                continue
            if category == "atom_orders":
                keys = set(values)
                for p in profiles:
                    keys.update(current[p][category])
                for key in keys:
                    edits = [(p, journal["seen"][p][category].get(key, []),
                              current[p][category].get(key, [])) for p in profiles]
                    values[key] = _merge_order(values.get(key, []), edits, removals,
                                              category + "/" + key, tombstones, conflicts)
                continue
            keys = set(values)
            for p in profiles:
                keys.update(journal["seen"][p][category])
                keys.update(current[p][category])
            for key in sorted(keys):
                edits = []
                for p in profiles:
                    before = journal["seen"][p][category].get(key, _MISSING)
                    now = current[p][category].get(key, _MISSING)
                    if not _same(before, now) and (removals or now is not _MISSING):
                        edits.append((p, now))
                if not edits:
                    continue
                if category == "thread_orders" and all(value is not _MISSING for _, value in edits):
                    order_edits = [(p, journal["seen"][p][category].get(key, {}).get("threadIds", []),
                                    current[p][category].get(key, {}).get("threadIds", [])) for p in profiles]
                    values[key] = {"threadIds": _merge_order(values.get(key, {}).get("threadIds", []),
                        order_edits, removals, category + "/" + key, tombstones, conflicts)}
                    continue
                if any(not _same(edits[0][1], value) for _, value in edits[1:]):
                    conflicts.append({"category": category, "key": key,
                                      "reason": "Competing record edits.",
                                      "profiles": [p for p, _ in edits]})
                    continue
                value = edits[0][1]
                token = json.dumps([category, key])
                if value is _MISSING:
                    values.pop(key, None)
                    tombstones[token] = True
                else:
                    values[key] = deepcopy(value)
                    tombstones.pop(token, None)
        result_journal["canonical"] = canonical
        result_journal["seen"] = deepcopy(current)
    if conflicts:
        return {"state": deepcopy(state), "journal": deepcopy(journal), "changes": [],
                "conflicts": conflicts, "warnings": warnings, "changed": False}
    for thread, assignment in previous_assignments.items():
        if (assignment.get("projectId") not in canonical["projects"]
                and thread not in canonical["assignments"] and thread not in canonical["projectless"]):
            canonical["projectless"].append(thread)
            warnings.append("A removed project's local thread was safely unassigned.")
    _safe_references(canonical, warnings)
    validate_view(canonical)
    proposed = apply_views(state, {p: deepcopy(canonical) for p in profiles})
    for p in profiles:
        for category in canonical:
            if current[p][category] != canonical[category]:
                changes.append({"profile": p, "category": category})
    return {"state": proposed, "journal": result_journal, "changes": changes,
            "conflicts": conflicts, "warnings": list(dict.fromkeys(warnings)),
            "changed": proposed != state}
