/**
 * Minimal structural types for the `node-seal` surface this app uses.
 *
 * `node-seal` ships its own declarations, but they are generated and awkward to
 * consume through a dynamic import. Declaring the handful of members actually
 * called keeps `seal.ts` type-checked without pulling the whole generated tree
 * into the build.
 */

export interface SealPlainText {
  save(): string;
  readonly scale: number;
}

export interface SealCipherText {
  save(): string;
  load(context: SealContext, base64: string): void;
  readonly scale: number;
}

interface Serialisable {
  save(): string;
  load(context: SealContext, base64: string): void;
}

export interface SealContext {
  parametersSet(): boolean;
}

export interface SealTypes {
  CKKSEncoder: {
    readonly slotCount: number;
    encode(values: Float64Array, scale: number, destination?: SealPlainText): SealPlainText | undefined;
    decode(plain: SealPlainText): Float64Array;
  };
  Evaluator: {
    add(a: SealCipherText, b: SealCipherText, destination: SealCipherText): void;
    sub(a: SealCipherText, b: SealCipherText, destination: SealCipherText): void;
    multiply(a: SealCipherText, b: SealCipherText, destination: SealCipherText): void;
    multiplyPlain(a: SealCipherText, b: SealPlainText, destination: SealCipherText): void;
    relinearize(a: SealCipherText, keys: SealTypes["RelinKeys"], destination: SealCipherText): void;
    rescaleToNext(a: SealCipherText, destination: SealCipherText): void;
    sumElements(
      a: SealCipherText,
      keys: SealTypes["GaloisKeys"],
      scheme: unknown,
      destination: SealCipherText,
    ): void;
  };
  Encryptor: { encrypt(plain: SealPlainText): SealCipherText | undefined };
  Decryptor: { decrypt(cipher: SealCipherText): SealPlainText | undefined };
  PublicKey: Serialisable;
  SecretKey: Serialisable;
  RelinKeys: Serialisable;
  GaloisKeys: Serialisable;
}

export interface LoadedSeal {
  SchemeType: { ckks: unknown };
  SecurityLevel: { tc128: unknown };
  EncryptionParameters(scheme: unknown): {
    setPolyModulusDegree(degree: number): void;
    setCoeffModulus(modulus: unknown): void;
  };
  CoeffModulus: { Create(degree: number, bitSizes: Int32Array): unknown };
  Context(parms: unknown, expandModChain: boolean, security: unknown): SealContext;
  KeyGenerator(
    context: SealContext,
    secretKey?: SealTypes["SecretKey"],
  ): {
    secretKey(): SealTypes["SecretKey"];
    createPublicKey(): SealTypes["PublicKey"];
    createRelinKeys(): SealTypes["RelinKeys"];
    createGaloisKeys(): SealTypes["GaloisKeys"];
  };
  CKKSEncoder(context: SealContext): SealTypes["CKKSEncoder"];
  Evaluator(context: SealContext): SealTypes["Evaluator"];
  Encryptor(context: SealContext, publicKey: SealTypes["PublicKey"]): SealTypes["Encryptor"];
  Decryptor(context: SealContext, secretKey: SealTypes["SecretKey"]): SealTypes["Decryptor"];
  CipherText(): SealCipherText;
  PlainText(): SealPlainText;
  PublicKey(): SealTypes["PublicKey"];
  SecretKey(): SealTypes["SecretKey"];
  RelinKeys(): SealTypes["RelinKeys"];
  GaloisKeys(): SealTypes["GaloisKeys"];
}
