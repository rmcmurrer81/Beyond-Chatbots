"""Explicit saved-label adapter. Reads validated state; never executes a brain."""
from .protocol import VoiceError, gesture, make_plan, need, owner_id, validate


def from_text_lab(directory, owner='synthetic_aster', method='INTERLEAVED', split='new', case_index=0):
    owner_id(owner)
    need(method in ('initial', 'baseline', 'INTERLEAVED', 'BLOCKED', 'ERROR_PRIORITIZED')
         and split in ('old', 'new', 'heldout') and type(case_index) is int and 0 <= case_index < 6,
         'lab_selection_refused')
    from experiments.newbrain_text.persistence import LabError, read_state
    try:
        envelope, report = read_state(directory, owner)
    except LabError as exc:
        raise VoiceError('text_lab_state_refused') from exc
    result = report[method] if method in ('initial', 'baseline') else report['arms'][method]
    rows = result['evaluation'][split]
    need(case_index < len(rows), 'lab_selection_refused')
    observed = rows[case_index]
    generation = observed['generation']
    tokens = generation['tokens']
    need(len(tokens) == 1 and tokens[0] in ('warm', 'cool')
         and generation['terminated_with_eos'] is True, 'unsupported_observed_output')
    # Actual output is used even when wrong; no target substitution. This is a
    # label-coded tract gesture, not a pronunciation of the English label.
    plan = make_plan([gesture('open' if tokens[0] == 'warm' else 'rounded', 650)], owner)
    plan['origin'] = {'kind': 'text_lab_observation', 'report_sha256': envelope['report_sha256'],
                      'model_sha256': envelope['models'][method]['model_sha256'], 'method': method,
                      'split': split, 'case_index': case_index, 'observed_token': tokens[0],
                      'exact_correct': observed['exact_correct'],
                      'adapter': 'aster.text-label-to-physical-pose.v1'}
    return validate(plan, owner)
