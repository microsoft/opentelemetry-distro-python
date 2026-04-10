# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

import unittest
from unittest.mock import MagicMock

from packaging.requirements import Requirement

from microsoft.opentelemetry._azure_monitor._utils.instrumentation import (
    DependencyConflict,
    _get_dependency_conflicts_any,
    get_dependency_conflicts,
    get_dist_dependency_conflicts,
)


class TestDependencyConflict(unittest.TestCase):
    def test_str_required(self):
        c = DependencyConflict(required="foo>=1.0", found="foo 0.9")
        self.assertIn("foo>=1.0", str(c))
        self.assertIn("foo 0.9", str(c))

    def test_str_required_any(self):
        c = DependencyConflict(required_any=["a", "b"], found_any=["a 0.1"])
        result = str(c)
        self.assertIn("requested any", result)
        self.assertIn("['a', 'b']", result)

    def test_str_no_required_with_found_any(self):
        c = DependencyConflict(found_any=["x 1.0"])
        result = str(c)
        self.assertIn("requested any", result)


class TestGetDistDependencyConflicts(unittest.TestCase):
    def test_no_requires(self):
        dist = MagicMock()
        dist.requires = None
        self.assertIsNone(get_dist_dependency_conflicts(dist))

    def test_empty_requires(self):
        dist = MagicMock()
        dist.requires = []
        self.assertIsNone(get_dist_dependency_conflicts(dist))

    def test_no_matching_extras(self):
        dist = MagicMock()
        dist.requires = ["some-package>=1.0"]
        self.assertIsNone(get_dist_dependency_conflicts(dist))

    def test_instruments_deps(self):
        dist = MagicMock()
        # Simulate a dep with 'extra == "instruments"' marker
        dist.requires = ['pytest>=8.0; extra == "instruments"']
        result = get_dist_dependency_conflicts(dist)
        # pytest is installed, so no conflict
        self.assertIsNone(result)

    def test_instruments_any_deps(self):
        dist = MagicMock()
        dist.requires = ['pytest>=8.0; extra == "instruments-any"']
        result = get_dist_dependency_conflicts(dist)
        self.assertIsNone(result)


class TestGetDependencyConflicts(unittest.TestCase):
    def test_no_deps(self):
        self.assertIsNone(get_dependency_conflicts([]))

    def test_requirement_object(self):
        req = Requirement("pytest>=8.0")
        self.assertIsNone(get_dependency_conflicts([req]))

    def test_string_dep_satisfied(self):
        self.assertIsNone(get_dependency_conflicts(["pytest>=8.0"]))

    def test_string_dep_not_found(self):
        result = get_dependency_conflicts(["nonexistent-package-xyz>=1.0"])
        self.assertIsNotNone(result)
        self.assertIn("nonexistent-package-xyz", str(result))

    def test_string_dep_wrong_version(self):
        result = get_dependency_conflicts(["pytest>=99999.0"])
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.found)

    def test_invalid_requirement(self):
        result = get_dependency_conflicts(["this is not valid!!!"])
        self.assertIsNotNone(result)

    def test_with_deps_any(self):
        result = get_dependency_conflicts([], ["pytest>=8.0"])
        self.assertIsNone(result)


class TestGetDependencyConflictsAny(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(_get_dependency_conflicts_any([]))

    def test_one_satisfied(self):
        self.assertIsNone(_get_dependency_conflicts_any(["pytest>=8.0"]))

    def test_one_not_found(self):
        result = _get_dependency_conflicts_any(["nonexistent-xyz>=1.0"])
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.required_any)

    def test_one_wrong_version(self):
        result = _get_dependency_conflicts_any(["pytest>=99999.0"])
        self.assertIsNotNone(result)
        self.assertTrue(len(result.found_any) > 0)

    def test_mixed_one_satisfied(self):
        # One not found + one satisfied = no conflict
        result = _get_dependency_conflicts_any(["nonexistent-xyz>=1.0", "pytest>=8.0"])
        self.assertIsNone(result)

    def test_requirement_object(self):
        req = Requirement("pytest>=8.0")
        self.assertIsNone(_get_dependency_conflicts_any([req]))

    def test_invalid_requirement(self):
        result = _get_dependency_conflicts_any(["this is not valid!!!"])
        self.assertIsNotNone(result)
