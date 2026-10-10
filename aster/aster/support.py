"""Explicit local support operations shared by CLI and the owning desktop worker.

The fixed registry is not reflection-based tool execution. Imported content and
NewBrain prompts never reach it. Each mutation needs a separate owner action.
"""
import inspect
import json


# name: (method, mutation, example arguments). Examples never run automatically.
OPERATIONS = {
    'ability': {
        'status': ('status', False, {}), 'list': ('list', False, {}),
        'propose': ('create', True, {'name': 'tidy-text', 'path': 'recipes/tidy.json', 'permissions': []}),
        'get': ('get', False, {'proposal_id': 'proposal-id'}),
        'source': ('source', False, {'proposal_id': 'proposal-id'}),
        'installed': ('installed', False, {'name': 'tidy-text'}),
        'receipt': ('receipt', False, {'receipt_id': 'receipt-id'}),
        'history': ('history', False, {'name': 'tidy-text'}),
        'test': ('test', True, {'proposal_id': 'proposal-id', 'source_sha256': 'exact-source-sha256',
                              'cases': [{'input': ' hello ', 'expected': 'HELLO'}]}),
        'review': ('review', True, {'proposal_id': 'proposal-id', 'verdict': 'approved',
                                  'note': 'Reviewed exact recipe and tests', 'source_sha256': 'exact-source-sha256',
                                  'test_receipt_id': 'receipt-id'}),
        'install': ('install', True, {'proposal_id': 'proposal-id', 'source_sha256': 'exact-source-sha256', 'review_id': 'review-id'}),
        'rollback': ('rollback', True, {'name': 'tidy-text'}),
        'preview-run': ('preview_run', True, {'name': 'tidy-text', 'input_text': ' hello '}),
        'run': ('run', True, {'plan_id': 'plan-id', 'input_sha256': 'exact-input-sha256'}),
    },
    'memory': {
        'status': ('status', False, {}),
        'search': ('search', False, {'query': '', 'limit': 50}),
        'get': ('get', False, {'id_': 'memory-id'}),
        'chain': ('chain', False, {'id_': 'memory-id'}),
        'remember': ('remember', True, {'body': 'A project decision', 'category': 'decision', 'source': 'user'}),
        'correct': ('correct', True, {'id_': 'memory-id', 'body': 'Corrected decision', 'source': 'user'}),
        'hide': ('hide', True, {'id_': 'memory-id'}),
        'delete': ('delete', True, {'id_': 'memory-id'}),
        'restore': ('restore', True, {'id_': 'memory-id'}),
    },
    'library': {
        'status': ('status', False, {}), 'folders': ('folders', False, {}),
        'sources': ('sources', False, {}), 'search': ('search', False, {'query': 'motor', 'limit': 20}),
        'approve-folder': ('approve_folder', True, {'relative_folder': 'references'}),
        'revoke-folder': ('revoke_folder', True, {'folder_id': 'folder-id'}),
        'index': ('index_files', True, {'folder_id': 'folder-id', 'paths': ['references/manual.txt']}),
    },
    'communications': {
        'status': ('status', False, {}),
        'preview-import': ('preview_import', False, {'path': 'exports/inbox.json'}),
        'import': ('import_export', True, {'path': 'exports/inbox.json', 'expected_sha256': 'exact-export-sha256'}),
        'search': ('search', False, {'query': '', 'limit': 50}),
        'read': ('read', False, {'snapshot_id': 'snapshot-id', 'record_id': 'record-id'}),
        'draft': ('create_draft', True, {'service': 'email', 'account': 'owner@example.invalid',
            'recipient': 'recipient@example.invalid', 'subject': 'Draft for review', 'body': 'Owner-written text'}),
        'outbox': ('outbox', False, {}),
        'get-draft': ('draft', False, {'id_': 'draft-id'}),
        'revise-draft': ('revise_draft', True, {'id_': 'draft-id', 'recipient': 'recipient@example.invalid',
            'subject': 'Revised draft', 'body': 'Revised owner-written text'}),
    },
    'media': {
        'status': ('status', False, {}), 'voice': ('inspect_voice', False, {}),
        'inspect': ('inspect', False, {'path': 'media/sample.wav'}),
        'preview-trim': ('preview_trim', False, {'path': 'media/sample.wav', 'start_frame': 0,
                                                'end_frame': 100, 'output_path': 'media/exports/trim.wav'}),
        'trim': ('trim', True, {'path': 'media/sample.wav', 'start_frame': 0,
            'end_frame': 100, 'output_path': 'media/exports/trim.wav', 'expected_sha256': 'exact-preview-sha256'}),
    },
    'resources': {
        'status': ('status', False, {}),
        'configure': ('configure', True, {'max_ram_mib': 512, 'reserve_ram_mib': 256, 'max_pending': 256}),
        'queue': ('submit', True, {'action': 'research.links', 'args': {'query': 'motor specifications'},
                                  'budget': 5, 'ram_mib': 16, 'gpu_mib': 0}),
        'run-one': ('run_one', True, {}),
        'control': ('control', True, {'id_': 'job-id', 'command': 'cancel'}),
    },
}


def parse_args(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON argument key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON numbers are not accepted')
    try:
        if type(raw) is not str or len(raw.encode('utf-8')) > 262144:
            raise ValueError('Support arguments exceed the 256 KiB bound')
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Support arguments contain invalid Unicode or excessive nesting') from exc
    if type(value) is not dict:
        raise ValueError('Support arguments must be one JSON object')
    return value


def operation(module, action):
    if type(module) is not str or type(action) is not str or action not in OPERATIONS.get(module, {}):
        raise ValueError('Unknown local support operation')
    return OPERATIONS[module][action]


def catalog():
    return {module: {action: {'requires_approval': item[1], 'example_args': item[2]}
                     for action, item in actions.items()} for module, actions in OPERATIONS.items()}


def invoke(store, files, jobs, module, action, args, *, approved=False):
    method, mutation, _ = operation(module, action)
    if type(args) is not dict or type(approved) is not bool:
        raise ValueError('Expected argument object and explicit boolean approval')
    if mutation and not approved:
        raise ValueError('This local change requires separate explicit approval')
    if module == 'ability':
        if action == 'propose':
            from .abilities import Abilities
            target = Abilities(store, files)
        else:
            from .ability_workshop import AbilityWorkshop
            target = AbilityWorkshop(store, files)
    elif module == 'memory':
        from .private_memory import PrivateMemory
        target = PrivateMemory(store)
    elif module == 'library':
        from .reference_library import ReferenceLibrary
        target = ReferenceLibrary(store, files)
    elif module == 'communications':
        from .communications import Communications
        target = Communications(store, files)
    elif module == 'media':
        from .media_workshop import MediaWorkshop
        target = MediaWorkshop(store, files)
    else:
        target = jobs if action in {'queue', 'run-one', 'control'} else jobs.resources
    call = getattr(target, method)  # method comes only from the fixed registry above.
    params = dict(args)
    if 'approved' in params:
        raise ValueError('Approval is a separate control, never part of imported arguments')
    signature = inspect.signature(call)
    if 'approved' in signature.parameters:
        params['approved'] = approved
    try:
        signature.bind(**params)
    except TypeError as exc:
        raise ValueError('Arguments do not match this support operation: ' + str(exc)) from exc
    result = call(**params)
    if module == 'memory' and action in {'hide', 'delete'}:
        result = {key: value for key, value in result.items() if key != 'body'}
        result['content_omitted'] = True
    return result
