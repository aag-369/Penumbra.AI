# Threat model and cryptographic assumptions

## The claim

The PENUMBRA server stores and computes on a user's portfolio without being able
to read it. This is not a policy commitment. The server does not possess the
secret key, so there is no configuration change, no administrator action and no
subpoena that would let it decrypt. What an attacker who fully compromises the
server obtains is ciphertext.

## What the security rests on

CKKS is a Ring Learning With Errors construction. Its security reduces to the
hardness of the decision-RLWE problem: distinguishing `(a, a·s + e)` from uniform,
where `a` is uniform in `R_q = Z_q[X]/(X^N + 1)`, `s` is a secret, and `e` is
drawn from a narrow error distribution.

Two properties matter.

**Classical hardness.** The best known attacks are lattice reduction — BKZ and
its variants — with cost exponential in the block size required. The
Homomorphic Encryption Security Standard (HomomorphicEncryption.org, 2018) tabulates,
for each ring dimension `N`, the largest coefficient modulus that keeps the best
known attack above a stated work factor. Those numbers are in
`SECURITY_TABLE` in `app/crypto/ckks_engine.py`, and both `CKKSParameters.validate()`
and `ContextInfo.assert_secure()` enforce them.

**Quantum hardness.** Shor's algorithm solves the hidden subgroup problem over
abelian groups, which is why it breaks RSA and elliptic-curve cryptography. It
does not apply to lattice problems. Grover's algorithm gives a square-root
speedup on unstructured search, which affects symmetric key sizes but not the
asymptotics of lattice reduction. The best known quantum improvements on lattice
sieving are modest constant-factor gains, not an asymptotic break.

This is the same reasoning behind NIST's post-quantum standards: ML-KEM
(FIPS 203) and ML-DSA (FIPS 204) are Module-LWE constructions, a close relative
of the Ring-LWE that CKKS uses. PENUMBRA is not claiming a novel assumption. It
is claiming the same one the standards bodies settled on.

**Caveat worth stating.** The published parameter tables target *classical*
security levels. There is no equally settled table for quantum security levels,
because the community has not converged on how to cost quantum lattice sieving
under realistic memory models. Treating the 128-bit classical row as offering
somewhat less than 128 bits of quantum security is the conservative reading, and
is the reading this project should take in the write-up.

## Deployed parameters

Default profile (`DEFAULT_PARAMETERS`):

| Parameter | Value |
| --- | --- |
| Ring dimension `N` | 8192 |
| Modulus chain | 60 + 40 + 40 + 60 = 200 bits |
| Budget at 128-bit security | 218 bits |
| Scale | 2^40 |
| Slots | 4096 |
| Multiplicative depth | 2 |
| Public context size | 35.3 MB (with rotation keys) |

`DEEP_PARAMETERS` moves to `N = 16384` with a depth-4 chain for the encrypted
covariance work, at the cost of a 179.5 MB public context.

## Trust boundaries

| Component | Location | Holds the secret key | Can decrypt |
| --- | --- | --- | --- |
| Key generation | Browser | yes | yes |
| Sealed key backup | Browser storage, AES-256-GCM under a scrypt-derived key | encrypted at rest | only with the passphrase |
| API server | Cloud | **no** | **no** |
| Keystore | Server disk | no — public contexts only | no |
| Database | Server | no | no |
| Agent pipeline | Server | no | no |
| Optimisation backend | Server or third party | no — sees an obfuscated QUBO | no |

`CKKSEngine.decrypt()` raises `SecretKeyUnavailable` when called on an engine
constructed from a public context, and `CKKSEngine.from_public_context()` raises
if the blob contains a secret key. Both are covered by tests. This is enforcement
by construction rather than by discipline: there is no server-side code path that
produces a private engine for a user's key.

## Residual leakage — what the server does learn

Honesty here is more valuable than a stronger-sounding claim.

1. **Ticker symbols.** Stored in plaintext. The server needs them to order slots
   and to fetch public market data. So the server knows *which* assets a user
   holds, just not how much. For many users the holding set alone is
   informative — a portfolio of three biotech tickers says something.
   *Mitigable* by padding the asset list to a fixed universe and encrypting zero
   weights for the rest. Cost: the ciphertext and every operation scale with the
   universe, not the portfolio. Not implemented; the trade-off should be a
   deliberate decision, not an omission.

2. **Portfolio cardinality.** The number of assets is visible. Padding to a fixed
   width fixes this and costs one ciphertext, since the slots are already there.

3. **Timing and access patterns.** When a user uploads, how often they request
   advice, how long an optimisation runs. Correlating run time with problem size
   leaks something about cardinality. Standard traffic-analysis exposure.

4. **Ciphertext sizes.** Near-constant by construction, so this leaks little —
   which is a side benefit of the single-ciphertext packing.

5. **Goals and constraints.** Risk tolerance, horizon and sector exclusions are
   plaintext. The Planning Agent has to reason about them, and they go to an
   external LLM API. They are user-stated preferences rather than positions, but
   they are not nothing.

6. **CKKS approximation error.** CKKS is *not* IND-CPA secure against an
   adversary who is given decryption results, because the noise in a decrypted
   plaintext depends on the secret key (Li–Micciancio, 2020). This matters for
   protocols where a decrypting party returns results to an untrusted party.
   PENUMBRA's decryption happens on the client, for the client, and results are
   not returned to the server — so the attack does not apply here. It would apply
   to a design where the server asks the client to decrypt something and observes
   the answer. Do not build that.

## What this does not defend against

- **A compromised client.** The secret key is in the browser. Cross-site
  scripting on the frontend is key exfiltration, not a defacement. This is why
  `SecurityHeadersMiddleware` sets a restrictive baseline and why the frontend
  must avoid `dangerouslySetInnerHTML`.
- **A malicious server returning wrong answers.** CKKS gives confidentiality, not
  integrity of computation. A dishonest server can return a ciphertext encoding
  bad advice and the client cannot tell. Verifiable computation over FHE exists
  but is not practical at this scale. A user must still trust the operator for
  *correctness* — just not for *confidentiality*.
- **Traffic analysis**, as above.
- **A user who loses their key.** There is no recovery. That is what "the server
  cannot decrypt" means in practice, and the UI has to say so before the user
  generates a key, not after.

## Classical cryptography around the edges

| Purpose | Primitive | Parameters |
| --- | --- | --- |
| Password hashing | bcrypt | cost 12 |
| Key backup at rest | scrypt + AES-256-GCM | N = 2^15, r = 8, p = 1; 96-bit nonce |
| Session tokens | JWT HS256 | 1 h access, 14 d refresh |
| Ciphertext authentication | HMAC-SHA256 | 256-bit key, length-prefixed message |
| Randomness | `secrets` (OS CSPRNG) | never `random` |
| Transport | TLS 1.3 | deployment concern; HSTS set in production |

Two notes. AES-GCM is used rather than AES-CBC so that a tampered key backup
fails to open instead of decrypting to garbage. And the HMAC message is
length-prefixed over `(ciphertext, session_id, sequence)` so that no two distinct
triples can collide — plain concatenation would let a crafted session id absorb
part of the ciphertext.

## References

1. Cheon, Kim, Kim, Song. *Homomorphic Encryption for Arithmetic of Approximate Numbers*. ASIACRYPT 2017.
2. Albrecht et al. *Homomorphic Encryption Security Standard*. HomomorphicEncryption.org, 2018.
3. Lyubashevsky, Peikert, Regev. *On Ideal Lattices and Learning with Errors over Rings*. EUROCRYPT 2010.
4. NIST FIPS 203 (ML-KEM) and FIPS 204 (ML-DSA), 2024.
5. Li, Micciancio. *On the Security of Homomorphic Encryption on Approximate Numbers*. EUROCRYPT 2021.
6. Bennett, Brassard. *Quantum Cryptography: Public Key Distribution and Coin Tossing*. 1984.
7. Shor, Preskill. *Simple Proof of Security of the BB84 Quantum Key Distribution Protocol*. PRL 2000.
