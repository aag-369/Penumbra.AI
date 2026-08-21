# Deviations from the master build prompt

Every place this implementation departs from `PENUMBRA_MASTER_BUILD_PROMPT.md`,
what the specification said, why it does not work, and what was built instead.

Read this before the viva. Several of these are defects in the original design
rather than matters of taste, and being the person who found them is a
considerably better position than being the person who shipped them.

---

## 1. The server never generates a user's keypair

**Specified.** `POST /portfolio/generate-keypair` calls
`ckks_engine.generate_keypair()` on the server, stores the public key, and
returns it — while the docstring states "Private key is generated client-side,
never transmitted."

**The problem.** Both cannot be true. If the server runs key generation, the
server holds the secret key at least momentarily, and the user has no way to
verify it was discarded. The entire value proposition of the system is that the
user does not have to take that on trust. One endpoint undoes it.

**Built instead.** There is no key-generation endpoint. `CKKSEngine.create_client()`
is the only place secret-key material comes into existence, and in production it
runs in the browser. The server accepts only the output of
`export_public_context()`, via `POST /portfolio/keys`, and
`KeystoreService.register` refuses any blob whose context reports `is_private()`
— returning `400 secret_key_rejected` and writing a **critical** audit row,
because a client that uploaded its secret key has a compromised key and needs to
rotate it.

Tests: `test_ckks_engine.py::test_server_refuses_a_context_containing_a_secret_key`,
`test_api_flow.py::test_a_context_containing_a_secret_key_is_refused`,
`test_api_flow.py::test_there_is_no_server_side_keypair_endpoint`.

---

## 2. A portfolio is one ciphertext, not one per ticker

**Specified.** `portfolio_encrypted: Dict[str, str]` — a mapping from ticker to
its own ciphertext.

**The problem.** A CKKS ciphertext holds `N/2` slots — 4096 at the default
parameters — and costs the same ~330 kB whether it carries one value or four
thousand. Per-ticker storage multiplies the footprint by the number of assets.
A 50-asset portfolio costs 16 MB instead of 330 kB, and every homomorphic
operation runs 50 times instead of once.

**Built instead.** The holdings vector is packed into a single ciphertext, with
a plaintext ticker list giving the slot order. `Portfolio.tickers_json` holds the
ordering; `holdings_ciphertext` and `cost_basis_ciphertext` hold one ciphertext
each.

Measured: `test_ckks_engine.py::test_ciphertext_size_is_independent_of_value_count`
shows one value and a thousand values differ in size by under 5%.

---

## 3. Covariance is estimated from public data, not homomorphically

**Specified.** `RiskAgent.compute_risk_metrics` computes the covariance matrix
homomorphically from encrypted return series.

**The problem.** Not that it cannot be done — it can, and it is implemented as
`HomomorphicOps.encrypted_covariance_from_returns`, tested against NumPy to
within 1e-5. The problem is that for a retail portfolio of listed equities it
protects nothing. Return series for AAPL and MSFT are public. Encrypting a
public input, computing on it at roughly a thousand times the cost, and
decrypting a public output is expensive theatre.

What is actually private is the *weights* — which assets the user holds and in
what proportion.

**Built instead.** Means and covariances are estimated from public market history
in plaintext. The user's weights stay encrypted, and the Markowitz objective is
evaluated over them under encryption:
`HomomorphicOps.mean_variance_objective` computes `mu^T w - lambda * w^T Sigma w`
without the server learning `w`.

The encrypted-covariance path is kept, tested, and documented, because it is the
right tool when the return series are themselves private — a fund's proprietary
factor returns, for instance. Being able to say which case is which is the
substance of the argument.

---

## 4. The specified QUBO obfuscation is a no-op

**Specified.**

```python
parts = [np.random.randn() * coeff for _ in range(k_parts - 1)]
parts.append(coeff - sum(parts))
qubo_obfuscated[(i, j)] = sum(parts)          # == coeff, exactly
...
qubo_obfuscated[(i, i)] = decoy_value
qubo_obfuscated[(i, i)] += -decoy_value       # == 0
```

**The problem.** `sum(parts)` reconstructs `coeff` by construction, so the
coefficient reaching the solver is bit-for-bit the original. The decoy loop adds
a value and immediately subtracts it. Neither step changes anything an adversary
observes. Shipping this and describing it as obfuscation would not survive an
examiner who read it.

Permutation alone — the one part of the scheme that does something — is also
weaker than it looks: the coefficient multiset, the degree sequence and the
spectrum of `Q` are all permutation-invariant.

**Built instead.** `qubo_obfuscator.py` specifies three transformations that are
exact symmetries of the argmin and genuinely change what the solver sees:

1. **Permutation** — relabels variables, hides which qubit is which asset.
2. **Gauge (spin-reversal) transformation** — substitute `x_i -> 1 - x_i` for a
   random subset. Standard practice on quantum annealers, where it cancels
   hardware bias. Changes coefficients including their signs, destroying the
   structure permutation leaves intact.
3. **Positive affine rescaling** — `Q -> aQ + b`, `a > 0`. Hides absolute
   magnitudes, which would otherwise leak the covariance scale and hence the
   asset class.

**The honest framing**, which belongs in the write-up: this is obfuscation, not
encryption. There is no hardness assumption behind it. An adversary with adaptive
query access, or one who observes many instances from the same user, does better
than chance. It raises the cost of casual inspection by an untrusted optimisation
provider. The cryptographic guarantee in this system comes from CKKS, and only
from CKKS.

---

## 5. BB84 is a demonstration, not a security mechanism

**Specified.** A "post-quantum secure channel" with BB84 key distribution as an
optional layer.

**The problem.** There is no quantum channel. The photons are Python integers,
and anyone who can read process memory reads the states directly. Presenting the
simulated output as key material would be a claim that does not survive one
question.

**Built instead.** `simulate_bb84` implements the protocol properly — basis
reconciliation, sifting, QBER estimation, abort above 11% — and is worth
demonstrating: an intercept-resend attacker produces a measured QBER of ~0.22
against the theoretical 0.25, and the session is refused. But the session MAC key
always comes from the OS CSPRNG; the sifted bits are XOR-mixed in, so the result
is no weaker than OS randomness even though the simulated bits are entirely
predictable. Disabling BB84 changes nothing about the system's security.

The post-quantum property comes from CKKS resting on Ring-LWE, which no known
quantum algorithm solves in polynomial time. That is the same assumption NIST
relied on for ML-KEM and ML-DSA. See `CRYPTO_ASSUMPTIONS.md`.

Tests: `test_post_quantum_channel.py::TestBB84IsNotTreatedAsKeyMaterial`.

---

## 6. Ciphertexts carry a key identifier

**Not in the specification at all.** Found while writing
`test_rejects_ciphertext_from_another_key`.

**The problem.** Decrypting a ciphertext with the *wrong secret key* does not
fail, provided the parameters match. SEAL returns floats — typically of order
1e31. A user who restored the wrong key backup would see numbers rather than an
error, and a portfolio read under a rotated key would silently produce nonsense
advice.

**Built instead.** Ciphertexts are wrapped as `pnb1.<key_id>.<base64 body>`, and
`load_vector` raises `KeyMismatch` when the tag does not match the engine. The
cost is 24 characters against a ~440 kB body. Bare ciphertexts without the tag
still load, so third-party CKKS clients interoperate.

A related discovery: the obvious key identifier — a hash of the serialised public
context — does not work. TenSEAL drops public and evaluation keys when
serialising a secret-key context and regenerates them on load, and that
regeneration is randomised, so a key that is backed up and restored produces a
different context blob. Identity is therefore an explicit `key_id` minted at
generation and carried in the export envelope, the same approach as a JWK `kid`.

---

## 7. Rotation keys are mandatory and expensive

**Not addressed in the specification**, which proposes `poly_modulus_degree = 2**14`
without discussing key sizes.

**Measured.** Every reduction — `sum`, `dot`, `matmul`, and therefore every
portfolio value, expected return and variance — is implemented as rotate-and-add
and requires Galois keys. They dominate the public context:

| Ring dimension | Without rotation keys | With rotation keys |
| --- | --- | --- |
| N = 4096 | 0.4 MB | 6.1 MB |
| N = 8192 | 1.9 MB | 35.3 MB |
| N = 16384 | 7.9 MB | 179.5 MB |

**Consequences.** The specification's `N = 2**14` implies a 180 MB public
context per user. That is not something to put in a database column.

Three changes follow. The default is `N = 8192` (35 MB), not 16384. Public
contexts live in a keystore directory keyed by fingerprint, with the database row
holding a path and metadata. And `LIGHT_PARAMETERS` provides a rotation-key-free
profile at 1.9 MB for the cases where the server only needs elementwise
operations, with `elementwise_for_client_reduction` handing the final summation
to the client — which costs nothing in privacy, since the client already knows
its own data.

---

## 8. Parameter validation against the security standard

**Not in the specification.**

**The problem.** SEAL will accept parameter combinations that are not secure, and
`Pyfhel`/`TenSEAL` expose no warning. A client could register a context with an
oversized modulus chain and every ciphertext under that key would be breakable,
while the system reported everything as normal.

**Built instead.** `SECURITY_TABLE` encodes Table 1 of the Homomorphic Encryption
Security Standard (128, 192 and 256-bit levels). `CKKSParameters.validate()`
checks it at construction, and — more importantly — `ContextInfo.assert_secure()`
checks the parameters *read back off the uploaded context*, so the server
validates what the client actually sent rather than what it claimed.

---

## 9. The Markowitz objective folds lambda into the covariance

**Not in the specification**, which did not consider multiplicative depth.

**The problem.** Computing `mu^T w - lambda * (w^T Sigma w)` naively costs three
levels: `w @ Sigma`, then `. dot w`, then the scalar multiply by lambda. The
default chain `(60, 40, 40, 60)` provides two. The third multiplication throws.

**Built instead.** Scale the plaintext covariance by `-lambda` *before* the
matmul. Scaling a plaintext operand is free, so the objective fits in depth 2.

Test: `test_homomorphic_ops.py::test_mean_variance_objective_fits_in_the_default_depth_budget`.

---

## 10. QAOA is not expected to beat the classical baseline

**Specified.** `optimization_metadata` reports an `improvement` figure, and the
benchmark is framed as demonstrating QAOA's advantage.

**The problem.** Mean-variance optimisation with a cardinality constraint is a
mixed-integer quadratic program. At 10–30 assets, branch-and-bound finds the
exact optimum in milliseconds. Shallow QAOA on a simulator will not beat that,
and a benchmark constructed to produce a favourable number is worse than no
benchmark.

**Built instead.** `ClassicalBaseline` is fully implemented and tested — including
`exhaustive`, which gives ground truth on small instances, and a cardinality-
preserving simulated annealer that mirrors what the Dicke + XY-mixer ansatz does
quantum-side. The benchmark harness is specified to *report* the approximation
ratio as a function of depth `p` and problem size. If QAOA loses, that is the
result. The defensible contribution is the privacy architecture, not a quantum
speedup.

---

## 11. Frontend encryption uses `node-seal`, not Pyfhel

**Specified.** `window.PyfhelCrypto.generateKeypair()` in the browser.

**The problem.** Pyfhel is a Python C-extension. There is no JavaScript or WASM
binding, so that call cannot exist.

**Built instead.** `node-seal` — Microsoft SEAL compiled to WebAssembly, published
on npm, with CKKS support — is the browser-side library.

**The interop constraint, stated plainly.** `node-seal` speaks SEAL's native
serialisation. TenSEAL wraps SEAL in its own protobuf envelope, so the two are
**not** wire-compatible. Three ways forward, and the choice should be made
deliberately in Phase 6:

1. Swap the server to `Pyfhel`, which uses SEAL's native format. Both sides then
   interoperate. Costs the ergonomic vector API TenSEAL provides.
2. Write a format shim between the two serialisations.
3. Compile TenSEAL itself to WASM. Most work, best ergonomics.

`backend/app/crypto/` is written against a narrow interface — `encrypt`,
`decrypt`, `load_vector`, `dump_vector` — precisely so this swap is contained.

---

## 12. Smaller corrections

| Area | Specified | Built | Why |
| --- | --- | --- | --- |
| Password hashing | `passlib[bcrypt]` | `bcrypt` directly | passlib 1.7.4 reads `bcrypt.__about__.__version__`, removed in bcrypt 4.1; the pair errors on every hash. Also rejects passwords over 72 bytes rather than letting bcrypt truncate silently. |
| Logout | Token blacklist in Redis | Per-user `token_version` counter | Immediate across all devices, no external dependency, no unbounded blacklist table. |
| Database | PostgreSQL required | SQLite default, PostgreSQL via env | The stack runs with no external services. `assert_production_ready()` refuses SQLite when `ENVIRONMENT=production`. |
| Timestamps | `datetime.utcnow()` | `UTCDateTime` type decorator | `utcnow()` returns a *naive* datetime; SQLite also returns naive on read. Mixing the two raises `TypeError` in duration arithmetic — this actually happened, in `_run_pipeline`. |
| QUBO matrix | Symmetrise by copying | Symmetrise by halving | `coefficients[(i,j)]` is the coefficient of one term. Copying into both triangles makes `x^T M x` double every coupling, silently doubling the risk term against the return term. |
| WebSocket auth | Token in the URL | Token in the first frame | URLs land in proxy logs and browser history. |
| Error bodies | Raw exception text | `{code, detail, context}` with an incident id | A stack trace or SQL fragment in a response body is an information leak; in this application the bodies are one layer from key material. |
| Audit details | Free-form dict | Scrubbed against a forbidden-key list | An audit trail that records ciphertexts or key material defeats its own purpose. |
| Account enumeration | Distinct errors for unknown email | Identical error and a dummy bcrypt comparison | Otherwise registration and login are membership oracles. |
| Job ownership | Fetch then compare | Scope the query on `user_id` | Returns 404 rather than 403, so the endpoint is not an existence oracle for other users' job ids. |
