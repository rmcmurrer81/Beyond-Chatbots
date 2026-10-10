"""UNRUN prefix-conditioned learned token generation, from scratch.

No provider, file IO, model instance, training or seed selection at import.
Root owns NumPy/source/native admission and all physical learning/restart tests.
This small fixed-vocabulary RNN is separate from GLIF and the old classifiers.
"""
import hashlib
import json
import struct
import numpy as np

SPECIALS = ('<UNK>', '<BOS>', '<EOS>', '<USER>', '<ASSISTANT>', '<MEMORY>', '<QUERY>')
EMBEDDING, HIDDEN = 16, 64
MAX_VOCABULARY, MAX_PREFIX, MAX_RESPONSE, MAX_BATCH = 96, 64, 16, 8
MAX_UPDATES = 16384
LEARNING_RATE, CLIP_NORM, PARAMETER_LIMIT = 0.01, 5.0, 1000.0
PARAMETER_NAMES = ('E', 'Wxh', 'Whh', 'bh', 'Wy', 'by')
MAGIC = b'NBDG064\x00'
MAX_STATE_BYTES, MAX_META_BYTES = 131072, 8192
BACKEND = 'newbrain.numpy_prefix_rnn_token_decoder_hidden64_v1'


def need(condition, label):
    if not condition:
        raise ValueError(label)


def hash_string(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def vocabulary(value):
    need(type(value) is tuple and len(SPECIALS) < len(value) <= MAX_VOCABULARY,
         'closed_bounded_vocabulary_required')
    need(all(type(word) is str and word.isascii() and 0 < len(word) <= 32
             and not any(c.isspace() for c in word) for word in value), 'bounded_ascii_tokens_required')
    need(value[:len(SPECIALS)] == SPECIALS and len(set(value)) == len(value), 'fixed_unique_special_roles_required')
    need(all(word.isalnum() and word == word.lower() for word in value[len(SPECIALS):]),
         'lowercase_alphanumeric_lexical_vocabulary_required')
    return value


def vocabulary_hash(value):
    return hashlib.sha256(json.dumps(list(value), separators=(',', ':')).encode('ascii')).hexdigest()


class DecoderTrainingError(RuntimeError):
    def __init__(self, primary, state):
        super().__init__('decoder_update_incomplete_partial_model_retained_no_retry')
        self.primary, self.state = primary, state


class DialogueDecoder:
    def __init__(self, words, root_seed):
        self._set_vocabulary(words)
        need(type(root_seed) is int and 0 <= root_seed < 2**32, 'root_postfreeze_seed_required')
        self.root_seed = root_seed
        generator = np.random.default_rng(root_seed)
        count = len(self.vocabulary)
        self.p = {'E': generator.normal(0, .15, (count, EMBEDDING)),
                  'Wxh': generator.normal(0, 1 / np.sqrt(EMBEDDING), (EMBEDDING, HIDDEN)),
                  'Whh': generator.normal(0, .3 / np.sqrt(HIDDEN), (HIDDEN, HIDDEN)),
                  'bh': np.zeros(HIDDEN),
                  'Wy': generator.normal(0, .1, (HIDDEN, count)),
                  'by': np.zeros(count)}
        self.training_updates = self.training_examples = 0
        self.prefix_tokens_seen = self.target_tokens_seen = 0
        self.validate_parameters()

    def _set_vocabulary(self, words):
        self.vocabulary = vocabulary(words)
        self.index = {word: index for index, word in enumerate(words)}
        # UNK, EOS and lexical words may be generated, never structural roles.
        self.output_ids = np.array((0, 2) + tuple(range(len(SPECIALS), len(words))), dtype=np.int64)

    def _shapes(self):
        count = len(self.vocabulary)
        return {'E': (count, EMBEDDING), 'Wxh': (EMBEDDING, HIDDEN),
                'Whh': (HIDDEN, HIDDEN), 'bh': (HIDDEN,),
                'Wy': (HIDDEN, count), 'by': (count,)}

    def validate_parameters(self):
        need(type(self.p) is dict and set(self.p) == set(PARAMETER_NAMES), 'closed_parameter_roles_required')
        for key, shape in self._shapes().items():
            value = self.p[key]
            need(type(value) is np.ndarray and value.shape == shape and value.dtype == np.dtype('float64')
                 and value.flags.c_contiguous and np.isfinite(value).all()
                 and np.max(np.abs(value), initial=0) <= PARAMETER_LIMIT, 'finite_exact_parameter_shape_required')
        need(type(self.root_seed) is int and 0 <= self.root_seed < 2**32, 'bounded_seed_metadata_required')
        need(type(self.training_updates) is int and 0 <= self.training_updates <= MAX_UPDATES, 'bounded_update_metadata_required')
        need(all(type(value) is int and 0 <= value < 2**32 for value in
                 (self.training_examples, self.prefix_tokens_seen, self.target_tokens_seen)), 'bounded_exposure_metadata_required')

    def _ids(self, words, reply=False):
        limit = MAX_RESPONSE - 1 if reply else MAX_PREFIX
        need(type(words) is tuple and 0 < len(words) <= limit, 'bounded_nonempty_token_tuple_required')
        need(all(type(word) is str and word.isascii() and 0 < len(word) <= 32
                 and not any(c.isspace() for c in word) for word in words), 'bounded_input_tokens_required')
        if reply:
            need(all(word in self.index and word not in SPECIALS[1:] for word in words), 'known_nonstructural_training_answer_required')
        else:
            need(all(word not in ('<BOS>', '<EOS>') for word in words), 'prefix_cannot_contain_decoder_boundary_tokens')
        return tuple(self.index.get(word, 0) for word in words)

    def _step(self, identity, previous):
        embedding = self.p['E'][identity]
        hidden = np.tanh(embedding @ self.p['Wxh'] + previous @ self.p['Whh'] + self.p['bh'])
        return hidden, (previous, embedding, hidden, identity)

    def _distribution(self, hidden):
        logits = hidden @ self.p['Wy'] + self.p['by']
        allowed = logits[self.output_ids]
        maximum = float(np.max(allowed))
        exp = np.exp(allowed - maximum)
        denominator = float(np.sum(exp))
        probability = np.zeros(len(self.vocabulary))
        probability[self.output_ids] = exp / denominator
        need(np.isfinite(probability).all() and denominator > 0, 'finite_decoder_probability_required')
        return probability, logits, maximum + float(np.log(denominator))

    def loss_and_gradients(self, batch):
        """Full teacher-forced next-token CE/BPTT through reply AND prefix.

        Gold reply tokens are training inputs only. Free generation takes no
        answer/label and feeds back its own preceding emitted token.
        """
        self.validate_parameters()
        need(type(batch) is tuple and 0 < len(batch) <= MAX_BATCH, 'bounded_training_batch_required')
        rows = []
        for example in batch:
            need(type(example) is dict and set(example) == {'prefix', 'answer'}, 'closed_training_row_required')
            prefix = self._ids(example['prefix'])
            answer = self._ids(example['answer'], reply=True) + (2,)
            rows.append((prefix, answer))
        total_targets = sum(len(answer) for _, answer in rows)
        gradients = {name: np.zeros_like(self.p[name]) for name in PARAMETER_NAMES}
        loss = 0.0
        for prefix, answer in rows:
            hidden = np.zeros(HIDDEN)
            cache = []
            for identity in prefix:
                hidden, item = self._step(identity, hidden)
                cache.append((item, None))
            previous_token = 1
            for target in answer:
                hidden, item = self._step(previous_token, hidden)
                probability, logits, log_normalizer = self._distribution(hidden)
                loss += (log_normalizer - float(logits[target])) / total_targets
                dz = probability.copy()
                dz[target] -= 1.0
                dz /= total_targets
                cache.append((item, dz))
                previous_token = target
            dh = np.zeros(HIDDEN)
            for (previous, embedding, current, identity), dz in reversed(cache):
                if dz is not None:
                    gradients['Wy'] += np.outer(current, dz)
                    gradients['by'] += dz
                    dh = dh + dz @ self.p['Wy'].T
                da = dh * (1.0 - current * current)
                gradients['Wxh'] += np.outer(embedding, da)
                gradients['Whh'] += np.outer(previous, da)
                gradients['bh'] += da
                gradients['E'][identity] += da @ self.p['Wxh'].T
                dh = da @ self.p['Whh'].T
        need(np.isfinite(loss) and loss >= 0 and all(np.isfinite(value).all() for value in gradients.values()),
             'finite_token_loss_and_full_gradients_required')
        return float(loss), gradients, {'examples': len(rows),
            'prefix_tokens': sum(len(prefix) for prefix, _ in rows), 'target_tokens_including_eos': total_targets}

    def train_step(self, batch):
        """One bounded SGD update; no curriculum/optimizer campaign in source."""
        state = {'model': self, 'phase': 'validate', 'gradient_arrays': None,
                 'loss': None, 'parameters_committed': False}
        try:
            self.validate_parameters()
            need(self.training_updates < MAX_UPDATES, 'declared_model_update_ceiling_reached')
            before = self.parameter_hash()
            state['phase'] = 'gradient'
            loss, gradients, counts = self.loss_and_gradients(batch)
            state['gradient_arrays'], state['loss'] = gradients, loss
            need(type(gradients) is dict and set(gradients) == set(PARAMETER_NAMES),
                 'closed_gradient_roles_required')
            need(type(counts) is dict and set(counts) == {'examples', 'prefix_tokens', 'target_tokens_including_eos'}
                 and all(type(value) is int and 0 < value < 2**32 for value in counts.values()),
                 'closed_positive_exposure_counts_required')
            need(all(type(gradients[name]) is np.ndarray and gradients[name].shape == self.p[name].shape
                     and gradients[name].dtype == np.dtype('float64') and np.isfinite(gradients[name]).all()
                     and np.max(np.abs(gradients[name]), initial=0) <= 1e6 for name in PARAMETER_NAMES),
                 'bounded_exact_gradient_roles_required')
            norm = float(np.sqrt(sum(float(np.sum(value * value)) for value in gradients.values())))
            multiplier = min(1.0, CLIP_NORM / norm) if norm > 0 else 1.0
            proposal = {name: self.p[name] - LEARNING_RATE * multiplier * gradients[name] for name in PARAMETER_NAMES}
            need(all(np.isfinite(value).all() and np.max(np.abs(value), initial=0) <= PARAMETER_LIMIT
                     for value in proposal.values()), 'finite_parameter_proposal_required')
            next_counts = (self.training_updates + 1, self.training_examples + counts['examples'],
                           self.prefix_tokens_seen + counts['prefix_tokens'],
                           self.target_tokens_seen + counts['target_tokens_including_eos'])
            need(all(type(value) is int and 0 <= value < 2**32 for value in next_counts), 'bounded_proposed_exposure_counts_required')
            state['phase'] = 'commit'
            self.p = proposal
            state['parameters_committed'] = True
            self.training_updates, self.training_examples, self.prefix_tokens_seen, self.target_tokens_seen = next_counts
            state['phase'] = 'postcommit_identity'
            after = self.parameter_hash()
            return {'schema': 'newbrain.trained-dialogue.update.v1', 'loss': loss,
                    'parameter_sha256_before': before, 'parameter_sha256_after': after,
                    'parameter_bytes_changed': before != after, 'gradient_norm': norm,
                    'clip_multiplier': multiplier, 'new_exposures': counts,
                    'updates_completed': self.training_updates, 'runtime_qualified': False}
        except Exception as primary:
            raise DecoderTrainingError(primary, state) from primary

    def generate(self, prefix):
        """Greedy learned next-token generation; no target, templates or updates."""
        self.validate_parameters()
        identities = self._ids(prefix)
        before = self.parameter_hash()
        hidden = np.zeros(HIDDEN)
        for identity in identities:
            hidden, _ = self._step(identity, hidden)
        previous_token = 1
        emitted = []
        terminated = False
        for _ in range(MAX_RESPONSE):
            hidden, _ = self._step(previous_token, hidden)
            probability, _, _ = self._distribution(hidden)
            selected = int(np.argmax(probability))
            if selected == 2:
                terminated = True
                break
            emitted.append(self.vocabulary[selected])
            previous_token = selected
        need(self.parameter_hash() == before, 'generation_must_preserve_weights')
        return {'schema': 'newbrain.trained-dialogue.generation.v1', 'backend': BACKEND,
                'tokens': tuple(emitted), 'answer_text': ' '.join(emitted),
                'terminated_with_eos': terminated, 'length_limit_reached': not terminated,
                'unknown_prefix_tokens': sum(word not in self.index for word in prefix),
                'parameter_sha256': before, 'qwen_calls_in_this_module': 0,
                'full_conversation_demonstrated': False, 'runtime_qualified': False}

    def parameter_hash(self):
        self.validate_parameters()
        digest = hashlib.sha256()
        for name in PARAMETER_NAMES:
            value = self.p[name]
            digest.update(name.encode('ascii'))
            digest.update(str(value.shape).encode('ascii'))
            digest.update(value.astype('<f8', copy=False).tobytes(order='C'))
        return digest.hexdigest()

    def parameter_details(self):
        self.validate_parameters()
        return {'parameter_scalars': sum(value.size for value in self.p.values()),
                'array_bytes': sum(value.nbytes for value in self.p.values()),
                'vocabulary_size': len(self.vocabulary), 'embedding': EMBEDDING, 'hidden': HIDDEN,
                'training_updates': self.training_updates, 'training_examples': self.training_examples,
                'prefix_tokens_seen': self.prefix_tokens_seen, 'target_tokens_seen': self.target_tokens_seen,
                'scope': 'private arrays and exposure counters, not process RAM or useful learning evidence'}

    def state_bytes(self, protocol_sha256):
        self.validate_parameters()
        need(hash_string(protocol_sha256), 'exact_protocol_hash_required')
        meta = {'schema': 'newbrain.trained-dialogue.state.hidden64.v1', 'vocabulary': list(self.vocabulary),
                'vocabulary_sha256': vocabulary_hash(self.vocabulary), 'protocol_sha256': protocol_sha256,
                'parameter_sha256': self.parameter_hash(), 'embedding': EMBEDDING, 'hidden': HIDDEN,
                'root_seed': self.root_seed, 'training_updates': self.training_updates,
                'training_examples': self.training_examples, 'prefix_tokens_seen': self.prefix_tokens_seen,
                'target_tokens_seen': self.target_tokens_seen, 'pretrained': False, 'glif_integrated': False}
        header = json.dumps(meta, sort_keys=True, separators=(',', ':')).encode('ascii')
        need(len(header) <= MAX_META_BYTES, 'bounded_complete_metadata_required')
        raw = MAGIC + struct.pack('<I', len(header)) + header + b''.join(
            self.p[name].astype('<f8', copy=False).tobytes(order='C') for name in PARAMETER_NAMES)
        need(len(raw) <= MAX_STATE_BYTES, 'bounded_complete_private_state_required')
        return raw

    @classmethod
    def from_state_bytes(cls, raw, words, protocol_sha256):
        need(type(raw) is bytes and 12 < len(raw) <= MAX_STATE_BYTES and raw[:8] == MAGIC, 'bounded_private_blob_required')
        words = vocabulary(words)
        need(hash_string(protocol_sha256), 'exact_protocol_hash_required')
        metadata_size = struct.unpack('<I', raw[8:12])[0]
        need(0 < metadata_size <= MAX_META_BYTES and 12 + metadata_size < len(raw), 'bounded_metadata_extent_required')
        metadata_raw = raw[12:12 + metadata_size]
        meta = json.loads(metadata_raw.decode('ascii'))
        fields = {'schema', 'vocabulary', 'vocabulary_sha256', 'protocol_sha256', 'parameter_sha256',
                  'embedding', 'hidden', 'root_seed', 'training_updates', 'training_examples',
                  'prefix_tokens_seen', 'target_tokens_seen', 'pretrained', 'glif_integrated'}
        need(type(meta) is dict and set(meta) == fields and json.dumps(meta, sort_keys=True, separators=(',', ':')).encode('ascii') == metadata_raw,
             'closed_canonical_metadata_required')
        need(meta['schema'] == 'newbrain.trained-dialogue.state.hidden64.v1' and meta['vocabulary'] == list(words)
             and meta['vocabulary_sha256'] == vocabulary_hash(words) and meta['protocol_sha256'] == protocol_sha256
             and type(meta['embedding']) is int and meta['embedding'] == EMBEDDING
             and type(meta['hidden']) is int and meta['hidden'] == HIDDEN
             and meta['pretrained'] is False and meta['glif_integrated'] is False
             and hash_string(meta['parameter_sha256']), 'exact_saved_architecture_vocabulary_origin_required')
        count = (EMBEDDING + HIDDEN + 1) * len(words) + EMBEDDING * HIDDEN + HIDDEN * HIDDEN + HIDDEN
        payload = raw[12 + metadata_size:]
        need(len(payload) == count * 8, 'exact_ordered_parameter_bytes_required')
        result = cls.__new__(cls)
        result._set_vocabulary(words)
        result.root_seed, result.training_updates = meta['root_seed'], meta['training_updates']
        result.training_examples = meta['training_examples']
        result.prefix_tokens_seen, result.target_tokens_seen = meta['prefix_tokens_seen'], meta['target_tokens_seen']
        flat = np.frombuffer(payload, dtype='<f8')
        result.p, offset = {}, 0
        for name, shape in result._shapes().items():
            size = 1
            for dimension in shape:
                size *= dimension
            result.p[name] = flat[offset:offset + size].reshape(shape).copy()
            offset += size
        result.validate_parameters()
        need(result.parameter_hash() == meta['parameter_sha256'], 'saved_parameter_identity_disagrees')
        return result
