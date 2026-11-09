from rediswidgets.tag_search import matching_tags


def test_matching_tags_is_case_insensitive_and_literal():
    assert matching_tags(['Alpha.X', 'alpha[x]', 'other'], 'A[X]') == ['alpha[x]']


def test_matching_tags_sorts_results():
    assert matching_tags(['zTag', 'ATag', 'none'], 'tag') == ['ATag', 'zTag']
