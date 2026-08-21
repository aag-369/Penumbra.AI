# Architecture

## Data flow

```
BROWSER                                    SERVER
─────────────────────────────────────      ──────────────────────────────────────
CKKS keypair generated locally
  secret key  ──► sealed in browser
                  storage (scrypt +
                  AES-256-GCM)
  public ctx  ──────────────────────────►  POST /portfolio/keys
                                             reject if it contains a secret key
                                             check parameters against the
                                               128-bit security table
                                             write blob to the keystore
                                             store path + metadata in the DB

CSV parsed locally
holdings encrypted locally
  ciphertext  ──────────────────────────►  POST /portfolio/
                                             validate tickers
                                             parse (not decrypt) the ciphertext
                                               under the registered key
                                             store

                                           POST /advisor/generate
                                             Planning  ─ plaintext goals only
                                             Risk      ─ public market data +
                                                         encrypted weights
                                             QUBO      ─ built from public data
                                             Obfuscate ─ permute, gauge, rescale
                                             QAOA      ─ solve obfuscated instance
                                             De-obfuscate
                                             Execution ─ simulate costs
                                             Encrypt the recommendation under
                                               the user's public key
  ciphertext  ◄──────────────────────────  GET /advisor/jobs/{id}
decrypted and displayed locally
```

The server crosses no trust boundary at any step. It never holds a secret key,
and the one place it could have — key generation — does not exist as an endpoint.

## Layers

| Layer | Module | Status |
| --- | --- | --- |
| CKKS engine | `app/crypto/ckks_engine.py` | implemented, 94% covered |
| Homomorphic operations | `app/crypto/homomorphic_ops.py` | implemented, 93% covered |
| Session and MAC | `app/crypto/post_quantum_channel.py` | implemented |
| Classical crypto | `app/crypto/security_utils.py` | implemented |
| Keystore | `app/services/keystore_service.py` | implemented |
| Auth, portfolio, audit | `app/services/` | implemented |
| REST API | `app/api/v1/endpoints/` | implemented |
| Planning / Risk / Execution agents | `app/agents/` | **Phase 2 — specified, not implemented** |
| QUBO builder and obfuscator | `app/optimization/qubo_*.py` | **Phase 3 — specified, not implemented** |
| QAOA solver | `app/optimization/qaoa_solver.py` | **Phase 4 — specified, not implemented** |
| Classical baseline | `app/optimization/classical_baseline.py` | implemented, 100% covered |
| Frontend | `frontend/` | scaffold |

Unimplemented endpoints return `501 Not Implemented` with the phase named, rather
than a fake success or a 500.

## Why the keystore is not a database column

A CKKS public context with rotation keys is 35 MB at `N = 8192` and 180 MB at
`N = 16384`. Rotation keys are not optional — every reduction (`sum`, `dot`,
`matmul`, and so every portfolio value and variance) is rotate-and-add.

Putting that in a column means every query touching the row pays for it. The
`encryption_keys` table holds a path, a fingerprint and the parameters; the bytes
live in `settings.keystore_dir`. Production should point that at object storage
with server-side encryption — `KeystoreService` is small and deliberately so.

## Ciphertext format

```
pnb1.<key_id>.<base64 CKKS ciphertext>
```

The tag exists because decrypting under the wrong key of the same parameters does
not fail — it returns floats of order 1e31. See `SPEC_DEVIATIONS.md` #6.

## Depth budget

| Operation | Levels | Rotation keys |
| --- | --- | --- |
| add, subtract | 0 | no |
| multiply by plaintext | 1 | no |
| multiply ciphertexts | 1 | no (relinearisation) |
| `sum` across slots | 0 | **yes** |
| `dot` with plaintext | 1 | **yes** |
| `dot` of ciphertexts | 1 | **yes** |
| `matmul` with plaintext | 1 | **yes** |
| `w^T Sigma w` | 2 | **yes** |
| Markowitz objective | 2 | **yes** |

The default chain provides 2. The objective fits only because the risk-aversion
coefficient is folded into the plaintext covariance before the matmul rather than
applied afterwards.

## Measured precision

At `N = 8192`, scale `2^40`:

| Depth | Relative error |
| --- | --- |
| 0 (fresh ciphertext) | ~1e-9 |
| 1 | ~1.4e-7 |
| 2 | ~8e-7 |
| 2 with a slot reduction | ~8e-5 |

A reduction sums noise from all 4096 slots, not just the occupied ones, which is
why the quadratic form is two orders of magnitude noisier than a bare product.
Portfolio values are accurate to a few parts per million. Share counts should be
rounded on the client after decryption — never treated as exact.

## Running it

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload      # docs at http://localhost:8000/docs
pytest -q                          # 255 tests
pytest --cov=app --cov-report=term # 89% coverage
```
