"""Public deterministic Aster-only synthetic test specifications, never user data."""

def binding(fresh=False):
    return {
        'schema': 'newbrain.hearing.waveform-corpus-binding.v1',
        'owner': 'aster-fixture', 'source': 'synthetic-tone',
        'corpus_id': 'aster-new' if fresh else 'aster-base', 'start_ns': 0,
        'frequencies': [375, 1000],
        # Public deterministic test seeds. These are not copied owner bindings.
        'train_nonce': 'a1' * 16,
        'query_nonce': ('c3' if fresh else 'b2') * 16,
        'query_parameters': {
            'amplitude': [[v, 0.0, 0, 0] for v in ([0.09, 0.66, 0.76] if fresh else [0.08, 0.65, 0.75])],
            'phase': [[0.35, v, 0, 0] for v in ([-0.3, -0.6, -0.9] if fresh else [0.3, 0.6, 0.9])],
            'onset': [[0.35, 0.0, v, 0] for v in ([40, 56, 72] if fresh else [32, 48, 64])],
            'noise': [[0.35, 0.0, 0, v] for v in ([384, 640, 896] if fresh else [256, 512, 768])],
        },
    }
