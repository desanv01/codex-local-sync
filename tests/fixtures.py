"""Invented account IDs, paths, and UUIDs; no captured application data."""

from copy import deepcopy

from codex_local_sync.state import ATOM_KEY, PROFILE_KEY

A, B = "synthetic-account-a", "synthetic-account-b"
T = "00000000-0000-4000-8000-000000000001"
REMOTE = "00000000-0000-4000-8000-000000000002"
P, Q = "synthetic-project-one", "synthetic-project-two"


def config(**overrides):
    return {"schema_version": 1, "profile_ids": [A, B], "seed_profile": A,
            "allow_removals": False, "aliases": {A: "Alpha", B: "Beta"}, **overrides}


def state():
    """A populated seed and an explicitly empty complete destination."""
    return {
        PROFILE_KEY: {"owner": A, "inactive": {
            B: {"globals": {"local-projects": {}, "thread-project-assignments": {},
                            "permissions": {"synthetic-permission": "beta-only"},
                            "account-identity": "beta-only"},
                "atoms": {"synthetic-private-atom": "beta-only"}},
        }},
        ATOM_KEY: {"synthetic-private-atom": "alpha-only",
                   "unified-sidebar-project-order-v1": ["cloud:synthetic", f"codex:project:{P}"]},
        "local-projects": {
            P: {"name": "One", "rootPaths": ["C:/synthetic/one"]},
            Q: {"name": "Two", "rootPaths": ["C:/synthetic/two"]},
            "g-p-synthetic-cloud": {"cloud-only": "alpha-only"},
        },
        "thread-project-assignments": {
            T: {"projectId": P, "projectKind": "local"},
            REMOTE: {"projectId": "remote-project", "projectKind": "local"},
            "cloud:synthetic-thread": {"projectId": "g-p-synthetic-cloud", "projectKind": "cloud"},
        },
        "thread-project-membership-host-ids": {T: "local", REMOTE: "ssh:synthetic"},
        "project-order": [P, Q, "g-p-synthetic-cloud"],
        "project-appearances": {P: {"color": "blue"}},
        "pinned-thread-ids": [T, "cloud:synthetic-thread", REMOTE],
        "account-identity": "alpha-only",
        "credentials": {"synthetic-marker": "alpha-only"},
        "permissions": {"synthetic-permission": "alpha-only"},
        "remote-settings": {"synthetic-marker": "alpha-only"},
    }


def accepted(plan):
    """Advance a pure plan's journal as a successful storage commit would."""
    from codex_local_sync.state import snapshot_profiles
    journal = deepcopy(plan["journal"])
    journal["seen"] = snapshot_profiles(plan["state"], [A, B])
    return plan["state"], journal
