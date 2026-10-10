"""Two explicitly selected neutral documentation reads, without retries or follows.

The production PublicReader supervisor, peer checks, TLS policy and disposable
worker are used unchanged. Only compact metadata leaves this module.
"""
import re

SMOKE_URLS = (
    'https://docs.python.org/3.12/library/urllib.parse.html',
    'https://docs.python.org/3.12/library/ssl.html',
)
MAX_GETS = 2
REASONS = frozenset(('ok', 'invalid_url', 'nonpublic_host', 'nonpublic_address',
    'ipv6_unsupported', 'dns_failed', 'dns_no_ipv4', 'dns_invalid', 'peer_mismatch',
    'tls_failed', 'timeout', 'connection_failed', 'invalid_response', 'header_limit',
    'wire_limit', 'body_limit', 'incomplete_body', 'unsupported_framing',
    'unsupported_encoding', 'unsupported_media', 'unsupported_attachment',
    'unsupported_status', 'redirect_review_required', 'redirect_blocked',
    'http_error', 'worker_timeout', 'worker_failed', 'worker_invalid_output',
    'worker_output_limit', 'cancelled', 'reader_busy', 'reader_closed',
    'smoke_exception', 'invalid_smoke_result', 'smoke_not_read'))


def compact_snapshot(url, value):
    """Allowlist fields; never return page text, titles, peer IPs or link values."""
    result = {'source_url': url if url in SMOKE_URLS else None, 'status': 'failed',
        'reason': 'invalid_smoke_result', 'http_status': None, 'title_characters': 0,
        'text_characters': 0, 'link_count': 0, 'body_sha256': None,
        'truncated': {key: False for key in ('body', 'title', 'text', 'links')},
        'tls_verified': False, 'success': False}
    if url not in SMOKE_URLS or type(value) is not dict:
        return result
    reason = value.get('reason')
    result['reason'] = reason if type(reason) is str and reason in REASONS else 'invalid_smoke_result'
    if value.get('status') in ('read', 'redirect', 'unsupported', 'failed'):
        result['status'] = value['status']
    status = value.get('http_status')
    if type(status) is int and 100 <= status <= 599:
        result['http_status'] = status
    result['tls_verified'] = value.get('tls_verified') is True
    for key, maximum in (('title', 256), ('text', 12000)):
        if type(value.get(key)) is str and len(value[key]) <= maximum:
            result[key + '_characters'] = len(value[key])
    if type(value.get('links')) is list and len(value['links']) <= 32:
        result['link_count'] = len(value['links'])
    digest = value.get('body_sha256')
    if type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest):
        result['body_sha256'] = digest
    truncated = value.get('truncated')
    if type(truncated) is dict:
        for key in result['truncated']:
            result['truncated'][key] = truncated.get(key) is True
    valid = (value.get('source_url') == url and result['status'] == 'read'
        and result['reason'] == 'ok' and result['http_status'] == 200
        and result['tls_verified'] and result['body_sha256'] is not None
        and 0 < result['title_characters'] <= 256
        and 0 < result['text_characters'] <= 12000
        and type(truncated) is dict and set(truncated) == set(result['truncated'])
        and all(type(item) is bool for item in truncated.values())
        and not truncated['body'])
    result['success'] = bool(valid)
    if not valid and result['reason'] == 'ok':
        result['reason'] = 'smoke_not_read'
    return result


def run_smoke():
    """Exactly two read attempts maximum. No caller URL, crawling or fallback."""
    from aster.browser_public import PublicReader
    results = []
    reader = PublicReader()
    try:
        for url in SMOKE_URLS[:MAX_GETS]:
            try:
                snapshot = reader.read(url)
            except Exception:
                snapshot = {'status': 'failed', 'reason': 'smoke_exception'}
            results.append(compact_snapshot(url, snapshot))
    finally:
        try:
            reader.close()
        except Exception:
            for result in results:
                result.update(success=False, reason='smoke_exception')
    return results
