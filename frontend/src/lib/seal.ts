/**
 * Real CKKS homomorphic encryption, in the browser.
 *
 * This is Microsoft SEAL compiled to WebAssembly by way of `node-seal`. The
 * keypairs are real, the ciphertexts are real, and every size and timing the UI
 * displays is measured on the machine it is running on. Open the network tab
 * during a demo and there is nothing to catch you out.
 *
 * ## Why not Pyfhel, as the original spec said
 *
 * Pyfhel is a Python C-extension. There is no JavaScript binding, so
 * `window.PyfhelCrypto.generateKeypair()` could never have existed. See
 * `docs/SPEC_DEVIATIONS.md` #11.
 *
 * ## The secret key never leaves this file's closure
 *
 * A `CkksEngine` built from a public bundle has no `Decryptor` at all -- not a
 * disabled one, not a guarded one. `decrypt()` on it throws because there is no
 * object to call. That mirrors the server, where `CKKSEngine.decrypt` raises on
 * a public engine, and it is the property the whole system rests on.
 *
 * ## Key sizes are the interesting constraint
 *
 * Measured at N=8192: public key ~0.6 MB, relinearisation keys ~1.9 MB,
 * **rotation keys ~44.8 MB**. Rotation keys are not optional -- every reduction
 * (`sum`, and therefore every portfolio value) is rotate-and-add. They are also
 * far too large for `localStorage`, which is why a backup stores only the
 * *secret* key (~0.3 MB) and regenerates everything else from it on restore.
 */

import type { LoadedSeal, SealCipherText, SealContext, SealTypes } from "./sealTypes";

export interface CkksParams {
  polyModulusDegree: number;
  coeffModBitSizes: number[];
  scaleBits: number;
}

/** Mirrors `DEFAULT_PARAMETERS` in `backend/app/crypto/ckks_engine.py`. */
export const DEFAULT_PARAMS: CkksParams = {
  polyModulusDegree: 8192,
  coeffModBitSizes: [60, 40, 40, 60],
  scaleBits: 40,
};

/**
 * Largest total coefficient modulus for a given ring dimension at 128-bit
 * classical security, from the Homomorphic Encryption Security Standard.
 * Same table the backend enforces.
 */
export const SECURITY_BUDGET_128: Record<number, number> = {
  1024: 27,
  2048: 54,
  4096: 109,
  8192: 218,
  16384: 438,
  32768: 881,
};

export const CIPHERTEXT_PREFIX = "pnb1";
const BUNDLE_VERSION = 1;

export class SealError extends Error {}
export class SecretKeyUnavailable extends SealError {}
export class KeyMismatch extends SealError {}

let sealPromise: Promise<LoadedSeal> | null = null;

/**
 * Load the SEAL WebAssembly module once, lazily.
 *
 * The web build is ~1.45 MB with the WASM inlined as base64, so it is a single
 * module with no second fetch -- but it is still 1.45 MB, and the login screen
 * has no business waiting for it. Callers trigger this when the user actually
 * reaches key setup.
 */
export async function loadSeal(): Promise<LoadedSeal> {
  if (!sealPromise) {
    sealPromise = import("node-seal/throws_wasm_web_es").then((mod) =>
      (mod.default as unknown as () => Promise<LoadedSeal>)(),
    );
  }
  return sealPromise;
}

export function sealIsLoaded(): boolean {
  return sealPromise !== null;
}

function randomKeyId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Split `pnb1.<keyId>.<body>`. A bare body returns a null key id. */
export function unwrapCiphertext(ciphertext: string): { keyId: string | null; body: string } {
  if (!ciphertext.startsWith(`${CIPHERTEXT_PREFIX}.`)) return { keyId: null, body: ciphertext };
  const first = ciphertext.indexOf(".");
  const second = ciphertext.indexOf(".", first + 1);
  if (second === -1) throw new SealError("ciphertext envelope is malformed");
  return { keyId: ciphertext.slice(first + 1, second), body: ciphertext.slice(second + 1) };
}

export interface KeyMetrics {
  keyId: string;
  polyModulusDegree: number;
  slotCount: number;
  coeffModBitSizes: number[];
  totalCoeffModulusBits: number;
  securityBudgetBits: number;
  scaleBits: number;
  multiplicativeDepth: number;
  hasRotationKeys: boolean;
  publicKeyBytes: number;
  relinKeyBytes: number;
  rotationKeyBytes: number;
  secretKeyBytes: number;
  publicBundleBytes: number;
  keygenMs: number;
  rotationKeygenMs: number;
}

/**
 * One CKKS keypair and the operations available under it.
 *
 * Construct through {@link createClient} (has the secret key) or
 * {@link fromPublicBundle} (does not, and cannot decrypt).
 */
export class CkksEngine {
  private constructor(
    private readonly seal: LoadedSeal,
    private readonly context: SealContext,
    private readonly encoder: SealTypes["CKKSEncoder"],
    private readonly evaluator: SealTypes["Evaluator"],
    private readonly encryptor: SealTypes["Encryptor"],
    private readonly decryptor: SealTypes["Decryptor"] | null,
    private readonly galoisKeys: SealTypes["GaloisKeys"] | null,
    private readonly relinKeys: SealTypes["RelinKeys"],
    private readonly secretKeyB64: string | null,
    private readonly publicKeyB64: string,
    private readonly relinKeyB64: string,
    private readonly galoisKeyB64: string | null,
    readonly keyId: string,
    readonly params: CkksParams,
    private readonly timings: { keygenMs: number; rotationKeygenMs: number },
  ) {}

  get isPrivate(): boolean {
    return this.decryptor !== null;
  }

  get hasRotationKeys(): boolean {
    return this.galoisKeys !== null;
  }

  get scale(): number {
    return Math.pow(2, this.params.scaleBits);
  }

  get slotCount(): number {
    return this.params.polyModulusDegree / 2;
  }

  // -- construction ---------------------------------------------------------

  /**
   * Generate a fresh keypair. This is the only place secret-key material comes
   * into existence, and it happens on the user's machine.
   *
   * @param rotationKeys generate Galois keys. Required for any reduction --
   *   `sum`, `dot`, and so every portfolio value. Costs ~45 MB and a few hundred
   *   milliseconds, which is why it is a deliberate choice rather than a default.
   */
  static async createClient(
    params: CkksParams = DEFAULT_PARAMS,
    { rotationKeys = true }: { rotationKeys?: boolean } = {},
  ): Promise<CkksEngine> {
    const seal = await loadSeal();
    const started = performance.now();
    const context = buildContext(seal, params);

    const keyGenerator = seal.KeyGenerator(context);
    const secretKey = keyGenerator.secretKey();
    const publicKey = keyGenerator.createPublicKey();
    const relin = keyGenerator.createRelinKeys();
    const keygenMs = performance.now() - started;

    let galois: SealTypes["GaloisKeys"] | null = null;
    let rotationKeygenMs = 0;
    if (rotationKeys) {
      const rotationStarted = performance.now();
      galois = keyGenerator.createGaloisKeys();
      rotationKeygenMs = performance.now() - rotationStarted;
    }

    return new CkksEngine(
      seal,
      context,
      seal.CKKSEncoder(context),
      seal.Evaluator(context),
      seal.Encryptor(context, publicKey),
      seal.Decryptor(context, secretKey),
      galois,
      relin,
      secretKey.save(),
      publicKey.save(),
      relin.save(),
      galois ? galois.save() : null,
      randomKeyId(),
      params,
      { keygenMs, rotationKeygenMs },
    );
  }

  /**
   * Rebuild the *server's* view: evaluation keys, no secret key.
   *
   * The resulting engine can encrypt (CKKS is public-key) and evaluate, and has
   * no decryptor at all.
   */
  static async fromPublicBundle(bundleJson: string): Promise<CkksEngine> {
    const seal = await loadSeal();
    const bundle = parseBundle(bundleJson);
    if (bundle.secretKey) {
      throw new SealError(
        "refusing a public bundle that contains a secret key -- re-export without it and rotate the key",
      );
    }
    const context = buildContext(seal, bundle.params);

    const publicKey = seal.PublicKey();
    publicKey.load(context, bundle.publicKey);
    const relin = seal.RelinKeys();
    relin.load(context, bundle.relinKeys);

    let galois: SealTypes["GaloisKeys"] | null = null;
    if (bundle.galoisKeys) {
      galois = seal.GaloisKeys();
      galois.load(context, bundle.galoisKeys);
    }

    return new CkksEngine(
      seal,
      context,
      seal.CKKSEncoder(context),
      seal.Evaluator(context),
      seal.Encryptor(context, publicKey),
      null,
      galois,
      relin,
      null,
      bundle.publicKey,
      bundle.relinKeys,
      bundle.galoisKeys,
      bundle.keyId,
      bundle.params,
      { keygenMs: 0, rotationKeygenMs: 0 },
    );
  }

  /**
   * Restore a client engine from a secret key alone.
   *
   * Public, relinearisation and rotation keys are *regenerated* from the secret
   * key rather than stored, because they are two orders of magnitude larger. The
   * same thing happens server-side in TenSEAL, and it is precisely why a hash of
   * the public context is not a valid key identifier -- the regeneration is
   * randomised, so the bytes differ every time. Hence the explicit `keyId`.
   */
  static async fromSecretKey(
    secretKeyB64: string,
    keyId: string,
    params: CkksParams = DEFAULT_PARAMS,
    { rotationKeys = true }: { rotationKeys?: boolean } = {},
  ): Promise<CkksEngine> {
    const seal = await loadSeal();
    const started = performance.now();
    const context = buildContext(seal, params);

    const secretKey = seal.SecretKey();
    secretKey.load(context, secretKeyB64);

    const keyGenerator = seal.KeyGenerator(context, secretKey);
    const publicKey = keyGenerator.createPublicKey();
    const relin = keyGenerator.createRelinKeys();
    const keygenMs = performance.now() - started;

    let galois: SealTypes["GaloisKeys"] | null = null;
    let rotationKeygenMs = 0;
    if (rotationKeys) {
      const rotationStarted = performance.now();
      galois = keyGenerator.createGaloisKeys();
      rotationKeygenMs = performance.now() - rotationStarted;
    }

    return new CkksEngine(
      seal,
      context,
      seal.CKKSEncoder(context),
      seal.Evaluator(context),
      seal.Encryptor(context, publicKey),
      seal.Decryptor(context, secretKey),
      galois,
      relin,
      secretKeyB64,
      publicKey.save(),
      relin.save(),
      galois ? galois.save() : null,
      keyId,
      params,
      { keygenMs, rotationKeygenMs },
    );
  }

  // -- export ---------------------------------------------------------------

  /** Everything the server needs, and nothing it must not have. */
  exportPublicBundle(): string {
    return JSON.stringify({
      v: BUNDLE_VERSION,
      keyId: this.keyId,
      params: this.params,
      publicKey: this.publicKeyB64,
      relinKeys: this.relinKeyB64,
      galoisKeys: this.galoisKeyB64,
    });
  }

  /** Client-only. Feeds the passphrase-sealed backup. */
  exportSecretKey(): string {
    if (!this.secretKeyB64) throw new SecretKeyUnavailable("this engine has no secret key");
    return this.secretKeyB64;
  }

  // -- core -----------------------------------------------------------------

  /** Encrypt a vector of numbers into one ciphertext, tagged with the key id. */
  encrypt(values: number[]): string {
    if (values.length === 0) throw new SealError("cannot encrypt an empty vector");
    if (values.length > this.slotCount) {
      throw new SealError(`${values.length} values exceeds the ${this.slotCount} available slots`);
    }
    if (values.some((v) => !Number.isFinite(v))) {
      throw new SealError("plaintext contains NaN or infinity");
    }
    const plain = this.encoder.encode(Float64Array.from(values), this.scale)!;
    const cipher = this.encryptor.encrypt(plain)!;
    return `${CIPHERTEXT_PREFIX}.${this.keyId}.${cipher.save()}`;
  }

  /**
   * Decrypt. Throws on a public engine, which is the guarantee stated as code.
   */
  decrypt(ciphertext: string, size?: number): number[] {
    if (!this.decryptor) {
      throw new SecretKeyUnavailable(
        "decrypt() called on a public (server-side) engine -- the secret key never left the browser, so this ciphertext cannot be opened here",
      );
    }
    const cipher = this.load(ciphertext);
    const decoded = this.encoder.decode(this.decryptor.decrypt(cipher)!);
    const out = Array.from(decoded);
    return size === undefined ? out : out.slice(0, size);
  }

  /** Deserialise a ciphertext, checking it belongs to this key. */
  load(ciphertext: string): SealCipherText {
    const { keyId, body } = unwrapCiphertext(ciphertext);
    if (keyId !== null && keyId !== this.keyId) {
      throw new KeyMismatch(
        `ciphertext was produced under key ${keyId}, but this engine holds ${this.keyId}. Decrypting it would return noise, not data.`,
      );
    }
    const cipher = this.seal.CipherText();
    cipher.load(this.context, body);
    return cipher;
  }

  private dump(cipher: SealCipherText): string {
    return `${CIPHERTEXT_PREFIX}.${this.keyId}.${cipher.save()}`;
  }

  // -- homomorphic operations ----------------------------------------------

  /** `a + b`, elementwise. Free in depth. */
  add(a: string, b: string): string {
    const result = this.seal.CipherText();
    this.evaluator.add(this.load(a), this.load(b), result);
    return this.dump(result);
  }

  /** `a - b`, elementwise. Free in depth. */
  subtract(a: string, b: string): string {
    const result = this.seal.CipherText();
    this.evaluator.sub(this.load(a), this.load(b), result);
    return this.dump(result);
  }

  /** Elementwise multiply by a plaintext vector. Costs one level. */
  multiplyPlain(ciphertext: string, factors: number[]): string {
    const cipher = this.load(ciphertext);
    const padded = Float64Array.from(
      Array.from({ length: Math.max(factors.length, 1) }, (_, i) => factors[i] ?? 0),
    );
    const plain = this.encoder.encode(padded, cipher.scale)!;
    const result = this.seal.CipherText();
    this.evaluator.multiplyPlain(cipher, plain, result);
    this.evaluator.rescaleToNext(result, result);
    return this.dump(result);
  }

  /** Multiply every slot by a scalar. Costs one level. */
  multiplyScalar(ciphertext: string, scalar: number): string {
    return this.multiplyPlain(ciphertext, new Array(this.slotCount).fill(scalar));
  }

  /**
   * Sum every slot into slot 0.
   *
   * **Requires rotation keys.** This is rotate-and-add: log2(slots) rotations,
   * each consuming a Galois key. Without them the operation is not merely slow,
   * it is unavailable.
   */
  sumSlots(ciphertext: string): string {
    if (!this.galoisKeys) {
      throw new SealError(
        "this key has no rotation keys, so slots cannot be summed on the server. Generate a key with rotation keys, or reduce on the client after decrypting.",
      );
    }
    const result = this.seal.CipherText();
    this.evaluator.sumElements(
      this.load(ciphertext),
      this.galoisKeys,
      this.seal.SchemeType.ckks,
      result,
    );
    return this.dump(result);
  }

  /**
   * Inner product with a plaintext vector: the portfolio-value operation.
   *
   * `sum_i holdings_i * price_i`, computed without the evaluator ever seeing a
   * holding. Costs one level and requires rotation keys.
   */
  dotPlain(ciphertext: string, weights: number[]): string {
    return this.sumSlots(this.multiplyPlain(ciphertext, weights));
  }

  // -- periodic packing ------------------------------------------------------
  //
  // A vector of n values is padded to the next power of two p and repeated
  // across all 4096 slots. Rotations then act cyclically *within* each block of
  // p, which buys two things: a reduction costs log2(p) rotations instead of
  // log2(4096), so it sums noise from p slots rather than all of them, and a
  // plaintext matrix-vector product can use the diagonal method. Together they
  // are enough to evaluate the Markowitz risk term w^T Sigma w in the default
  // depth-2 chain.

  /** Block length used to pack `n` values: the next power of two. */
  static periodFor(n: number): number {
    let period = 1;
    while (period < n) period *= 2;
    return period;
  }

  /** Pad to the block length and repeat across every slot. */
  replicate(values: number[], period = CkksEngine.periodFor(values.length)): number[] {
    const block = Array.from({ length: period }, (_, i) => values[i] ?? 0);
    return Array.from({ length: this.slotCount }, (_, i) => block[i % period]!);
  }

  /** Encrypt `values` in periodic packing. */
  encryptReplicated(values: number[]): string {
    if (values.length === 0) throw new SealError("cannot encrypt an empty vector");
    return this.encrypt(this.replicate(values));
  }

  /** How many rescales this ciphertext has left before the chain is exhausted. */
  levelsRemaining(ciphertext: string): number {
    const cipher = this.load(ciphertext);
    const level = this.context.getContextData(cipher.parmsId).chainIndex;
    cipher.delete();
    return level;
  }

  /**
   * `sum_i x_i * factors_i` over one block of a periodically packed vector.
   * One level, log2(period) rotations.
   */
  dotPlainPeriodic(ciphertext: string, factors: number[], period = CkksEngine.periodFor(factors.length)): string {
    this.requireRotationKeys("an encrypted inner product");
    const x = this.load(ciphertext);
    const product = this.multiplyPlainCipher(x, this.replicate(factors, period));
    x.delete();
    const summed = this.sumBlock(product, period);
    const out = this.dump(summed);
    summed.delete();
    return out;
  }

  /**
   * `x^T M x` for a periodically packed `x` and a public matrix `M`.
   *
   * Diagonal method for `M x` (one level, `period - 1` rotations), then a
   * ciphertext-ciphertext product with `x` (second level, relinearised), then a
   * block reduction. Exactly the default chain's depth of two. Scale `M` by the
   * risk-aversion coefficient beforehand and this is the Markowitz risk term.
   */
  quadraticFormPeriodic(ciphertext: string, matrix: number[][]): string {
    this.requireRotationKeys("an encrypted quadratic form");
    const n = matrix.length;
    if (n === 0 || matrix.some((row) => row.length !== n)) {
      throw new SealError("quadratic form needs a square, non-empty matrix");
    }
    const period = CkksEngine.periodFor(n);
    const x = this.load(ciphertext);

    let mx: SealCipherText | null = null;
    for (let k = 0; k < period; k += 1) {
      const diagonal = Array.from({ length: period }, (_, j) => {
        const col = (j + k) % period;
        return j < n && col < n ? matrix[j]![col]! : 0;
      });
      if (diagonal.every((v) => v === 0)) continue;
      const rotated = k === 0 ? x : this.rotateCipher(x, k);
      const term = this.multiplyPlainCipher(rotated, this.replicate(diagonal, period));
      if (rotated !== x) rotated.delete();
      if (mx === null) {
        mx = term;
      } else {
        this.evaluator.add(mx, term, mx);
        term.delete();
      }
    }
    if (mx === null) throw new SealError("quadratic form of a zero matrix");

    const xAligned = this.seal.CipherText();
    this.evaluator.cipherModSwitchTo(x, mx.parmsId, xAligned);
    const product = this.seal.CipherText();
    this.evaluator.multiply(xAligned, mx, product);
    this.evaluator.relinearize(product, this.relinKeys, product);
    this.evaluator.rescaleToNext(product, product);
    x.delete();
    xAligned.delete();
    mx.delete();

    const summed = this.sumBlock(product, period);
    const out = this.dump(summed);
    summed.delete();
    return out;
  }

  private requireRotationKeys(what: string): void {
    if (!this.galoisKeys) {
      throw new SealError(`${what} needs rotation keys, and this key was generated without them`);
    }
  }

  private rotateCipher(cipher: SealCipherText, steps: number): SealCipherText {
    const out = this.seal.CipherText();
    this.evaluator.rotateVector(cipher, steps, this.galoisKeys!, out);
    return out;
  }

  /** Multiply by a plaintext vector encoded at the ciphertext's scale, then rescale. */
  private multiplyPlainCipher(cipher: SealCipherText, factors: number[]): SealCipherText {
    const plain = this.encoder.encode(Float64Array.from(factors), cipher.scale)!;
    const out = this.seal.CipherText();
    this.evaluator.multiplyPlain(cipher, plain, out);
    this.evaluator.rescaleToNext(out, out);
    plain.delete();
    return out;
  }

  /** Rotate-and-add within each block; consumes `cipher`. */
  private sumBlock(cipher: SealCipherText, period: number): SealCipherText {
    for (let step = 1; step < period; step *= 2) {
      const rotated = this.rotateCipher(cipher, step);
      this.evaluator.add(cipher, rotated, cipher);
      rotated.delete();
    }
    return cipher;
  }

  // -- measurement ----------------------------------------------------------

  ciphertextBytes(ciphertext: string): number {
    return Math.floor((unwrapCiphertext(ciphertext).body.length * 3) / 4);
  }

  metrics(): KeyMetrics {
    const totalBits = this.params.coeffModBitSizes.reduce((sum, b) => sum + b, 0);
    const b = (s: string | null) => (s ? Math.floor((s.length * 3) / 4) : 0);
    return {
      keyId: this.keyId,
      polyModulusDegree: this.params.polyModulusDegree,
      slotCount: this.slotCount,
      coeffModBitSizes: this.params.coeffModBitSizes,
      totalCoeffModulusBits: totalBits,
      securityBudgetBits: SECURITY_BUDGET_128[this.params.polyModulusDegree] ?? 0,
      scaleBits: this.params.scaleBits,
      multiplicativeDepth: this.params.coeffModBitSizes.length - 2,
      hasRotationKeys: this.hasRotationKeys,
      publicKeyBytes: b(this.publicKeyB64),
      relinKeyBytes: b(this.relinKeyB64),
      rotationKeyBytes: b(this.galoisKeyB64),
      secretKeyBytes: b(this.secretKeyB64),
      publicBundleBytes: b(this.publicKeyB64) + b(this.relinKeyB64) + b(this.galoisKeyB64),
      keygenMs: this.timings.keygenMs,
      rotationKeygenMs: this.timings.rotationKeygenMs,
    };
  }
}

function buildContext(seal: LoadedSeal, params: CkksParams): SealContext {
  const total = params.coeffModBitSizes.reduce((sum, b) => sum + b, 0);
  const budget = SECURITY_BUDGET_128[params.polyModulusDegree];
  if (budget !== undefined && total > budget) {
    throw new SealError(
      `total coefficient modulus ${total} bits exceeds the ${budget}-bit budget for N=${params.polyModulusDegree} at 128-bit security`,
    );
  }
  const parms = seal.EncryptionParameters(seal.SchemeType.ckks);
  parms.setPolyModulusDegree(params.polyModulusDegree);
  parms.setCoeffModulus(
    seal.CoeffModulus.Create(params.polyModulusDegree, Int32Array.from(params.coeffModBitSizes)),
  );
  const context = seal.Context(parms, true, seal.SecurityLevel.tc128);
  if (!context.parametersSet()) {
    throw new SealError("SEAL rejected these encryption parameters");
  }
  return context;
}

interface Bundle {
  keyId: string;
  params: CkksParams;
  publicKey: string;
  relinKeys: string;
  galoisKeys: string | null;
  secretKey?: string;
}

function parseBundle(json: string): Bundle {
  let parsed: Partial<Bundle> & { v?: number };
  try {
    parsed = JSON.parse(json);
  } catch {
    throw new SealError("public bundle is not valid JSON");
  }
  if (parsed.v !== BUNDLE_VERSION) throw new SealError(`unsupported bundle version ${parsed.v}`);
  if (!parsed.keyId || !parsed.params || !parsed.publicKey || !parsed.relinKeys) {
    throw new SealError("public bundle is missing required fields");
  }
  return {
    keyId: parsed.keyId,
    params: parsed.params,
    publicKey: parsed.publicKey,
    relinKeys: parsed.relinKeys,
    galoisKeys: parsed.galoisKeys ?? null,
    secretKey: parsed.secretKey,
  };
}
