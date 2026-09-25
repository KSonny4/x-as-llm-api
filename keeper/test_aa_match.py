"""AA model-id matching: alias > exact > normalized > persisted AI decision.

Fixture names/slugs/creators/Coding Index values are the live AA v2 snapshot
retrieved 2026-09-25 (GPT-6 Luna: listed, Coding Index still null).
"""
import json
import os
from unittest.mock import patch

import pytest

import aa
import aa_match
from aa import match_for, rank_models, score_for

AA_INDEX = {
    'muse-spark-1-3': {'name': 'Muse Spark 1.3 (max)', 'creator': 'meta', 'coding': 75.8},
    'muse-spark-1-3-xhigh': {'name': 'Muse Spark 1.3 (xhigh)', 'creator': 'meta', 'coding': 76.5},
    'mimo-v2-6-pro': {'name': 'MiMo-V2.6-Pro', 'creator': 'xiaomi', 'coding': None},
    'mimo-v2-5-0424': {'name': 'MiMo-V2.5', 'creator': 'xiaomi', 'coding': 56.8},
    'mimo-v2-flash': {'name': 'MiMo-V2-Flash (Non-reasoning)', 'creator': 'xiaomi', 'coding': 49.8},
    'mimo-v2-flash-reasoning': {'name': 'MiMo-V2-Flash (Reasoning)', 'creator': 'xiaomi', 'coding': None},
    'gpt-6-luna': {'name': 'GPT-6 Luna (max)', 'creator': 'openai', 'coding': None},
    'gpt-6-luna-xhigh': {'name': 'GPT-6 Luna (xhigh)', 'creator': 'openai', 'coding': None},
    'gpt-6-luna-high': {'name': 'GPT-6 Luna (high)', 'creator': 'openai', 'coding': None},
    'gpt-6-luna-medium': {'name': 'GPT-6 Luna (medium)', 'creator': 'openai', 'coding': None},
    'gpt-6-luna-low': {'name': 'GPT-6 Luna (low)', 'creator': 'openai', 'coding': None},
    'gpt-6-luna-non-reasoning': {'name': 'GPT-6 Luna (Non-reasoning)', 'creator': 'openai', 'coding': None},
    'gpt-5-6-luna': {'name': 'GPT-5.6 Luna (max)', 'creator': 'openai', 'coding': 71.4},
    'gpt-5-6-luna-xhigh': {'name': 'GPT-5.6 Luna (xhigh)', 'creator': 'openai', 'coding': 68.6},
    'gpt-5-6-luna-high': {'name': 'GPT-5.6 Luna (high)', 'creator': 'openai', 'coding': 63.3},
    'gpt-5-6-luna-medium': {'name': 'GPT-5.6 Luna (medium)', 'creator': 'openai', 'coding': 50.7},
    'gpt-5-6-luna-low': {'name': 'GPT-5.6 Luna (low)', 'creator': 'openai', 'coding': 44.2},
    'gpt-5-6-luna-non-reasoning': {'name': 'GPT-5.6 Luna (Non-reasoning)', 'creator': 'openai', 'coding': 39.3},
    'glm-5-2': {'name': 'GLM-5.2 (max)', 'creator': 'zai', 'coding': 68.8},
    'glm-5-2-non-reasoning': {'name': 'GLM-5.2 (Non-reasoning)', 'creator': 'zai', 'coding': 46.5},
    'qwen3-8-27b': {'name': 'Qwen3.8 27B (xhigh)', 'creator': 'alibaba', 'coding': 68.1},
    'qwen3-8-27b-medium': {'name': 'Qwen3.8 27B (medium)', 'creator': 'alibaba', 'coding': 56.1},
    'qwen3-8-27b-low': {'name': 'Qwen3.8 27B (low)', 'creator': 'alibaba', 'coding': 58.2},
    'qwen3-8-27b-non-reasoning': {'name': 'Qwen3.8 27B (Non-reasoning)', 'creator': 'alibaba', 'coding': 44.6},
    'inkling': {'name': 'Inkling (xhigh)', 'creator': 'thinking-machines', 'coding': 52.1},
    'inkling-small': {'name': 'Inkling Small', 'creator': 'thinking-machines', 'coding': 52.9},
    'ling-3-0-flash-vl': {'name': 'Ling-3.0-flash-VL', 'creator': 'inclusionai', 'coding': 57},
    'ling-3-0-flash-fin': {'name': 'Ling-3.0-flash-Fin', 'creator': 'inclusionai', 'coding': 55.6},
    'nvidia-nemotron-3-ultra-550b-a55b': {'name': 'Nemotron 3 Ultra 550B A55B (Reasoning)', 'creator': 'nvidia', 'coding': 49.3},
    'nemotron-3-5-lightning': {'name': 'Nemotron 3.5 Lightning', 'creator': 'nvidia', 'coding': 26.8},
    'step-3-7-flash': {'name': 'Step 3.7 Flash', 'creator': 'stepfun', 'coding': 39.6},
    'north-mini-code': {'name': 'North Mini Code', 'creator': 'cohere', 'coding': 36.5},
    'lfm2-5-2-6b': {'name': 'LFM2.5-2.6B', 'creator': 'liquidai', 'coding': 7.7},
}

NEMO_ULTRA = 'nvidia-nemotron-3-ultra-550b-a55b'


def scores_of(index):
    return {slug: e['coding'] for slug, e in index.items() if e['coding'] is not None}


def served(*pairs):
    return [{'id': p + '/' + m, 'provider': p, 'model': m, 'working_keys': 1} for p, m in pairs]


class Asker:
    """Stub LLM: replies from a {model: reply-or-exception} map; records prompts."""
    def __init__(self, replies):
        self.replies, self.prompts = replies, []

    def __call__(self, messages):
        prompt = messages[-1]['content']
        self.prompts.append(prompt)
        for model, reply in self.replies.items():
            if repr(model) in prompt:
                if isinstance(reply, Exception):
                    raise reply
                return reply if isinstance(reply, str) else json.dumps(reply)
        raise AssertionError('unexpected prompt')


@pytest.fixture
def table(tmp_path):
    aa_match.install(AA_INDEX, {})
    yield {'aa_cache': str(tmp_path / 'aa-coding.json')}
    aa_match.install({}, {})


def test_normalization_strips_namespaces_free_tiers_and_separators():
    n = aa_match.normalize
    assert n('openai/gpt-6-luna') == 'gpt-6-luna'
    assert n('stealth/space-bunny-alpha') == 'space-bunny-alpha'
    assert n('space-bunny-free') == 'space-bunny'
    assert n('nvidia/nemotron-3.5-lightning:free') == 'nemotron-3-5-lightning'
    assert n('mimo-v2.6-flash-free') == 'mimo-v2-6-flash'
    assert n('Ling 3.0 Flash Fin Free') == 'ling-3-0-flash-fin'
    assert n('qwen/qwen3.8-27b:free') == 'qwen3-8-27b'


def test_luna_is_matched_exactly_but_unscored_until_aa_publishes_coding(table):
    scores = scores_of(AA_INDEX)
    for provider, model, method in [('openai', 'gpt-6-luna', 'exact'),
                                    ('openrouter', 'openai/gpt-6-luna', 'normalized'),
                                    ('opencode-zen', 'gpt-6-luna', 'exact')]:
        assert match_for(scores, provider, model) == {'slug': 'gpt-6-luna', 'method': method, 'confidence': 1.0}
        assert score_for(scores, provider, model) is None
    # A resolved-but-unscored model never reaches the LLM (no gpt-5-6-luna guess).
    ask = Asker({})
    aa_match.run(table, scores, aa.ALIASES, 1, ask, served(('openai', 'gpt-6-luna')))
    assert ask.prompts == []
    # Once AA publishes Luna's Coding Index, the lowest effort variant counts.
    later = {**scores, 'gpt-6-luna': 80.0, 'gpt-6-luna-low': 60.0}
    assert score_for(later, 'openai', 'gpt-6-luna') == 60.0


def test_variant_conservatism_unless_the_endpoint_names_an_effort(table):
    scores = scores_of(AA_INDEX)
    assert score_for(scores, 'openai', 'gpt-5.6-luna') == 39.3
    assert match_for(scores, 'openai', 'gpt-5.6-luna')['picked'] == 'gpt-5-6-luna'
    assert score_for(scores, 'openrouter', 'openai/gpt-5.6-luna-high') == 63.3
    # Reviewed aliases are taken verbatim (muse-spark precedent: max 75.8).
    assert score_for(scores, 'opencode-zen', 'muse-spark-1.3-contributor-free') == 75.8


def test_ai_accepts_confident_shortlisted_match_and_persists_it(table):
    scores = scores_of(AA_INDEX)
    ask = Asker({'nemotron-3-ultra-free': 'Sure!\n```json\n{"slug": "%s", "confidence": 0.9, '
                                          '"reason": "same Nemotron 3 Ultra"}\n```' % NEMO_ULTRA})
    aa_match.run(table, scores, aa.ALIASES, 1000, ask, served(('opencode-zen', 'nemotron-3-ultra-free')))
    assert NEMO_ULTRA in ask.prompts[0]
    m = match_for(scores, 'opencode-zen', 'nemotron-3-ultra-free')
    assert m['slug'] == NEMO_ULTRA and m['method'] == 'ai' and m['confidence'] == 0.9
    assert m['reason'] == 'same Nemotron 3 Ultra' and m['decided_at'] == 1000
    assert score_for(scores, 'opencode-zen', 'nemotron-3-ultra-free') == 49.3
    doc = json.load(open(os.path.join(os.path.dirname(table['aa_cache']), 'aa-matches.json')))
    assert doc['format'] == 'aa-matches-v1'
    [d] = doc['ai']
    assert d['slug'] == NEMO_ULTRA and d['method'] == 'ai' and NEMO_ULTRA in d['candidates']
    assert doc['served'][0]['coding_index'] == 49.3


@pytest.mark.parametrize('model,reply,why', [
    ('nemotron-3-ultra-free', {'slug': NEMO_ULTRA, 'confidence': 0.6, 'reason': 'maybe'}, 'low_confidence'),
    ('nemotron-3-ultra-free', {'slug': 'gpt-5-6-luna', 'confidence': 0.95, 'reason': 'x'}, 'out_of_shortlist'),
    ('mimo-v2.6-flash-free', {'slug': 'mimo-v2-flash', 'confidence': 0.9, 'reason': 'x'}, 'version_mismatch'),
])
def test_ai_rejections_stay_unscored_and_are_audited(table, model, reply, why):
    scores = scores_of(AA_INDEX)
    aa_match.run(table, scores, aa.ALIASES, 1, Asker({model: reply}), served(('opencode-zen', model)))
    assert match_for(scores, 'opencode-zen', model) is None
    d = aa_match.table()['ai'][('opencode-zen', model)]
    assert d['slug'] is None and d['rejected'] == why and d['picked'] == reply['slug']


def test_ai_null_answer_and_no_candidate_skip(table):
    scores = scores_of(AA_INDEX)
    ask = Asker({'mimo-v2.6-flash-free': {'slug': None, 'confidence': 0.9, 'reason': 'AA lists no V2.6 Flash'}})
    aa_match.run(table, scores, aa.ALIASES, 1, ask,
                 served(('opencode-zen', 'big-pickle'), ('opencode-zen', 'mimo-v2.6-flash-free'),
                        ('openrouter', 'stealth/space-bunny-alpha')))
    assert len(ask.prompts) == 1  # codenames share no name token with any AA entry
    decisions = aa_match.table()['ai']
    assert decisions[('opencode-zen', 'big-pickle')]['rejected'] == 'no_candidate'
    assert decisions[('openrouter', 'stealth/space-bunny-alpha')]['rejected'] == 'no_candidate'
    assert decisions[('opencode-zen', 'mimo-v2.6-flash-free')]['slug'] is None
    for provider, model in [('opencode-zen', 'big-pickle'), ('opencode-zen', 'mimo-v2.6-flash-free'),
                            ('openrouter', 'stealth/space-bunny-alpha')]:
        assert score_for(scores, provider, model) is None


def test_ai_pick_of_a_reasoning_variant_is_lowered_to_family_minimum(table):
    scores = scores_of(AA_INDEX)
    ask = Asker({'qwen-3.8-27b-it': {'slug': 'qwen3-8-27b', 'confidence': 0.85, 'reason': 'Qwen3.8 27B'}})
    aa_match.run(table, scores, aa.ALIASES, 1, ask, served(('x', 'qwen-3.8-27b-it')))
    m = match_for(scores, 'x', 'qwen-3.8-27b-it')
    assert m['method'] == 'ai' and m['picked'] == 'qwen3-8-27b' and m['slug'] == 'qwen3-8-27b-non-reasoning'
    assert score_for(scores, 'x', 'qwen-3.8-27b-it') == 44.6


def test_llm_failure_keeps_prior_decisions_and_leaves_new_models_unscored(table):
    scores = scores_of(AA_INDEX)
    prior = {'provider': 'opencode-zen', 'model': 'nemotron-3-ultra-free', 'method': 'ai', 'slug': NEMO_ULTRA,
             'confidence': 0.9, 'reason': 'earlier', 'decided_at': 5, 'shortlist_hash': 'stale-hash'}
    aa_match.install(AA_INDEX, {('opencode-zen', 'nemotron-3-ultra-free'): prior})
    ask = Asker({'nemotron-3-ultra-free': RuntimeError('upstream down'),
                 'qwen-3.8-27b-it': ValueError('garbage')})
    aa_match.run(table, scores, aa.ALIASES, 9, ask,
                 served(('opencode-zen', 'nemotron-3-ultra-free'), ('x', 'qwen-3.8-27b-it')))
    assert len(ask.prompts) == 2
    assert score_for(scores, 'opencode-zen', 'nemotron-3-ultra-free') == 49.3
    assert match_for(scores, 'opencode-zen', 'nemotron-3-ultra-free')['decided_at'] == 5
    assert match_for(scores, 'x', 'qwen-3.8-27b-it') is None
    assert ('x', 'qwen-3.8-27b-it') not in aa_match.table()['ai']  # retried next refresh
    with pytest.raises(ValueError):
        aa_match.parse_reply('I think it is the Nemotron one')


def test_decisions_reused_until_shortlist_changes_and_survive_restart(table, tmp_path):
    scores = scores_of(AA_INDEX)
    reply = {'slug': NEMO_ULTRA, 'confidence': 0.9, 'reason': 'same'}
    ask = Asker({'nemotron-3-ultra-free': reply})
    models = served(('opencode-zen', 'nemotron-3-ultra-free'))
    aa_match.run(table, scores, aa.ALIASES, 1, ask, models)
    aa_match.run(table, scores, aa.ALIASES, 2, ask, models)
    assert len(ask.prompts) == 1
    # Restart: a fresh state reloads decisions from aa-matches.json with the index.
    aa_match.install({}, {})
    with open(table['aa_cache'], 'w') as fh:
        json.dump({'format': 'coding-v1', 'scores': scores, 'index': AA_INDEX, 'succeeded_at': 100}, fh)
    state = {'aa_cache': table['aa_cache'], 'aa_api_key': '', 'aa_matcher': ask}
    aa.refresh_state(state, now=200)
    assert score_for(state['aa_scores'], 'opencode-zen', 'nemotron-3-ultra-free') == 49.3
    # A new AA entry that enters the shortlist triggers one re-decision.
    grown = {**AA_INDEX, 'nemotron-3-ultra-v2': {'name': 'Nemotron 3 Ultra v2', 'creator': 'nvidia', 'coding': 60.0}}
    aa_match.install(grown, aa_match.table()['ai'])
    aa_match.run(table, scores, aa.ALIASES, 3, ask, models)
    assert len(ask.prompts) == 2


def test_refresh_state_runs_matcher_daily_never_on_request_path(tmp_path):
    payload = {'data': [{'id': 'u' + str(i), 'slug': slug, 'name': e['name'],
                         'model_creator': {'slug': e['creator']},
                         'evaluations': {'artificial_analysis_coding_index': e['coding']}}
                        for i, (slug, e) in enumerate(AA_INDEX.items())]}

    class Resp:
        def read(self):
            return json.dumps(payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class Availability:
        def catalog(self):
            return {'models': served(('opencode-zen', 'nemotron-3-ultra-free')) + [
                {'id': 'idle', 'provider': 'opencode-zen', 'model': 'mimo-v2.6-flash-free', 'working_keys': 0}]}

    ask = Asker({'nemotron-3-ultra-free': {'slug': NEMO_ULTRA, 'confidence': 0.92, 'reason': 'same'}})
    state = {'aa_cache': str(tmp_path / 'aa-coding.json'), 'aa_api_key': 'synthetic-aa',
             'availability': Availability(), 'aa_matcher': ask, 'aa_match_background': False}
    try:
        with patch('aa.urlopen', return_value=Resp()):
            aa.refresh_state(state, now=1800000000)
        assert len(ask.prompts) == 1  # served models only; idle mimo not asked
        assert state['aa_index']['gpt-6-luna']['coding'] is None
        cached = json.load(open(state['aa_cache']))
        assert cached['index']['gpt-6-luna']['name'] == 'GPT-6 Luna (max)' and 'synthetic-aa' not in json.dumps(cached)
        rows = rank_models(Availability().catalog()['models'], state['aa_scores'])
        assert rows[0]['coding_index'] == 49.3 and rows[0]['coding_index_match']['method'] == 'ai'
        assert len(ask.prompts) == 1  # ranking (request path) never calls the LLM
        aa.refresh_state(state, now=1800000100)  # within the day: no fetch, no LLM
        assert len(ask.prompts) == 1
    finally:
        aa_match.install({}, {})


def test_catalog_rows_carry_match_provenance(tmp_path):
    from test_api_v2 import state_for, call
    state, _ = state_for(tmp_path)
    model = state['availability'].catalog()['models'][0]['model']
    state['aa_scores'] = {model: 42.0}
    code, body, _ = call(state, 'GET', '/api/v2/catalog')
    row = next(m for m in json.loads(body)['models'] if m['model'] == model)
    assert code == 200 and row['coding_index'] == 42.0
    assert row['coding_index_match'] == {'slug': model, 'method': 'exact', 'confidence': 1.0}
