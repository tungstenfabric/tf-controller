import unittest

from assert_dictionaries import assert_dictionaries

class TestAssertDictionaries(unittest.TestCase):
    def test_none(self):
        expected = None
        actual = {"key": "value"}

        self.assertTrue(assert_dictionaries(expected, actual))

    def test_empty_dict(self):
        expected = {}
        actual = {"key": "value"}

        self.assertTrue(assert_dictionaries(expected, actual))

    def test_single_level_equal_dicts(self):
        expected = {
            "str_key": 10,
            5: "str_value"
        }
        actual = {
            "str_key": 10,
            5: "str_value"
        }
        self.assertTrue(assert_dictionaries(expected, actual))

    def test_single_level_with_missing_expected_key(self):
        expected = {
            "key": "value",
            "non_existing_key": "some_value"
        }
        actual = {
            "key": "value",
        }
        self.assertFalse(assert_dictionaries(expected, actual))

    def test_single_level_with_invalid_expected_value_type(self):
        expected = {
            "key": 5
        }
        actual = {
            "key": "not_int_value"
        }
        self.assertFalse(assert_dictionaries(expected, actual))

    def test_single_level_with_invalid_expected_value(self):
        expected = {
            "key": "value_a"
        }
        actual = {
            "key": "value_b"
        }
        self.assertFalse(assert_dictionaries(expected, actual))

    def test_single_level_with_additional_actual_key(self):
        expected = {
            "key": "value"
        }
        actual = {
            "key": "value",
            "extra_key": "extra_value"
        }
        self.assertTrue(assert_dictionaries(expected, actual))

    def test_list_with_invalid_number_of_elements(self):
        expected = {
            "list": [1, 2]
        }
        actual = {
            "list": [1, 2, 3]
        }
        self.assertFalse(assert_dictionaries(expected, actual))

    def test_list_with_invalid_elements(self):
        expected = {
            "list": [1, 2, 4],
        }
        actual = {
            "list": [1, 2, 3]
        }
        self.assertFalse(assert_dictionaries(expected, actual))

    def test_list_with_invalid_element_types(self):
        expected = {
            "list": [1, "x", 3]
        }
        actual = {
            "list": [1, 2, 3]
        }
        self.assertFalse(assert_dictionaries(expected, actual))

    def test_list_with_dicts(self):
        expected = {
            "list_with_dict": [
                1, {"key": "value"}
            ],
            "some_key": "some_value"
        }
        actual = {
            "list_with_dict": [
                1, {"key": "value", "extra_key": "extra_value"}
            ],
            "some_key": "some_value"
        }
        self.assertTrue(assert_dictionaries(expected, actual))

    def test_multiple_levels(self):
        expected = {
            "list": [1, {
                "key": "value",
                "nested_dict": {
                    "int": 7,
                    "str": "abc"
                }
            }],
            "dict": {
                "key": "value"
            }
        }
        actual = {
            "list": [1, {
                "key": "value",
                "extra_key": "extra_value",
                "nested_dict": {
                    "int": 7,
                    "str": "abc",
                    "extra_list": ["a", "b", "c"]
                }
            }],
            "dict": {
                "key": "value",
            }
        }
        self.assertTrue(assert_dictionaries(expected, actual))
