# Publishing and deploying

Two things happen here: the repository goes to GitHub, and the frontend goes to
Vercel. The backend does **not** go to Vercel, and the reason is worth
understanding rather than working around — it is covered at the end.

---

## 1 · Push it with GitHub Desktop

Everything is already arranged for this. There is a `.gitignore` that keeps
`node_modules`, build output, databases and any key material out of the
repository, and no secrets are committed.

1. Open **GitHub Desktop**.
2. **File → Add local repository…** and choose the `Penumbra.AI` folder.
3. It will say the folder is not a Git repository and offer to **create one** —
   accept.
4. In the left panel you should see roughly 120 changed files. Check that
   **`node_modules` is not among them**. If it is, `.gitignore` did not get
   picked up — close Desktop, confirm `.gitignore` sits at the top level of the
   folder, and reopen.
5. Summary: `PENUMBRA: privacy-preserving quantum-enhanced advisory`.
   Click **Commit to main**.
6. Click **Publish repository**. Untick *Keep this code private* only if you
   want it public — for a final-year project, private until submission is the
   safer default, and Vercel deploys private repositories fine.

### If the repository is very large

`frontend/node_modules` is about 380 MB and must never be committed. If GitHub
Desktop is showing thousands of files, stop and check `.gitignore` before
committing — untangling it afterwards means rewriting history.

---

## 2 · Deploy the frontend to Vercel

1. Go to [vercel.com/new](https://vercel.com/new) and sign in with GitHub.
2. **Import** the `Penumbra.AI` repository.
3. Leave every setting at its default and press **Deploy**.

The `vercel.json` at the repository root already tells Vercel what to do:

```json
"buildCommand":     "npm --prefix frontend install && npm --prefix frontend run build",
"outputDirectory":  "frontend/dist"
```

It also sets the SPA rewrite, so a direct link to `/lab` or `/advisor` resolves
instead of 404-ing, and adds the security headers that matter for a page holding
a secret key in browser memory.

The first build takes two to three minutes, most of it compiling the SEAL
WebAssembly bundle. You get a URL like `penumbra-ai.vercel.app`, and every push
to `main` redeploys automatically.

**Alternative if you prefer no config file:** delete `vercel.json`, and in
Vercel's project settings set **Root Directory** to `frontend`. Vercel then
detects Vite on its own. Both routes work; the committed config means you do not
have to remember to set anything.

### What the deployed site actually does

It runs standalone. Accounts and portfolios live in the browser's own storage —
but the CKKS encryption is **real Microsoft SEAL compiled to WebAssembly**, so
the demonstration is genuine. When you press *Attempt server decryption* in the
Crypto Lab and it refuses, that is a real exception from a real engine that has
no decryptor.

To point it at a running backend later, add `VITE_API_URL` in
**Settings → Environment Variables** and redeploy. Read
`docs/SPEC_DEVIATIONS.md` #11 first: the browser uses `node-seal` and the
backend uses TenSEAL, and their serialisation formats do not yet interoperate.

---

## 3 · Run it locally

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

Then in the browser: create an account → generate a key → upload the sample
portfolio → dashboard. About ninety seconds end to end.

Key generation takes a few seconds and produces roughly 34 MB of rotation keys
in memory. That is not a bug; it is the measurement the Keys page reports, and it
is the reason the backend stores public contexts on disk rather than in a
database column.

### The backend, locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

uvicorn app.main:app --reload    # http://localhost:8000/docs
pytest -q                        # 261 tests
python -m scripts.demo           # the end-to-end privacy demonstration
```

---

## 4 · Why the backend cannot go on Vercel

Worth being able to answer, because it is a reasonable question to be asked.

| Constraint | Vercel serverless | What PENUMBRA needs |
| --- | --- | --- |
| Bundle size | 250 MB unzipped | TenSEAL plus its SEAL binaries approach that on their own |
| Filesystem | ephemeral, read-only outside `/tmp` | a keystore holding 35 MB public contexts that must persist |
| Execution time | 10–60 s | a QAOA simulation runs for minutes |
| Process model | cold-started per request | key material cached across a session |

None of these is a flaw in Vercel — it is a static and serverless platform, and
the backend is a stateful compute service. They are different shapes.

**Where the backend does belong:** anywhere that runs a container. `Dockerfile`
and `docker-compose.yml` are both in the repository, so Render, Railway and
Fly.io all take it as-is, and every one of them has a free tier that suits a
project demo. Deploy there, put the resulting URL in `VITE_API_URL`, and the two
halves meet.

---

## 5 · Before the viva

- Run `npm run build` locally once, so a broken build never surprises you on the
  day.
- Open the deployed URL on your phone. The layout is responsive and it is a good
  way to show the project without a laptop.
- Have `docs/SPEC_DEVIATIONS.md` open in a tab. The four defects found in the
  original specification are the strongest material in the project.
- Know the three numbers the Crypto Lab prints live: **34 MB** of rotation keys
  against **1.8 MB** without, **~19×**; a homomorphic sum in **tens of
  milliseconds**; a relative error around **1e-9** fresh, growing to **1e-7**
  after a reduction.
