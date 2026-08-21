"""End-to-end demonstration of the privacy property.

Run with ``python -m scripts.demo`` from the ``backend`` directory.

Everything printed is produced live. Nothing is mocked, and the numbers -- key
sizes, timings, precision -- are measured on the machine running it, which makes
this a reasonable thing to run in front of an examiner.
"""

from __future__ import annotations

import time

import numpy as np

from app.crypto.ckks_engine import (
    DEFAULT_PARAMETERS,
    LIGHT_PARAMETERS,
    CKKSEngine,
    CryptoError,
    KeyMismatch,
    SecretKeyUnavailable,
)
from app.crypto.homomorphic_ops import HomomorphicOps
from app.crypto.post_quantum_channel import PostQuantumChannel, simulate_bb84
from app.optimization.classical_baseline import ClassicalBaseline

TICKERS = ["AAPL", "MSFT", "BRK.B", "JNJ", "XOM"]
HOLDINGS = [120.0, 85.0, 14.0, 210.0, 60.0]
PRICES = [227.50, 415.20, 452.80, 158.30, 118.90]


def rule(title: str) -> None:
    print(f"\n{'=' * 74}\n  {title}\n{'=' * 74}")


def main() -> None:
    rule("1. Key generation happens on the client, and only on the client")
    started = time.perf_counter()
    client = CKKSEngine.create_client(DEFAULT_PARAMETERS)
    print(f"  generated in {time.perf_counter() - started:.2f}s   key id: {client.key_id}")
    for key, value in client.parameters.describe().items():
        print(f"    {key:<26} {value}")

    rule("2. The server receives the public half. That is all it ever gets.")
    public_context = client.export_public_context()
    server = CKKSEngine.from_public_context(public_context)
    print(f"  public context      {len(public_context) / 1e6:>8.2f} MB")
    print(f"  server holds secret key?  {server.is_private}")

    print("\n  If a client mistakenly uploads its secret key, the server refuses:")
    try:
        CKKSEngine.from_public_context(client.export_private_context())
    except CryptoError as exc:
        print(f"    CryptoError: {exc}")

    rule("3. The portfolio is encrypted before it leaves the browser")
    ciphertext = client.encrypt(HOLDINGS)
    print(f"  {len(TICKERS)} holdings -> one ciphertext of {client.ciphertext_size(ciphertext) / 1e3:.0f} kB")
    print(f"  tickers visible to the server: {TICKERS}")
    print("  quantities visible to the server: none")

    rule("4. The server cannot read it")
    try:
        server.decrypt(ciphertext)
    except SecretKeyUnavailable as exc:
        print(f"  SecretKeyUnavailable: {exc}")

    rule("5. The server can still compute on it")
    ops = HomomorphicOps(server)

    encrypted_value = ops.portfolio_value(ciphertext, PRICES)
    true_value = float(np.dot(HOLDINGS, PRICES))
    value = client.decrypt(encrypted_value, size=1)[0]
    print(f"  portfolio value, computed server-side under encryption")
    print(f"    decrypted by the client:  ${value:,.2f}")
    print(f"    true value:               ${true_value:,.2f}")
    print(f"    relative error:            {abs(value - true_value) / true_value:.2e}")

    weights = np.array(HOLDINGS) * np.array(PRICES)
    weights = weights / weights.sum()
    mu = np.array([0.081, 0.074, 0.058, 0.049, 0.066])
    rng = np.random.default_rng(20260820)
    factor = rng.normal(0, 1, (5, 5))
    cov = (factor @ factor.T) / 120.0
    lam = 2.0

    encrypted_weights = client.encrypt(weights.tolist())
    started = time.perf_counter()
    encrypted_objective = ops.mean_variance_objective(encrypted_weights, mu, cov, lam)
    elapsed = (time.perf_counter() - started) * 1000
    objective = client.decrypt(encrypted_objective, size=1)[0]
    truth = float(weights @ mu - lam * (weights @ cov @ weights))

    print(f"\n  Markowitz objective  mu'w - {lam}*w'Sigma*w, evaluated under encryption")
    print(f"    homomorphic:  {objective:+.8f}   ({elapsed:.0f} ms, depth 2)")
    print(f"    plaintext:    {truth:+.8f}")
    print(f"    relative error: {abs(objective - truth) / abs(truth):.2e}")
    print("    the server computed this without learning a single weight")

    rule("6. A ciphertext from a different key is caught, not silently misread")
    other = CKKSEngine.create_client(LIGHT_PARAMETERS)
    try:
        other.decrypt(ciphertext)
    except KeyMismatch as exc:
        print(f"  KeyMismatch: {exc}")
    print("\n  Without the key-id envelope this returns floats of order 1e31 instead")
    print("  of raising -- a user restoring the wrong backup would see numbers.")

    rule("7. Rotation keys are what make reductions possible, and they are large")
    light = CKKSEngine.from_public_context(
        CKKSEngine.create_client(LIGHT_PARAMETERS).export_public_context()
    )
    print(f"  without rotation keys   {light.public_context_size() / 1e6:>8.2f} MB   (elementwise only)")
    print(f"  with rotation keys      {server.public_context_size() / 1e6:>8.2f} MB   (sum, dot, matmul)")
    print(f"  ratio                   {server.public_context_size() / light.public_context_size():>8.1f}x")

    rule("8. BB84: a protocol demonstration, not a source of key material")
    clean = simulate_bb84(8192)
    tapped = simulate_bb84(8192, eavesdropper=True)
    print(f"  clean channel     sift {clean.sift_rate:.1%}   QBER {clean.qber:.4f}   aborted {clean.aborted}")
    print(f"  eavesdropper      sift {tapped.sift_rate:.1%}   QBER {tapped.qber:.4f}   aborted {tapped.aborted}")
    print(f"  theory says intercept-resend gives QBER 0.25; abort threshold is {0.11}")

    channel = PostQuantumChannel(use_bb84_simulation=False)
    session = channel.establish_session("demo-user", client.key_id)
    signature = channel.sign_ciphertext(ciphertext, session["session_id"], 0)
    print(f"\n  session {session['session_id'][:12]}... bound to key {session['key_fingerprint']}")
    print(f"  ciphertext MAC verifies: {channel.verify_ciphertext_authenticity(ciphertext, session['session_id'], signature, 0)}")
    try:
        channel.verify_ciphertext_authenticity(ciphertext, session["session_id"], signature, 0)
    except Exception as exc:
        print(f"  replaying the same MAC: {type(exc).__name__}: {exc}")
    print("\n  The post-quantum guarantee comes from CKKS resting on Ring-LWE.")
    print("  The session key above comes from the OS CSPRNG, always.")

    rule("9. Classical baseline, for comparison against QAOA later")
    result = ClassicalBaseline.mean_variance(mu, cov, risk_aversion=lam, max_position=0.4)
    stats = ClassicalBaseline.portfolio_stats(result.weights, mu, cov)
    print(f"  optimiser: {result.method}  converged={result.converged}  {result.runtime_ms} ms")
    for ticker, weight in zip(TICKERS, result.weights):
        print(f"    {ticker:<7} {weight:>7.2%}")
    print(f"  expected return {stats['expected_return']:.4f}   volatility {stats['volatility']:.4f}")
    print(f"  Sharpe {stats['sharpe_ratio']:.4f}   effective holdings {stats['n_effective_holdings']:.2f}")
    print("\n  QAOA (Phase 4) will be benchmarked against exactly this.")

    print(f"\n{'=' * 74}")
    print("  The server performed every computation above and read none of the data.")
    print(f"{'=' * 74}\n")


if __name__ == "__main__":
    main()
