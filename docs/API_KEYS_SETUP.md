# API keys: Materials Project and Anthropic (10 minutes, once)

Both keys live only in `~/.iris_env` on Carbon (mode 600, sourced by the demo scripts). IRIS reads them from the
environment (`MP_API_KEY`, `ANTHROPIC_API_KEY`); they are never written to a config, a log, or the archive.

## 1. Materials Project key (structures for f0)
1. Log in at https://next-gen.materialsproject.org (free; UIC/ANL email is fine).
2. Click your profile (top right) → **API** → **Generate API key** (or copy the existing one). It is a 32-character string.
3. Where it is used: `iris_agent/engines/mp_fetch.py` → `GET https://api.materialsproject.org/materials/summary/`
   with header `X-API-KEY`, fields `material_id, structure, symmetry, energy_above_hull`. One call per structure.
4. Test from Carbon (after step 3 below):
   ```bash
   source ~/.iris_env && curl -s -m 20 -H "X-API-KEY: $MP_API_KEY" "https://api.materialsproject.org/materials/summary/?formula=BaTiO3&spacegroup_number=221&_fields=material_id,energy_above_hull&_limit=3"
   ```
   expect JSON with `mp-…` ids. `{"detail":"Not authenticated"}` = wrong key; no output / `000` = the login node has no HTTPS to that host.
   Expected ids (check in the browser too): cubic Pm-3m mp-2998, tetragonal P4mm mp-5986, orthorhombic Amm2 mp-5020, rhombohedral R3m mp-5777 —
   the fetcher picks the lowest-energy-above-hull entry of the requested space group and records the choice in `provenance.json`;
   pin one with `--parent-id/--child-id` (chat) if you prefer.

## 2. Anthropic key (the LLM intake in f0 and the sub-agents in recover)
1. https://console.anthropic.com → **API keys** → **Create key** (name it e.g. `iris-carbon`); copy it once (starts with `sk-ant-`).
2. Make sure the organization has credit (Billing); one demo is a few cents (intake ≈ 1–2k tokens per request, sub-agents only on gate failures).
3. Where it is used: `iris_agent/llm.py` → `https://api.anthropic.com/v1/messages`, model from `eval/models.yaml`
   (`claude-sonnet` = `claude-sonnet-5-5`); structured JSON output; the prompts are the frozen ones in `intake/` and `prompts/`.
4. Test from Carbon:
   ```bash
   source ~/.iris_env && curl -s -m 20 https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" | head -c 300
   ```
   expect a JSON list of models (contains `claude-sonnet-5-5`); `authentication_error` = wrong key.
5. Optional: `pip install anthropic` in the `iris` env lets the staged walkthrough print its agent commentary in the
   ISODISTORT log (`[agent unavailable: No module named 'anthropic']` otherwise — harmless, the run does not need it).

## 3. Put them on Carbon
```bash
cp 00_setup/iris_env.template ~/.iris_env && chmod 600 ~/.iris_env && nano ~/.iris_env     # paste the two keys, set the paths
source ~/.iris_env && [ -n "$MP_API_KEY" ] && [ -n "$ANTHROPIC_API_KEY" ] && echo keys set
```
Do not `export` them in `.bashrc` (they would be in every shell and in `ps e`), do not put them in any yaml under the repo,
and never paste them in the chat here. `00_setup/check_carbon.sh` reports only whether each is set.

## 4. If the Carbon login node cannot reach the internet
`curl -m 15 -sI https://api.anthropic.com` returning nothing means the HTTPS calls (Claude, Materials Project, and
FINDSYM/ISODISTORT at iso.byu.edu for f1) have to go elsewhere. Options, in order of simplicity: (a) a proxy Carbon
provides (`echo $https_proxy`; `module avail proxy`); (b) the reverse tunnel from the Mac: `ssh -R 3128:localhost:3128 carbon`
with a local proxy on the Mac and `export https_proxy=http://localhost:3128` in `~/.iris_env`; (c) the split layout
(chat + f0/f1 on the Mac, executor on Carbon). Tell me which `curl` fails and I set the kit up for the matching option.
