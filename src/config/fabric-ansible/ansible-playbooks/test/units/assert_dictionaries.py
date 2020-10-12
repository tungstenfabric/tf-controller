def assert_subset_dictionaries(expected, actual):
    """This function is a helper to check if all fields from expected
    dictionary exist in actual dictionary.

    Right now it compares only 4 values: dictionaries, lists, strings, ints.
    Any other value types that appears in the expected dictionary will raise
    NotImplemented exception.
    """
    if expected is None:
        return True
    if not isinstance(expected, dict):
        return False
    if not isinstance(actual, dict):
        return False

    for k in expected:
        if k not in actual:
            return False
        if not _compare_values(expected[k], actual[k]):
            return False
    return True


def _compare_values(expected, actual):
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return _compare_lists(expected, actual)
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return assert_subset_dictionaries(expected, actual)
    if isinstance(expected, int):
        if not isinstance(actual, int):
            return False
        return expected == actual
    if isinstance(expected, str):
        if not isinstance(actual, str):
            return False
        return expected == actual
    if expected is None:
        return actual is None
    raise NotImplementedError(' '.join([str(type(expected)),
                                        str(type(actual))]))


def _compare_lists(expected, actual):
    if not isinstance(expected, list):
        return False
    if not isinstance(actual, list):
        return False
    if len(expected) != len(actual):
        return False
    for i in range(len(expected)):
        if not _compare_values(expected[i], actual[i]):
            return False
    return True
