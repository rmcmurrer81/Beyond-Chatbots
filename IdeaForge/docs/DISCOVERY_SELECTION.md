# Evidence-bound discovery selection

The October 6 change evaluates a bounded, source-balanced shortlist instead of
letting the first 40 web rows exclude all scholarly results. It is a retrieval
and bookkeeping improvement, not a scientific truth score or live-model quality
qualification.

## Selection and identity

- At most 40 records per assessment, round-robin across papers, web and images.
  Within each category, preserved query tags also take turns. Legacy rows without
  query tags remain eligible. Old pending records precede new records.
- DOI identity takes priority when provided; otherwise the normalized source URL
  is used. Only known tracking parameters and fragments are removed. Other query
  parameters are retained. Same titles alone never merge different sources.
- Distinct source versions are retained, including multiple revisions in one
  incoming batch. A shortlist contains at most one version per source; additional
  versions remain pending for later passes. Exact duplicates prefer the scholarly
  bucket. Provider order otherwise remains intact. This is an explicit coverage policy,
  not a claim that publication-date order measures relevance.
- A result-version fingerprint covers its bounded title, excerpt/summary and
  publication-date metadata. It is a saved search-result version, not a hash of
  the full original paper. URL-only updates without new metadata are not treated
  as proven new scientific findings. Explicit arXiv version URLs remain distinct.
- Initial pre-existing results seed a baseline without generating old alerts.
  Later unseen versions enter a project-local SQLite queue. Unchanged results
  that disappear and reappear do not trigger another assessment.

## Failure and concurrency behavior

A transaction claims up to 40 candidates with a ten-minute lease. Failed model
requests or invalid output return them to pending. Expired leases recover after
restart; stale workers cannot complete newer workers' claims. Concurrent workers
cannot claim the same candidate version. The local ledger is scoped to the exact
project directory. Background work still runs only while the app is open.

Accepted reports and processed candidate states commit in one transaction.
JSON history and `LATEST_DISCOVERIES.md` are atomic, rebuildable projections of
that ledger. If the filesystem write fails, a later assessment reconstructs the
saved report; it does not silently consume the underlying evidence. The UI
notification is not a distributed exactly-once delivery guarantee.

## Model boundaries

Ollama receives bounded, complete JSON candidate records marked as untrusted.
The response uses a JSON Schema and is validated again in Python. Only supplied
IDs, finite scores in [0,1], supported categories and bounded explanations are
accepted. Unknown IDs, duplicate IDs, invented extra title/URL fields and malformed
responses fail the batch visibly and preserve pending work.

Titles, links, source identity and versions are constructed from saved candidates,
not copied from model-written replacements. Explanations are explicitly model
judgments; valid IDs do not prove their claims or feasibility. No provider/model
change, extra model download, paid service or network permission is introduced.

The source-balanced joining pattern is informed by Haystack DocumentJoiner
(Apache-2.0). No Haystack code or framework dependency is incorporated:
https://github.com/deepset-ai/haystack/blob/v3.3.0/haystack/components/joiners/document_joiner.py
