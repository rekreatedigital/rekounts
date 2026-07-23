"""sounds_like -> correct spelling replacement in the text cleaner."""
from rekounts.text_cleaner import TextCleaner


def cleaner(pairs, **kw):
    """A cleaner with every other transform off unless a test asks for it, so
    each assertion is about replacement alone."""
    opts = dict(strip_fillers=False, auto_capitalize=False,
                fix_punctuation_spacing=False)
    opts.update(kw)
    return TextCleaner(replacements_provider=lambda: pairs, **opts)


# ---------------------------------------------------------- backwards compat
def test_no_provider_changes_nothing():
    c = TextCleaner(strip_fillers=False, auto_capitalize=False,
                    fix_punctuation_spacing=False)
    assert c.clean("cooper netties is fine") == "cooper netties is fine"


def test_empty_provider_list_changes_nothing():
    assert cleaner([]).clean("cooper netties") == "cooper netties"


def test_positional_construction_still_works():
    # __main__ builds this positionally; the new arg must stay at the end.
    c = TextCleaner(True, True, True)
    assert c.clean("um hello") == "Hello"


# ------------------------------------------------------------- the basic swap
def test_misheard_form_is_replaced():
    assert cleaner([("cooper netties", "Kubernetes")]).clean(
        "we deploy on cooper netties today") == "we deploy on Kubernetes today"


def test_match_is_case_insensitive():
    c = cleaner([("cooper netties", "Kubernetes")])
    assert c.clean("Cooper Netties rocks") == "Kubernetes rocks"
    assert c.clean("COOPER NETTIES rocks") == "Kubernetes rocks"


def test_all_occurrences_are_replaced():
    assert cleaner([("graf ana", "Grafana")]).clean("graf ana and graf ana") == \
        "Grafana and Grafana"


def test_extra_whitespace_inside_the_phrase_still_matches():
    assert cleaner([("cooper netties", "Kubernetes")]).clean(
        "cooper   netties") == "Kubernetes"


# -------------------------------------------------------------- word boundaries
def test_substrings_of_larger_words_are_left_alone():
    c = cleaner([("net", "NET")])
    assert c.clean("netties on the internet") == "netties on the internet"
    assert c.clean("the net is up") == "the NET is up"


def test_adjacent_punctuation_does_not_block_a_match():
    c = cleaner([("cooper netties", "Kubernetes")])
    assert c.clean("(cooper netties), yes") == "(Kubernetes), yes"
    assert c.clean("cooper netties.") == "Kubernetes."


def test_hyphenated_neighbour_is_matched_not_the_whole_token():
    # '-' is not a word character, so the boundary is real.
    assert cleaner([("kube", "Kubernetes")]).clean("kube-proxy") == "Kubernetes-proxy"


# ------------------------------------------------------------------ casing
def test_leading_capital_is_preserved_for_a_lowercase_entry():
    c = cleaner([("kloud", "cloud")])
    assert c.clean("Kloud costs money") == "Cloud costs money"
    assert c.clean("the kloud costs money") == "the cloud costs money"


def test_user_typed_capitalisation_wins_over_sentence_position():
    # "iPhone" must never become "IPhone" just because it starts a sentence.
    assert cleaner([("i phone", "iPhone")]).clean("I phone is here") == "iPhone is here"
    assert cleaner([("recounts", "Rekounts")]).clean(
        "Recounts works") == "Rekounts works"


def test_auto_capitalize_does_not_wreck_a_replacement_at_a_sentence_start():
    # The whole point of the dictionary is the user's exact spelling; the
    # sentence-start capitalizer must not turn "iPhone" into "IPhone".
    c = cleaner([("i phone", "iPhone")], auto_capitalize=True,
                fix_punctuation_spacing=True)
    assert c.clean("i phone is here. i phone again.") == "iPhone is here. iPhone again."


def test_shouted_match_does_not_shout_the_replacement():
    assert cleaner([("kloud", "cloud")]).clean("KLOUD") == "Cloud"


# ------------------------------------------------------------ multiple rules
def test_longest_phrase_wins():
    c = cleaner([("netties", "Netties"), ("cooper netties", "Kubernetes")])
    assert c.clean("cooper netties") == "Kubernetes"


def test_a_replacement_is_never_re_replaced_by_another_rule():
    # a -> b and b -> c must not turn a into c.
    c = cleaner([("alpha", "beta"), ("beta", "gamma")])
    assert c.clean("alpha") == "beta"


def test_rules_are_independent_of_input_order():
    pairs = [("bee", "B"), ("ay", "A")]
    assert cleaner(pairs).clean("ay then bee") == "A then B"


# --------------------------------------------------------------- provider care
def test_provider_is_re_read_on_every_call():
    pairs = []
    c = cleaner(pairs)
    assert c.clean("graf ana") == "graf ana"
    pairs.append(("graf ana", "Grafana"))       # user adds it in the dashboard
    assert c.clean("graf ana") == "Grafana"


def test_broken_provider_never_costs_the_user_their_text():
    def boom():
        raise RuntimeError("db gone")

    c = TextCleaner(strip_fillers=False, auto_capitalize=False,
                    fix_punctuation_spacing=False, replacements_provider=boom)
    assert c.clean("hello world") == "hello world"


def test_junk_rows_are_ignored():
    c = cleaner([("", "Kubernetes"), ("graf ana", ""), (None, "x"), ("ok", "OK")])
    assert c.clean("graf ana ok") == "graf ana OK"


def test_regex_metacharacters_in_a_misheard_form_are_literal():
    c = cleaner([("c++", "cpp")])
    assert c.clean("i write c++ daily") == "i write cpp daily"
    assert c.clean("i write ccc daily") == "i write ccc daily"


def test_empty_text_is_still_empty():
    assert cleaner([("a", "b")]).clean("") == ""
    assert cleaner([("a", "b")]).clean(None) == ""


# ------------------------------------------------------ order in the pipeline
def test_replacement_runs_before_filler_stripping():
    # "uh mazon" would lose its "uh" and never match if fillers went first.
    c = cleaner([("uh mazon", "Amazon")], strip_fillers=True)
    assert c.clean("uh mazon is uh big") == "Amazon is big"


def test_replacement_survives_repeat_collapsing():
    c = cleaner([("nay nay", "NeNe")], collapse_repeats=True)
    assert c.clean("nay nay is here") == "NeNe is here"


def test_auto_capitalize_still_applies_after_a_replacement():
    c = cleaner([("kloud", "cloud")], auto_capitalize=True)
    assert c.clean("kloud is up") == "Cloud is up"
