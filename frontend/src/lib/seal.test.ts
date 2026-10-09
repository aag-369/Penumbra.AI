/**
 * The landing page's live demo makes three numeric claims about ciphertexts it
 * never decrypts server-side. These tests hold the engine to them.
 */

import { beforeAll, describe, expect, it } from "vitest";

import { covarianceFor, meanReturnsFor, pricesFor } from "./market";
import { CkksEngine, DEFAULT_PARAMS, SecretKeyUnavailable } from "./seal";

const TICKERS = ["AAPL", "MSFT", "NVDA", "JNJ", "XOM", "JPM", "BRK.B", "UNH"];
const SHARES = [120, 85, 40, 210, 160, 95, 14, 30];

let client: CkksEngine;
let server: CkksEngine;

beforeAll(async () => {
  client = await CkksEngine.createClient(DEFAULT_PARAMS, { rotationKeys: true });
  server = await CkksEngine.fromPublicBundle(client.exportPublicBundle());
}, 120_000);

function relErr(actual: number, expected: number): number {
  return Math.abs(actual - expected) / Math.abs(expected);
}

describe("periodic packing", () => {
  it("pads to a power of two and repeats across every slot", () => {
    expect(CkksEngine.periodFor(8)).toBe(8);
    expect(CkksEngine.periodFor(5)).toBe(8);
    const packed = client.replicate([1, 2, 3]);
    expect(packed).toHaveLength(client.slotCount);
    expect(packed.slice(0, 8)).toEqual([1, 2, 3, 0, 1, 2, 3, 0]);
  });

  it("computes portfolio value on ciphertext", () => {
    const prices = pricesFor(TICKERS);
    const truth = SHARES.reduce((sum, q, i) => sum + q * prices[i]!, 0);
    const encrypted = server.dotPlainPeriodic(client.encryptReplicated(SHARES), prices);
    expect(relErr(client.decrypt(encrypted, 1)[0]!, truth)).toBeLessThan(1e-6);
  });

  it("computes the Markowitz risk term w'Sigma w in the depth-2 budget", () => {
    const prices = pricesFor(TICKERS);
    const values = SHARES.map((q, i) => q * prices[i]!);
    const total = values.reduce((a, b) => a + b, 0);
    const weights = values.map((v) => v / total);
    const sigma = covarianceFor(TICKERS);
    const truth = weights.reduce(
      (sum, wi, i) => sum + wi * sigma[i]!.reduce((s, sij, j) => s + sij * weights[j]!, 0),
      0,
    );

    const encW = client.encryptReplicated(weights);
    expect(client.levelsRemaining(encW)).toBe(2);
    const encrypted = server.quadraticFormPeriodic(encW, sigma);
    expect(server.levelsRemaining(encrypted)).toBe(0);
    // Two levels deep on values of order 0.03: CKKS noise is ~1e-6 in absolute terms.
    expect(relErr(client.decrypt(encrypted, 1)[0]!, truth)).toBeLessThan(5e-4);
  });

  it("is far more precise with weights in percentage points, as the demo encodes them", () => {
    const prices = pricesFor(TICKERS);
    const values = SHARES.map((q, i) => q * prices[i]!);
    const total = values.reduce((a, b) => a + b, 0);
    const weights = values.map((v) => v / total);
    const mu = meanReturnsFor(TICKERS);
    const sigma = covarianceFor(TICKERS);
    const retTruth = weights.reduce((s, w, i) => s + w * mu[i]!, 0);
    const riskTruth = weights.reduce(
      (sum, wi, i) => sum + wi * sigma[i]!.reduce((s, sij, j) => s + sij * weights[j]!, 0),
      0,
    );
    const encW = client.encryptReplicated(weights.map((w) => w * 100));
    const ret = client.decrypt(server.dotPlainPeriodic(encW, mu), 1)[0]! / 100;
    const risk = client.decrypt(server.quadraticFormPeriodic(encW, sigma), 1)[0]! / 1e4;
    expect(relErr(ret, retTruth)).toBeLessThan(1e-6);
    expect(relErr(risk, riskTruth)).toBeLessThan(1e-6);
  });

  it("handles a block that is not a power of two", () => {
    const tickers = TICKERS.slice(0, 5);
    const w = [0.3, 0.1, 0.2, 0.25, 0.15];
    const mu = meanReturnsFor(tickers);
    const sigma = covarianceFor(tickers);
    const ret = client.decrypt(server.dotPlainPeriodic(client.encryptReplicated(w), mu), 1)[0]!;
    const risk = client.decrypt(server.quadraticFormPeriodic(client.encryptReplicated(w), sigma), 1)[0]!;
    const retTruth = w.reduce((s, wi, i) => s + wi * mu[i]!, 0);
    const riskTruth = w.reduce((s, wi, i) => s + wi * sigma[i]!.reduce((t, sij, j) => t + sij * w[j]!, 0), 0);
    expect(relErr(ret, retTruth)).toBeLessThan(1e-4);
    expect(relErr(risk, riskTruth)).toBeLessThan(5e-4);
  });

  it("still cannot decrypt on the server", () => {
    expect(() => server.decrypt(client.encryptReplicated(SHARES))).toThrow(SecretKeyUnavailable);
  });
});
