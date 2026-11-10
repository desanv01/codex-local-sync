"""Pure adapter for the supported account-renderer settings schema.

Only local organization metadata enters a normalized view. Everything else is
retained in its original account. No function in this module performs I/O.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

from .errors import CompatibilityError, ValidationError

PROFILE_KEY = "electron-account-renderer-state-v1"
ATOM_KEY = "electron-persisted-atom-state"
MAP_FIELDS = {
    "projects": "local-projects",
    "assignments": "thread-project-assignments",
    "hosts": "thread-project-membership-host-ids",
    "thread_orders": "sidebar-project-thread-orders",
    "appearances": "project-appearances",
    "hints": "thread-workspace-root-hints",
    "outputs": "thread-projectless-output-directories",
}
LIST_FIELDS = {"project_order": "project-order", "pins": "pinned-thread-ids",
               "projectless": "projectless-thread-ids"}
ORDER_ATOMS = ("unified-sidebar-project-order-v1", "unified-sidebar-pinned-order-v1")
PREF_ATOMS = ("flat-project-sidebar-preferences-v1", "sidebar-project-list-expanded-v1")
IDS_KEY = "app-server-project-id-by-legacy-project-id-by-host"
_UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
_PROJECT_FIELDS = {"id", "name", "rootPaths", "createdAt", "updatedAt"}
_ASSIGNMENT_FIELDS = {"projectId", "projectKind"}
_APPEARANCE_FIELDS = {"color", "icon", "emoji"}
_EXPANDED = "sidebar-project-expanded-v1-codex:"
_FLAT_PREF_FIELDS = {"mode", "chatSortMode", "projectSortMode", "initialized"}


def empty_view() -> dict:
    return {**{key: {} for key in MAP_FIELDS},
            **{key: [] for key in LIST_FIELDS}, "ids": {}, "preferences": {},
            "atom_orders": {key: [] for key in ORDER_ATOMS}}


def _mapping(value, label: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(k, str) or not k for k in value):
        raise CompatibilityError(f"Unsupported {label} map; sync paused.")
    return value


def _strings(value, label: str) -> list:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise CompatibilityError(f"Unsupported {label} list; sync paused.")
    if len(set(value)) != len(value):
        raise ValidationError(f"Duplicate entries in {label}.")
    return value


def _identity(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 512 and not any(ord(c) < 32 for c in value)


def _profiles(state: dict) -> dict[str, tuple[dict, dict]]:
    _mapping(state, "settings")
    envelope = state.get(PROFILE_KEY)
    if not isinstance(envelope, dict) or set(envelope) != {"owner", "inactive"}:
        raise CompatibilityError("Unknown account profile schema; sync paused.")
    owner = envelope["owner"]
    if owner is not None and not _identity(owner):
        raise CompatibilityError("Invalid active account key; sync paused.")
    inactive = _mapping(envelope["inactive"], "inactive profiles")
    if owner in inactive or any(not _identity(key) for key in inactive):
        raise CompatibilityError("Invalid or duplicate account keys; sync paused.")
    atoms = _mapping(state.get(ATOM_KEY, {}), "active atoms")
    # Signed-out settings keep every account in inactive snapshots. Top-level
    # globals and atoms then belong to no selected account and remain untouched.
    result = {owner: (state, atoms)} if owner is not None else {}
    for identity, record in inactive.items():
        if not isinstance(record, dict) or not isinstance(record.get("globals"), dict) or not isinstance(record.get("atoms"), dict):
            raise CompatibilityError("Incomplete saved account snapshot; sync paused.")
        result[identity] = (record["globals"], _mapping(record["atoms"], "saved atoms"))
    for globals_, _ in result.values():
        # These maps distinguish an actual organization snapshot from a partial
        # account switch. Missing optional fields never imply a deletion.
        has_projects = "local-projects" in globals_
        has_assignments = "thread-project-assignments" in globals_
        if has_projects != has_assignments and (globals_.get("local-projects") or globals_.get("thread-project-assignments")):
            raise CompatibilityError("Incomplete organization snapshot; sync paused.")
        for key in (*MAP_FIELDS.values(), IDS_KEY):
            _mapping(globals_.get(key, {}), "organization metadata")
        for key in LIST_FIELDS.values():
            _strings(globals_.get(key, []), "organization order")
    return result


def _local_thread(identifier, globals_: dict) -> bool:
    if not isinstance(identifier, str) or not _UUID.fullmatch(identifier):
        return False
    hosts = globals_.get(MAP_FIELDS["hosts"], {})
    assignments = globals_.get(MAP_FIELDS["assignments"], {})
    if identifier in hosts and hosts[identifier] != "local":
        return False
    assignment = assignments.get(identifier)
    if identifier in assignments and not isinstance(assignment, dict):
        return False
    if isinstance(assignment, dict) and assignment.get("projectKind") != "local":
        return False
    if isinstance(assignment, dict):
        project = assignment.get("projectId")
        if not isinstance(project, str) or not project:
            return False
        if isinstance(project, str):
            if project.startswith("g-p-"):
                return False
            record = globals_.get(MAP_FIELDS["projects"], {}).get(project)
            if record is not None and not _project(project, record):
                return False
    return hosts.get(identifier) == "local" or isinstance(assignment, dict)


def _incoming_thread_allowed(identifier: str, globals_: dict) -> bool:
    """An unknown destination may accept proven local source metadata.

    Source classification requires positive evidence, while a destination only
    needs to establish that no explicit account-scoped record would be changed.
    """
    if identifier not in globals_.get(MAP_FIELDS["hosts"], {}) and identifier not in globals_.get(MAP_FIELDS["assignments"], {}):
        return True
    return _local_thread(identifier, globals_)


def _project(identifier: str, value) -> bool:
    if identifier.startswith("g-p-"):
        return False
    if not isinstance(value, dict) or "rootPaths" not in value:
        raise CompatibilityError("Unknown local project record; sync paused.")
    roots = _strings(value["rootPaths"], "project roots")
    for key in ("id", "name"):
        if key in value and not isinstance(value[key], str):
            raise CompatibilityError("Unknown project identity format; sync paused.")
    if "id" in value and value["id"] != identifier:
        raise CompatibilityError("Inconsistent local project identity; sync paused.")
    for key in ("createdAt", "updatedAt"):
        if key in value and (isinstance(value[key], bool) or not isinstance(value[key], (str, int, float))):
            raise CompatibilityError("Unknown project timestamp format; sync paused.")
    return not any(".chatgpt-projects" in path.replace("\\", "/").lower().split("/") for path in roots)


def _project_records(globals_: dict) -> dict:
    return {key: {k: deepcopy(v) for k, v in value.items() if k in _PROJECT_FIELDS}
            for key, value in globals_.get(MAP_FIELDS["projects"], {}).items() if _project(key, value)}


def _normalize(globals_: dict, atoms: dict, known: set[str]) -> dict:
    view = empty_view()
    view["projects"] = _project_records(globals_)
    local = lambda value: _local_thread(value, globals_)
    for key, record in globals_.get(MAP_FIELDS["assignments"], {}).items():
        if not local(key):
            continue
        if not isinstance(record, dict):
            raise CompatibilityError("Unknown thread assignment format; sync paused.")
        if record.get("projectKind") == "local":
            if not isinstance(record.get("projectId"), str):
                raise CompatibilityError("Invalid local project reference; sync paused.")
            # Retain dangling local references so the engine can explicitly
            # report safe unassignment, rather than silently infer a deletion.
            view["assignments"][key] = {k: deepcopy(v) for k, v in record.items() if k in _ASSIGNMENT_FIELDS}
    for category in ("hosts", "hints", "outputs"):
        for key, value in globals_.get(MAP_FIELDS[category], {}).items():
            if local(key):
                if category == "hosts" and value != "local":
                    continue
                if category != "hosts" and not isinstance(value, str):
                    raise CompatibilityError("Unknown local thread metadata; sync paused.")
                view[category][key] = deepcopy(value)
    # Appearance schema has not been verified. Keep those records entirely
    # account scoped until a future adapter explicitly supports their shape.
    for category in ("thread_orders",):
        for key, value in globals_.get(MAP_FIELDS[category], {}).items():
            if key not in known:
                continue
            if category == "thread_orders":
                if not isinstance(value, dict) or "threadIds" not in value:
                    raise CompatibilityError("Unknown project thread order format; sync paused.")
                view[category][key] = {"threadIds": [v for v in _strings(value["threadIds"], "project thread order") if local(v)]}
    for category, key in LIST_FIELDS.items():
        view[category] = [v for v in globals_.get(key, []) if (v in known if category == "project_order" else local(v))]
    for host, values in globals_.get(IDS_KEY, {}).items():
        if host.startswith("local:"):
            for key, value in _mapping(values, "local project ids").items():
                if key in known:
                    if not isinstance(value, str):
                        raise CompatibilityError("Unknown local server project id; sync paused.")
                    view["ids"][json.dumps([host, key])] = value
    for key, value in atoms.items():
        if key == "sidebar-project-list-expanded-v1" or key.startswith(_EXPANDED) and key[len(_EXPANDED):] in known:
            if not isinstance(value, bool):
                raise CompatibilityError("Unknown sidebar preference format; sync paused.")
            view["preferences"][key] = value
        elif key == "flat-project-sidebar-preferences-v1":
            # Only observed sidebar controls are portable; future atom fields
            # remain at their original account.
            values = _mapping(value, "flat sidebar preferences")
            view["preferences"][key] = {k: deepcopy(v) for k, v in values.items() if k in _FLAT_PREF_FIELDS}
            if any(not isinstance(v, (str, bool)) for v in view["preferences"][key].values()):
                raise CompatibilityError("Unknown sidebar preference value; sync paused.")
    for key in ORDER_ATOMS:
        view["atom_orders"][key] = [v for v in _strings(atoms.get(key, []), "sidebar atom order") if
            v.startswith("codex:project:") and v[14:] in known or
            v.startswith("codex:thread:local:") and local(v[19:])]
    return view


def discover_profiles(state: dict) -> list[dict]:
    profiles = _profiles(state)
    known = set().union(*(set(_project_records(g)) for g, _ in profiles.values()))
    result = []
    for identity, (globals_, atoms) in profiles.items():
        view = _normalize(globals_, atoms, known)
        result.append({"id": identity, "active": identity == state[PROFILE_KEY]["owner"],
                       "project_count": len(view["projects"]), "assignment_count": len(view["assignments"])})
    return result


def snapshot_profiles(state: dict, profile_ids: list[str]) -> dict[str, dict]:
    if not isinstance(profile_ids, list) or not profile_ids or any(not _identity(i) for i in profile_ids) or len(set(profile_ids)) != len(profile_ids):
        raise ValidationError("Select distinct valid account keys.")
    profiles = _profiles(state)
    if any(identity not in profiles for identity in profile_ids):
        raise CompatibilityError("Selected account snapshot is unavailable; sync paused.")
    known = set().union(*(set(_project_records(profiles[i][0])) for i in profile_ids))
    return {identity: _normalize(*profiles[identity], known) for identity in profile_ids}


def validate_view(view: dict) -> None:
    if not isinstance(view, dict) or set(view) != set(empty_view()):
        raise ValidationError("Unknown normalized view schema.")
    try:
        for key in (*MAP_FIELDS, "ids", "preferences", "atom_orders"):
            _mapping(view[key], "normalized metadata")
        for key in LIST_FIELDS:
            _strings(view[key], "normalized order")
        projects = set(view["projects"])
        for key, value in view["projects"].items():
            if not _project(key, value) or set(value) - _PROJECT_FIELDS:
                raise ValidationError("View contains a nonlocal project.")
        for key, value in view["assignments"].items():
            if not _UUID.fullmatch(key) or not isinstance(value, dict) or set(value) - _ASSIGNMENT_FIELDS or value.get("projectKind") != "local" or value.get("projectId") not in projects:
                raise ValidationError("View contains an invalid local assignment.")
        for category in ("hosts", "hints", "outputs"):
            for key, value in view[category].items():
                if not _UUID.fullmatch(key) or category == "hosts" and value != "local":
                    raise ValidationError("View contains nonlocal thread metadata.")
                if category != "hosts" and not isinstance(value, str):
                    raise ValidationError("Invalid thread metadata value.")
        for category in ("thread_orders", "appearances"):
            if set(view[category]) - projects:
                raise ValidationError("View references an absent project.")
        if view["appearances"]:
            raise ValidationError("Appearance synchronization is unsupported by this adapter.")
        for project, order in view["thread_orders"].items():
            if not isinstance(order, dict) or set(order) != {"threadIds"}:
                raise ValidationError("Unknown normalized thread order schema.")
            if any(not _UUID.fullmatch(v) for v in _strings(order["threadIds"], "thread order")):
                raise ValidationError("View contains a nonlocal thread order.")
            if any(view["assignments"].get(thread, {}).get("projectId") != project for thread in order["threadIds"]):
                raise ValidationError("Thread order references an unassigned or different-project thread.")
        for value in view["appearances"].values():
            if not isinstance(value, dict) or set(value) - _APPEARANCE_FIELDS or any(not isinstance(v, str) for v in value.values()):
                raise ValidationError("Invalid appearance metadata.")
        if set(view["project_order"]) - projects or any(not _UUID.fullmatch(v) for key in ("pins", "projectless") for v in view[key]):
            raise ValidationError("Invalid project or thread order reference.")
        if set(view["projectless"]) & set(view["assignments"]):
            raise ValidationError("A thread cannot be both assigned and projectless.")
        for encoded, value in view["ids"].items():
            pair = json.loads(encoded)
            if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(v, str) for v in pair) or not pair[0].startswith("local:") or pair[1] not in projects or not isinstance(value, str):
                raise ValidationError("Invalid local server project mapping.")
        if set(view["atom_orders"]) != set(ORDER_ATOMS):
            raise ValidationError("Unknown sidebar order atoms.")
        for values in view["atom_orders"].values():
            for value in _strings(values, "atom order"):
                if not (value.startswith("codex:project:") and value[14:] in projects or value.startswith("codex:thread:local:") and _UUID.fullmatch(value[19:])):
                    raise ValidationError("Invalid local sidebar order reference.")
        for key, value in view["preferences"].items():
            if key == "flat-project-sidebar-preferences-v1":
                if not isinstance(value, dict) or set(value) - _FLAT_PREF_FIELDS or any(not isinstance(v, (str, bool)) for v in value.values()):
                    raise ValidationError("Unknown sidebar preference field.")
            elif not (key == "sidebar-project-list-expanded-v1" or key.startswith(_EXPANDED) and key[len(_EXPANDED):] in projects) or not isinstance(value, bool):
                raise ValidationError("Unknown sidebar preference.")
        json.dumps(view, allow_nan=False)
    except (CompatibilityError, TypeError, ValueError) as error:
        raise ValidationError("Invalid normalized organization metadata.") from error


def _replace(existing: dict, previous: dict, desired: dict) -> dict:
    result = deepcopy(existing)
    for key in previous.keys() | desired.keys():
        if key in desired:
            result[key] = deepcopy(desired[key])
        else:
            result.pop(key, None)
    return result


def _place(existing: list, previous: list, desired: list) -> list:
    scoped = set(previous) | set(desired)
    result, inserted = [], False
    for value in existing:
        if value in scoped:
            if not inserted:
                result.extend(desired)
                inserted = True
        else:
            result.append(value)
    if not inserted:
        result.extend(desired)
    return result


def _records(existing: dict, previous: dict, desired: dict, fields: set) -> dict:
    result = deepcopy(existing)
    for key in previous.keys() | desired.keys():
        if key in desired and key in existing and key not in previous:
            raise CompatibilityError("Incoming local metadata collides with account-scoped metadata; review required.")
        current = result.get(key, {})
        extras = {k: deepcopy(v) for k, v in current.items() if k not in fields} if isinstance(current, dict) else {}
        if key in desired:
            result[key] = {**extras, **deepcopy(desired[key])}
        elif extras:
            # Removing a record carrying unknown metadata would destroy data
            # whose ownership this adapter cannot prove.
            raise CompatibilityError("Removal would discard unknown record metadata; review required.")
        else:
            result.pop(key, None)
    return result


def apply_views(state: dict, views: dict[str, dict]) -> dict:
    _mapping(views, "profile views")
    if not views:
        raise ValidationError("No account views selected.")
    for view in views.values():
        validate_view(view)
    previous = snapshot_profiles(state, list(views))
    result = deepcopy(state)
    targets = _profiles(result)
    for identity, desired in views.items():
        globals_, atoms = targets[identity]
        before = previous[identity]
        incoming_threads = set(desired["assignments"]) | set(desired["hosts"]) | set(desired["hints"]) | set(desired["outputs"]) | set(desired["pins"]) | set(desired["projectless"])
        incoming_threads.update(v[19:] for order in desired["atom_orders"].values() for v in order if v.startswith("codex:thread:local:"))
        incoming_threads.update(v for record in desired["thread_orders"].values() for v in record["threadIds"])
        if any(not _incoming_thread_allowed(thread, globals_) for thread in incoming_threads):
            raise CompatibilityError("Incoming thread conflicts with an account-scoped host; review required.")
        for category, key in MAP_FIELDS.items():
            if category == "appearances":
                continue
            existing = globals_.get(key, {})
            if category in ("projects", "assignments", "appearances"):
                fields = {"projects": _PROJECT_FIELDS, "assignments": _ASSIGNMENT_FIELDS, "appearances": _APPEARANCE_FIELDS}[category]
                value = _records(existing, before[category], desired[category], fields)
            elif category == "thread_orders":
                value = deepcopy(existing)
                for project in before[category].keys() | desired[category].keys():
                    record = deepcopy(existing.get(project, {}))
                    order = _place(record.get("threadIds", []), before[category].get(project, {}).get("threadIds", []), desired[category].get(project, {}).get("threadIds", []))
                    if project in desired[category] or order:
                        record["threadIds"] = order
                        value[project] = record
                    elif set(record) - {"threadIds"}:
                        raise CompatibilityError("Removal would discard unknown thread order metadata; review required.")
                    else:
                        value.pop(project, None)
            else:
                value = _replace(existing, before[category], desired[category])
            if key in globals_ or value:
                globals_[key] = value
        for category, key in LIST_FIELDS.items():
            value = _place(globals_.get(key, []), before[category], desired[category])
            if key in globals_ or value:
                globals_[key] = value
        mappings = deepcopy(globals_.get(IDS_KEY, {}))
        for encoded in before["ids"].keys() | desired["ids"].keys():
            host, project = json.loads(encoded)
            if encoded in desired["ids"]:
                mappings.setdefault(host, {})[project] = deepcopy(desired["ids"][encoded])
            elif host in mappings:
                mappings[host].pop(project, None)
        if IDS_KEY in globals_ or mappings:
            globals_[IDS_KEY] = mappings
        for key in before["preferences"].keys() | desired["preferences"].keys():
            if key == "flat-project-sidebar-preferences-v1":
                atoms[key] = _replace(atoms.get(key, {}), before["preferences"].get(key, {}), desired["preferences"].get(key, {}))
            elif key in desired["preferences"]:
                atoms[key] = deepcopy(desired["preferences"][key])
            else:
                atoms.pop(key, None)
        for key in ORDER_ATOMS:
            value = _place(atoms.get(key, []), before["atom_orders"][key], desired["atom_orders"][key])
            if key in atoms or value:
                atoms[key] = value
        if identity == result[PROFILE_KEY]["owner"] and atoms and ATOM_KEY not in result:
            result[ATOM_KEY] = atoms
    return result
