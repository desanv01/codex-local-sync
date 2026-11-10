"""Focused merge guards and local-only organization boundaries."""

from copy import deepcopy
import unittest

from codex_local_sync.engine import plan_sync
from codex_local_sync.errors import SyncError, ValidationError
from codex_local_sync.state import ATOM_KEY, PROFILE_KEY, apply_views, snapshot_profiles, validate_view
from tests.fixtures import A, B, P, Q, T, REMOTE, accepted, config, state


class MergeTests(unittest.TestCase):
    def baseline(self, **options):
        return accepted(plan_sync(state(), None, config(**options)))

    def test_bootstrap_preserves_scoped_cloud_remote_permissions_and_unknowns(self):
        original = state()
        original["local-projects"][P]["synthetic-account-only-field"] = "alpha-only"
        original["sidebar-project-thread-orders"] = {
            P: {"threadIds": [T, REMOTE], "synthetic-private-order-field": "alpha-only"}}
        untouched = deepcopy(original)
        plan = plan_sync(original, None, config())
        result = plan["state"]
        self.assertTrue(plan["changed"])
        self.assertEqual(untouched, original, "pure planning mutated the input")
        views = snapshot_profiles(result, [A, B])
        self.assertEqual(views[A], views[B])
        self.assertEqual({P, Q}, set(views[B]["projects"]))
        self.assertEqual("alpha-only", result["local-projects"][P]["synthetic-account-only-field"])
        self.assertNotIn("synthetic-account-only-field", result[PROFILE_KEY]["inactive"][B]["globals"]["local-projects"][P])
        self.assertEqual("alpha-only", result["sidebar-project-thread-orders"][P]["synthetic-private-order-field"])
        self.assertIn(REMOTE, result["sidebar-project-thread-orders"][P]["threadIds"])
        self.assertNotIn("synthetic-private-order-field", result[PROFILE_KEY]["inactive"][B]["globals"]["sidebar-project-thread-orders"][P])
        self.assertNotIn(REMOTE, views[B]["assignments"])
        for key in ("account-identity", "credentials", "permissions", "remote-settings"):
            self.assertEqual(original[key], result[key])
        for key in ("credentials", "remote-settings"):
            self.assertNotIn(key, result[PROFILE_KEY]["inactive"][B]["globals"])
        self.assertEqual(original[PROFILE_KEY]["inactive"][B]["globals"]["permissions"],
                         result[PROFILE_KEY]["inactive"][B]["globals"]["permissions"])
        self.assertEqual("beta-only", result[PROFILE_KEY]["inactive"][B]["globals"]["account-identity"])
        self.assertEqual("alpha-only", result[ATOM_KEY]["synthetic-private-atom"])
        self.assertEqual("beta-only", result[PROFILE_KEY]["inactive"][B]["atoms"]["synthetic-private-atom"])
        self.assertEqual(original["local-projects"]["g-p-synthetic-cloud"],
                         result["local-projects"]["g-p-synthetic-cloud"])
        self.assertEqual(original["thread-project-assignments"][REMOTE],
                         result["thread-project-assignments"][REMOTE])
        self.assertEqual(original["thread-project-assignments"]["cloud:synthetic-thread"],
                         result["thread-project-assignments"]["cloud:synthetic-thread"])
        self.assertIn("cloud:synthetic", result[ATOM_KEY]["unified-sidebar-project-order-v1"])

    def test_missing_both_maps_in_fresh_destination_can_bootstrap(self):
        for empty_active in (False, True):
            with self.subTest(empty_active=empty_active):
                initial = state()
                if empty_active:
                    initial[PROFILE_KEY]["owner"] = B
                    initial[PROFILE_KEY]["inactive"] = {A: {
                        "globals": {key: deepcopy(value) for key, value in initial.items()
                                    if key not in (PROFILE_KEY, ATOM_KEY)},
                        "atoms": deepcopy(initial[ATOM_KEY])}}
                    initial = {PROFILE_KEY: initial[PROFILE_KEY], ATOM_KEY: {}}
                else:
                    destination = initial[PROFILE_KEY]["inactive"][B]["globals"]
                    del destination["local-projects"]
                    del destination["thread-project-assignments"]
                plan = plan_sync(initial, None, config())
                self.assertEqual({P, Q}, set(snapshot_profiles(plan["state"], [B])[B]["projects"]))

    def test_incomplete_and_unknown_schemas_pause(self):
        incomplete = state()
        del incomplete["thread-project-assignments"]
        unknown = state()
        unknown[PROFILE_KEY]["unexpected-schema-field"] = 2
        for value in (incomplete, unknown):
            before = deepcopy(value)
            with self.subTest(value=value), self.assertRaises(SyncError):
                plan_sync(value, None, config())
            self.assertEqual(before, value)

    def test_populated_snapshot_becoming_empty_is_not_mass_deletion(self):
        initial, journal = self.baseline(allow_removals=True)
        empty = deepcopy(initial)
        # A complete account can transiently become empty during account switching.
        empty[PROFILE_KEY]["inactive"][B]["globals"] = {
            "local-projects": {}, "thread-project-assignments": {}}
        empty[PROFILE_KEY]["inactive"][B]["atoms"] = {}
        before = deepcopy(empty)
        with self.assertRaises(ValidationError):
            plan_sync(empty, journal, config(allow_removals=True))
        self.assertEqual(before, empty)

    def test_competing_project_edits_return_conflicts_without_mutation(self):
        initial, journal = self.baseline()
        views = snapshot_profiles(initial, [A, B])
        views[A]["projects"][P]["name"] = "Left edit"
        views[B]["projects"][P]["name"] = "Right edit"
        edited = apply_views(initial, views)
        old_journal = deepcopy(journal)
        plan = plan_sync(edited, journal, config())
        self.assertTrue(plan["conflicts"])
        self.assertFalse(plan["changed"])
        self.assertEqual(edited, plan["state"])
        self.assertEqual(old_journal, journal)
        self.assertEqual(old_journal, plan["journal"])

    def test_removals_default_off_and_opt_in_safely_unassigns(self):
        for enabled in (False, True):
            with self.subTest(allow_removals=enabled):
                initial, journal = self.baseline(allow_removals=enabled)
                views = snapshot_profiles(initial, [A, B])
                edited = deepcopy(initial)
                # Only the source account has acknowledged this project removal.
                del edited["local-projects"][P]
                edited["thread-project-assignments"].pop(T)
                edited["project-order"].remove(P)
                edited["project-appearances"].pop(P)
                edited[ATOM_KEY]["unified-sidebar-project-order-v1"] = ["cloud:synthetic"]
                plan = plan_sync(edited, journal, config(allow_removals=enabled))
                self.assertFalse(plan["conflicts"])
                for view in snapshot_profiles(plan["state"], [A, B]).values():
                    validate_view(view)
                    self.assertIn(Q, view["projects"])
                    if enabled:
                        self.assertNotIn(P, view["projects"])
                        self.assertNotIn(T, view["assignments"])
                        self.assertIn(T, view["projectless"])
                        self.assertNotIn(P, view["project_order"])
                        self.assertNotIn(P, view["appearances"])
                    else:
                        self.assertIn(P, view["projects"])
                        self.assertEqual(views[B]["assignments"][T], view["assignments"][T])
                if enabled:
                    self.assertTrue(plan["journal"]["tombstones"])

    def test_exactly_two_explicit_profiles_required(self):
        for profiles in ([], [A], [A, A], [A, B, "synthetic-third"]):
            with self.subTest(profiles=profiles), self.assertRaises(SyncError):
                plan_sync(state(), None, config(profile_ids=profiles))

    def test_validation_rejects_dangling_assignment(self):
        view = snapshot_profiles(state(), [A])[A]
        view["assignments"][T]["projectId"] = "missing-project"
        with self.assertRaises(ValidationError):
            validate_view(view)

    def test_incoming_local_thread_cannot_overwrite_remote_host_identity(self):
        initial = state()
        target = initial[PROFILE_KEY]["inactive"][B]["globals"]
        target["thread-project-membership-host-ids"] = {T: "ssh:synthetic-other"}
        before = deepcopy(initial)
        with self.assertRaises(SyncError):
            plan_sync(initial, None, config())
        self.assertEqual(before, initial)

    def test_cloud_project_referenced_uuid_metadata_stays_account_scoped(self):
        for cloud_project in ("g-p-synthetic-cloud", "synthetic-cloud-root"):
            with self.subTest(cloud_project=cloud_project):
                initial = state()
                cloud_thread = "00000000-0000-4000-8000-000000000003"
                initial["local-projects"]["synthetic-cloud-root"] = {
                    "name": "Synthetic cloud root", "rootPaths": ["C:/synthetic/.chatgpt-projects/cloud"]}
                assignment = {"projectId": cloud_project, "projectKind": "local"}
                initial["thread-project-assignments"][cloud_thread] = deepcopy(assignment)
                initial["thread-project-membership-host-ids"][cloud_thread] = "local"
                initial["pinned-thread-ids"].append(cloud_thread)
                initial["projectless-thread-ids"] = [cloud_thread]
                initial["thread-workspace-root-hints"] = {cloud_thread: "C:/synthetic/cloud-hint"}
                initial["thread-projectless-output-directories"] = {cloud_thread: "C:/synthetic/cloud-output"}
                initial["sidebar-project-thread-orders"] = {P: {"threadIds": [T, cloud_thread]}}
                initial[ATOM_KEY]["unified-sidebar-pinned-order-v1"] = [f"codex:thread:local:{cloud_thread}"]
                plan = plan_sync(initial, None, config())
                result = plan["state"]
                self.assertEqual(assignment, result["thread-project-assignments"][cloud_thread])
                self.assertIn(cloud_thread, result["pinned-thread-ids"])
                self.assertIn(cloud_thread, result["projectless-thread-ids"])
                self.assertIn(cloud_thread, result["sidebar-project-thread-orders"][P]["threadIds"])
                self.assertIn(f"codex:thread:local:{cloud_thread}", result[ATOM_KEY]["unified-sidebar-pinned-order-v1"])
                for category in ("thread-workspace-root-hints", "thread-projectless-output-directories"):
                    self.assertEqual(initial[category][cloud_thread], result[category][cloud_thread])
                for view in snapshot_profiles(result, [A, B]).values():
                    self.assertNotIn(cloud_thread, view["assignments"])
                    self.assertNotIn(cloud_thread, view["pins"])
                    self.assertNotIn(cloud_thread, view["projectless"])
                    self.assertNotIn(cloud_thread, view["hints"])
                    self.assertNotIn(cloud_thread, view["outputs"])
                    self.assertNotIn(cloud_thread, view["thread_orders"].get(P, {}).get("threadIds", []))

    def test_signed_out_state_preserves_shared_globals_atoms_and_envelope(self):
        original = state()
        account_a = {"globals": {key: deepcopy(value) for key, value in original.items()
                                 if key not in (PROFILE_KEY, ATOM_KEY)},
                     "atoms": deepcopy(original[ATOM_KEY])}
        shared = {
            PROFILE_KEY: {"owner": None, "inactive": {
                A: account_a, B: deepcopy(original[PROFILE_KEY]["inactive"][B])}},
            ATOM_KEY: {"shared-synthetic-atom": "stay-shared",
                       "unified-sidebar-project-order-v1": ["cloud:shared-synthetic"]},
            "local-projects": {"synthetic-shared-project": {
                "name": "Shared", "rootPaths": ["C:/synthetic/shared"]}},
            "thread-project-assignments": {},
            "shared-synthetic-setting": {"marker": "stay-shared"},
        }
        before = deepcopy(shared)
        plan = plan_sync(shared, None, config())
        self.assertEqual(before, shared)
        result = plan["state"]
        self.assertIsNone(result[PROFILE_KEY]["owner"])
        self.assertEqual({A, B}, set(result[PROFILE_KEY]["inactive"]))
        for key, value in before.items():
            if key != PROFILE_KEY:
                self.assertEqual(value, result[key])
        views = snapshot_profiles(result, [A, B])
        self.assertEqual(views[A], views[B])
        self.assertEqual({P, Q}, set(views[B]["projects"]))

    def test_uuid_without_local_evidence_remains_scoped_while_known_local_transfers(self):
        initial = state()
        unknown = "00000000-0000-4000-8000-000000000004"
        initial["pinned-thread-ids"].append(unknown)
        initial["projectless-thread-ids"] = [unknown]
        initial["thread-workspace-root-hints"] = {unknown: "C:/synthetic/unknown"}
        initial["thread-projectless-output-directories"] = {unknown: "C:/synthetic/unknown-output"}
        initial["sidebar-project-thread-orders"] = {P: {"threadIds": [T, unknown]}}
        initial[ATOM_KEY]["unified-sidebar-pinned-order-v1"] = [f"codex:thread:local:{unknown}"]
        plan = plan_sync(initial, None, config())
        result = plan["state"]
        target = result[PROFILE_KEY]["inactive"][B]
        self.assertIn(unknown, result["pinned-thread-ids"])
        self.assertIn(unknown, result["projectless-thread-ids"])
        self.assertIn(unknown, result["sidebar-project-thread-orders"][P]["threadIds"])
        self.assertEqual(initial["thread-workspace-root-hints"], result["thread-workspace-root-hints"])
        self.assertEqual(initial["thread-projectless-output-directories"], result["thread-projectless-output-directories"])
        self.assertIn(f"codex:thread:local:{unknown}", result[ATOM_KEY]["unified-sidebar-pinned-order-v1"])
        self.assertNotIn(unknown, target["globals"]["pinned-thread-ids"])
        self.assertIn(T, target["globals"]["pinned-thread-ids"])
        self.assertIn(T, target["globals"]["thread-project-assignments"])
        for view in snapshot_profiles(result, [A, B]).values():
            self.assertNotIn(unknown, view["pins"])
            self.assertNotIn(unknown, view["projectless"])
            self.assertNotIn(unknown, view["hints"])
            self.assertNotIn(unknown, view["outputs"])
            self.assertNotIn(unknown, view["thread_orders"][P]["threadIds"])
